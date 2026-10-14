"""CLI smoke tests through a real subprocess (`python3 -m failover`)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import GCID, PROJECT, SRC_DIR


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        env = dict(os.environ, PYTHONPATH=str(SRC_DIR))
        cmd = [sys.executable, "-m", "failover", "--fake-world", "world.json", *args]
        return subprocess.run(cmd, capture_output=True, text=True, cwd=self.dir, env=env, timeout=60, check=False)

    def test_status(self):
        p = self.run_cli("status")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("us-east-1   primary      healthy      writer (global)", p.stdout)
        self.assertIn("Warnings: none", p.stdout)

    def test_status_json(self):
        p = self.run_cli("status", "--json")
        data = json.loads(p.stdout)
        self.assertEqual(data["global_writer"], "us-east-1")
        self.assertEqual([r["region"] for r in data["regions"]], ["us-east-1", "us-west-2"])

    def test_plan_prints_steps_and_changes_nothing(self):
        p = self.run_cli("plan", "--mode", "planned")
        self.assertEqual(p.returncode, 0, p.stderr)
        for n, sid in enumerate(["precheck", "fence-source", "promote-target", "scale-target",
                                 "flip-dns", "postcheck"], 1):
            self.assertIn(f"{n}. {sid}", p.stdout)
        self.assertIn("Nothing was executed.", p.stdout)
        self.assertFalse((self.dir / ".failover").exists())

    def test_execute_wrong_confirm_exits_2(self):
        p = self.run_cli("execute", "--mode", "planned", "--confirm", "nope", "--target", "us-west-2")
        self.assertEqual(p.returncode, 2)
        self.assertIn("does not match", p.stderr)
        audit = (self.dir / ".failover" / "audit.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(audit[-1])["status"], "confirm-mismatch")
        self.assertFalse((self.dir / ".failover" / "state.json").exists())

    def test_execute_then_status_then_failback_refused(self):
        p = self.run_cli("execute", "--mode", "planned", "--confirm", GCID, "--target", "us-west-2")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("[6/6] postcheck", p.stdout)
        lines = (self.dir / ".failover" / "audit.jsonl").read_text().splitlines()
        records = [json.loads(line) for line in lines]
        self.assertEqual(records[0]["event"], "run_started")
        self.assertEqual(records[-1]["event"], "run_completed")

        s = self.run_cli("status")
        self.assertIn("DNS PRIMARY: us-west-2", s.stdout)

        f = self.run_cli("execute", "--mode", "planned", "--confirm", GCID, "--target", "us-east-1")
        self.assertEqual(f.returncode, 3)
        self.assertIn("failback refused", f.stderr)

    def test_lagging_scenario_exits_4(self):
        p = self.run_cli("--scenario", "lagging", "execute", "--mode", "planned", "--confirm", GCID)
        self.assertEqual(p.returncode, 4)
        self.assertIn("42.0s", p.stderr)

    def test_aws_adapters_need_explicit_config(self):
        p = self.run_cli("--adapters", "aws", "status")
        self.assertEqual(p.returncode, 2)
        self.assertIn("explicit --config", p.stderr)

    def test_bad_config_exits_2(self):
        bad = self.dir / "bad.json"
        bad.write_text('{"primary_region": "us-east-1"}')
        p = self.run_cli("--config", str(bad), "status")
        self.assertEqual(p.returncode, 2)
        self.assertIn("dr_region", p.stderr)

    def test_package_imports_without_boto3(self):
        code = ("import sys; import failover.cli, failover.aws, failover.orchestrator; "
                "print('boto3' in sys.modules)")
        env = dict(os.environ, PYTHONPATH=str(SRC_DIR))
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                           cwd=PROJECT, timeout=60, check=False)
        self.assertEqual(p.stdout.strip(), "False", p.stderr)


if __name__ == "__main__":
    unittest.main()
