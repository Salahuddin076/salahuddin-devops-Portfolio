"""traffic_shift_sim.py: timelines per config type and alarm rollback."""

import unittest

import traffic_shift_sim as sim

CANARY5 = "CodeDeployDefault.ECSCanary10Percent5Minutes"
CANARY15 = "CodeDeployDefault.ECSCanary10Percent15Minutes"
LINEAR1 = "CodeDeployDefault.ECSLinear10PercentEvery1Minutes"
LINEAR3 = "CodeDeployDefault.ECSLinear10PercentEvery3Minutes"
ALL = "CodeDeployDefault.ECSAllAtOnce"


def greens(result):
    return [s.green_percent for s in result.steps]


class ParseTests(unittest.TestCase):
    def test_known_configs_parse(self):
        kinds = {name: sim.parse_config(name).kind for name in sim.KNOWN_CONFIGS}
        self.assertEqual(kinds[ALL], "all_at_once")
        self.assertEqual(kinds[CANARY5], "canary")
        self.assertEqual(kinds[LINEAR3], "linear")

    def test_complete_minutes(self):
        self.assertEqual(sim.parse_config(ALL).shift_complete_minute, 0)
        self.assertEqual(sim.parse_config(CANARY15).shift_complete_minute, 15)
        self.assertEqual(sim.parse_config(LINEAR1).shift_complete_minute, 9)
        self.assertEqual(sim.parse_config(LINEAR3).shift_complete_minute, 27)
        self.assertEqual(sim.parse_config("Custom.ECSLinear30PercentEvery2Minutes").shift_complete_minute, 6)

    def test_rejects_unknown_and_out_of_range(self):
        for name in ("CodeDeployDefault.OneAtATime", "CodeDeployDefault.LambdaCanary10Percent5Minutes",
                     "CodeDeployDefault.ECSCanary0Percent5Minutes", "CodeDeployDefault.ECSCanary100Percent5Minutes",
                     "CodeDeployDefault.ECSLinear10PercentEvery0Minutes", ""):
            with self.subTest(name=name), self.assertRaises(sim.SimulationError):
                sim.parse_config(name)


class TimelineTests(unittest.TestCase):
    def test_all_at_once(self):
        r = sim.simulate(ALL, 10, termination_wait_minutes=5)
        self.assertEqual(greens(r), [100] * 6)
        self.assertEqual((r.outcome, r.outcome_minute), (sim.SUCCEEDED, 5))

    def test_canary(self):
        r = sim.simulate(CANARY5, 30, termination_wait_minutes=10)
        self.assertEqual(greens(r)[:7], [10, 10, 10, 10, 10, 100, 100])
        self.assertEqual((r.outcome, r.outcome_minute), (sim.SUCCEEDED, 15))
        self.assertEqual(len(r.steps), 16)

    def test_linear(self):
        r = sim.simulate(LINEAR1, 20)
        self.assertEqual(greens(r), [10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
        r3 = sim.simulate(LINEAR3, 40)
        self.assertEqual([s.green_percent for s in r3.steps if s.minute % 3 == 0][:4], [10, 20, 30, 40])
        self.assertEqual(r3.steps[4].green_percent, 20)  # minute 4 is still in the second step

    def test_linear_with_uneven_percent_caps_at_100(self):
        r = sim.simulate("Custom.ECSLinear30PercentEvery1Minutes", 10)
        self.assertEqual(greens(r), [30, 60, 90, 100])

    def test_horizon_too_short_is_in_progress(self):
        r = sim.simulate(CANARY15, 5)
        self.assertEqual(r.outcome, sim.IN_PROGRESS)
        self.assertIsNone(r.outcome_minute)
        self.assertEqual(len(r.steps), 6)


class RollbackTests(unittest.TestCase):
    def test_alarm_mid_canary_rolls_back(self):
        r = sim.simulate(CANARY5, 20, alarm_at=3, termination_wait_minutes=10)
        self.assertEqual(greens(r), [10, 10, 10, 0])
        self.assertEqual((r.outcome, r.outcome_minute, r.peak_green_percent), (sim.ROLLED_BACK, 3, 10))
        self.assertIn("rollback", r.steps[-1].events[0])

    def test_alarm_at_canary_step_beats_the_shift(self):
        r = sim.simulate(CANARY5, 20, alarm_at=5, termination_wait_minutes=10)
        self.assertEqual(r.outcome, sim.ROLLED_BACK)
        self.assertEqual(r.peak_green_percent, 10)

    def test_alarm_mid_linear(self):
        r = sim.simulate(LINEAR1, 20, alarm_at=4, termination_wait_minutes=5)
        self.assertEqual(greens(r), [10, 20, 30, 40, 0])
        self.assertEqual(r.peak_green_percent, 40)

    def test_alarm_during_termination_wait_still_rolls_back(self):
        r = sim.simulate(CANARY5, 30, alarm_at=12, termination_wait_minutes=10)
        self.assertEqual((r.outcome, r.outcome_minute, r.peak_green_percent), (sim.ROLLED_BACK, 12, 100))

    def test_all_at_once_alarm_rolls_back_from_100(self):
        r = sim.simulate(ALL, 10, alarm_at=2, termination_wait_minutes=5)
        self.assertEqual((r.outcome, r.peak_green_percent), (sim.ROLLED_BACK, 100))

    def test_alarm_after_blue_terminated_cannot_roll_back(self):
        r = sim.simulate(CANARY5, 30, alarm_at=20, termination_wait_minutes=10)
        self.assertEqual((r.outcome, r.outcome_minute), (sim.SUCCEEDED, 15))

    def test_alarm_at_termination_minute_does_not_roll_back(self):
        r = sim.simulate(CANARY5, 30, alarm_at=15, termination_wait_minutes=10)
        self.assertEqual(r.outcome, sim.SUCCEEDED)
        self.assertTrue(any("no automatic rollback" in e for e in r.steps[-1].events))

    def test_zero_termination_wait_leaves_no_rollback_window_after_shift(self):
        r = sim.simulate(ALL, 5, alarm_at=1, termination_wait_minutes=0)
        self.assertEqual((r.outcome, r.outcome_minute), (sim.SUCCEEDED, 0))

    def test_invalid_inputs(self):
        for kwargs in ({"total_minutes": -1}, {"alarm_at": -2}, {"termination_wait_minutes": -1}):
            args = {"config_name": CANARY5, "total_minutes": 10, **kwargs}
            with self.subTest(kwargs=kwargs), self.assertRaises(sim.SimulationError):
                sim.simulate(**args)


class RenderTests(unittest.TestCase):
    def test_text_and_dict(self):
        r = sim.simulate(CANARY5, 20, alarm_at=3, termination_wait_minutes=10)
        text = sim.render_text(r)
        self.assertTrue(text.endswith("result: ROLLED_BACK at minute 3; 100% back on blue (green peaked at 10%)"))
        data = r.to_dict()
        self.assertEqual(data["steps"][0]["blue_percent"], 90)
        events_only = sim.render_text(sim.simulate(LINEAR3, 40), events_only=True)
        self.assertNotIn("\n     1 ", events_only)


if __name__ == "__main__":
    unittest.main()
