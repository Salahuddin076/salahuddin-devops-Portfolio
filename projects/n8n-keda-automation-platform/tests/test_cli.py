"""CLI smoke tests: each script runs as a subprocess with the documented exit codes."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import CHART_DIR, FIXTURES, PROJECT, SAMPLE_CSV


def run(*args, stdin=None):
    return subprocess.run([sys.executable, *map(str, args)], cwd=PROJECT, capture_output=True, text=True,
                          input=stdin, timeout=60, check=False)


class SimCliTests(unittest.TestCase):
    def test_text_output(self):
        proc = run("scripts/keda_scaling_sim.py", SAMPLE_CSV)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("not KEDA itself", proc.stdout)
        self.assertIn("KEDA activation", proc.stdout)
        self.assertIn("KEDA cooldown", proc.stdout)
        self.assertRegex(proc.stdout.splitlines()[-1], r"^summary: peak 10 replicas")

    def test_json_and_flag_override(self):
        proc = run("scripts/keda_scaling_sim.py", SAMPLE_CSV, "--values", CHART_DIR / "values.yaml",
                   "--max-replicas", "4", "--format", "json")
        data = json.loads(proc.stdout)
        self.assertEqual(data["settings"]["max_replicas"], 4)
        self.assertEqual(data["peak"], 4)
        self.assertIn("not KEDA itself", data["note"])

    def test_bad_csv_exit_2(self):
        proc = run("scripts/keda_scaling_sim.py", FIXTURES / "manifests" / "good.yaml")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", proc.stderr)


class PolicyCliTests(unittest.TestCase):
    def test_good_bad_and_stdin(self):
        self.assertEqual(run("scripts/check_chart_policy.py", FIXTURES / "manifests" / "good.yaml").returncode, 0)
        bad = run("scripts/check_chart_policy.py", FIXTURES / "manifests" / "bad.yaml")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("10 error(s), 1 warning(s)", bad.stdout)
        text = (FIXTURES / "manifests" / "good.yaml").read_text()
        self.assertEqual(run("scripts/check_chart_policy.py", "-", stdin=text).returncode, 0)

    def test_fail_on_warning_and_json(self):
        text = (FIXTURES / "manifests" / "good.yaml").read_text().replace("type: Recreate", "type: RollingUpdate")
        self.assertEqual(run("scripts/check_chart_policy.py", "-", stdin=text).returncode, 0)
        self.assertEqual(run("scripts/check_chart_policy.py", "-", "--fail-on", "warning", stdin=text).returncode, 1)
        data = json.loads(run("scripts/check_chart_policy.py", "-", "--format", "json", stdin=text).stdout)
        self.assertEqual([f["rule"] for f in data["findings"]], ["CP004"])

    def test_missing_file_exit_2(self):
        self.assertEqual(run("scripts/check_chart_policy.py", "does-not-exist.yaml").returncode, 2)


class GuardCliTests(unittest.TestCase):
    def test_demo_exit_codes(self):
        ok = run("scripts/duplicate_job_guard.py", "demo")
        self.assertEqual(ok.returncode, 0)
        self.assertIn("messages delivered: 1", ok.stdout)
        naive = run("scripts/duplicate_job_guard.py", "demo", "--no-guard")
        self.assertEqual(naive.returncode, 1)
        self.assertIn("messages delivered: 2", naive.stdout)

    def test_key_command(self):
        a = run("scripts/duplicate_job_guard.py", "key", "wf", "Send", "--execution-id", "101").stdout
        b = run("scripts/duplicate_job_guard.py", "key", "wf", "Send", "--execution-id", "102",
                "--retry-of", "101").stdout
        self.assertEqual(a, b)
        self.assertEqual(run("scripts/duplicate_job_guard.py", "key", "wf", "Send").returncode, 2)


if __name__ == "__main__":
    unittest.main()
