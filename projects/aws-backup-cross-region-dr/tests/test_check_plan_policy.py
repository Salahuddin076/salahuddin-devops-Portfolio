"""Backup policy checker: each check on good and bad input, cron parsing, exit codes."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from helpers import BAD_POLICY_FILE, POLICY_FILE

import check_plan_policy as cpp

GOOD = json.loads(POLICY_FILE.read_text())


def checks_for(policy):
    findings, _ = cpp.evaluate(policy)
    return sorted({f.check for f in findings}), findings


def mutate(fn):
    policy = copy.deepcopy(GOOD)
    fn(policy)
    return policy


def gold(policy, name):
    return next(r for r in policy["plans"]["gold"]["rules"] if r["name"] == name)


def call(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cpp.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class ShippedFilesTests(unittest.TestCase):
    def test_shipped_policy_passes(self):
        self.assertEqual(checks_for(GOOD)[0], [])

    def test_noncompliant_fixture_trips_every_check(self):
        ids, findings = checks_for(json.loads(BAD_POLICY_FILE.read_text()))
        self.assertEqual(ids, sorted(cpp.CHECKS))
        self.assertEqual(len(findings), 9)


class CheckTests(unittest.TestCase):
    def test_bkp001_gold_without_copy(self):
        ids, findings = checks_for(mutate(lambda p: gold(p, "weekly").update(copy_to_dr=False)))
        self.assertEqual(ids, ["BKP-001"])
        self.assertEqual(findings[0].where, "gold/weekly")

    def test_bkp001_silver_without_copy_is_fine(self):
        self.assertEqual(checks_for(GOOD)[0], [])
        self.assertFalse(GOOD["plans"]["silver"]["rules"][0]["copy_to_dr"])

    def test_bkp002_primary_and_dr_minimums(self):
        ids, findings = checks_for(mutate(lambda p: gold(p, "monthly").update(delete_after_days=200, dr_delete_after_days=180)))
        self.assertEqual(ids, ["BKP-002"])
        self.assertEqual(len(findings), 2)

    def test_bkp003_cold_storage_gap(self):
        # 365 - 276 = 89 days in cold: one short.
        ids, findings = checks_for(mutate(lambda p: gold(p, "monthly").update(cold_storage_after_days=276)))
        self.assertEqual(ids, ["BKP-003"])
        self.assertIn("276d + 90d = 366d > delete at 365d", findings[0].message)

    def test_bkp003_exact_90_days_is_allowed(self):
        self.assertEqual(checks_for(mutate(lambda p: gold(p, "monthly").update(cold_storage_after_days=275)))[0], [])

    def test_bkp003_dr_copy_lifecycle(self):
        ids, _ = checks_for(mutate(lambda p: gold(p, "monthly").update(dr_cold_storage_after_days=300)))
        self.assertEqual(ids, ["BKP-003"])

    def test_bkp004_bad_schedule(self):
        ids, _ = checks_for(mutate(lambda p: gold(p, "daily").update(schedule="0 3 * * *")))
        self.assertEqual(ids, ["BKP-004"])

    def test_bkp005_min_greater_than_max(self):
        ids, _ = checks_for(mutate(lambda p: p["vault_lock"].update(min_retention_days=500)))
        self.assertIn("BKP-005", ids)

    def test_bkp005_mode_and_grace(self):
        self.assertEqual(checks_for(mutate(lambda p: p["vault_lock"].update(mode="strict")))[0], ["BKP-005"])
        ok = mutate(lambda p: p["vault_lock"].update(mode="compliance", changeable_for_days=3))
        self.assertEqual(checks_for(ok)[0], [])
        bad = mutate(lambda p: p["vault_lock"].update(mode="compliance", changeable_for_days=None))
        self.assertEqual(checks_for(bad)[0], ["BKP-005"])

    def test_bkp006_retention_outside_lock(self):
        ids, findings = checks_for(mutate(lambda p: p["vault_lock"].update(min_retention_days=10)))
        self.assertEqual(ids, ["BKP-006"])
        self.assertEqual(findings[0].where, "silver/daily")

    def test_bkp007_continuous_limits(self):
        ids, _ = checks_for(mutate(lambda p: gold(p, "weekly").update(continuous=True)))
        self.assertEqual(ids, ["BKP-007"])


class CronTests(unittest.TestCase):
    def test_valid(self):
        for expr in ("cron(0 3 * * ? *)", "cron(0 4 ? * SUN *)", "cron(0 5 1 * ? *)", "cron(15 0/6 * * ? *)",
                     "cron(0 2 ? * MON-FRI *)", "cron(0 1 L * ? *)", "cron(0 1 ? * 6#3 *)", "cron(0 0 1 JAN,JUL ? 2027)"):
            self.assertIsNone(cpp.cron_error(expr), expr)

    def test_invalid(self):
        cases = {
            "rate(1 day)": "cron(",
            "cron(0 3 * * *)": "6 fields",
            "cron(0 3 * * MON *)": "exactly one",
            "cron(0 3 ? * ? *)": "exactly one",
            "cron(60 3 * * ? *)": "minutes",
            "cron(0 24 * * ? *)": "hours",
            "cron(0 3 32 * ? *)": "day-of-month",
            "cron(0 3 ? * FOO *)": "day-of-week",
            "cron(0 3 5-1 * ? *)": "backwards",
            "cron(0/0 3 * * ? *)": "step",
            "cron(*/5 3 * * ? *)": "once per hour",
        }
        for expr, fragment in cases.items():
            error = cpp.cron_error(expr)
            self.assertIsNotNone(error, expr)
            self.assertIn(fragment, error, expr)
        self.assertIsNotNone(cpp.cron_error(None))


class CliTests(unittest.TestCase):
    def test_good_exit_0(self):
        code, out, _ = call(str(POLICY_FILE))
        self.assertEqual(code, 0)
        self.assertIn("Result: PASS", out)

    def test_bad_exit_1(self):
        code, out, _ = call(str(BAD_POLICY_FILE))
        self.assertEqual(code, 1)
        self.assertIn("Summary: 9 finding(s) in 7 check(s). Result: FAIL", out)

    def test_list_checks(self):
        code, out, _ = call("--list-checks")
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), len(cpp.CHECKS))

    def test_malformed_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_json = Path(tmp) / "bad.json"
            bad_json.write_text("{not json")
            self.assertEqual(call(str(bad_json))[0], 2)
            no_plans = Path(tmp) / "noplans.json"
            no_plans.write_text(json.dumps({"vault_lock": {}, "retention_minimums_days": {}}))
            code, _, err = call(str(no_plans))
            self.assertEqual(code, 2)
            self.assertIn("plans", err)
            broken = mutate(lambda p: gold(p, "daily").update(delete_after_days="35"))
            typed = Path(tmp) / "typed.json"
            typed.write_text(json.dumps(broken))
            self.assertEqual(call(str(typed))[0], 2)
        self.assertEqual(call("/nonexistent.json")[0], 2)


if __name__ == "__main__":
    unittest.main()
