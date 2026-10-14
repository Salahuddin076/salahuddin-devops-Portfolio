"""Exit codes, the shipped fixtures, and CLI smoke tests via subprocess."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from helpers import FIXTURES, POLICY_DIR, PROJECT, SAMPLE_LOGS, SCRIPTS_DIR

import check_plan

COMPLIANT = str(FIXTURES / "plan-compliant.json")
NONCOMPLIANT = str(FIXTURES / "plan-noncompliant.json")
TODAY = ["--today", "2026-10-14"]


def call(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = check_plan.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class ExitCodeTests(unittest.TestCase):
    def test_compliant_fixture_exits_0(self):
        code, out, _ = call(COMPLIANT, *TODAY)
        self.assertEqual(code, 0, out)
        self.assertIn("Result: PASS", out)

    def test_compliant_fixture_passes_without_exceptions(self):
        self.assertEqual(call(COMPLIANT, "--no-exceptions", *TODAY)[0], 0)

    def test_noncompliant_fixture_exits_1_with_expected_rules(self):
        code, out, _ = call(NONCOMPLIANT, *TODAY)
        self.assertEqual(code, 1)
        report = check_plan.evaluate(json.loads(Path(NONCOMPLIANT).read_text()), NONCOMPLIANT,
                                     check_plan.load_exceptions(check_plan.default_exceptions_path()),
                                     check_plan.dt.date(2026, 10, 14))
        self.assertEqual(sorted((f.rule_id, f.address) for f in report.active), sorted([
            ("CSP-S3-001", "aws_s3_bucket.public_site"),
            ("CSP-S3-001", "aws_s3_bucket_public_access_block.uploads"),
            ("CSP-SG-001", "aws_security_group.admin"),
            ("CSP-IAM-001", "aws_iam_policy.break_glass"),
            ("CSP-RDS-001", "aws_db_instance.reporting"),
            ("CSP-CT-001", "aws_cloudtrail.main"),
            ("CSP-WAF-001", "aws_lb.public"),
        ]))
        self.assertEqual([(f.rule_id, f.address) for f in report.excepted],
                         [("CSP-SG-001", "aws_vpc_security_group_ingress_rule.legacy_bastion_ssh")])
        self.assertIn("Result: FAIL", out)

    def test_medium_only_plan_exits_0(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "plan.json"
            p.write_text(json.dumps({"resource_changes": [{"address": "aws_cloudtrail.t", "type": "aws_cloudtrail",
                                                           "name": "t", "change": {"actions": ["create"], "after": {}}}]}))
            code, out, _ = call(str(p), "--no-exceptions", *TODAY)
        self.assertEqual(code, 0)
        self.assertIn("CSP-CT-001", out)

    def test_input_errors_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text("{")
            notplan = Path(d) / "notplan.json"
            notplan.write_text("{}")
            badexc = Path(d) / "exc.json"
            badexc.write_text(json.dumps({"exceptions": [{"rule_id": "CSP-SG-001"}]}))
            for argv in ([str(Path(d) / "missing.json")], [str(bad)], [str(notplan)],
                         [COMPLIANT, "--exceptions", str(badexc)], [COMPLIANT, "--today", "tomorrow"]):
                with self.subTest(argv=argv):
                    code, _, err = call(*argv)
                    self.assertEqual(code, 2)
                    self.assertIn("error:", err)

    def test_output_file(self):
        with tempfile.TemporaryDirectory() as d:
            out_path = Path(d) / "r.sarif"
            code, out, _ = call(NONCOMPLIANT, "--format", "sarif", "--output", str(out_path), *TODAY)
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(out_path.read_text())["version"], "2.1.0")
            self.assertIn("FAIL", out)


class SubprocessSmokeTests(unittest.TestCase):
    def run_script(self, *argv):
        return subprocess.run([sys.executable, *argv], cwd=PROJECT, capture_output=True, text=True, timeout=60)

    def test_check_plan_text(self):
        ok = self.run_script(str(POLICY_DIR / "check_plan.py"), COMPLIANT, *TODAY)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        bad = self.run_script(str(POLICY_DIR / "check_plan.py"), NONCOMPLIANT, *TODAY)
        self.assertEqual(bad.returncode, 1)
        for rule in ("CSP-S3-001", "CSP-SG-001", "CSP-IAM-001", "CSP-RDS-001", "CSP-CT-001", "CSP-WAF-001"):
            self.assertIn(rule, bad.stdout)

    def test_check_plan_sarif_stdout(self):
        res = self.run_script(str(POLICY_DIR / "check_plan.py"), NONCOMPLIANT, "--format", "sarif", *TODAY)
        self.assertEqual(res.returncode, 1)
        self.assertEqual(json.loads(res.stdout)["version"], "2.1.0")

    def test_check_plan_list_rules(self):
        res = self.run_script(str(POLICY_DIR / "check_plan.py"), "--list-rules")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(len(res.stdout.strip().splitlines()), 6)

    def test_waf_log_summary(self):
        res = self.run_script(str(SCRIPTS_DIR / "waf_log_summary.py"), str(SAMPLE_LOGS))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Top blocked rules", res.stdout)
        self.assertIn("would newly block", res.stdout)
        res = self.run_script(str(SCRIPTS_DIR / "waf_log_summary.py"), "--json", str(SAMPLE_LOGS))
        self.assertEqual(json.loads(res.stdout)["records"], 47)

    def test_waf_log_summary_empty_input_exits_2(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl") as f:
            res = self.run_script(str(SCRIPTS_DIR / "waf_log_summary.py"), f.name)
        self.assertEqual(res.returncode, 2)


if __name__ == "__main__":
    unittest.main()
