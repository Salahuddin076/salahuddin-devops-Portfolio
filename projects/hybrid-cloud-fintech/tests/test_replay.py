"""Unit tests for replay_pending: draining the outbox once the link is back,
and the retry-budget / permanent-failure path."""

from __future__ import annotations

import unittest

from helpers import CountingIds, FakeClock

from degrade.client import DegradingClient
from degrade.exceptions import OnPremUnavailableError
from degrade.outbox import InMemoryOutbox, OutboxStatus
from degrade.replay import replay_pending


class AlwaysDown:
    def __call__(self, payload: dict) -> dict:
        raise OnPremUnavailableError("still down")


class AlwaysUp:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, payload: dict) -> dict:
        self.calls.append(payload)
        return {"status": "posted"}


class ReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.outbox = InMemoryOutbox(clock=self.clock, id_factory=CountingIds("obx"))

    def _queue_some(self, n: int) -> None:
        client = DegradingClient(AlwaysDown(), self.outbox, clock=self.clock)
        for i in range(n):
            client.call_or_queue("post_ledger_entry", {"account": f"a{i}"})

    def test_replay_drains_outbox_when_link_recovers(self) -> None:
        self._queue_some(3)
        self.assertEqual(len(self.outbox.pending()), 3)

        summary = replay_pending(self.outbox, AlwaysUp(), max_attempts=5)

        self.assertEqual(summary.attempted, 3)
        self.assertEqual(len(summary.succeeded), 3)
        self.assertEqual(summary.still_pending, [])
        self.assertEqual(summary.permanently_failed, [])
        self.assertTrue(summary.all_drained)
        self.assertEqual(self.outbox.pending(), [])

    def test_replay_leaves_entries_pending_while_link_is_still_down(self) -> None:
        self._queue_some(2)

        summary = replay_pending(self.outbox, AlwaysDown(), max_attempts=5)

        self.assertEqual(summary.attempted, 2)
        self.assertEqual(summary.succeeded, [])
        self.assertEqual(len(summary.still_pending), 2)
        self.assertFalse(summary.all_drained)
        for entry in self.outbox.pending():
            self.assertEqual(entry.attempts, 1)
            self.assertEqual(entry.status, OutboxStatus.PENDING)

    def test_entry_moves_to_permanently_failed_after_max_attempts(self) -> None:
        self._queue_some(1)

        for _ in range(3):
            summary = replay_pending(self.outbox, AlwaysDown(), max_attempts=3)

        self.assertEqual(summary.permanently_failed, [list(self.outbox.all())[0].id])
        self.assertEqual(self.outbox.pending(), [])
        entry = self.outbox.all()[0]
        self.assertEqual(entry.status, OutboxStatus.FAILED)
        self.assertEqual(entry.attempts, 3)

    def test_mixed_outcomes_in_one_replay_run(self) -> None:
        """One entry whose account is in a deny-list still raises a business
        error on replay, which must propagate rather than be absorbed as a
        connectivity failure -- replay has the same error-classification
        contract as the original call."""
        self._queue_some(2)

        def partial(payload: dict) -> dict:
            if payload["account"] == "a0":
                raise ValueError("account closed since queued")
            return {"status": "posted"}

        with self.assertRaises(ValueError):
            replay_pending(self.outbox, partial, max_attempts=5)


if __name__ == "__main__":
    unittest.main()
