"""End-to-end smoke tests: run ``python3 -m finops`` as a subprocess."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import PROJECT_DIR


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "finops", *args],
        cwd=PROJECT_DIR, capture_output=True, text=True, timeout=120,
    )


class CliSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.data = Path(cls._tmp.name) / "data"
        proc = run("generate", "--out", str(cls.data), "--days", "45", "--seed", "3")
        assert proc.returncode == 0, proc.stderr

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_allocate_json(self):
        proc = run("allocate", "--input", str(self.data), "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertGreater(float(payload["total"]), 0)
        self.assertIn("team", payload["untagged_by_key"])

    def test_text_commands_succeed(self):
        for cmd in ("rightsize", "commitments", "forecast"):
            with self.subTest(cmd=cmd):
                proc = run(cmd, "--input", str(self.data))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertTrue(proc.stdout.strip())

    def test_budget_gate_exit_codes(self):
        ok = run("budget", "--input", str(self.data), "--budget", "1000000")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        breach = run("budget", "--input", str(self.data), "--budget", "1")
        self.assertEqual(breach.returncode, 3)
        self.assertIn("BREACH", breach.stdout)
        self.assertIn("budget gate", breach.stderr)

    def test_report_writes_markdown_html_and_json(self):
        out = Path(self._tmp.name) / "report"
        proc = run("report", "--input", str(self.data), "--out", str(out), "--html", "--budget", "5000")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        md = (out / "report.md").read_text()
        for heading in ("Cost allocation", "Rightsizing", "Commitments", "Forecast", "Budget"):
            self.assertIn(heading, md)
        self.assertIn("No real savings are claimed", md)
        self.assertTrue((out / "report.html").read_text().startswith("<!doctype html>"))
        self.assertIn("commitments", json.loads((out / "summary.json").read_text()))

    def test_missing_input_is_a_clean_error(self):
        proc = run("allocate", "--billing", str(Path(self._tmp.name) / "nope.csv"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("file not found", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
