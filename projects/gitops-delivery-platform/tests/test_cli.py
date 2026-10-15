"""CLI smoke tests: each script runs as a subprocess with the documented exit codes."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES, PROJECT, REPO_ROOT, SAMPLES, ScratchRepo


def run(*args, stdin=None):
    return subprocess.run([sys.executable, *map(str, args)], cwd=PROJECT, capture_output=True, text=True,
                          input=stdin, timeout=120, check=False)


class PromoteCliTests(unittest.TestCase):
    def test_dry_run_writes_nothing(self):
        with ScratchRepo() as repo:
            before = (repo / "envs/staging/values.yaml").read_bytes()
            proc = run("scripts/promote.py", "--config-repo", repo, "--from", "dev", "--to", "staging", "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("dry run: envs/staging/values.yaml not written", proc.stdout)
            self.assertIn("```diff", proc.stdout)
            self.assertEqual((repo / "envs/staging/values.yaml").read_bytes(), before)

    def test_write_and_pr_body_file(self):
        with ScratchRepo() as repo, tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "pr.md"
            proc = run("scripts/promote.py", "--config-repo", repo, "--from", "dev", "--to", "staging",
                       "--pr-body", body)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("wrote envs/staging/values.yaml", proc.stdout)
            self.assertTrue(body.read_text().startswith("## Promote orders-api to `staging`"))
            again = run("scripts/promote.py", "--config-repo", repo, "--from", "dev", "--to", "staging")
            self.assertEqual((again.returncode, again.stdout.strip()),
                             (0, "promote: staging already runs 9f3c2a7e5b1d4c8f6a0e2b7d9c1f3a5e7b9d0c2e; nothing to do"))

    def test_refusals_exit_1_and_usage_exit_2(self):
        with ScratchRepo() as repo:
            skip = run("scripts/promote.py", "--config-repo", repo, "--from", "dev", "--to", "prod")
            self.assertEqual(skip.returncode, 1)
            self.assertIn("REFUSED", skip.stdout)
            latest = run("scripts/promote.py", "--config-repo", repo, "--tag", "latest", "--to", "dev")
            self.assertEqual(latest.returncode, 1)
            hotfix = run("scripts/promote.py", "--config-repo", repo, "--from", "dev", "--to", "prod",
                         "--force-hotfix", "--reason", "INC-123", "--dry-run")
            self.assertEqual(hotfix.returncode, 0, hotfix.stderr)
            self.assertIn("Promotion-Hotfix: true", hotfix.stdout)
            noreason = run("scripts/promote.py", "--config-repo", repo, "--from", "dev", "--to", "prod",
                           "--force-hotfix")
            self.assertEqual(noreason.returncode, 2)
        missing = run("scripts/promote.py", "--config-repo", "/nonexistent", "--from", "dev", "--to", "staging")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("cannot read", missing.stderr)
        self.assertEqual(run("scripts/promote.py", "--to", "qa").returncode, 2)


class DriftCliTests(unittest.TestCase):
    def test_exit_codes_and_json(self):
        desired = SAMPLES / "desired" / "dev.yaml"
        self.assertEqual(run("scripts/drift_report.py", "--desired", desired,
                             "--live", SAMPLES / "live" / "dev-in-sync.json").returncode, 0)
        drift = run("scripts/drift_report.py", "--desired", desired, "--live", SAMPLES / "live" / "dev-drifted.json")
        self.assertEqual(drift.returncode, 1)
        self.assertTrue(drift.stdout.splitlines()[-1].startswith("summary: DRIFT: 1 of 9"))
        js = run("scripts/drift_report.py", "--desired", desired, "--live", SAMPLES / "live" / "dev-drifted.json",
                 "--format", "json")
        self.assertEqual(json.loads(js.stdout)["summary"]["fields"], 2)
        self.assertEqual(run("scripts/drift_report.py", "--desired", "-", "--live", FIXTURES / "drift" / "live.yaml",
                             stdin=(FIXTURES / "drift" / "desired.yaml").read_text()).returncode, 0)
        bad = run("scripts/drift_report.py", "--desired", desired, "--live", "/nonexistent.json")
        self.assertEqual(bad.returncode, 2)


class PolicyCliTests(unittest.TestCase):
    def test_good_bad_and_usage(self):
        good = run("scripts/check_gitops_policy.py", "--fail-on", "warning")
        self.assertEqual(good.returncode, 0, good.stdout)
        self.assertEqual(good.stdout.splitlines()[-1], "0 error(s), 0 warning(s)")
        bad = run("scripts/check_gitops_policy.py", "--config-repo", FIXTURES / "policy" / "bad")
        self.assertEqual(bad.returncode, 1)
        self.assertEqual(bad.stdout.splitlines()[-1], "23 error(s), 6 warning(s)")
        js = json.loads(run("scripts/check_gitops_policy.py", "--format", "json").stdout)
        self.assertEqual(js["findings"], [])
        self.assertEqual(run("scripts/check_gitops_policy.py", "--config-repo", "/nonexistent").returncode, 2)
        self.assertEqual(run("scripts/check_gitops_policy.py", "--business-hours", "17-8").returncode, 2)


class WorkflowLintTests(unittest.TestCase):
    """The repo's hardening linter on the real CI workflow and the app repo's example."""

    def test_both_workflows_lint_clean(self):
        linter = REPO_ROOT / "projects" / "devsecops-pipeline" / "policy" / "check_workflows.py"
        if not linter.is_file():
            self.skipTest("devsecops-pipeline linter not present")
        proc = subprocess.run([sys.executable, str(linter), "--fail-on", "warning",
                               ".github/workflows/gitops-delivery-platform.yml",
                               "projects/gitops-delivery-platform/app-repo/.github/workflows/ci.yml"],
                              cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("2 file(s) checked: 0 error(s), 0 warning(s)", proc.stdout)


if __name__ == "__main__":
    unittest.main()
