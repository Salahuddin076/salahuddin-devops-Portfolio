"""CLI smoke tests through subprocess: exit codes and output shape."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import HEADERS_BAD, HEADERS_GOOD, PROJECT, SAMPLE_BUILD, SAMPLE_MANIFEST, SCRIPTS_DIR


def run(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS_DIR / script), *map(str, args)],
                          capture_output=True, text=True, cwd=PROJECT, timeout=60, check=False)


class DeployPlanCliTests(unittest.TestCase):
    def test_sample_plan(self):
        proc = run("deploy_plan.py", SAMPLE_BUILD, "--manifest", SAMPLE_MANIFEST)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        plan = json.loads(proc.stdout)
        self.assertEqual(set(plan), {"upload", "delete", "retained", "invalidation", "summary"})

    def test_threshold_flag(self):
        proc = run("deploy_plan.py", SAMPLE_BUILD, "--manifest", SAMPLE_MANIFEST, "--threshold", "2", "--compact")
        self.assertEqual(json.loads(proc.stdout)["invalidation"]["paths"], ["/*"])

    def test_bad_manifest_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "m.json"
            bad.write_text("{not json")
            proc = run("deploy_plan.py", SAMPLE_BUILD, "--manifest", bad)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not valid JSON", proc.stderr)

    def test_missing_build_exits_2(self):
        self.assertEqual(run("deploy_plan.py", "/nonexistent", "--manifest", SAMPLE_MANIFEST).returncode, 2)

    def test_empty_manifest_file_means_empty_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "m.json"
            empty.write_text("")
            proc = run("deploy_plan.py", SAMPLE_BUILD, "--manifest", empty, "--compact")
        self.assertEqual(json.loads(proc.stdout)["summary"]["new"], 8)


class CheckHeadersCliTests(unittest.TestCase):
    def test_good_exits_0(self):
        proc = run("check_headers.py", HEADERS_GOOD)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Result: PASS", proc.stdout)

    def test_bad_exits_1(self):
        proc = run("check_headers.py", HEADERS_BAD)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Result: FAIL (5 fail, 0 warn)", proc.stdout)

    def test_json_output(self):
        data = json.loads(run("check_headers.py", HEADERS_BAD, "--json").stdout)
        self.assertEqual(data["result"], "FAIL")
        self.assertEqual(len(data["findings"]), 5)

    def test_missing_file_exits_2(self):
        self.assertEqual(run("check_headers.py", "/nonexistent/headers.txt").returncode, 2)

    def test_url_must_be_https(self):
        # Rejected before any network access.
        proc = run("check_headers.py", "--url", "http://www.example.com/")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("https://", proc.stderr)

    def test_file_and_url_are_exclusive(self):
        self.assertEqual(run("check_headers.py", HEADERS_GOOD, "--url", "https://www.example.com/").returncode, 2)


class RewriteCliTests(unittest.TestCase):
    def test_decisions(self):
        proc = run("rewrite.py", "/", "/docs?x=1", "/a.css")
        self.assertEqual(proc.returncode, 0)
        lines = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual([d["action"] for d in lines], ["rewrite", "redirect", "pass"])
        self.assertEqual(lines[1]["location"], "/docs/?x=1")

    def test_relative_uri_exits_2(self):
        self.assertEqual(run("rewrite.py", "docs").returncode, 2)


if __name__ == "__main__":
    unittest.main()
