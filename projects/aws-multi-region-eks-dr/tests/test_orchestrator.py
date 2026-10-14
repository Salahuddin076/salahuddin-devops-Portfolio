"""Failover orchestrator against the in-memory world: order, guards, resume, audit."""

import unittest

from helpers import DR, GCID, PRIMARY, CrashingStore, build, rebuild

from failover.fakes import FakeCloud
from failover.orchestrator import (
    STEP_IDS,
    ConfirmationError,
    FailbackRefused,
    LagTooHigh,
    PostcheckFailed,
    PrecheckFailed,
    RunConflict,
    SplitBrainRefused,
    StepFailed,
)


def events(audit):
    return [(r["event"], r["step"]) for r in audit.records]


class PlannedHappyPathTests(unittest.TestCase):
    def setUp(self):
        self.orch, self.world, self.store, self.audit = build("healthy")
        self.result = self.orch.execute("planned", GCID)

    def test_steps_run_in_exact_order(self):
        self.assertEqual([s[0] for s in self.result.steps], list(STEP_IDS))
        self.assertTrue(all(s[1] == "done" for s in self.result.steps))

    def test_side_effects_in_order(self):
        # fence before promote, promote before scale-up, scale-up before DNS
        self.assertEqual(self.world.mutating_calls(), [
            ("set_scale", (PRIMARY, None, 0)),
            ("switchover", (DR,)),
            ("set_scale", (DR, 3, 2)),
            ("set_active", (DR,)),
        ])

    def test_end_state(self):
        self.assertEqual(self.world.writer, DR)
        self.assertEqual(self.world.members, [PRIMARY, DR])  # topology kept: no data loss
        self.assertEqual(self.world.dns_primary, DR)
        self.assertEqual(self.world.regions[PRIMARY].workers, 0)
        self.assertEqual(self.world.regions[DR].workers, 2)
        self.assertEqual(self.world.regions[DR].api_min_replicas, 3)

    def test_state_file(self):
        state = self.store.data
        self.assertEqual(state["writer_region"], DR)
        self.assertEqual(state["epoch"], 1)
        self.assertIsNone(state["run"])
        self.assertEqual(state["fenced"][PRIMARY]["workers_confirmed_zero"], True)
        self.assertEqual(state["history"][-1]["status"], "completed")
        self.assertEqual(list(state["history"][-1]["steps"]), list(STEP_IDS))

    def test_second_execute_is_a_noop(self):
        calls = len(self.world.mutating_calls())
        again = self.orch.execute("planned", GCID, target=DR)
        self.assertTrue(again.noop)
        self.assertEqual(len(self.world.mutating_calls()), calls)
        self.assertEqual(self.audit.records[-1]["event"], "noop")


class UnplannedTests(unittest.TestCase):
    def test_primary_unreachable_fence_skipped_but_recorded(self):
        orch, world, store, audit = build("primary-down")
        result = orch.execute("unplanned", GCID)
        steps = {sid: (status, detail) for sid, status, detail in result.steps}
        self.assertEqual(steps["fence-source"][0], "skipped")
        self.assertIn("NOT confirmed", steps["fence-source"][1])
        self.assertIn("Fence later", steps["fence-source"][1])
        state = store.data
        self.assertEqual(state["fenced"][PRIMARY]["workers_confirmed_zero"], False)
        self.assertEqual(state["history"][-1]["rpo_exposure_seconds"], 1.2)
        # detach + promote, never a switchover (it would need the dead primary)
        names = [c[0] for c in world.mutating_calls()]
        self.assertIn("detach_and_promote", names)
        self.assertNotIn("switchover", names)
        self.assertEqual(world.detached, [DR])
        self.assertEqual(world.dns_primary, DR)
        skipped = [r for r in audit.records if r["event"] == "step_skipped"]
        self.assertEqual([r["step"] for r in skipped], ["fence-source"])

    def test_unplanned_refused_when_source_is_healthy(self):
        orch, world, store, _ = build("healthy")
        with self.assertRaises(PrecheckFailed) as ctx:
            orch.execute("unplanned", GCID)
        self.assertIn("Use --mode planned", str(ctx.exception))
        self.assertEqual(world.mutating_calls(), [])
        self.assertIsNone(store.data["run"])

    def test_planned_refused_when_source_is_down(self):
        orch, world, _, _ = build("primary-down")
        with self.assertRaises(PrecheckFailed) as ctx:
            orch.execute("planned", GCID)
        self.assertIn("--mode unplanned", str(ctx.exception))
        self.assertEqual(world.mutating_calls(), [])

    def test_unhealthy_target_refused(self):
        world = FakeCloud.scenario("healthy")
        world.regions[DR].healthy = False
        orch, world, _, _ = build(world=world)
        with self.assertRaises(PrecheckFailed):
            orch.execute("planned", GCID)
        self.assertEqual(world.mutating_calls(), [])


class ResumeTests(unittest.TestCase):
    def test_crash_mid_run_resumes_without_repeating_steps(self):
        orch, world, store, audit = build("healthy")
        world.fail_next["set_active"] = 1  # Route 53 call fails once
        with self.assertRaises(StepFailed):
            orch.execute("planned", GCID)
        state = store.data
        self.assertEqual(state["run"]["status"], "failed")
        self.assertEqual(state["run"]["failed_step"], "flip-dns")
        before = list(world.mutating_calls())

        second = rebuild(world, store, audit)
        result = second.execute("planned", GCID)
        after = world.mutating_calls()[len(before):]
        # only the failed step's action runs again
        self.assertEqual(after, [("set_active", (DR,))])
        self.assertEqual([c[0] for c in world.calls].count("switchover"), 1)
        resumed = [r["step"] for r in audit.records if r["event"] == "step_resume_skip"]
        self.assertEqual(resumed, ["precheck", "fence-source", "promote-target", "scale-target"])
        self.assertEqual([s[0] for s in result.steps], list(STEP_IDS))
        self.assertEqual(store.data["epoch"], 1)  # promotion counted once

    def test_crash_after_switchover_before_recording(self):
        # saves: 1 run created, 2 precheck, 3 fence, 4 promote <- crash here
        store = CrashingStore(crash_on_save=4)
        orch, world, store, audit = build("healthy", store=store)
        with self.assertRaises(KeyboardInterrupt):
            orch.execute("planned", GCID)
        self.assertEqual(world.writer, DR)  # the switchover itself happened
        self.assertNotIn("promote-target", store.data["run"]["steps"])

        result = rebuild(world, store, audit).execute("planned", GCID)
        self.assertEqual([c[0] for c in world.calls].count("switchover"), 1)
        promote = dict((s[0], s[2]) for s in result.steps)["promote-target"]
        self.assertIn("already the global writer", promote)
        self.assertEqual(store.data["epoch"], 1)

    def test_resume_in_other_mode_is_refused(self):
        orch, world, store, audit = build("healthy")
        world.fail_next["set_active"] = 1
        with self.assertRaises(StepFailed):
            orch.execute("planned", GCID)
        with self.assertRaises(RunConflict):
            rebuild(world, store, audit).execute("unplanned", GCID)

    def test_dns_change_not_taking_effect_fails_the_step(self):
        orch, world, store, audit = build("healthy")
        orch.a.dns.set_active = lambda region: None  # change silently ignored
        with self.assertRaises(StepFailed):
            orch.execute("planned", GCID)
        self.assertEqual(store.data["run"]["failed_step"], "flip-dns")

    def test_postcheck_detects_workers_left_in_source(self):
        orch, world, store, audit = build("healthy")
        original = world.set_scale

        def leaky(region, api_min_replicas=None, workers=None):
            original(region, api_min_replicas, workers)
            if region == PRIMARY and workers == 0:
                world.regions[PRIMARY].workers = 1  # someone scaled it back up

        world.set_scale = leaky
        with self.assertRaises(PostcheckFailed) as ctx:
            orch.execute("planned", GCID)
        self.assertIn("still runs 1 workers", str(ctx.exception))
        self.assertEqual(store.data["run"]["failed_step"], "postcheck")


class GuardTests(unittest.TestCase):
    def test_confirm_token_mismatch(self):
        orch, world, store, audit = build("healthy")
        with self.assertRaises(ConfirmationError) as ctx:
            orch.execute("planned", "dr-app-globl")
        self.assertIn("does not match", str(ctx.exception))
        self.assertEqual(world.mutating_calls(), [])
        self.assertIsNone(store.data)  # nothing written
        self.assertEqual(audit.records[-1]["event"], "refused")
        self.assertEqual(audit.records[-1]["status"], "confirm-mismatch")

    def test_split_brain_refused_when_other_run_already_promoted(self):
        orch, world, store, audit = build("healthy")
        world.fail_next["set_active"] = 1
        with self.assertRaises(StepFailed):
            orch.execute("planned", GCID)  # promoted us-west-2, then stopped at DNS
        with self.assertRaises(SplitBrainRefused) as ctx:
            rebuild(world, store, audit, actor="oncall-b").execute("planned", GCID, target=PRIMARY)
        self.assertIn("already promoted us-west-2", str(ctx.exception))
        self.assertEqual(audit.records[-1]["status"], "split-brain")
        self.assertEqual(audit.records[-1]["actor"], "oncall-b")

    def test_split_brain_refused_with_two_unfenced_writers(self):
        orch, world, store, audit = build("split-brain")
        with self.assertRaises(SplitBrainRefused):
            orch.execute("planned", GCID)
        self.assertEqual(world.mutating_calls(), [])
        self.assertIn("SPLIT BRAIN", " ".join(orch.status()["warnings"]))

    def test_failback_refused_without_rebuild_flag(self):
        orch, world, store, audit = build("healthy")
        orch.execute("planned", GCID)
        with self.assertRaises(FailbackRefused) as ctx:
            orch.execute("planned", GCID, target=PRIMARY)
        self.assertIn("--rebuild-confirmed", str(ctx.exception))
        self.assertEqual(world.writer, DR)

    def test_failback_after_planned_switchover(self):
        orch, world, store, audit = build("healthy")
        orch.execute("planned", GCID)
        result = orch.execute("planned", GCID, target=PRIMARY, rebuild_confirmed=True)
        self.assertEqual([s[0] for s in result.steps], list(STEP_IDS))
        state = store.data
        self.assertEqual(state["writer_region"], PRIMARY)
        self.assertEqual(state["epoch"], 2)
        self.assertNotIn(PRIMARY, state["fenced"])
        self.assertIn(DR, state["fenced"])
        self.assertEqual(world.regions[DR].workers, 0)
        self.assertEqual(world.dns_primary, PRIMARY)

    def test_failback_after_unplanned_needs_real_rebuild(self):
        orch, world, store, audit = build("primary-down")
        orch.execute("unplanned", GCID)
        world.regions[PRIMARY].reachable = True  # region is back, cluster not rebuilt
        world.regions[PRIMARY].healthy = True
        with self.assertRaises(PrecheckFailed) as ctx:
            orch.execute("planned", GCID, target=PRIMARY, rebuild_confirmed=True)
        self.assertIn("not been rebuilt", str(ctx.exception))
        world.rebuild_as_secondary(PRIMARY)
        orch.execute("planned", GCID, target=PRIMARY, rebuild_confirmed=True)
        self.assertEqual(world.writer, PRIMARY)
        self.assertEqual(store.data["epoch"], 2)

    def test_lag_threshold_blocks_planned_mode(self):
        orch, world, store, audit = build("lagging")
        with self.assertRaises(LagTooHigh) as ctx:
            orch.execute("planned", GCID)
        self.assertIn("42.0s", str(ctx.exception))
        self.assertEqual(world.mutating_calls(), [])
        state = store.data
        self.assertIsNone(state["run"])
        self.assertEqual(state["history"][-1]["status"], "aborted")
        self.assertEqual(audit.records[-1]["event"], "run_aborted")

    def test_lag_at_threshold_and_unknown_lag_block(self):
        for lag in (5.0, None):
            with self.subTest(lag=lag):
                world = FakeCloud.scenario("healthy")
                world.lag[DR] = lag
                orch, world, _, _ = build(world=world)
                with self.assertRaises(LagTooHigh):
                    orch.execute("planned", GCID)

    def test_lag_just_below_threshold_passes(self):
        world = FakeCloud.scenario("healthy")
        world.lag[DR] = 4.9
        orch, world, _, _ = build(world=world)
        orch.execute("planned", GCID)
        self.assertEqual(world.writer, DR)


class AuditTests(unittest.TestCase):
    def test_happy_path_audit_sequence(self):
        orch, _, _, audit = build("healthy")
        orch.execute("planned", GCID)
        expected = [("run_started", None)]
        for sid in STEP_IDS:
            expected += [("step_started", sid), ("step_completed", sid)]
        expected.append(("run_completed", None))
        self.assertEqual(events(audit), expected)

    def test_every_line_carries_context(self):
        orch, _, _, audit = build("healthy")
        orch.execute("planned", GCID)
        run_ids = {r["run_id"] for r in audit.records}
        self.assertEqual(run_ids, {"20261014T090000Z-planned-us-west-2"})
        for r in audit.records:
            self.assertEqual(r["actor"], "oncall-a")
            self.assertEqual(r["global_cluster_id"], GCID)
            self.assertEqual((r["mode"], r["source"], r["target"]), ("planned", PRIMARY, DR))
            self.assertRegex(r["ts"], r"^2026-10-14T09:00:\d\dZ$")
        ts = [r["ts"] for r in audit.records]
        self.assertEqual(ts, sorted(ts))
        completed = [r for r in audit.records if r["event"] == "step_completed"]
        self.assertEqual(completed[2]["epoch"], 1)  # after promote-target


class PlanAndStatusTests(unittest.TestCase):
    def test_plan_lists_steps_without_side_effects(self):
        orch, world, store, audit = build("healthy")
        plan = orch.plan("planned")
        self.assertEqual([s.id for s in plan.steps], list(STEP_IDS))
        self.assertEqual((plan.source, plan.target), (PRIMARY, DR))
        self.assertIn("--switchover", plan.steps[2].detail)
        self.assertEqual(world.mutating_calls(), [])
        self.assertIsNone(store.data)
        self.assertEqual(audit.records, [])

    def test_unplanned_plan_mentions_rpo(self):
        orch, _, _, _ = build("primary-down")
        plan = orch.plan("unplanned")
        self.assertIn("remove-from-global-cluster", plan.steps[2].detail)
        self.assertIn("RPO", plan.steps[2].detail)

    def test_plan_shows_resume_position(self):
        orch, world, store, audit = build("healthy")
        world.fail_next["set_active"] = 1
        with self.assertRaises(StepFailed):
            orch.execute("planned", GCID)
        plan = orch.plan("planned")
        self.assertIsNotNone(plan.resumes_run)
        self.assertEqual([s.state for s in plan.steps], ["done"] * 4 + ["pending"] * 2)

    def test_status_after_unplanned_warns_about_old_writer(self):
        orch, world, _, _ = build("primary-down")
        orch.execute("unplanned", GCID)
        s = orch.status()
        regions = {r["region"]: r for r in s["regions"]}
        self.assertEqual(regions[PRIMARY]["health"], "unreachable")
        self.assertIsNone(regions[PRIMARY]["workers"])
        self.assertTrue(regions[PRIMARY]["fenced"])
        self.assertEqual(regions[DR]["db_role"], "writer (detached)")
        joined = " ".join(s["warnings"])
        self.assertIn("never confirmed at 0", joined)
        self.assertIn("still accepts writes", joined)
        self.assertNotIn("SPLIT BRAIN", joined)

    def test_status_healthy(self):
        orch, _, _, _ = build("healthy")
        s = orch.status()
        self.assertEqual(s["global_writer"], PRIMARY)
        self.assertEqual(s["warnings"], [])
        lag = {r["region"]: r["replication_lag_seconds"] for r in s["regions"]}
        self.assertEqual(lag, {PRIMARY: None, DR: 0.4})


if __name__ == "__main__":
    unittest.main()
