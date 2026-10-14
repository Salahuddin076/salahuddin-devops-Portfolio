"""The KEDA + HPA model: activation, scale-up math, stabilization, cooldown, no flapping."""

from __future__ import annotations

import unittest

from helpers import CHART_DIR, SAMPLE_CSV

import keda_scaling_sim as sim


def csv(*rows, active=False):
    head = "t_seconds,wait,active" if active else "t_seconds,wait"
    return sim.load_csv("\n".join([head, *(",".join(map(str, r)) for r in rows)]), is_text=True)


def settings(**kw):
    base = dict(list_length=10, activation_list_length=0, min_replicas=0, max_replicas=10,
                polling_interval=15, cooldown_period=300, stabilization_window=300,
                scale_down_percent=100, scale_down_period=60, scale_up_pods=100, scale_up_period=15,
                active_list_length=0, hpa_sync_period=15, tolerance=0.1)
    base.update(kw)
    return sim.Settings(**base)


class ActivationTests(unittest.TestCase):
    def test_idle_queue_stays_at_zero(self):
        res = sim.simulate(csv((0, 0), (600, 0)), settings())
        self.assertEqual(res.peak, 0)
        self.assertEqual(res.events, [])

    def test_keda_activates_zero_to_one_on_first_poll_after_work_arrives(self):
        res = sim.simulate(csv((0, 0), (20, 3), (100, 3)), settings())
        first = res.events[0]
        self.assertEqual((first.t, first.before, first.after, first.actor), (30, 0, 1, "KEDA"))
        self.assertEqual(res.replicas_at(29), 0)

    def test_activation_threshold_is_strictly_greater(self):
        res = sim.simulate(csv((0, 5), (300, 5)), settings(activation_list_length=5))
        self.assertEqual(res.peak, 0, "5 waiting is not > activationListLength 5")
        res = sim.simulate(csv((0, 6), (300, 6)), settings(activation_list_length=5))
        self.assertEqual(res.events[0].after, 1)

    def test_min_replicas_above_zero_never_scales_to_zero(self):
        res = sim.simulate(csv((0, 0), (1200, 0)), settings(min_replicas=2, initial_replicas=2))
        self.assertEqual(min(r for _, r in res.timeline), 2)


class ScaleUpTests(unittest.TestCase):
    def test_hpa_sizes_to_ceil_of_wait_over_list_length(self):
        for wait, expected in ((1, 1), (10, 1), (11, 2), (45, 5), (99, 10)):
            with self.subTest(wait=wait):
                res = sim.simulate(csv((0, wait), (60, wait)), settings(tolerance=0.0))
                self.assertEqual(res.replicas_at(60), expected)

    def test_capped_at_max_replicas(self):
        res = sim.simulate(csv((0, 1000), (60, 1000)), settings(max_replicas=7))
        self.assertEqual(res.peak, 7)

    def test_scale_up_pods_policy_limits_each_period(self):
        res = sim.simulate(csv((0, 200), (120, 200)), settings(max_replicas=20, scale_up_pods=4))
        # KEDA 0->1, then +4 per 15s window: 5, 9, 13, 17, 20.
        self.assertEqual([res.replicas_at(t) for t in (0, 15, 30, 45, 60)], [5, 9, 13, 17, 20])

    def test_tolerance_keeps_current_count_near_target(self):
        res = sim.simulate(csv((0, 50), (15, 52), (60, 52)), settings(tolerance=0.1))
        self.assertEqual(res.replicas_at(60), 5, "52/50 is within 10%: no change to 6")

    def test_active_trigger_holds_workers_while_jobs_run(self):
        rows = [(0, 40, 0), (30, 0, 40), (400, 0, 40), (420, 0, 0), (1200, 0, 0)]
        with_active = sim.simulate(csv(*rows, active=True), settings(active_list_length=10))
        without = sim.simulate(csv(*rows, active=True), settings(active_list_length=0))
        self.assertEqual(with_active.replicas_at(390), 4, "40 running jobs / concurrency 10")
        self.assertEqual(without.replicas_at(390), 0, "wait list alone looks idle: scaled to zero mid-run")


class ScaleDownTests(unittest.TestCase):
    def test_stabilization_window_delays_scale_down(self):
        res = sim.simulate(csv((0, 80), (60, 0), (600, 0)), settings(stabilization_window=300, cooldown_period=900))
        self.assertEqual(res.replicas_at(60), 8)
        self.assertEqual(res.replicas_at(330), 8, "the 8-recommendation from t=45 is still in the window")
        self.assertEqual(res.replicas_at(345), 1, "window (45, 345] no longer holds it")

    def test_percent_policy_limits_scale_down_rate(self):
        res = sim.simulate(csv((0, 100), (15, 0), (900, 0)),
                           settings(stabilization_window=0, scale_down_percent=50, scale_down_period=60,
                                    cooldown_period=900))
        downs = [(e.t, e.after) for e in res.events if e.actor == "HPA" and e.after < e.before]
        self.assertEqual(downs[0], (15, 5))
        self.assertTrue(all(b - a >= 60 for (a, _), (b, _) in zip(downs, downs[1:])))


class CooldownTests(unittest.TestCase):
    def test_returns_to_zero_after_cooldown(self):
        res = sim.simulate(csv((0, 30), (60, 0), (1000, 0)), settings(cooldown_period=300))
        zero = [e for e in res.events if e.after == 0]
        self.assertEqual(len(zero), 1)
        self.assertEqual(zero[0].actor, "KEDA")
        # Last active poll at t=45 (wait 30); first poll with 300s idle is t=345.
        self.assertEqual(zero[0].t, 345)

    def test_no_flapping_on_gaps_shorter_than_cooldown(self):
        rows = [(0, 30)]
        for start in range(60, 1200, 180):  # 120s gaps between bursts, cooldown 300s
            rows += [(start, 0), (start + 120, 30)]
        rows.append((1500, 30))
        res = sim.simulate(csv(*rows), settings(cooldown_period=300))
        self.assertEqual(res.scale_to_zero_count(), 0)
        self.assertEqual(min(r for t, r in res.timeline if t >= 15), 3, "stabilization holds 3 across every gap")
        self.assertEqual(sum(1 for e in res.events if e.actor == "KEDA"), 1, "one activation, never re-activated")

    def test_stabilization_rides_out_short_gap_without_scale_in(self):
        res = sim.simulate(csv((0, 50), (60, 0), (150, 50), (400, 50)), settings(stabilization_window=300))
        self.assertEqual(min(r for t, r in res.timeline if t >= 15), 5)

    def test_reactivates_after_reaching_zero(self):
        res = sim.simulate(csv((0, 20), (30, 0), (900, 20), (960, 20)), settings(cooldown_period=300))
        self.assertEqual([e.actor for e in res.events if e.before == 0], ["KEDA", "KEDA"])
        self.assertEqual(res.scale_to_zero_count(), 1)


class SampleAndValuesTests(unittest.TestCase):
    def test_sample_csv_shape(self):
        samples = sim.load_csv(SAMPLE_CSV)
        waits = [s.wait for s in samples]
        self.assertEqual(samples[0].t, 0)
        self.assertGreater(max(waits), 100)
        # burst, idle, second burst
        bursts = sum(1 for a, b in zip(waits, waits[1:]) if a == 0 and b > 0)
        self.assertGreaterEqual(bursts, 2)

    def test_sample_with_chart_values_scales_to_zero_twice(self):
        params = sim.settings_from_values(CHART_DIR / "values.yaml")
        self.assertEqual(params["list_length"], 10)
        self.assertEqual(params["cooldown_period"], 300)
        self.assertEqual(params["active_list_length"], 10)
        res = sim.simulate(sim.load_csv(SAMPLE_CSV), sim.Settings(**params))
        self.assertEqual(res.peak, 10)
        self.assertEqual(res.scale_to_zero_count(), 2)
        self.assertEqual(res.replicas_at(res.end), 0)

    def test_prod_values_are_read(self):
        params = sim.settings_from_values(CHART_DIR / "values-prod.yaml")
        self.assertEqual((params["max_replicas"], params["cooldown_period"]), (30, 600))

    def test_bad_input_rejected(self):
        for text in ("t_seconds,wait\n5,1", "t_seconds,wait\n0,1\n0,2", "time,depth\n0,1", "t_seconds,wait\n0,-1"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                sim.load_csv(text, is_text=True)
        with self.assertRaises(ValueError):
            sim.simulate(csv((0, 1)), settings(min_replicas=11))


if __name__ == "__main__":
    unittest.main()
