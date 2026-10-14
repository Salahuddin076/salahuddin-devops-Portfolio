"""cidr_plan.py: overlaps, RFC 1918, prefix length, host bits, environments."""

import copy
import json
import unittest

from helpers import FIXTURES, POLICY_DIR

import cidr_plan
from cidr_plan import check

SHIPPED = json.loads((POLICY_DIR / "cidr-plan.json").read_text())


def plan_with(**spokes):
    p = copy.deepcopy(SHIPPED)
    p["spokes"].update(spokes)
    return p


def ids(plan):
    return sorted({f.rule_id for f in check(plan).findings})


class ShippedPlanTests(unittest.TestCase):
    def test_shipped_plan_passes(self):
        report = check(SHIPPED)
        self.assertEqual(report.findings, [])
        self.assertEqual(str(report.next_free), "10.2.0.0/16")

    def test_every_environment_is_present(self):
        self.assertEqual({s["environment"] for s in SHIPPED["spokes"].values()}, {"prod", "nonprod", "shared"})


class RuleTests(unittest.TestCase):
    def test_overlap_with_spoke_detected(self):
        report = check(plan_with(dup={"cidr": "10.16.0.0/16", "environment": "prod"}))
        self.assertEqual(sorted({f.rule_id for f in report.findings}), ["CIDR-004"])
        self.assertIn("prod-payments/dup", {f.subject for f in report.findings})

    def test_partial_overlap_detected(self):
        p = plan_with(small={"cidr": "10.17.64.0/18", "environment": "prod"})
        p["spoke_prefix_length"] = None
        self.assertEqual(ids(p), ["CIDR-004"])

    def test_overlap_with_reserved_detected(self):
        self.assertEqual(ids(plan_with(x={"cidr": "10.0.0.0/16", "environment": "shared"})), ["CIDR-004"])

    def test_adjacent_blocks_do_not_overlap(self):
        self.assertEqual(ids(plan_with(x={"cidr": "10.18.0.0/16", "environment": "prod"})), [])

    def test_public_range_rejected(self):
        p = plan_with(x={"cidr": "203.0.113.0/24", "environment": "prod"})
        self.assertIn("CIDR-002", ids(p))

    def test_rfc1918_outside_allowed_ranges_rejected(self):
        self.assertEqual(ids(plan_with(x={"cidr": "172.16.0.0/16", "environment": "prod"})), ["CIDR-002"])

    def test_other_rfc1918_ranges_allowed_when_listed(self):
        p = plan_with(x={"cidr": "172.20.0.0/16", "environment": "prod"})
        p["allowed_ranges"] = ["10.0.0.0/8", "172.16.0.0/12"]
        self.assertEqual(ids(p), [])

    def test_wrong_prefix_rejected(self):
        self.assertEqual(ids(plan_with(x={"cidr": "10.40.0.0/17", "environment": "prod"})), ["CIDR-003"])

    def test_host_bits_rejected(self):
        self.assertEqual(ids(plan_with(x={"cidr": "10.40.1.0/16", "environment": "prod"})), ["CIDR-001"])

    def test_garbage_rejected(self):
        self.assertEqual(ids(plan_with(x={"cidr": "10.400.0.0/16", "environment": "prod"})), ["CIDR-001"])

    def test_unknown_environment_rejected(self):
        self.assertEqual(ids(plan_with(x={"cidr": "10.40.0.0/16", "environment": "staging"})), ["CIDR-005"])

    def test_bad_fixture_hits_every_rule(self):
        plan = json.loads((FIXTURES / "cidr-plan-bad.json").read_text())
        self.assertEqual(ids(plan), ["CIDR-001", "CIDR-002", "CIDR-003", "CIDR-004", "CIDR-005"])

    def test_next_free_skips_used_blocks(self):
        p = plan_with(x={"cidr": "10.2.0.0/16", "environment": "prod"})
        self.assertEqual(str(check(p).next_free), "10.3.0.0/16")

    def test_missing_spokes_is_input_error(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "p.json"
            path.write_text("{}")
            with self.assertRaises(cidr_plan.InputError):
                cidr_plan.load_plan(path)


if __name__ == "__main__":
    unittest.main()
