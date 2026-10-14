"""The CloudFront Function JS against its Python specification.

Two layers, both lightweight:

1. A regex-level sanity check that the JS has the same three branches,
   literals and response shape as scripts/rewrite.py. This is NOT a JS
   runtime test; it catches a branch deleted or a literal changed on one
   side only.
2. When ``node`` is on PATH, the JS handler is executed with node on the
   same events as the Python, and the outputs must be identical. Node is not
   the CloudFront Functions runtime (cloudfront-js-2.0 is a restricted
   ECMAScript 2020 subset), so this proves the logic, not deployability:
   the function only uses features that runtime documents (endsWith,
   lastIndexOf, for-in, var). Skipped cleanly without node; CI installs it.
"""

import json
import re
import shutil
import subprocess
import unittest

from helpers import FUNCTION_JS, SCRIPTS_DIR
from rewrite import handler, make_event

JS = FUNCTION_JS.read_text(encoding="utf-8")
PY = (SCRIPTS_DIR / "rewrite.py").read_text(encoding="utf-8")

CASES = [
    ("/", ""),
    ("/docs", ""),
    ("/docs/", ""),
    ("/a.css", ""),
    ("/assets/app.3f9a1c2e.js", ""),
    ("/docs/index.html", ""),
    ("/docs", "page=2&lang=en"),
    ("/docs", "preview"),
    ("/docs", "tag=a&x=1&tag=b"),
    ("/docs/", "page=2"),
    ("/a.css", "v=3"),
    ("/search", "q=a%20b%26c"),
    ("/caf%C3%A9", ""),
    ("/caf%C3%A9/", ""),
    ("/docs%2F", ""),
    ("/a%2Ecss", ""),
    ("/v1.2/guide", ""),
    ("/.well-known/security.txt", ""),
    ("/files/caf%C3%A9.pdf", ""),
]

NODE_RUNNER = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const handler = new Function(src + '\nreturn handler;')();
const events = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(events.map((e) => handler(e))));
"""


class BranchParityTests(unittest.TestCase):
    """Same branches and literals on both sides (static, regex level)."""

    def assert_both(self, js_pattern, py_pattern):
        self.assertRegex(JS, js_pattern)
        self.assertRegex(PY, py_pattern)

    def test_handler_entry_point(self):
        self.assertRegex(JS, r"function handler\(event\)")
        self.assertRegex(PY, r"def handler\(event")

    def test_branch_1_trailing_slash_rewrite(self):
        self.assert_both(r"uri\.endsWith\('/'\)", r'uri\.endswith\("/"\)')
        self.assert_both(r"request\.uri = uri \+ 'index\.html'", r'request\["uri"\] = uri \+ "index\.html"')

    def test_branch_2_last_segment_has_dot(self):
        self.assert_both(r"uri\.lastIndexOf\('/'\) \+ 1", r'uri\.rfind\("/"\) \+ 1')
        self.assert_both(r"lastSegment\.indexOf\('\.'\) !== -1", r'"\." in last_segment')

    def test_branch_3_redirect(self):
        self.assert_both(r"statusCode: 301", r'"statusCode": 301')
        self.assert_both(r"'Moved Permanently'", r'"Moved Permanently"')
        self.assert_both(r"uri \+ '/' \+ buildQueryString", r'uri \+ "/" \+ build_query_string')
        self.assert_both(r"'public, max-age=3600'", r'"public, max-age=3600"')

    def test_query_serialisation(self):
        self.assert_both(r"entry\.multiValue \? entry\.multiValue : \[entry\]",
                         r'entry\["multiValue"\] if entry\.get\("multiValue"\) else \[entry\]')
        self.assert_both(r"value === '' \? name : name \+ '=' \+ value",
                         r'name if value == "" else f"\{name\}=\{value\}"')
        self.assert_both(r"'\?' \+ parts\.join\('&'\)", r'"\?" \+ "&"\.join\(parts\)')

    def test_exactly_three_returns_in_handler(self):
        js_body = JS[JS.index("function handler(event)"):]
        py_body = PY[PY.index("def handler("):PY.index("def make_event(")]
        self.assertEqual(len(re.findall(r"\breturn\b", js_body)), 3)
        self.assertEqual(len(re.findall(r"\breturn\b", py_body)), 3)

    def test_js_avoids_unsupported_constructs(self):
        # cloudfront-js-2.0 has no module system or Node APIs.
        for forbidden in ("require(", "import ", "export ", "process.", "console.log"):
            self.assertNotIn(forbidden, JS)


@unittest.skipUnless(shutil.which("node"), "node not installed: JS execution test skipped")
class NodeExecutionTests(unittest.TestCase):
    """Run the real JS handler under node and compare with the Python spec."""

    @classmethod
    def setUpClass(cls):
        events = [make_event(uri, query) for uri, query in CASES]
        proc = subprocess.run(
            ["node", "-e", NODE_RUNNER, str(FUNCTION_JS)],
            input=json.dumps(events), capture_output=True, text=True, timeout=30, check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(f"node failed: {proc.stderr}")
        cls.js_results = json.loads(proc.stdout)
        cls.py_results = [handler(e) for e in events]

    def test_same_number_of_results(self):
        self.assertEqual(len(self.js_results), len(CASES))

    def test_js_output_identical_to_python(self):
        for (uri, query), js, py in zip(CASES, self.js_results, self.py_results):
            with self.subTest(uri=uri, query=query):
                self.assertEqual(js, py)

    def test_spot_checks(self):
        by_case = dict(zip(CASES, self.js_results))
        self.assertEqual(by_case[("/", "")]["uri"], "/index.html")
        self.assertEqual(by_case[("/docs", "")]["headers"]["location"]["value"], "/docs/")
        self.assertEqual(by_case[("/docs", "page=2&lang=en")]["headers"]["location"]["value"],
                         "/docs/?page=2&lang=en")
        self.assertEqual(by_case[("/a.css", "")]["uri"], "/a.css")


if __name__ == "__main__":
    unittest.main()
