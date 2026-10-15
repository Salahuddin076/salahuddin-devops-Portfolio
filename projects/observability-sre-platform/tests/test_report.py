"""Error-budget report on the sample CSV, with the expected numbers worked out by hand.

The sample (sample-data/checkout-api-availability-hourly.csv) is 168 hours ending
2026-09-01T01:00Z .. 2026-09-08T00:00Z, 10000 requests every hour, against the
99.9% / 30d checkout availability SLO (budget 0.1% = 10 errors per hour at 1x):

  row i (0-based) ends at 2026-09-01T00:00Z + (i+1)h
  baseline     4 errors/h  (0.4x)
  incident    rows 60-61, 300 errors/h (30x)
  degradation rows 110-139, 35 errors/h (3.5x)
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from helpers import SAMPLE_CSV, SLO_DIR

import slogen

START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def at(row: int) -> datetime:
    return START + timedelta(hours=row + 1)


class SampleReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        service = slogen.load_service(SLO_DIR / "checkout-api.json")
        cls.slo = service["slos"][0]
        cls.rows = slogen.read_hourly_csv(SAMPLE_CSV)
        cls.rep = slogen.error_budget_report(cls.rows, cls.slo)

    def first(self, tier):
        return next(a for a in self.rep["alerts"] if a["tier"] == tier)

    def test_totals(self):
        self.assertEqual(self.rep["hours"], 168)
        self.assertEqual(self.rep["requests"], 168 * 10000)
        # 136 baseline hours x 4 + 2 x 300 + 30 x 35
        self.assertEqual(self.rep["errors"], 136 * 4 + 600 + 1050)

    def test_budget_consumed(self):
        # Each hour burns (errors / 10000) / 0.001 = errors / 10; over a 720h window
        # that hour spends burn / 720 of the budget. 2194 / 10 / 720 = 0.304722...
        self.assertAlmostEqual(self.rep["budget_consumed"], 2194 / 7200, places=12)
        self.assertAlmostEqual(self.rep["budget_remaining"], 1 - 2194 / 7200, places=12)

    def test_page_1h_first_fires_on_the_first_incident_hour(self):
        # Row 60: 1h burn = 300/10000/0.001 = 30x > 14.4 (5m approximated by the hour).
        a = self.first("page-1h")
        self.assertEqual(a["fired"], at(60))
        self.assertEqual(a["fired"], datetime(2026, 9, 3, 13, tzinfo=timezone.utc))
        self.assertEqual(a["resolved"], at(62))
        self.assertAlmostEqual(a["peak_long_burn"], 30.0)

    def test_page_6h_needs_the_second_incident_hour(self):
        # Row 60: 6h = (5x4 + 300) / 60000 = 0.533% -> 5.33x, below 6.
        # Row 61: 6h = (4x4 + 600) / 60000 = 1.027% -> 10.27x; 30m ~ row 61 = 30x.
        a = self.first("page-6h")
        self.assertEqual(a["fired"], at(61))
        self.assertEqual(a["resolved"], at(62))  # short window (hour 62) back to 0.4x
        self.assertAlmostEqual(a["peak_long_burn"], 616 / 60000 / 0.001)

    def test_ticket_1d_fires_on_the_21st_degraded_hour(self):
        # With k degraded hours in the last 24: errors = 35k + 4(24-k) = 96 + 31k.
        # Fires when > 3 x 0.001 x 240000 = 720  ->  k = 21  ->  row 110 + 20 = 130.
        # The incident (rows 60-61) never reaches 3x over 1d: row 61 = 688/240000 = 2.87x.
        a = self.first("ticket-1d")
        self.assertEqual(a["fired"], at(130))
        self.assertEqual(a["fired"], datetime(2026, 9, 6, 11, tzinfo=timezone.utc))
        # Row 140: 2h = (35 + 4) / 20000 = 1.95x < 3.
        self.assertEqual(a["resolved"], at(140))
        self.assertEqual(sum(x["tier"] == "ticket-1d" for x in self.rep["alerts"]), 1)

    def test_ticket_3d_fires_twice(self):
        three = [a for a in self.rep["alerts"] if a["tier"] == "ticket-3d"]
        self.assertEqual(len(three), 2)
        # Incident: row 61 3d (62 rows of data) = (60x4 + 600) / 620000 -> 1.35x, 6h 10.27x.
        # Resolves at row 67, when the 6h window no longer contains the incident.
        self.assertEqual((three[0]["fired"], three[0]["resolved"]), (at(61), at(67)))
        # Degradation: row 111 6h = (70 + 16) / 60000 = 1.43x and the 3d window still
        # holds the incident. Row 144: 6h = (35 + 20) / 60000 = 0.92x -> resolved.
        self.assertEqual((three[1]["fired"], three[1]["resolved"]), (at(111), at(144)))

    def test_alert_order_and_counts(self):
        self.assertEqual([a["tier"] for a in self.rep["alerts"]],
                         ["page-1h", "page-6h", "ticket-3d", "ticket-3d", "ticket-1d"])

    def test_burn_at_end(self):
        burn = self.rep["burn_at_end"]
        self.assertAlmostEqual(burn["1h"], 0.4)
        self.assertAlmostEqual(burn["1d"], 0.4)
        # Rows 96-167: 30 x 35 + 42 x 4 = 1218 errors in 720000 requests.
        self.assertAlmostEqual(burn["3d"], 1218 / 720000 / 0.001)

    def test_render_matches_the_checked_in_report(self):
        text = slogen.render_report(self.rep, "checkout-api", "availability", "sample-data/checkout-api-availability-hourly.csv")
        self.assertEqual(text, (SLO_DIR.parent / "generated" / "reports" / "checkout-api-availability.txt").read_text())
        self.assertIn("fired 2026-09-03T13:00:00Z", text)
        self.assertIn("budget consumed 30.47%", text)

    def test_quiet_series_fires_nothing(self):
        rows = [(at(i), 9999, 10000) for i in range(100)]
        rep = slogen.error_budget_report(rows, self.slo)
        self.assertEqual(rep["alerts"], [])
        self.assertIn("  none", slogen.render_report(rep, "s", "n", "x.csv"))

    def test_still_firing_at_the_end(self):
        rows = [(at(i), 9000, 10000) for i in range(3)]
        rep = slogen.error_budget_report(rows, self.slo)
        self.assertTrue(all(a["resolved"] is None for a in rep["alerts"]))
        self.assertIn("still firing", slogen.render_report(rep, "s", "n", "x.csv"))


class CsvValidationTests(unittest.TestCase):
    def check(self, text, needle):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.csv"
            path.write_text(text)
            with self.assertRaisesRegex(slogen.SLOError, needle):
                slogen.read_hourly_csv(path)

    def test_bad_inputs(self):
        self.check("time,good,total\n", "header")
        self.check("timestamp,good,total\n", "no data rows")
        self.check("timestamp,good,total\n2026-09-01T01:00:00Z,11,10\n", "good <= total")
        self.check("timestamp,good,total\n2026-09-01T01:00:00Z,1,10\n2026-09-01T03:00:00Z,1,10\n", "consecutive")
        self.check("timestamp,good,total\nyesterday,1,10\n", "x.csv:2")


if __name__ == "__main__":
    unittest.main()
