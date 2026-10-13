import unittest

from helpers import D, rec, util, volume

from finops.rightsizing import RightsizeConfig, downsize_target, graviton_equivalent, recommend


def kinds(result):
    return [r.kind for r in result.recommendations]


class GravitonMappingTest(unittest.TestCase):
    def test_x86_families_map_to_same_size_graviton(self):
        self.assertEqual(graviton_equivalent("m5.xlarge"), "m7g.xlarge")
        self.assertEqual(graviton_equivalent("c5.4xlarge"), "c7g.4xlarge")
        self.assertEqual(graviton_equivalent("r5.large"), "r7g.large")

    def test_no_mapping_for_graviton_or_unknown_families(self):
        self.assertIsNone(graviton_equivalent("m7g.xlarge"))
        self.assertIsNone(graviton_equivalent("t3.micro"))
        self.assertIsNone(graviton_equivalent("m5.24xlarge"))  # size not in price table

    def test_malformed_type_raises(self):
        with self.assertRaises(ValueError):
            graviton_equivalent("m5")


class RightsizingRulesTest(unittest.TestCase):
    def test_idle_instance_is_terminate_candidate_with_full_cost(self):
        res = recommend([util("m5.large", p95=2, mem=10)])
        self.assertEqual(kinds(res), ["terminate"])
        # illustrative m5.large 0.096/h * 730h
        self.assertEqual(res.recommendations[0].monthly_delta, D("-70.08"))
        self.assertEqual(res.recommendations[0].confidence, "high")

    def test_idle_cpu_but_busy_memory_is_not_idle(self):
        res = recommend([util("m5.large", p95=2, mem=60)])
        self.assertNotIn("terminate", kinds(res))

    def test_downsize_one_step_then_incremental_graviton(self):
        res = recommend([util("m5.2xlarge", p95=24, mem=35)])
        self.assertEqual(kinds(res), ["downsize", "graviton"])
        down, grav = res.recommendations
        self.assertEqual((down.current, down.proposed), ("m5.2xlarge", "m5.xlarge"))
        self.assertEqual(down.monthly_delta, D("-140.16"))  # (0.192 - 0.384) * 730
        self.assertEqual((grav.current, grav.proposed), ("m5.xlarge", "m7g.xlarge"))
        self.assertEqual(grav.monthly_delta, D("-21.02"))  # (0.1632 - 0.192) * 730
        self.assertTrue(grav.requires_compat_testing)
        self.assertEqual(grav.confidence, "medium")
        self.assertEqual(res.total_monthly_delta, D("-161.18"))

    def test_downsize_two_steps_capped_by_max_steps(self):
        proposed, steps = downsize_target(util("m5.4xlarge", p95=5.5, mem=10), RightsizeConfig())
        self.assertEqual((proposed, steps), ("m5.xlarge", 2))
        proposed, steps = downsize_target(util("m5.4xlarge", p95=5.5, mem=10), RightsizeConfig(max_steps=1))
        self.assertEqual((proposed, steps), ("m5.2xlarge", 1))

    def test_p95_exactly_at_threshold_is_not_downsized(self):
        res = recommend([util("m5.2xlarge", p95=40, mem=10)])
        self.assertEqual(kinds(res), ["graviton"])

    def test_projected_cpu_ceiling_blocks_downsize(self):
        # 36% doubles to 72% > 70% ceiling
        res = recommend([util("m5.xlarge", p95=36, mem=10)])
        self.assertNotIn("downsize", kinds(res))

    def test_memory_bound_instance_not_downsized(self):
        res = recommend([util("r5.2xlarge", p95=10, mem=50)])
        self.assertNotIn("downsize", kinds(res))

    def test_smallest_size_cannot_downsize_but_gets_graviton(self):
        res = recommend([util("c5.large", p95=10, mem=10)])
        self.assertEqual(kinds(res), ["graviton"])
        self.assertEqual(res.recommendations[0].proposed, "c7g.large")

    def test_graviton_instances_get_no_graviton_rec(self):
        res = recommend([util("m7g.xlarge", p95=50, mem=50)])
        self.assertEqual(res.recommendations, [])

    def test_graviton_can_be_disabled(self):
        res = recommend([util("c5.xlarge", p95=60, mem=40)], config=RightsizeConfig(graviton=False))
        self.assertEqual(res.recommendations, [])

    def test_run_ratio_scales_monthly_delta(self):
        res = recommend([util("m5.large", p95=1, mem=1, observed=720, running=360)])
        self.assertEqual(res.recommendations[0].monthly_delta, D("-35.04"))

    def test_short_observation_lowers_confidence(self):
        res = recommend([util("m5.large", p95=1, mem=1, observed=48)])
        self.assertEqual(res.recommendations[0].confidence, "low")

    def test_unpriced_and_never_running_instances_are_skipped(self):
        res = recommend([
            util("x2iedn.metal", p95=1, mem=1, resource_id="i-a"),
            util("m5.large", p95=1, mem=1, running=0, resource_id="i-b"),
        ])
        self.assertEqual(res.recommendations, [])
        self.assertEqual(len(res.skipped), 2)

    def test_owner_comes_from_billing_tags(self):
        billing = [rec("1", resource_id="i-test", tags={"team": "Payments", "app": "api"})]
        res = recommend([util("m5.large", p95=1, mem=1)], billing=billing)
        self.assertEqual(res.recommendations[0].owner, "payments/api")


class UnattachedVolumeTest(unittest.TestCase):
    def test_only_available_volumes_are_flagged(self):
        res = recommend([], [volume("available", 1000, "gp2", vid="vol-a"), volume("in-use", vid="vol-b")])
        self.assertEqual([r.resource_id for r in res.recommendations], ["vol-a"])
        self.assertEqual(res.recommendations[0].monthly_delta, D("-100.00"))  # 1000 GB * 0.10

    def test_confidence_by_days_unattached(self):
        res = recommend([], [
            volume("available", days=45, vid="v1"),
            volume("available", days=10, vid="v2"),
            volume("available", days=2, vid="v3"),
        ])
        conf = {r.resource_id: r.confidence for r in res.recommendations}
        self.assertEqual(conf, {"v1": "high", "v2": "medium", "v3": "low"})

    def test_unknown_volume_type_skipped(self):
        res = recommend([], [volume("available", vtype="io2")])
        self.assertEqual(res.recommendations, [])
        self.assertIn("io2", res.skipped[0])


if __name__ == "__main__":
    unittest.main()
