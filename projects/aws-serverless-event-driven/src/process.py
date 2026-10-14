"""SQS consumer: idempotent order acceptance plus the ``OrderAccepted`` event.

Invoked by a Lambda event source mapping with ``ReportBatchItemFailures``.
Every record is handled in isolation and the handler never raises for a
single bad record: it returns only the failed message IDs, so SQS deletes
the successes and redelivers just the failures (ADR 0002). A record that
keeps failing reaches ``maxReceiveCount`` and the queue's redrive policy
moves it to the dead-letter queue.

Per record:

1. Parse and re-validate the message (the queue is an API boundary too).
2. Claim the idempotency key with one conditional write.
3. First time: record the order, publish ``OrderAccepted``, mark complete.
   Duplicate of finished work: skip and surface the stored result.
   Duplicate still in flight: report a failure so SQS retries later.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from adapters import EventBusPort, StorePort
from events import order_accepted_detail, to_put_events_entry
from idempotency import IdempotencyGuard, Outcome, payload_hash
from logging_utils import CORRELATION_ATTRIBUTE, JsonLogger, iso_timestamp
from validation import order_total_cents, validate_order

ORDER_PREFIX = "ORDER#"
REQUIRED_MESSAGE_FIELDS = ("schemaVersion", "orderId", "idempotencyKey", "payloadHash", "order")


class PoisonMessage(Exception):
    """The message can never succeed as-is; it should end up in the DLQ."""


class RetryableError(Exception):
    """A transient condition; redelivery may succeed."""


@dataclass
class ProcessDeps:
    store: StorePort
    bus: EventBusPort
    guard: IdempotencyGuard
    logger: JsonLogger
    bus_name: str
    clock: Callable[[], float] = time.time


@dataclass
class RecordResult:
    message_id: str
    status: str  # processed | duplicate | failed
    correlation_id: str
    result: dict[str, Any] | None = None
    reason: str | None = None
    retryable: bool | None = None


@dataclass
class BatchResult:
    records: list[RecordResult] = field(default_factory=list)

    @property
    def failed_ids(self) -> list[str]:
        return [record.message_id for record in self.records if record.status == "failed"]

    def lambda_response(self) -> dict[str, Any]:
        """The exact shape the event source mapping reads, nothing more."""
        return {"batchItemFailures": [{"itemIdentifier": message_id} for message_id in self.failed_ids]}


def correlation_id_of(record: dict[str, Any]) -> str:
    attribute = (record.get("messageAttributes") or {}).get(CORRELATION_ATTRIBUTE) or {}
    return attribute.get("stringValue") or f"sqs-{record.get('messageId', 'unknown')}"


def parse_message(body: str) -> dict[str, Any]:
    try:
        message = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PoisonMessage(f"body is not valid JSON ({exc.msg}, char {exc.pos})") from exc
    if not isinstance(message, dict):
        raise PoisonMessage("body is not a JSON object")
    missing = [name for name in REQUIRED_MESSAGE_FIELDS if name not in message]
    if missing:
        raise PoisonMessage(f"missing fields: {', '.join(missing)}")
    if message["schemaVersion"] != 1:
        raise PoisonMessage(f"unsupported schemaVersion {message['schemaVersion']!r}")
    errors = validate_order(message["order"])
    if errors:
        raise PoisonMessage("invalid order: " + "; ".join(f"{e.field} {e.message}" for e in errors))
    if payload_hash(message["order"]) != message["payloadHash"]:
        raise PoisonMessage("payloadHash does not match order")
    return message


def _accept_order(message: dict[str, Any], correlation_id: str, deps: ProcessDeps) -> dict[str, Any]:
    order = message["order"]
    now = deps.clock()
    total = order_total_cents(order)
    item_count = sum(item["quantity"] for item in order["items"])
    deps.store.put(
        {
            "pk": ORDER_PREFIX + message["orderId"],
            "status": "ACCEPTED",
            "customer_id": order["customerId"],
            "currency": order["currency"],
            "total_cents": total,
            "item_count": item_count,
            "correlation_id": correlation_id,
            "accepted_at": iso_timestamp(now),
        }
    )
    detail = order_accepted_detail(
        order_id=message["orderId"],
        customer_id=order["customerId"],
        currency=order["currency"],
        total_cents=total,
        item_count=item_count,
        correlation_id=correlation_id,
        occurred_at=now,
    )
    failed = deps.bus.put_events([to_put_events_entry(detail, bus_name=deps.bus_name)])
    if failed:
        raise RetryableError(f"PutEvents failed: {failed[0].get('ErrorCode')}")
    return {"orderId": message["orderId"], "status": "ACCEPTED", "totalCents": total, "eventId": detail["id"]}


def process_record(record: dict[str, Any], deps: ProcessDeps) -> RecordResult:
    message_id = record["messageId"]
    correlation_id = correlation_id_of(record)
    log = deps.logger.bind(
        correlation_id=correlation_id,
        message_id=message_id,
        receive_count=int((record.get("attributes") or {}).get("ApproximateReceiveCount", "1")),
    )
    try:
        message = parse_message(record.get("body", ""))
        key = message["idempotencyKey"]
        claim = deps.guard.claim(key, message["payloadHash"])

        if claim.outcome is Outcome.DUPLICATE_COMPLETED:
            log.info("duplicate_skipped", order_id=message["orderId"], stored_result=claim.stored_result)
            return RecordResult(message_id, "duplicate", correlation_id, result=claim.stored_result)
        if claim.outcome is Outcome.DUPLICATE_IN_PROGRESS:
            raise RetryableError("another invocation holds the idempotency lock")
        if claim.outcome is Outcome.PAYLOAD_MISMATCH:
            raise PoisonMessage("idempotency key reused with a different payload")

        try:
            result = _accept_order(message, correlation_id, deps)
        except Exception:
            deps.guard.release(key)
            raise
        deps.guard.complete(key, result)
        log.info("order_accepted", order_id=result["orderId"], event_id=result["eventId"], total_cents=result["totalCents"])
        return RecordResult(message_id, "processed", correlation_id, result=result)

    except PoisonMessage as exc:
        log.error("poison_message", reason=str(exc), retryable=False)
        return RecordResult(message_id, "failed", correlation_id, reason=str(exc), retryable=False)
    except Exception as exc:  # transient: throttling, network, held lock
        log.warning("record_failed", reason=str(exc), error=type(exc).__name__, retryable=True)
        return RecordResult(message_id, "failed", correlation_id, reason=str(exc), retryable=True)


def process_batch(event: dict[str, Any], deps: ProcessDeps) -> BatchResult:
    batch = BatchResult()
    for record in event.get("Records", []):
        batch.records.append(process_record(record, deps))
    return batch


def handle(event: dict[str, Any], deps: ProcessDeps) -> dict[str, Any]:
    batch = process_batch(event, deps)
    deps.logger.info(
        "batch_complete",
        records=len(batch.records),
        failed=len(batch.failed_ids),
    )
    return batch.lambda_response()


_DEPS: ProcessDeps | None = None


def _deps_from_environment() -> ProcessDeps:
    from adapters import DynamoDbStore, EventBridgeBus

    store = DynamoDbStore(os.environ["TABLE_NAME"])
    return ProcessDeps(
        store=store,
        bus=EventBridgeBus(),
        guard=IdempotencyGuard(
            store,
            ttl_seconds=int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", "86400")),
            lock_seconds=int(os.environ.get("IDEMPOTENCY_LOCK_SECONDS", "60")),
        ),
        logger=JsonLogger("orders-process", level=os.environ.get("LOG_LEVEL", "INFO")),
        bus_name=os.environ["EVENT_BUS_NAME"],
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point. Clients are built once per execution environment."""
    global _DEPS
    if _DEPS is None:
        _DEPS = _deps_from_environment()
    return handle(event, _DEPS)
