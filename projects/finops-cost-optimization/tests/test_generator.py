import tempfile
import unittest
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import helpers  # noqa: F401  (puts the project on sys.path)

from finops.generator import generate
from finops.io import read_billing, read_utilization, read_volumes


class GeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        cls.a = generate(base / "a", seed=7, days=14)
        cls.b = generate(base / "b", seed=7, days=14)
        cls.c = generate(base / "c", seed=8, days=14)
        cls.records = read_billing(cls.a["billing"])

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_same_seed_is_byte_identical(self):
        for name in ("billing", "utilization", "volumes"):
            self.assertEqual(self.a[name].read_bytes(), self.b[name].read_bytes(), name)

    def test_different_seed_differs(self):
        self.assertNotEqual(self.a["billing"].read_bytes(), self.c["billing"].read_bytes())

    def test_covers_expected_services_and_days(self):
        services = {r.service_name for r in self.records}
        for s in ("Amazon EC2", "Amazon EKS", "Amazon RDS", "Amazon S3", "Amazon EBS",
                  "NAT Gateway", "Data Transfer", "Savings Plans"):
            self.assertIn(s, services)
        self.assertEqual(len({r.charge_date for r in self.records}), 14)

    def test_mix_of_x86_graviton_tagged_untagged_and_committed(self):
        types = {r.instance_type for r in self.records if r.service_name == "Amazon EC2"}
        self.assertTrue({"m5.2xlarge", "c5.xlarge", "r5.2xlarge", "m7g.xlarge"} <= types)
        self.assertTrue(any(not r.tags for r in self.records))
        self.assertTrue(any(r.tags for r in self.records))
        self.assertEqual({r.pricing_category for r in self.records}, {"On-Demand", "Committed"})

    def test_savings_plan_fee_equals_covered_effective_cost(self):
        covered = defaultdict(Decimal)
        fees = defaultdict(Decimal)
        for r in self.records:
            if r.charge_category == "Purchase":
                fees[r.charge_date] += r.billed_cost
                self.assertEqual(r.effective_cost, 0)
            elif r.pricing_category == "Committed":
                covered[r.charge_date] += r.effective_cost
                self.assertEqual(r.billed_cost, 0)
        self.assertEqual(covered, fees)

    def test_utilization_and_volume_inventory_match_billing(self):
        util = read_utilization(self.a["utilization"])
        instance_ids = {r.resource_id for r in self.records if r.service_name == "Amazon EC2"}
        self.assertEqual({u.resource_id for u in util}, instance_ids)
        volumes = read_volumes(self.a["volumes"])
        self.assertTrue(any(v.state == "available" for v in volumes))
        self.assertTrue(any(v.state == "in-use" for v in volumes))

    def test_rejects_zero_days(self):
        with self.assertRaises(ValueError):
            generate(Path(self._tmp.name) / "z", days=0)


if __name__ == "__main__":
    unittest.main()
