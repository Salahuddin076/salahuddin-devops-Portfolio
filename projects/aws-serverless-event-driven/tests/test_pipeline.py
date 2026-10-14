"""End-to-end through the fakes: API -> queue (with redrive) -> processor -> bus."""

import json
import unittest

from helpers import BUS_NAME, Harness, api_event

import ingest
import process


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(max_receive_count=3)
        self.consume = lambda event: process.handle(event, self.h.process_deps)

    def test_same_key_twice_processes_once_and_returns_same_order(self):
        first = ingest.handle(api_event(key="key-dup-0001"), self.h.ingest_deps)
        second = ingest.handle(api_event(key="key-dup-0001"), self.h.ingest_deps)
        self.assertEqual(json.loads(first["body"])["orderId"], json.loads(second["body"])["orderId"])

        report = self.h.queue.poll(self.consume)
        self.assertEqual(len(report.delivered), 2, "both messages are acknowledged")
        self.assertEqual(len(self.h.bus.entries), 1, "but only one OrderAccepted is published")
        self.assertEqual(self.h.queue.messages, [])
        self.assertEqual(self.h.queue.dlq, [])
        skipped = [r for r in self.h.logs() if r["message"] == "duplicate_skipped"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["stored_result"]["orderId"], json.loads(first["body"])["orderId"])

    def test_poison_message_is_redriven_to_dlq_after_max_receives(self):
        ingest.handle(api_event(key="key-good-0001"), self.h.ingest_deps)
        poison_id = self.h.queue.inject_raw("{truncated", {"correlationId": "req-poison"})

        reports = [self.h.queue.poll(self.consume) for _ in range(3)]
        self.assertEqual(reports[0].failed, [poison_id])
        self.assertEqual(reports[1].failed, [poison_id])
        self.assertEqual(reports[2].redriven_to_dlq, [poison_id])
        self.assertEqual([m.message_id for m in self.h.queue.dlq], [poison_id])
        self.assertEqual(self.h.queue.dlq[0].receive_count, 3)
        self.assertEqual(self.h.queue.messages, [])
        # The good order was not held back by its poisoned neighbour.
        self.assertEqual(len(self.h.bus.entries), 1)

        poison_logs = [r for r in self.h.logs() if r["message"] == "poison_message"]
        self.assertEqual([r["receive_count"] for r in poison_logs], [1, 2, 3])
        self.assertTrue(all(r["correlation_id"] == "req-poison" for r in poison_logs))

    def test_transient_failure_recovers_without_dlq(self):
        h = Harness(max_receive_count=3, bus_failures=1)
        ingest.handle(api_event(key="key-flaky-001"), h.ingest_deps)
        consume = lambda event: process.handle(event, h.process_deps)
        self.assertEqual(len(h.queue.poll(consume).failed), 1)
        self.assertEqual(len(h.queue.poll(consume).delivered), 1)
        self.assertEqual(h.queue.dlq, [])
        self.assertEqual(len(h.bus.entries), 1)

    def test_correlation_id_propagates_api_to_sqs_to_eventbridge(self):
        response = ingest.handle(api_event(correlation_id="req-trace-42"), self.h.ingest_deps)
        self.assertEqual(response["headers"]["x-correlation-id"], "req-trace-42")
        self.h.queue.poll(self.consume)

        detail = self.h.bus.details()[0]
        self.assertEqual(detail["metadata"]["correlationId"], "req-trace-42")
        traced = {r["message"] for r in self.h.logs() if r.get("correlation_id") == "req-trace-42"}
        self.assertEqual(traced, {"order_enqueued", "order_accepted"})

    def test_event_entry_targets_the_custom_bus(self):
        ingest.handle(api_event(), self.h.ingest_deps)
        self.h.queue.poll(self.consume)
        entry = self.h.bus.entries[0]
        self.assertEqual(entry["EventBusName"], BUS_NAME)
        self.assertEqual(entry["Source"], "com.example.orders")
        self.assertEqual(entry["DetailType"], "OrderAccepted")


if __name__ == "__main__":
    unittest.main()
