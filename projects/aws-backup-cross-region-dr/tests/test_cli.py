"""CLI smoke tests through subprocess, exactly as CI and the README run them."""

import subprocess
import sys
import unittest

from helpers import BAD_POLICY_FILE, PROJECT, SAMPLE_JOBS


def run(*args):
    return subprocess.run([sys.executable, *args], cwd=PROJECT, capture_output=True, text=True, timeout=60)


class CliSmokeTests(unittest.TestCase):
    def test_policy_check_passes_on_shipped_policy(self):
        proc = run("scripts/check_plan_policy.py", "policy/backup-policy.json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Result: PASS", proc.stdout)

    def test_policy_check_fails_on_noncompliant_fixture(self):
        proc = run("scripts/check_plan_policy.py", str(BAD_POLICY_FILE.relative_to(PROJECT)))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL BKP-003", proc.stdout)

    def test_rpo_report_exits_1_on_sample(self):
        proc = run("scripts/rpo_rto_report.py", str(SAMPLE_JOBS.relative_to(PROJECT)))
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertTrue(proc.stdout.startswith("## RPO/RTO report (as of 2026-10-14T06:00:00Z)"))
        self.assertEqual(proc.stderr, "")

    def test_help_works_for_both_scripts(self):
        for script in ("scripts/check_plan_policy.py", "scripts/rpo_rto_report.py"):
            proc = run(script, "--help")
            self.assertEqual(proc.returncode, 0, script)
            self.assertIn("usage:", proc.stdout)

    def test_validator_package_imports_without_boto3(self):
        code = (
            "import sys; sys.path.insert(0, 'src/restore_validator'); "
            "import handler, adapters, validators, telemetry; "
            "assert 'boto3' not in sys.modules; print('ok')"
        )
        proc = run("-c", code)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ok")


class ReadmeExcerptTests(unittest.TestCase):
    """The README's sample output must be what the tools print today."""

    readme = (PROJECT / "README.md").read_text()

    def assertInReadme(self, *args):
        proc = run(*args)
        self.assertIn(proc.stdout, self.readme, f"README excerpt for {args} is stale")

    def test_rpo_report_excerpt(self):
        self.assertInReadme("scripts/rpo_rto_report.py", "sample-data/jobs.json")

    def test_policy_check_excerpts(self):
        self.assertInReadme("scripts/check_plan_policy.py", "policy/backup-policy.json")
        self.assertInReadme("scripts/check_plan_policy.py", "policy/fixtures/backup-policy-noncompliant.json")


if __name__ == "__main__":
    unittest.main()
