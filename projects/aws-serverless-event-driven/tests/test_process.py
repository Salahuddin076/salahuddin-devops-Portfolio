import json
import unittest

from helpers import Harness, valid_order

from idempotency import payload_hash
from process import handle, process_batch


def sqs_record(message_id, body, correlation_id="corr-test", receive_count=1):
    if not isinstance(body, str):
        body = json.dumps(body)
    return {
        "messageId": message_id,
        "receiptHandle": f"rh-{message_id}",
        "body": body,
        "attributes": {"ApproximateReceiveCount": str(receive_count)},
        "messageAttributes": {"correlationId": {"stringValue": correlation_id, "dataType": "String"}},
        "eventSource": "aws:sqs",
    }


def order_message(key="key-00000001", order=None, order_id=None):
    order = order or valid_order()
    return {
        "schemaVersion": 1,
        "orderId": order_id or f"ord_{key}",
        "idempotencyKey": key,
        "payloadHash": payload_hash(order),
        "receivedAt": "2026-09-21T00:00:00.000Z",
        "order": order,
    }


class ProcessRecordTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def test_happy_path_records_order_and_publishes_event(self):
        response = handle({"Records": [sqs_record("m1", order_message())]}, self.h.process_deps)
        self.assertEqual(response, {"batchItemFailures": []})

        order = self.h.store.items["ORDER#ord_key-00000001"]
        self.assertEqual(order["status"], "ACCEPTED")
        self.assertEqual(order["total_cents"], 3900)
        self.assertEqual(order["item_count"], 3)
        self.assertNotIn("expires_at", order, "order records must not expire")
        self.assertEqual(self.h.store.items["IDEMPOTENCY#key-00000001"]["status"], "COMPLETED")
        self.assertEqual(len(self.h.bus.entries), 1)

    def test_partial_batch_failure_reports_only_failed_ids(self):
        records = [
            sqs_record("m1", order_message("key-00000001")),
            sqs_record("m2", "{this is not json"),
            sqs_record("m3", order_message("key-00000003")),
            sqs_record("m4", {"schemaVersion": 1}),
        ]
        response = handle({"Records": records}, self.h.process_deps)
        self.assertEqual(
            response,
            {"batchItemFailures": [{"itemIdentifier": "m2"}, {"itemIdentifier": "m4"}]},
        )
        self.assertEqual(len(self.h.bus.entries), 2)

    def test_response_contains_only_batch_item_failures(self):
        response = handle({"Records": [sqs_record("m1", order_message())]}, self.h.process_deps)
        self.assertEqual(set(response), {"batchItemFailures"})

    def test_duplicate_completed_is_skipped_with_stored_result(self):
        first = process_batch({"Records": [sqs_record("m1", order_message())]}, self.h.process_deps)
        second = process_batch({"Records": [sqs_record("m2", order_message())]}, self.h.process_deps)
        self.assertEqual(first.records[0].status, "processed")
        self.assertEqual(second.records[0].status, "duplicate")
        self.assertEqual(second.records[0].result, first.records[0].result)
        self.assertEqual(len(self.h.bus.entries), 1, "duplicate must not publish again")
        self.assertEqual(second.failed_ids, [])

    def test_duplicate_in_same_batch_processed_once(self):
        batch = process_batch(
            {"Records": [sqs_record("m1", order_message()), sqs_record("m2", order_message())]},
            self.h.process_deps,
        )
        self.assertEqual([r.status for r in batch.records], ["processed", "duplicate"])
        self.assertEqual(len(self.h.bus.entries), 1)

    def test_in_progress_duplicate_is_retried_not_processed(self):
        self.h.guard.claim("key-00000001", payload_hash(valid_order()))  # someone else holds it
        batch = process_batch({"Records": [sqs_record("m1", order_message())]}, self.h.process_deps)
        self.assertEqual(batch.failed_ids, ["m1"])
        self.assertTrue(batch.records[0].retryable)
        self.assertEqual(self.h.bus.entries, [])

    def test_publish_failure_releases_lock_and_is_retryable(self):
        h = Harness(bus_failures=1)
        first = process_batch({"Records": [sqs_record("m1", order_message())]}, h.process_deps)
        self.assertEqual(first.failed_ids, ["m1"])
        self.assertTrue(first.records[0].retryable)
        self.assertNotIn("IDEMPOTENCY#key-00000001", h.store.items)

        retry = process_batch({"Records": [sqs_record("m1", order_message(), receive_count=2)]}, h.process_deps)
        self.assertEqual(retry.records[0].status, "processed")
        self.assertEqual(len(h.bus.entries), 1)

    def test_poison_messages_are_non_retryable_failures(self):
        cases = {
            "bad-json": "{oops",
            "not-object": "[1, 2]",
            "missing": {"schemaVersion": 1, "orderId": "ord_x"},
            "version": {**order_message(), "schemaVersion": 2},
            "invalid-order": order_message(order={"customerId": "nope", "currency": "USD", "items": []}),
            "tampered": {**order_message(), "payloadHash": "0" * 64},
        }
        records = [sqs_record(mid, body) for mid, body in cases.items()]
        batch = process_batch({"Records": records}, self.h.process_deps)
        self.assertEqual(batch.failed_ids, list(cases))
        self.assertTrue(all(r.retryable is False for r in batch.records))
        self.assertEqual(self.h.bus.entries, [])

    def test_key_reuse_with_different_payload_is_poison(self):
        process_batch({"Records": [sqs_record("m1", order_message())]}, self.h.process_deps)
        changed = valid_order(currency="EUR")
        batch = process_batch({"Records": [sqs_record("m2", order_message(order=changed))]}, self.h.process_deps)
        self.assertEqual(batch.failed_ids, ["m2"])
        self.assertEqual(batch.records[0].reason, "idempotency key reused with a different payload")
        self.assertFalse(batch.records[0].retryable)

    def test_correlation_id_flows_into_event_and_logs(self):
        process_batch({"Records": [sqs_record("m1", order_message(), correlation_id="req-xyz")]}, self.h.process_deps)
        detail = self.h.bus.details()[0]
        self.assertEqual(detail["metadata"]["correlationId"], "req-xyz")
        accepted = [r for r in self.h.logs() if r["message"] == "order_accepted"][0]
        self.assertEqual(accepted["correlation_id"], "req-xyz")
        self.assertEqual(accepted["message_id"], "m1")
        self.assertEqual(self.h.store.items["ORDER#ord_key-00000001"]["correlation_id"], "req-xyz")

    def test_missing_correlation_attribute_falls_back_to_message_id(self):
        record = sqs_record("m9", order_message())
        record["messageAttributes"] = {}
        process_batch({"Records": [record]}, self.h.process_deps)
        self.assertEqual(self.h.bus.details()[0]["metadata"]["correlationId"], "sqs-m9")

    def test_empty_event(self):
        self.assertEqual(handle({"Records": []}, self.h.process_deps), {"batchItemFailures": []})


if __name__ == "__main__":
    unittest.main()
