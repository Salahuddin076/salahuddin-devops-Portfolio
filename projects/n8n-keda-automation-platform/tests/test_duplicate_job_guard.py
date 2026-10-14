"""Idempotency guard: stable keys, conditional claims, and no double-send after a worker crash."""

from __future__ import annotations

import threading
import unittest

import duplicate_job_guard as g


class KeyTests(unittest.TestCase):
    def test_retry_has_the_same_key_as_the_original(self):
        original = g.idempotency_key("wf-1", "Send e-mail", execution_id="101")
        retry = g.idempotency_key("wf-1", "Send e-mail", execution_id="102", retry_of="101")
        self.assertEqual(original, retry)

    def test_business_key_wins_and_parts_matter(self):
        a = g.idempotency_key("wf-1", "Send e-mail", business_key="order-7", execution_id="101")
        self.assertEqual(a, g.idempotency_key("wf-1", "Send e-mail", business_key="order-7", execution_id="999"))
        for other in (g.idempotency_key("wf-2", "Send e-mail", business_key="order-7"),
                      g.idempotency_key("wf-1", "Post to CRM", business_key="order-7"),
                      g.idempotency_key("wf-1", "Send e-mail", business_key="order-7", item_index=1)):
            self.assertNotEqual(a, other)
        self.assertRegex(a, r"^idem:[0-9a-f]{32}$")

    def test_key_needs_an_anchor(self):
        with self.assertRaises(ValueError):
            g.idempotency_key("wf-1", "Send e-mail")
        with self.assertRaises(ValueError):
            g.idempotency_key("", "Send e-mail", execution_id="1")


class StoreContract:
    """Run against every Store implementation."""

    def make(self):
        raise NotImplementedError

    def test_first_claim_wins_second_is_busy(self):
        s = self.make()
        self.assertEqual(s.claim("k", "a", 100.0, 60).status, g.ACQUIRED)
        self.assertEqual(s.claim("k", "b", 110.0, 60).status, g.BUSY)

    def test_done_returns_stored_result(self):
        s = self.make()
        s.claim("k", "a", 100.0, 60)
        self.assertTrue(s.complete("k", "a", "msg-1"))
        claim = s.claim("k", "b", 5000.0, 60)
        self.assertEqual((claim.status, claim.result), (g.DONE, "msg-1"))

    def test_expired_lease_can_be_taken_over_once(self):
        s = self.make()
        s.claim("k", "a", 100.0, 60)
        takeover = s.claim("k", "b", 161.0, 60)
        self.assertEqual((takeover.status, takeover.takeover), (g.ACQUIRED, True))
        self.assertEqual(s.claim("k", "c", 162.0, 60).status, g.BUSY)
        self.assertFalse(s.complete("k", "a", "late"), "the crashed owner can no longer complete")
        self.assertTrue(s.complete("k", "b", "msg-2"))

    def test_release_frees_the_key(self):
        s = self.make()
        s.claim("k", "a", 100.0, 60)
        s.release("k", "a")
        self.assertEqual(s.claim("k", "b", 101.0, 60).status, g.ACQUIRED)

    def test_concurrent_claims_have_one_winner(self):
        s = self.make()
        results = []
        threads = [threading.Thread(target=lambda i=i: results.append(s.claim("k", f"w{i}", 100.0, 60).status))
                   for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(g.ACQUIRED), 1)
        self.assertEqual(results.count(g.BUSY), 15)


class MemoryStoreTests(StoreContract, unittest.TestCase):
    def make(self):
        return g.MemoryStore()


class SqliteStoreTests(StoreContract, unittest.TestCase):
    def make(self):
        return g.SqliteStore()


class GuardedTests(unittest.TestCase):
    def test_runs_once_then_returns_cached_result(self):
        store, calls = g.MemoryStore(), []
        effect = lambda k: calls.append(k) or "msg-1"  # noqa: E731
        self.assertEqual(g.guarded(store, "k", "a", effect, clock=lambda: 100.0), ("msg-1", True))
        self.assertEqual(g.guarded(store, "k", "b", effect, clock=lambda: 200.0), ("msg-1", False))
        self.assertEqual(calls, ["k"])

    def test_failed_effect_releases_the_key(self):
        store = g.SqliteStore()

        def boom(_):
            raise ConnectionError("provider down")

        with self.assertRaises(ConnectionError):
            g.guarded(store, "k", "a", boom, clock=lambda: 100.0)
        self.assertEqual(g.guarded(store, "k", "b", lambda k: "msg-1", clock=lambda: 101.0), ("msg-1", True))

    def test_live_lease_raises_already_in_progress(self):
        store = g.MemoryStore()
        store.claim("k", "a", 100.0, 300)
        with self.assertRaises(g.AlreadyInProgress):
            g.guarded(store, "k", "b", lambda k: "x", clock=lambda: 150.0)


class CrashRetryScenarioTests(unittest.TestCase):
    def test_crash_after_send_retry_does_not_double_send(self):
        out = g.run_scenario(guard=True, crash="after")
        self.assertEqual(out["delivered"], 1)
        self.assertIn("crashed after", out["log"][0][1])

    def test_crash_before_send_retry_sends_exactly_once(self):
        self.assertEqual(g.run_scenario(guard=True, crash="before")["delivered"], 1)

    def test_no_crash_retry_is_a_no_op(self):
        out = g.run_scenario(guard=True, crash="none")
        self.assertEqual(out["delivered"], 1)
        self.assertEqual(out["log"][0][1], out["log"][1][1], "retry returns the stored message id")

    def test_without_guard_the_retry_double_sends(self):
        self.assertEqual(g.run_scenario(guard=False, crash="after")["delivered"], 2)

    def test_limit_crash_after_send_needs_downstream_idempotency(self):
        # The honest edge: the claim can't know whether the send happened.
        self.assertEqual(g.run_scenario(guard=True, crash="after", provider_dedupe=False)["delivered"], 2)


if __name__ == "__main__":
    unittest.main()
