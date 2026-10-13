import unittest
from datetime import date

from helpers import D, daily

from finops.budget import EXIT_BREACH, EXIT_OK, evaluate


class BudgetTest(unittest.TestCase):
    def setUp(self):
        # $10/day for Sep 1..20 -> MTD $200, flat forecast for the remaining 10 days -> $300
        self.records = daily([10] * 20)

    def test_mtd_and_month_end_forecast(self):
        res = evaluate(self.records, budget=400)
        self.assertEqual(res.as_of, date(2026, 9, 20))
        self.assertEqual((res.days_elapsed, res.days_in_month), (20, 30))
        self.assertEqual(res.month_to_date, D("200.00"))
        self.assertEqual(res.forecast_month_end, D("300.00"))
        self.assertEqual(res.forecast_pct, D("75.0"))
        self.assertFalse(res.breached)
        self.assertEqual(res.exit_code, EXIT_OK)

    def test_breach_when_forecast_reaches_fail_at(self):
        res = evaluate(self.records, budget=300)  # forecast exactly 100%
        self.assertTrue(res.breached)
        self.assertEqual(res.exit_code, EXIT_BREACH)
        self.assertNotEqual(EXIT_BREACH, 0)

    def test_threshold_statuses(self):
        res = evaluate(self.records, budget=300, thresholds=(50, 80, 100))
        crossed = {t.threshold_pct: (t.actual_crossed, t.forecast_crossed) for t in res.thresholds}
        self.assertEqual(crossed[D(50)], (True, True))     # actual 66.7%
        self.assertEqual(crossed[D(80)], (False, True))
        self.assertEqual(crossed[D(100)], (False, True))

    def test_actual_measure_ignores_forecast(self):
        res = evaluate(self.records, budget=250, measure="actual")  # actual 80%, forecast 120%
        self.assertFalse(res.breached)
        res = evaluate(self.records, budget=250, measure="actual", fail_at=80)
        self.assertTrue(res.breached)

    def test_as_of_filters_later_days(self):
        res = evaluate(self.records, budget=1000, as_of=date(2026, 9, 10))
        self.assertEqual(res.month_to_date, D("100.00"))
        self.assertEqual(res.forecast_month_end, D("300.00"))

    def test_last_day_of_month_has_no_forecast_remainder(self):
        res = evaluate(daily([10] * 30), budget=1000)
        self.assertEqual(res.forecast_remaining, D("0.00"))

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            evaluate(self.records, budget=0)
        with self.assertRaises(ValueError):
            evaluate(self.records, budget=100, measure="vibes")
        with self.assertRaises(ValueError):
            evaluate([], budget=100)


if __name__ == "__main__":
    unittest.main()
