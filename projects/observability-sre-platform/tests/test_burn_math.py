"""Burn-rate math: budgets, thresholds, budget consumed per window, time to exhaustion."""

from __future__ import annotations

import unittest
from decimal import Decimal
from fractions import Fraction

import helpers  # noqa: F401  (sys.path)
import slogen


class BurnMathTests(unittest.TestCase):
    def test_error_budget(self):
        self.assertEqual(slogen.error_budget(Decimal("99.9")), Decimal("0.001"))
        self.assertEqual(slogen.error_budget(Decimal("99.5")), Decimal("0.005"))
        self.assertEqual(slogen.error_budget(Decimal("99")), Decimal("0.01"))

    def test_tiers_are_the_workbook_values(self):
        got = [(t.name, t.severity, t.factor, t.long, t.short) for t in slogen.TIERS]
        self.assertEqual(got, [
            ("page-1h", "page", Decimal("14.4"), "1h", "5m"),
            ("page-6h", "page", Decimal("6"), "6h", "30m"),
            ("ticket-1d", "ticket", Decimal("3"), "1d", "2h"),
            ("ticket-3d", "ticket", Decimal("1"), "3d", "6h"),
        ])
        for t in slogen.TIERS:
            # The short window is 1/12 of the long one, as the workbook recommends.
            self.assertEqual(slogen.seconds(t.long), 12 * slogen.seconds(t.short), t.name)

    def test_thresholds(self):
        self.assertEqual(slogen.burn_threshold(Decimal("14.4"), Decimal("99.9")), Decimal("0.0144"))
        self.assertEqual(slogen.burn_threshold(Decimal("6"), Decimal("99.9")), Decimal("0.006"))
        self.assertEqual(slogen.burn_threshold(Decimal("14.4"), Decimal("99.5")), Decimal("0.072"))
        self.assertEqual(slogen.burn_threshold(Decimal("1"), Decimal("99")), Decimal("0.01"))

    def test_budget_consumed_is_rate_times_window_over_slo_window(self):
        # 30d window: the workbook's 2% / 5% / 10% / 10%.
        self.assertEqual(slogen.budget_consumed(Decimal("14.4"), "1h", "30d"), Fraction(2, 100))
        self.assertEqual(slogen.budget_consumed(6, "6h", "30d"), Fraction(5, 100))
        self.assertEqual(slogen.budget_consumed(3, "1d", "30d"), Fraction(10, 100))
        self.assertEqual(slogen.budget_consumed(1, "3d", "30d"), Fraction(10, 100))
        # 28d window: same factors spend a little more per window.
        self.assertEqual(slogen.budget_consumed(Decimal("14.4"), "1h", "28d"), Fraction(144, 10) / 672)
        for rate in (Decimal("0.5"), 1, 2, Decimal("14.4"), 1000):
            for window in ("5m", "1h", "6h", "3d"):
                with self.subTest(rate=rate, window=window):
                    expected = Fraction(Decimal(str(rate))) * slogen.seconds(window) / slogen.seconds("30d")
                    self.assertEqual(slogen.budget_consumed(rate, window, "30d"), expected)

    def test_a_1x_burn_spends_exactly_the_budget_over_the_window(self):
        self.assertEqual(slogen.budget_consumed(1, "30d", "30d"), 1)
        self.assertEqual(slogen.time_to_exhaustion(1, "30d"), slogen.seconds("30d"))

    def test_time_to_exhaustion(self):
        self.assertEqual(slogen.time_to_exhaustion(Decimal("14.4"), "30d"), 50 * 3600)
        self.assertEqual(slogen.time_to_exhaustion(6, "30d"), 5 * 86400)
        self.assertEqual(slogen.days(slogen.time_to_exhaustion(Decimal("14.4"), "28d")), "1.9d")

    def test_durations(self):
        self.assertEqual([slogen.seconds(w) for w in slogen.SLI_WINDOWS],
                         [300, 1800, 3600, 7200, 21600, 86400, 259200])
        for bad in ("", "5", "0m", "1w", "1.5h", "-1h"):
            with self.subTest(bad=bad), self.assertRaises(slogen.SLOError):
                slogen.seconds(bad)

    def test_formatting(self):
        self.assertEqual(slogen.dec(Decimal("14.40")), "14.4")
        self.assertEqual(slogen.dec(Decimal("6.0")), "6")
        self.assertEqual(slogen.dec(Decimal("100")), "100")
        self.assertEqual(slogen.pct(Fraction(1, 1000), 3), "0.1")
        self.assertEqual(slogen.pct(Fraction(144, 10) / 672), "2.14")


if __name__ == "__main__":
    unittest.main()
