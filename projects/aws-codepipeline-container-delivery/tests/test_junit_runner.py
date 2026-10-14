import io
import itertools
import os
import sys
import tempfile
import textwrap
import unittest
import xml.etree.ElementTree as ET

import helpers  # noqa: F401  (sys.path)

import junit_runner

SAMPLE = textwrap.dedent(
    """
    import unittest

    class Sample(unittest.TestCase):
        def test_pass(self):
            self.assertTrue(True)

        def test_fail(self):
            self.assertEqual(1, 2)

        def test_error(self):
            raise RuntimeError("boom")

        @unittest.skip("not today")
        def test_skip(self):
            pass
    """
)


_COUNTER = itertools.count()


class JunitRunnerTests(unittest.TestCase):
    def _run(self, source):
        # A unique module name per run: unittest refuses to re-import a
        # module name already in sys.modules from another directory.
        module = f"test_junit_sample_{next(_COUNTER)}"
        self.addCleanup(sys.modules.pop, module, None)
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = os.path.join(tmp, "sample_tests")
            os.makedirs(tests_dir)
            with open(os.path.join(tests_dir, f"{module}.py"), "w", encoding="utf-8") as handle:
                handle.write(source)
            output = os.path.join(tmp, "reports", "junit", "unit.xml")
            code = junit_runner.run(tests_dir, output, "sample", top_level_dir=tests_dir, stream=io.StringIO())
            tree = ET.parse(output)
        return code, tree.getroot()

    def test_report_counts_and_exit_code(self):
        code, root = self._run(SAMPLE)
        self.assertEqual(code, 1)
        module = root.find("testsuite").find("testcase").get("classname").split(".")[0]
        suite = root.find("testsuite")
        self.assertEqual(
            {k: suite.get(k) for k in ("name", "tests", "failures", "errors", "skipped")},
            {"name": "sample", "tests": "4", "failures": "1", "errors": "1", "skipped": "1"},
        )
        cases = {case.get("name"): case for case in suite.findall("testcase")}
        self.assertEqual(sorted(cases), ["test_error", "test_fail", "test_pass", "test_skip"])
        self.assertIsNotNone(cases["test_fail"].find("failure"))
        self.assertIn("boom", cases["test_error"].find("error").get("message"))
        self.assertEqual(cases["test_skip"].find("skipped").get("message"), "not today")
        self.assertEqual(cases["test_pass"].get("classname"), f"{module}.Sample")

    def test_all_passing_exits_0(self):
        source = "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
        code, root = self._run(source)
        self.assertEqual(code, 0)
        self.assertEqual(root.find("testsuite").get("tests"), "1")


if __name__ == "__main__":
    unittest.main()
