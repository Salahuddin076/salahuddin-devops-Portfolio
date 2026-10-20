"""Unit tests for DegradingClient: the happy path, the degrade-and-queue
path, and that non-connectivity errors are never swallowed."""

from __future__ import annotations

import unittest

from helpers import CountingIds, FakeClock

from degrade.client import CallOutcome, DegradingClient
from degrade.exceptions import OnPremUnavailableError
from degrade.outbox import InMemoryOutbox


class FlakyTransport:
    def __init__(self) -> None:
        self.down = False
        self.calls: list[dict] = []
        self.raise_value_error = False

    def __call__(self, payload: dict) -> dict:
        self.calls.append(payload)
        if self.raise_value_error:
            raise ValueError("negative amount")
        if self.down:
            raise OnPremUnavailableError("tunnel down")
        return {"status": "posted", "n": len(self.calls)}


class DegradingClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.outbox = InMemoryOutbox(clock=self.clock, id_factory=CountingIds("obx"))
        self.transport = FlakyTransport()

    def test_happy_path_completes_synchronously_and_does_not_touch_outbox(self) -> None:
        client = DegradingClient(self.transport, self.outbox, clock=self.clock)
        result = client.call_or_queue("post_ledger_entry", {"account": "a1"})
        self.assertEqual(result.outcome, CallOutcome.COMPLETED)
        self.assertFalse(result.queued)
        self.assertEqual(result.result, {"status": "posted", "n": 1})
        self.assertEqual(self.outbox.pending(), [])

    def test_on_prem_unavailable_degrades_to_queued_instead_of_raising(self) -> None:
        self.transport.down = True
        client = DegradingClient(self.transport, self.outbox, clock=self.clock)

        result = client.call_or_queue("post_ledger_entry", {"account": "a1"})

        self.assertEqual(result.outcome, CallOutcome.QUEUED)
        self.assertTrue(result.queued)
        self.assertIsNone(result.result)
        self.assertIsNotNone(result.outbox_entry)
        pending = self.outbox.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].operation, "post_ledger_entry")
        self.assertEqual(pending[0].payload, {"account": "a1"})

    def test_timeout_error_also_degrades(self) -> None:
        def timing_out(payload: dict) -> dict:
            raise TimeoutError("socket timed out after 2000ms")

        client = DegradingClient(timing_out, self.outbox, clock=self.clock)
        result = client.call_or_queue("post_ledger_entry", {"account": "a1"})
        self.assertTrue(result.queued)

    def test_non_connectivity_error_propagates_and_is_not_queued(self) -> None:
        self.transport.raise_value_error = True
        client = DegradingClient(self.transport, self.outbox, clock=self.clock)

        with self.assertRaises(ValueError):
            client.call_or_queue("post_ledger_entry", {"account": "a1"})

        self.assertEqual(self.outbox.pending(), [], "a business-rule rejection must never be queued for silent retry")

    def test_on_degrade_hook_is_called_with_operation_payload_and_exception(self) -> None:
        self.transport.down = True
        seen = []
        client = DegradingClient(
            self.transport,
            self.outbox,
            clock=self.clock,
            on_degrade=lambda op, payload, exc: seen.append((op, payload, str(exc))),
        )
        client.call_or_queue("post_ledger_entry", {"account": "a1"})
        self.assertEqual(seen, [("post_ledger_entry", {"account": "a1"}, "tunnel down")])

    def test_service_keeps_accepting_requests_while_link_is_down(self) -> None:
        """The core claim of the pattern: N requests during an outage all
        get a successful (queued) outcome, none raise, and all land in the
        outbox for later replay."""
        self.transport.down = True
        client = DegradingClient(self.transport, self.outbox, clock=self.clock)

        results = [client.call_or_queue("post_ledger_entry", {"account": f"a{i}"}) for i in range(10)]

        self.assertTrue(all(r.queued for r in results))
        self.assertEqual(len(self.outbox.pending()), 10)


if __name__ == "__main__":
    unittest.main()
