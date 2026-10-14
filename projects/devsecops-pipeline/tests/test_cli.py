"""CLI smoke tests: run the scripts as subprocesses, as CI does."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import helpers

PY = sys.executable


def run(*args):
    return subprocess.run([PY, *map(str, args)], capture_output=True, text=True, cwd=helpers.PROJECT, timeout=60)


class CheckWorkflowsCli(unittest.TestCase):
    SCRIPT = helpers.POLICY_DIR / "check_workflows.py"

    def test_own_workflows_pass(self):
        r = run(self.SCRIPT, "--uri-base", helpers.REPO_ROOT, *helpers.OWN_WORKFLOWS)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("2 file(s) checked: 0 error(s), 0 warning(s)", r.stdout)

    def test_bad_fixture_fails_with_text_report(self):
        r = run(self.SCRIPT, helpers.WORKFLOW_FIXTURES / "bad-injection.yml")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ERROR WF030 script-injection", r.stdout)

    def test_warnings_only_pass_unless_fail_on_warning(self):
        text = (
            "on: push\npermissions:\n  contents: read\njobs:\n  a:\n    runs-on: x\n    steps:\n"
            "      - uses: actions/setup-python@v5\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp) / "w.yml"
            wf.write_text(text)
            self.assertEqual(run(self.SCRIPT, wf).returncode, 0)
            self.assertEqual(run(self.SCRIPT, wf, "--fail-on", "warning").returncode, 1)

    def test_sarif_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.sarif"
            r = run(self.SCRIPT, helpers.WORKFLOW_FIXTURES, "--format", "sarif", "--output", out,
                    "--uri-base", helpers.PROJECT)
            self.assertEqual(r.returncode, 1)
            sarif = json.loads(out.read_text())
            uris = {res["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for res in sarif["runs"][0]["results"]}
            self.assertIn("tests/fixtures/workflows/bad-pr-target.yml", uris)

    def test_whole_repo_runs_read_only(self):
        before = {p: p.stat().st_mtime_ns for p in helpers.REPO_WORKFLOWS.glob("*.yml")}
        r = run(self.SCRIPT, helpers.REPO_WORKFLOWS)
        self.assertIn(r.returncode, (0, 1))
        self.assertIn("file(s) checked", r.stdout)
        self.assertNotIn("WF000", r.stdout)
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in helpers.REPO_WORKFLOWS.glob("*.yml")})

    def test_missing_path_is_usage_error(self):
        self.assertEqual(run(self.SCRIPT, "does/not/exist").returncode, 2)


class TrivyignoreCli(unittest.TestCase):
    SCRIPT = helpers.POLICY_DIR / "trivyignore_check.py"

    def test_shipped_file_passes(self):
        r = run(self.SCRIPT, helpers.PROJECT / ".trivyignore")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("0 problem(s)", r.stdout)

    def test_bad_fixture_fails(self):
        r = run(self.SCRIPT, helpers.TRIVYIGNORE_FIXTURES / "bad.trivyignore", "--today", "2026-10-14")
        self.assertEqual(r.returncode, 1)
        self.assertIn("TI003", r.stdout)

    def test_missing_file(self):
        self.assertEqual(run(self.SCRIPT, "nope.trivyignore").returncode, 2)


if __name__ == "__main__":
    unittest.main()
