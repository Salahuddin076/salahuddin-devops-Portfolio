import unittest
from datetime import date

from helpers import D, rec

from finops.commitments import analyze, hourly_on_demand_series, percentile, simulate


class PercentileTest(unittest.TestCase):
    def test_linear_interpolation_matches_numpy_linear(self):
        values = [D(v) for v in (5, 1, 4, 2, 3)]  # unsorted on purpose
        self.assertEqual(percentile(values, 0), D(1))
        self.assertEqual(percentile(values, 25), D(2))
        self.assertEqual(percentile(values, 50), D(3))
        self.assertEqual(percentile(values, 100), D(5))
        self.assertEqual(percentile(values, 10), D("1.4"))

    def test_single_value_and_invalid_input(self):
        self.assertEqual(percentile([D(7)], 90), D(7))
        with self.assertRaises(ValueError):
            percentile([], 50)
        with self.assertRaises(ValueError):
            percentile([D(1)], 101)


class HourlySeriesTest(unittest.TestCase):
    def test_daily_row_is_spread_across_24_hours(self):
        series = hourly_on_demand_series([rec("48.00")])
        self.assertEqual(len(series), 24)
        self.assertTrue(all(v == D(2) for v in series))

    def test_committed_purchase_and_ineligible_rows_excluded(self):
        records = [
            rec("24", day=date(2026, 9, 1)),
            rec("24", day=date(2026, 9, 1), committed=True),
            rec("99", day=date(2026, 9, 1), service="Savings Plans", category="Purchase"),
            rec("99", day=date(2026, 9, 1), service="Amazon S3"),
        ]
        series = hourly_on_demand_series(records)
        self.assertEqual(sum(series), D(24))

    def test_hours_with_only_committed_usage_count_as_zero(self):
        records = [rec("24", day=date(2026, 9, 1)), rec("24", day=date(2026, 9, 2), committed=True)]
        series = hourly_on_demand_series(records)
        self.assertEqual(len(series), 48)
        self.assertEqual(series[30], D(0))


class SimulationTest(unittest.TestCase):
    def test_flat_usage_full_utilisation(self):
        row = simulate([D(10)] * 4, D(10), D("0.30"), "x")
        self.assertEqual(row.commitment_hourly, D("7.0000"))
        self.assertEqual(row.utilization_pct, D("100.0"))
        self.assertEqual(row.monthly_net_savings, D("2190.00"))  # 3 $/h * 730

    def test_overcommitment_wastes_the_discount(self):
        # usage 10,10,0,0 with 50% discount, committing to 10: pay 5*4=20 == on-demand 20
        row = simulate([D(10), D(10), D(0), D(0)], D(10), D("0.5"), "x")
        self.assertEqual(row.utilization_pct, D("50.0"))
        self.assertEqual(row.monthly_net_savings, D("0.00"))


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        # 10 days on-demand ($24..$240/day => $1..$10/h) plus one committed day
        self.records = [rec(str(24 * (i + 1)), day=date(2026, 9, i + 1)) for i in range(10)]
        self.records.append(rec("21.60", day=date(2026, 9, 1), committed=True, list_cost="30.00"))

    def test_coverage_uses_list_cost(self):
        res = analyze(self.records, percentile_value=20, discount="0.28")
        on_demand = sum(24 * (i + 1) for i in range(10))
        self.assertEqual(res.covered_list_cost, D("30.00"))
        self.assertEqual(res.on_demand_list_cost, D(on_demand).quantize(D("0.01")))
        self.assertEqual(res.coverage_pct, (D(30) * 100 / (30 + on_demand)).quantize(D("0.1")))

    def test_recommendation_is_percentile_of_hourly_baseline(self):
        res = analyze(self.records, percentile_value=20, discount="0.28")
        # hourly values 1..10 each repeated 24 times; P20 of 240 values
        expected = percentile([D(v) for v in range(1, 11) for _ in range(24)], 20)
        self.assertEqual(res.recommended.od_equivalent_hourly, expected.quantize(D("0.0001")))
        self.assertEqual(res.recommended.commitment_hourly, (expected * D("0.72")).quantize(D("0.0001")))
        self.assertEqual(res.recommended.label, "P20")
        self.assertEqual(res.breakeven_percentile, D("28.00"))

    def test_sweep_sorted_and_includes_mean(self):
        res = analyze(self.records)
        levels = [s.od_equivalent_hourly for s in res.sweep]
        self.assertEqual(levels, sorted(levels))
        self.assertIn("mean", [s.label for s in res.sweep])
        self.assertEqual(res.mean_od_hourly, D("5.5000"))

    def test_invalid_discount_and_no_eligible_usage(self):
        with self.assertRaises(ValueError):
            analyze(self.records, discount="1.5")
        with self.assertRaises(ValueError):
            analyze([rec("10", service="Amazon S3")])


if __name__ == "__main__":
    unittest.main()
