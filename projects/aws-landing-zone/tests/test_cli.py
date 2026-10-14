"""CLI smoke tests through subprocess, and exit codes through main()."""

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

from helpers import BAD_SCPS, FIXTURES, POLICY_DIR, PROJECT

import check_scps
import cidr_plan
import simulate_scp


def cli(script, *args):
    proc = subprocess.run([sys.executable, str(POLICY_DIR / script), *args],
                          capture_output=True, text=True, cwd=PROJECT, timeout=60)
    return proc.returncode, proc.stdout, proc.stderr


def call(module, *argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = module.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CheckScpsCliTests(unittest.TestCase):
    def test_shipped_policies_exit_0(self):
        code, out, err = cli("check_scps.py")
        self.assertEqual(code, 0, out + err)
        self.assertIn("Result: PASS", out)
        self.assertIn("root 4/5", out)

    def test_bad_fixtures_exit_1(self):
        code, out, _ = cli("check_scps.py", "--scp-dir", str(BAD_SCPS), "--attachments", str(BAD_SCPS / "attachments.json"))
        self.assertEqual(code, 1)
        self.assertIn("Summary: 7 finding(s). Result: FAIL", out)

    def test_list_rules(self):
        code, out, _ = call(check_scps, "--list-rules")
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), len(check_scps.RULES))

    def test_missing_dir_exit_2(self):
        code, _, err = call(check_scps, "--scp-dir", "/nonexistent/scps")
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_bad_flag_exit_2(self):
        self.assertEqual(call(check_scps, "--nope")[0], 2)

    def test_no_attachments_flag(self):
        code, out, _ = call(check_scps, "--scp-dir", str(BAD_SCPS), "--no-attachments")
        self.assertEqual(code, 1)
        self.assertNotIn("SCP-007", out)


class SimulateCliTests(unittest.TestCase):
    def test_denied_exit_1(self):
        code, out, _ = cli("simulate_scp.py", "--ou", "prod", "--action", "ec2:RunInstances", "--region", "ap-southeast-1")
        self.assertEqual(code, 1)
        self.assertIn("DENY   region-allowlist/DenyOutsideAllowedRegions (attached to root)", out)
        self.assertIn("Result: DENIED", out)

    def test_global_service_exit_0(self):
        code, out, _ = cli("simulate_scp.py", "--ou", "prod", "--action", "iam:CreateRole", "--region", "ap-southeast-1")
        self.assertEqual(code, 0)
        self.assertIn("Result: NOT DENIED", out)

    def test_root_flag(self):
        code, out, _ = call(simulate_scp, "--ou", "security", "--action", "s3:ListAllMyBuckets",
                            "--region", "us-east-1", "--root")
        self.assertEqual(code, 1)
        self.assertIn("arn:aws:iam::123456789012:root", out)
        self.assertIn("deny-root-user/DenyRootUserActions", out)

    def test_context_flag(self):
        args = ["--ou", "sandbox", "--action", "ec2:RunInstances", "--region", "eu-west-1"]
        self.assertEqual(call(simulate_scp, *args)[0], 1)
        self.assertEqual(call(simulate_scp, *args, "--context", "ec2:MetadataHttpTokens=required")[0], 0)

    def test_suspended(self):
        code, out, _ = call(simulate_scp, "--ou", "suspended", "--action", "sts:GetCallerIdentity", "--region", "us-east-1")
        self.assertEqual(code, 1)
        self.assertIn("deny-all/DenyAllSuspendedAccount", out)

    def test_bad_context_exit_2(self):
        code, _, err = call(simulate_scp, "--ou", "prod", "--action", "s3:GetObject", "--region", "us-east-1",
                            "--context", "novalue")
        self.assertEqual(code, 2)
        self.assertIn("KEY=VALUE", err)

    def test_unknown_ou_exit_2(self):
        self.assertEqual(call(simulate_scp, "--ou", "finance", "--action", "s3:GetObject", "--region", "us-east-1")[0], 2)

    def test_missing_required_flag_exit_2(self):
        self.assertEqual(call(simulate_scp, "--ou", "prod")[0], 2)


class CidrPlanCliTests(unittest.TestCase):
    def test_shipped_plan_exit_0(self):
        code, out, _ = cli("cidr_plan.py")
        self.assertEqual(code, 0)
        self.assertIn("Next free spoke block: 10.2.0.0/16", out)
        self.assertIn("Result: PASS", out)

    def test_bad_plan_exit_1(self):
        code, out, _ = cli("cidr_plan.py", str(FIXTURES / "cidr-plan-bad.json"))
        self.assertEqual(code, 1)
        self.assertIn("CIDR-004", out)

    def test_missing_file_exit_2(self):
        self.assertEqual(call(cidr_plan, "/nonexistent/plan.json")[0], 2)


if __name__ == "__main__":
    unittest.main()
