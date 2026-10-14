import io
import json
import unittest

from helpers import START, FakeClock

from adapters import EventBridgeBus, InMemoryQueue, SqsQueue
from logging_utils import JsonLogger, iso_timestamp


class JsonLoggerTests(unittest.TestCase):
    def test_one_json_object_per_line_with_bound_context(self):
        stream = io.StringIO()
        log = JsonLogger("svc", stream=stream, clock=FakeClock()).bind(correlation_id="req-1")
        log.info("hello", order_id="ord_1")
        log.bind(message_id="m1").warning("careful")
        lines = stream.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        first, second = (json.loads(line) for line in lines)
        self.assertEqual(
            first,
            {
                "timestamp": iso_timestamp(START),
                "level": "INFO",
                "service": "svc",
                "message": "hello",
                "correlation_id": "req-1",
                "order_id": "ord_1",
            },
        )
        self.assertEqual(second["message_id"], "m1")
        self.assertEqual(second["correlation_id"], "req-1")

    def test_level_filtering(self):
        stream = io.StringIO()
        log = JsonLogger("svc", level="WARNING", stream=stream)
        log.info("dropped")
        log.debug("dropped")
        log.error("kept")
        self.assertEqual([json.loads(l)["message"] for l in stream.getvalue().splitlines()], ["kept"])

    def test_unknown_level_rejected(self):
        with self.assertRaises(ValueError):
            JsonLogger("svc", level="LOUD")

    def test_iso_timestamp(self):
        self.assertEqual(iso_timestamp(0.5), "1970-01-01T00:00:00.500Z")


class _StubSqsClient:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "sqs-1"}


class _StubEventsClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def put_events(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class BotoAdapterTests(unittest.TestCase):
    """The real adapters, driven through stub clients (no boto3 import)."""

    def test_sqs_adapter_maps_attributes(self):
        client = _StubSqsClient()
        message_id = SqsQueue("https://sqs.example.com/q", client=client).send("{}", {"correlationId": "req-1"})
        self.assertEqual(message_id, "sqs-1")
        self.assertEqual(
            client.calls[0],
            {
                "QueueUrl": "https://sqs.example.com/q",
                "MessageBody": "{}",
                "MessageAttributes": {"correlationId": {"DataType": "String", "StringValue": "req-1"}},
            },
        )

    def test_eventbridge_adapter_success(self):
        client = _StubEventsClient({"FailedEntryCount": 0, "Entries": [{"EventId": "e1"}]})
        self.assertEqual(EventBridgeBus(client=client).put_events([{"Source": "s"}]), [])
        self.assertEqual(client.calls[0], {"Entries": [{"Source": "s"}]})

    def test_eventbridge_adapter_returns_failed_entries(self):
        client = _StubEventsClient(
            {
                "FailedEntryCount": 1,
                "Entries": [{"EventId": "e1"}, {"ErrorCode": "ThrottlingException", "ErrorMessage": "slow down"}],
            }
        )
        failed = EventBridgeBus(client=client).put_events([{"Source": "a"}, {"Source": "b"}])
        self.assertEqual(failed, [{"Source": "b", "ErrorCode": "ThrottlingException", "ErrorMessage": "slow down"}])


class InMemoryQueueTests(unittest.TestCase):
    def test_records_have_lambda_sqs_event_shape(self):
        queue = InMemoryQueue()
        queue.send("{}", {"correlationId": "req-1"})
        record = queue.receive_batch()[0]
        self.assertEqual(record["eventSource"], "aws:sqs")
        self.assertEqual(record["attributes"]["ApproximateReceiveCount"], "1")
        self.assertEqual(record["messageAttributes"]["correlationId"]["stringValue"], "req-1")

    def test_batch_size_is_respected(self):
        queue = InMemoryQueue()
        for _ in range(12):
            queue.send("{}", {})
        self.assertEqual(len(queue.receive_batch(10)), 10)


if __name__ == "__main__":
    unittest.main()
