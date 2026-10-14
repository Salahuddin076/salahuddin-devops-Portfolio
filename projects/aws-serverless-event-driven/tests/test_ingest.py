import base64
import json
import unittest

from helpers import Harness, api_event, valid_order

from ingest import handle, order_id_for
from validation import MAX_BODY_BYTES


def body_of(response):
    return json.loads(response["body"])


class IngestValidationTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def test_valid_request_is_accepted_and_enqueued(self):
        response = handle(api_event(key="key-00000001"), self.h.ingest_deps)
        self.assertEqual(response["statusCode"], 202)
        body = body_of(response)
        self.assertEqual(body["status"], "ACCEPTED")
        self.assertEqual(body["orderId"], order_id_for("key-00000001"))
        self.assertEqual(self.h.queue.sent_count, 1)

        message = json.loads(self.h.queue.messages[0].body)
        self.assertEqual(message["schemaVersion"], 1)
        self.assertEqual(message["idempotencyKey"], "key-00000001")
        self.assertEqual(message["order"], valid_order())
        self.assertEqual(message["receivedAt"], "2026-09-21T14:13:20.000Z")

    def test_missing_idempotency_key_is_400_and_not_enqueued(self):
        response = handle(api_event(key=None), self.h.ingest_deps)
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(
            body_of(response)["details"],
            [{"field": "Idempotency-Key", "message": "header is required"}],
        )
        self.assertEqual(self.h.queue.sent_count, 0)

    def test_header_name_is_case_insensitive(self):
        event = api_event()
        event["headers"] = {"Idempotency-Key": "key-00000009", "Content-Type": "application/json"}
        self.assertEqual(handle(event, self.h.ingest_deps)["statusCode"], 202)

    def test_schema_errors_are_400_with_details(self):
        response = handle(api_event({"customerId": "cus_demo0001", "currency": "JPY", "items": []}), self.h.ingest_deps)
        self.assertEqual(response["statusCode"], 400)
        body = body_of(response)
        self.assertEqual(body["error"], "validation_failed")
        self.assertEqual([d["field"] for d in body["details"]], ["currency", "items"])
        self.assertEqual(self.h.queue.sent_count, 0)

    def test_header_and_body_errors_reported_together(self):
        response = handle(api_event({"currency": "USD"}, key="bad key"), self.h.ingest_deps)
        fields = [d["field"] for d in body_of(response)["details"]]
        self.assertEqual(fields, ["Idempotency-Key", "customerId", "items"])

    def test_malformed_json_is_400(self):
        response = handle(api_event(raw="{not json"), self.h.ingest_deps)
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(body_of(response)["details"][0]["message"], "body is not valid JSON")

    def test_empty_body_is_400(self):
        response = handle(api_event(raw=""), self.h.ingest_deps)
        self.assertEqual(response["statusCode"], 400)

    def test_base64_body_is_decoded(self):
        event = api_event()
        event["body"] = base64.b64encode(event["body"].encode()).decode()
        event["isBase64Encoded"] = True
        self.assertEqual(handle(event, self.h.ingest_deps)["statusCode"], 202)

    def test_invalid_base64_is_400(self):
        event = api_event(raw="%%%not-base64%%%")
        event["isBase64Encoded"] = True
        self.assertEqual(handle(event, self.h.ingest_deps)["statusCode"], 400)

    def test_oversized_body_is_413(self):
        response = handle(api_event(raw="x" * (MAX_BODY_BYTES + 1)), self.h.ingest_deps)
        self.assertEqual(response["statusCode"], 413)
        self.assertEqual(self.h.queue.sent_count, 0)

    def test_queue_outage_is_503_with_retry_after(self):
        h = Harness(queue_send_failures=1)
        response = handle(api_event(), h.ingest_deps)
        self.assertEqual(response["statusCode"], 503)
        self.assertEqual(response["headers"]["retry-after"], "1")
        self.assertEqual([r["message"] for r in h.logs()], ["enqueue_failed"])


class IngestCorrelationTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def test_client_correlation_id_is_propagated_to_sqs_attributes(self):
        response = handle(api_event(correlation_id="req-abc-123"), self.h.ingest_deps)
        self.assertEqual(response["headers"]["x-correlation-id"], "req-abc-123")
        self.assertEqual(body_of(response)["correlationId"], "req-abc-123")
        self.assertEqual(self.h.queue.messages[0].attributes, {"correlationId": "req-abc-123"})

    def test_correlation_id_generated_when_absent(self):
        response = handle(api_event(), self.h.ingest_deps)
        self.assertEqual(response["headers"]["x-correlation-id"], "corr-0001")
        self.assertEqual(self.h.queue.messages[0].attributes["correlationId"], "corr-0001")

    def test_unsafe_correlation_id_is_replaced(self):
        response = handle(api_event(correlation_id="evil\ninjected"), self.h.ingest_deps)
        self.assertEqual(response["headers"]["x-correlation-id"], "corr-0001")

    def test_rejections_also_carry_the_correlation_id_and_log_it(self):
        response = handle(api_event(key=None, correlation_id="req-400"), self.h.ingest_deps)
        self.assertEqual(response["headers"]["x-correlation-id"], "req-400")
        record = self.h.logs()[0]
        self.assertEqual(record["correlation_id"], "req-400")
        self.assertEqual(record["reason"], "validation_failed")

    def test_same_key_returns_same_order_id(self):
        first = body_of(handle(api_event(key="key-retry-0001"), self.h.ingest_deps))
        second = body_of(handle(api_event(key="key-retry-0001"), self.h.ingest_deps))
        self.assertEqual(first["orderId"], second["orderId"])
        self.assertNotEqual(order_id_for("key-retry-0001"), order_id_for("key-retry-0002"))


if __name__ == "__main__":
    unittest.main()
