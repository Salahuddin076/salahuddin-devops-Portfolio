"""RPO/RTO report: the math on the sample, edge cases and the exit code."""

import copy
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone

from helpers import POLICY_FILE, SAMPLE_JOBS

import rpo_rto_report as rr

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)
POLICY = json.loads(POLICY_FILE.read_text())
SAMPLE = json.loads(SAMPLE_JOBS.read_text())


def call(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = rr.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def by_name(reports):
    return {r.name: r for r in reports}


class SampleMathTests(unittest.TestCase):
    reports = by_name(rr.build_report(SAMPLE, POLICY, NOW))

    def test_healthy_gold_resource(self):
        r = self.reports["orders-db"]
        self.assertEqual(rr.fmt_hours(r.last_backup_age), "2h55m")   # 03:04:31 -> 06:00
        self.assertEqual(rr.fmt_hours(r.copy_lag), "0h40m")           # backup done 03:39:31, copy done 04:20
        self.assertEqual((r.tests_passed, r.tests_finished), (2, 2))
        self.assertEqual(rr.fmt_hours(r.worst_restore), "0h52m")
        self.assertEqual(r.status, "OK")

    def test_rpo_breach_uses_last_successful_backup(self):
        r = self.reports["sessions-table"]
        self.assertAlmostEqual(r.last_backup_age, 50 + 57 / 60 + 55 / 3600, places=4)  # 2026-10-12T03:02:05
        self.assertTrue(r.rpo_breach)
        self.assertEqual(r.status, "RPO BREACH")

    def test_failed_copy_and_dr_age(self):
        r = self.reports["media-assets"]
        self.assertEqual(r.last_copy_state, "FAILED")
        self.assertEqual(rr.fmt_hours(r.dr_copy_age), "26h50m")  # newest copied point is 10-13 03:10
        self.assertFalse(r.rpo_breach)
        self.assertTrue(r.rto_breach)
        self.assertEqual(r.status, "COPY FAILED, RTO BREACH")
        self.assertTrue(any("destination vault key" in f for f in r.findings))

    def test_restore_pass_rate(self):
        r = self.reports["build-cache"]
        self.assertEqual((r.tests_passed, r.tests_finished), (1, 2))
        self.assertEqual(r.status, "RESTORE TEST FAILED")

    def test_silver_dr_age_not_flagged_and_missing_tests_noted(self):
        r = self.reports["reports-db"]
        self.assertEqual(r.status, "OK")
        self.assertEqual(r.tests_finished, 0)
        self.assertIsNone(r.worst_restore)
        self.assertEqual(r.findings, ["reports-db: no restore test on record, RTO unproven"])

    def test_targets_come_from_policy(self):
        self.assertEqual((self.reports["orders-db"].rpo_hours, self.reports["orders-db"].rto_hours), (26.0, 4.0))
        self.assertEqual(self.reports["build-cache"].rpo_hours, 50.0)


class EdgeCaseTests(unittest.TestCase):
    def test_no_successful_backup_is_a_breach(self):
        data = copy.deepcopy(SAMPLE)
        for job in data["backup_jobs"]["BackupJobs"]:
            if job["ResourceArn"].endswith("db:orders-db"):
                job["State"] = "FAILED"
        r = by_name(rr.build_report(data, POLICY, NOW))["orders-db"]
        self.assertIsNone(r.last_backup_age)
        self.assertTrue(r.rpo_breach)
        self.assertIn("no successful backup on record", r.findings[0])

    def test_restore_without_validation_is_not_a_pass(self):
        data = copy.deepcopy(SAMPLE)
        for job in data["restore_jobs"]["RestoreJobs"]:
            job.pop("ValidationStatus", None)
        r = by_name(rr.build_report(data, POLICY, NOW))["orders-db"]
        self.assertEqual((r.tests_passed, r.tests_finished), (0, 2))

    def test_running_restore_is_excluded(self):
        data = copy.deepcopy(SAMPLE)
        data["restore_jobs"]["RestoreJobs"][0]["Status"] = "RUNNING"
        r = by_name(rr.build_report(data, POLICY, NOW))["orders-db"]
        self.assertEqual(r.tests_finished, 1)

    def test_time_parsing(self):
        self.assertEqual(rr.parse_time("2026-10-14T06:00:00Z"), NOW)
        self.assertEqual(rr.parse_time("2026-10-14T08:00:00.000000+02:00"), NOW)
        self.assertEqual(rr.fmt_hours(None), "n/a")
        self.assertEqual(rr.fmt_hours(1.9999), "2h00m")

    def test_jobs_after_now_are_ignored(self):
        earlier = datetime(2026, 10, 13, 5, 0, tzinfo=timezone.utc)
        reports = by_name(rr.build_report(SAMPLE, POLICY, earlier))
        media = reports["media-assets"]
        self.assertEqual(media.last_copy_state, "COMPLETED")  # the failed copy starts on 10-14
        self.assertEqual(rr.fmt_hours(media.last_backup_age), "1h50m")
        self.assertEqual(rr.fmt_hours(reports["sessions-table"].last_backup_age), "25h58m")
        self.assertFalse(any(r.rpo_breach for r in reports.values()))

    def test_unknown_tier_is_input_error(self):
        data = copy.deepcopy(SAMPLE)
        data["resources"][0]["tier"] = "bronze"
        with self.assertRaises(rr.InputError):
            rr.build_report(data, POLICY, NOW)


class ExitCodeTests(unittest.TestCase):
    def test_sample_exits_1_on_gold_rpo_breach(self):
        code, out, _ = call(str(SAMPLE_JOBS))
        self.assertEqual(code, 1)
        self.assertIn("Result: FAIL (1 gold resource(s) breach RPO: sessions-table)", out)
        self.assertIn("| sessions-table | DynamoDB | gold | 50h58m | 26h00m |", out)

    def test_exits_0_when_no_gold_breach(self):
        # Evaluated the morning after the last good backup, nothing is stale yet.
        code, out, _ = call(str(SAMPLE_JOBS), "--now", "2026-10-13T05:00:00Z")
        self.assertEqual(code, 0, out)
        self.assertIn("Result: PASS", out)

    def test_silver_breach_alone_does_not_fail(self):
        data = copy.deepcopy(SAMPLE)
        data["resources"] = [r for r in data["resources"] if r["tier"] == "silver"]
        reports = rr.build_report(data, POLICY, datetime(2026, 10, 20, tzinfo=timezone.utc))
        self.assertTrue(all(r.rpo_breach for r in reports))
        self.assertIn("Result: PASS", rr.render_markdown(reports, NOW))

    def test_markdown_table_shape(self):
        _, out, _ = call(str(SAMPLE_JOBS))
        rows = [line for line in out.splitlines() if line.startswith("| ")]
        self.assertEqual(len(rows), 1 + len(SAMPLE["resources"]))
        self.assertTrue(all(line.count("|") == 13 for line in rows))

    def test_bad_input_exits_2(self):
        self.assertEqual(call("/nonexistent/jobs.json")[0], 2)
        code, _, err = call(str(SAMPLE_JOBS), "--policy", str(SAMPLE_JOBS))
        self.assertEqual(code, 2)
        self.assertIn("targets", err)


if __name__ == "__main__":
    unittest.main()
