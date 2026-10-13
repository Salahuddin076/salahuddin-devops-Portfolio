import unittest

from helpers import D, rec

from finops.allocation import UNTAGGED, allocate, tag_value


def shares(result, key):
    return {s.name: (s.cost, s.pct) for s in result.by_key[key]}


class AllocationMathTest(unittest.TestCase):
    def setUp(self):
        self.records = [
            rec("60.00", tags={"team": "a", "env": "prod", "app": "api"}, resource_id="r-a"),
            rec("30.00", tags={"team": "b", "env": "prod"}, service="Amazon RDS", resource_id="r-b"),
            rec("10.00", tags={}, service="Data Transfer", resource_id=""),
        ]

    def test_totals_and_percentages(self):
        res = allocate(self.records, keys=("team",))
        self.assertEqual(res.total, D("100.00"))
        self.assertEqual(shares(res, "team"), {
            "a": (D("60.00"), D("60.0")),
            "b": (D("30.00"), D("30.0")),
            UNTAGGED: (D("10.00"), D("10.0")),
        })
        # ranked by cost descending
        self.assertEqual([s.name for s in res.by_key["team"]], ["a", "b", UNTAGGED])

    def test_untagged_is_per_key(self):
        res = allocate(self.records)
        self.assertEqual(res.untagged_by_key["team"].cost, D("10.00"))
        self.assertEqual(res.untagged_by_key["env"].cost, D("10.00"))
        # r-b has no "app" tag, so it is untagged for app but not for team
        self.assertEqual(res.untagged_by_key["app"].cost, D("40.00"))
        self.assertEqual(res.untagged_by_key["app"].pct, D("40.0"))
        self.assertEqual(res.no_tags_at_all.cost, D("10.00"))

    def test_blank_tag_value_counts_as_untagged(self):
        r = rec("5", tags={"team": "   "})
        self.assertIsNone(tag_value(r, "team"))
        res = allocate([r], keys=("team",))
        self.assertEqual(res.untagged_by_key["team"].pct, D("100.0"))

    def test_normalisation_merges_casing_drift(self):
        records = [rec("1", tags={"team": "Search"}), rec("2", tags={"team": " search "})]
        merged = allocate(records, keys=("team",))
        self.assertEqual(shares(merged, "team"), {"search": (D("3.00"), D("100.0"))})
        raw = allocate(records, keys=("team",), normalise=False)
        self.assertEqual(len(raw.by_key["team"]), 2)

    def test_top_services_limit_and_order(self):
        res = allocate(self.records, top_n=2)
        self.assertEqual([s.name for s in res.top_services], ["Amazon EC2", "Amazon RDS"])

    def test_untagged_resources_label_missing_resource_id(self):
        res = allocate(self.records)
        self.assertEqual(res.top_untagged_resources[0].name, "Data Transfer (no resource id)")

    def test_billed_vs_effective_column(self):
        records = [rec("7.20", committed=True, tags={"team": "a"})]  # billed 0, effective 7.20
        effective = allocate(records, keys=("team",))
        billed = allocate(records, keys=("team",), cost_column="billed")
        self.assertEqual(effective.total, D("7.20"))
        self.assertEqual(billed.total, D("0.00"))

    def test_zero_cost_rows_ignored_and_empty_input(self):
        res = allocate([rec("0", tags={})], keys=("team",))
        self.assertEqual(res.total, D("0.00"))
        self.assertEqual(res.no_tags_at_all.pct, D("0.0"))


if __name__ == "__main__":
    unittest.main()
