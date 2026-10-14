"""Ports to AWS services, their boto3 implementations, and in-memory fakes.

The handlers depend only on the three small interfaces below. boto3 ships
with the Lambda Python runtime, so the real adapters import it lazily inside
their constructors: the test suite and the local demo never import it and
run on the standard library alone.

Each fake reproduces the behaviour the handlers rely on, not the whole API:

* ``InMemoryQueue`` models SQS standard-queue delivery as the Lambda event
  source mapping sees it: receive counts, visibility (a failed message comes
  back), and redrive to a dead-letter queue after ``max_receive_count``.
* ``InMemoryStore`` implements the same conditional-put rule the DynamoDB
  adapter sends as a ``ConditionExpression``.
* ``InMemoryEventBus`` records ``PutEvents`` entries and can be told to fail.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

IN_PROGRESS = "IN_PROGRESS"
COMPLETED = "COMPLETED"

# The claim rule, shared by the DynamoDB adapter and the fake. A key can be
# claimed when nobody holds it, when its record has passed its TTL (DynamoDB
# deletes expired items lazily, up to days later), or when a previous
# processor died holding the in-progress lock.
CLAIM_CONDITION = (
    "attribute_not_exists(pk) OR expires_at < :now "
    "OR (#status = :in_progress AND lock_expires_at < :now)"
)


# --------------------------------------------------------------------------
# Ports
# --------------------------------------------------------------------------


class QueuePort(Protocol):
    def send(self, body: str, attributes: dict[str, str]) -> str:
        """Enqueue a message with string message attributes; return its id."""


class StorePort(Protocol):
    def put_if_claimable(self, item: dict[str, Any], now: int) -> tuple[bool, dict[str, Any] | None]:
        """Conditionally write ``item``. Return (written, existing_item_if_not)."""

    def put(self, item: dict[str, Any]) -> None:
        """Unconditional write (upsert)."""

    def update(self, pk: str, fields: dict[str, Any]) -> None:
        """Set ``fields`` on an existing item."""

    def delete(self, pk: str) -> None:
        """Delete an item if present."""


class EventBusPort(Protocol):
    def put_events(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Publish entries; return the entries that failed (empty on success)."""


# --------------------------------------------------------------------------
# boto3 adapters (used inside Lambda only)
# --------------------------------------------------------------------------


class SqsQueue:
    def __init__(self, queue_url: str, client: Any = None) -> None:
        if client is None:
            import boto3  # available in the Lambda runtime

            client = boto3.client("sqs")
        self._client = client
        self._queue_url = queue_url

    def send(self, body: str, attributes: dict[str, str]) -> str:
        response = self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=body,
            MessageAttributes={
                name: {"DataType": "String", "StringValue": value}
                for name, value in attributes.items()
            },
        )
        return response["MessageId"]


class DynamoDbStore:
    def __init__(self, table_name: str, resource: Any = None) -> None:
        if resource is None:
            import boto3

            resource = boto3.resource("dynamodb")
        self._table = resource.Table(table_name)

    def put_if_claimable(self, item: dict[str, Any], now: int) -> tuple[bool, dict[str, Any] | None]:
        from boto3.dynamodb.types import TypeDeserializer
        from botocore.exceptions import ClientError

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression=CLAIM_CONDITION,
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":now": now, ":in_progress": IN_PROGRESS},
                # Return the blocking item with the failure: saves a GetItem
                # (and the IAM permission for it) on every duplicate.
                ReturnValuesOnConditionCheckFailure="ALL_OLD",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            raw = exc.response.get("Item") or {}
            deserializer = TypeDeserializer()
            existing = {key: deserializer.deserialize(value) for key, value in raw.items()}
            return False, _plain_numbers(existing)
        return True, None

    def put(self, item: dict[str, Any]) -> None:
        self._table.put_item(Item=item)

    def update(self, pk: str, fields: dict[str, Any]) -> None:
        names = {f"#f{i}": name for i, name in enumerate(fields)}
        values = {f":v{i}": value for i, value in enumerate(fields.values())}
        expression = "SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(fields)))
        self._table.update_item(
            Key={"pk": pk},
            UpdateExpression=expression,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def delete(self, pk: str) -> None:
        self._table.delete_item(Key={"pk": pk})


def _plain_numbers(item: dict[str, Any]) -> dict[str, Any]:
    """DynamoDB numbers deserialize as Decimal; the handlers only store ints."""
    out: dict[str, Any] = {}
    for key, value in item.items():
        if type(value).__name__ == "Decimal":
            out[key] = int(value)
        else:
            out[key] = value
    return out


class EventBridgeBus:
    def __init__(self, client: Any = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("events")
        self._client = client

    def put_events(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        response = self._client.put_events(Entries=entries)
        if response.get("FailedEntryCount", 0) == 0:
            return []
        return [
            {**entry, "ErrorCode": result.get("ErrorCode"), "ErrorMessage": result.get("ErrorMessage")}
            for entry, result in zip(entries, response["Entries"])
            if result.get("ErrorCode")
        ]


# --------------------------------------------------------------------------
# In-memory fakes (tests and scripts/local_demo.py)
# --------------------------------------------------------------------------


def sequential_ids(prefix: str) -> Callable[[], str]:
    """Deterministic id factory, so test and demo output is reproducible."""
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter):04d}"


@dataclass
class _Message:
    message_id: str
    body: str
    attributes: dict[str, str]
    receive_count: int = 0


@dataclass
class DeliveryReport:
    """What one simulated event-source-mapping poll did."""

    delivered: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    redriven_to_dlq: list[str] = field(default_factory=list)


class InMemoryQueue:
    """An SQS standard queue plus its DLQ, as seen through a Lambda ESM."""

    def __init__(
        self,
        *,
        max_receive_count: int = 3,
        id_factory: Callable[[], str] | None = None,
        fail_sends: int = 0,
    ) -> None:
        self.max_receive_count = max_receive_count
        self._ids = id_factory or sequential_ids("msg")
        self._fail_sends = fail_sends
        self.messages: list[_Message] = []
        self.dlq: list[_Message] = []
        self.sent_count = 0

    # QueuePort
    def send(self, body: str, attributes: dict[str, str]) -> str:
        if self._fail_sends > 0:
            self._fail_sends -= 1
            raise ConnectionError("simulated SQS outage")
        message = _Message(self._ids(), body, dict(attributes))
        self.messages.append(message)
        self.sent_count += 1
        return message.message_id

    def inject_raw(self, body: str, attributes: dict[str, str] | None = None) -> str:
        """Enqueue a message that bypassed the ingest API (e.g. a buggy producer)."""
        return self.send(body, attributes or {})

    def receive_batch(self, max_messages: int = 10) -> list[dict[str, Any]]:
        """Return Lambda SQS-event records, incrementing receive counts."""
        batch = self.messages[:max_messages]
        records = []
        for message in batch:
            message.receive_count += 1
            records.append(
                {
                    "messageId": message.message_id,
                    "receiptHandle": f"rh-{message.message_id}-{message.receive_count}",
                    "body": message.body,
                    "attributes": {"ApproximateReceiveCount": str(message.receive_count)},
                    "messageAttributes": {
                        name: {"stringValue": value, "dataType": "String"}
                        for name, value in message.attributes.items()
                    },
                    "eventSource": "aws:sqs",
                }
            )
        return records

    def settle(self, records: list[dict[str, Any]], failed_ids: set[str]) -> DeliveryReport:
        """Apply a batch response: delete successes, return or redrive failures."""
        report = DeliveryReport()
        by_id = {message.message_id: message for message in self.messages}
        for record in records:
            message = by_id[record["messageId"]]
            if message.message_id not in failed_ids:
                self.messages.remove(message)
                report.delivered.append(message.message_id)
            elif message.receive_count >= self.max_receive_count:
                self.messages.remove(message)
                self.dlq.append(message)
                report.redriven_to_dlq.append(message.message_id)
            else:
                report.failed.append(message.message_id)
        return report

    def poll(self, handler: Callable[[dict[str, Any]], dict[str, Any]], max_messages: int = 10) -> DeliveryReport:
        """One ESM poll: receive, invoke ``handler``, honour batchItemFailures."""
        records = self.receive_batch(max_messages)
        if not records:
            return DeliveryReport()
        response = handler({"Records": records})
        failed = {item["itemIdentifier"] for item in response.get("batchItemFailures", [])}
        return self.settle(records, failed)


class InMemoryStore:
    """A dict keyed on ``pk`` with the DynamoDB claim condition."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.conditional_put_calls = 0

    def put_if_claimable(self, item: dict[str, Any], now: int) -> tuple[bool, dict[str, Any] | None]:
        self.conditional_put_calls += 1
        existing = self.items.get(item["pk"])
        claimable = (
            existing is None
            or existing.get("expires_at", 0) < now
            or (existing.get("status") == IN_PROGRESS and existing.get("lock_expires_at", 0) < now)
        )
        if not claimable:
            return False, json.loads(json.dumps(existing))
        self.items[item["pk"]] = dict(item)
        return True, None

    def put(self, item: dict[str, Any]) -> None:
        self.items[item["pk"]] = dict(item)

    def update(self, pk: str, fields: dict[str, Any]) -> None:
        if pk not in self.items:
            raise KeyError(pk)
        self.items[pk].update(fields)

    def delete(self, pk: str) -> None:
        self.items.pop(pk, None)


class InMemoryEventBus:
    """Records published entries; ``fail_next`` makes the next N calls fail."""

    def __init__(self, fail_next: int = 0) -> None:
        self.entries: list[dict[str, Any]] = []
        self.fail_next = fail_next

    def put_events(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.fail_next > 0:
            self.fail_next -= 1
            return [{**entry, "ErrorCode": "InternalFailure", "ErrorMessage": "simulated"} for entry in entries]
        self.entries.extend(entries)
        return []

    def details(self) -> list[dict[str, Any]]:
        """Decoded ``Detail`` payloads of everything published so far."""
        return [json.loads(entry["Detail"]) for entry in self.entries]
