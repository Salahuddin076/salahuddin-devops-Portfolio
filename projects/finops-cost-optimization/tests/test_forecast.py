import unittest
from datetime import date

from helpers import D, daily, rec

from finops.forecast import daily_totals, forecast, linear_fit


class LinearFitTest(unittest.TestCase):
    def test_perfect_line(self):
        fit = linear_fit([10 + 2 * x for x in range(20)])
        self.assertAlmostEqual(fit.slope, 2.0, places=9)
        self.assertAlmostEqual(fit.intercept, 10.0, places=9)
        self.assertAlmostEqual(fit.r_squared, 1.0, places=9)
        self.assertEqual(fit.residual_std, 0.0)

    def test_constant_series(self):
        fit = linear_fit([5.0] * 7)
        self.assertEqual((fit.slope, fit.intercept, fit.r_squared), (0.0, 5.0, 1.0))

    def test_single_point_and_empty(self):
        self.assertEqual(linear_fit([3.0]).predict(10), 3.0)
        with self.assertRaises(ValueError):
            linear_fit([])


class ForecastTest(unittest.TestCase):
    def test_extends_perfect_line(self):
        records = daily([10 + 2 * i for i in range(10)])  # Sep 1..10
        res = forecast(records, horizon_days=3, lookback_days=None)
        self.assertEqual([p.cost for p in res.predictions], [D("30.00"), D("32.00"), D("34.00")])
        self.assertEqual(res.predictions[0].day, date(2026, 9, 11))
        self.assertEqual(res.total, D("96.00"))
        self.assertEqual(res.predictions[0].low, res.predictions[0].high)  # zero residual band

    def test_lookback_window_limits_history(self):
        records = daily([100] * 5 + [10, 20, 30])
        res = forecast(records, horizon_days=1, lookback_days=3)
        self.assertEqual(res.lookback_days, 3)
        self.assertEqual(res.predictions[0].cost, D("40.00"))

    def test_declining_trend_clamped_at_zero(self):
        res = forecast(daily([30, 20, 10]), horizon_days=3, lookback_days=None)
        self.assertEqual([p.cost for p in res.predictions], [D("0.00"), D("0.00"), D("0.00")])

    def test_daily_totals_sum_and_fill_gaps(self):
        records = [rec("1.50", day=date(2026, 9, 1)), rec("2.50", day=date(2026, 9, 1)),
                   rec("4", day=date(2026, 9, 3))]
        totals = daily_totals(records)
        self.assertEqual([(p.day.day, p.cost) for p in totals], [(1, D("4.00")), (2, D(0)), (3, D(4))])


if __name__ == "__main__":
    unittest.main()
