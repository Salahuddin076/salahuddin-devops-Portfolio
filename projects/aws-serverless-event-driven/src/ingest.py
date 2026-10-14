"""``POST /orders``: validate, then hand off to SQS and answer 202.

The API does no business processing. It checks the contract (body shape and
a mandatory ``Idempotency-Key`` header), derives a deterministic order ID
from the key, and enqueues. That keeps the synchronous path short and
lets the queue absorb bursts and downstream outages.

Deduplication happens in the processor, not here: SQS standard queues
deliver at least once anyway, so the consumer has to be idempotent
regardless, and one mechanism is easier to reason about than two. A client
that retries with the same key gets the same ``orderId`` back, and the
processor turns the duplicate message into a no-op (see ADR 0001).

Event shape: API Gateway HTTP API, payload format 2.0.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from adapters import QueuePort
from idempotency import payload_hash
from logging_utils import CORRELATION_ATTRIBUTE, CORRELATION_HEADER, JsonLogger, iso_timestamp
from validation import (
    MAX_BODY_BYTES,
    FieldError,
    is_valid_correlation_id,
    validate_idempotency_key,
    validate_order,
)

MESSAGE_SCHEMA_VERSION = 1


@dataclass
class IngestDeps:
    queue: QueuePort
    logger: JsonLogger
    clock: Callable[[], float] = time.time
    new_correlation_id: Callable[[], str] = field(default=lambda: str(uuid.uuid4()))


def order_id_for(idempotency_key: str) -> str:
    """Same key, same order ID: a retried request is recognisably the same order."""
    return "ord_" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]


def _response(status: int, body: dict[str, Any], correlation_id: str, extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
    headers = {
        "content-type": "application/json",
        "x-correlation-id": correlation_id,
        **(extra_headers or {}),
    }
    return {"statusCode": status, "headers": headers, "body": json.dumps(body, sort_keys=True)}


def _bad_request(errors: list[FieldError], correlation_id: str) -> dict[str, Any]:
    return _response(
        400,
        {"error": "validation_failed", "details": [error.as_dict() for error in errors]},
        correlation_id,
    )


def _read_body(event: dict[str, Any]) -> str:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw, validate=True).decode("utf-8")
    return raw


def handle(event: dict[str, Any], deps: IngestDeps) -> dict[str, Any]:
    # HTTP API lower-cases header names in payload format 2.0.
    headers = {name.lower(): value for name, value in (event.get("headers") or {}).items()}
    supplied = headers.get(CORRELATION_HEADER)
    correlation_id = supplied if is_valid_correlation_id(supplied) else deps.new_correlation_id()
    log = deps.logger.bind(correlation_id=correlation_id)

    try:
        raw_body = _read_body(event)
    except (binascii.Error, UnicodeDecodeError):
        log.warning("request_rejected", reason="undecodable_body")
        return _bad_request([FieldError("$", "body is not valid base64 UTF-8")], correlation_id)

    if len(raw_body.encode("utf-8")) > MAX_BODY_BYTES:
        log.warning("request_rejected", reason="body_too_large")
        return _response(413, {"error": "payload_too_large", "limitBytes": MAX_BODY_BYTES}, correlation_id)

    errors = validate_idempotency_key(headers.get("idempotency-key"))
    try:
        order = json.loads(raw_body) if raw_body else None
    except json.JSONDecodeError:
        order = None
        errors.append(FieldError("$", "body is not valid JSON"))
    else:
        errors.extend(validate_order(order))

    if errors:
        log.warning("request_rejected", reason="validation_failed", error_count=len(errors))
        return _bad_request(errors, correlation_id)

    idempotency_key = headers["idempotency-key"]
    order_id = order_id_for(idempotency_key)
    message = {
        "schemaVersion": MESSAGE_SCHEMA_VERSION,
        "orderId": order_id,
        "idempotencyKey": idempotency_key,
        "payloadHash": payload_hash(order),
        "receivedAt": iso_timestamp(deps.clock()),
        "order": order,
    }
    try:
        message_id = deps.queue.send(
            json.dumps(message, sort_keys=True),
            {CORRELATION_ATTRIBUTE: correlation_id},
        )
    except Exception as exc:  # any SQS failure means "not accepted"
        log.error("enqueue_failed", order_id=order_id, error=type(exc).__name__)
        return _response(
            503,
            {"error": "temporarily_unavailable"},
            correlation_id,
            {"retry-after": "1"},
        )

    log.info("order_enqueued", order_id=order_id, message_id=message_id)
    return _response(
        202,
        {"orderId": order_id, "status": "ACCEPTED", "correlationId": correlation_id},
        correlation_id,
    )


_DEPS: IngestDeps | None = None


def _deps_from_environment() -> IngestDeps:
    from adapters import SqsQueue

    return IngestDeps(
        queue=SqsQueue(os.environ["QUEUE_URL"]),
        logger=JsonLogger("orders-ingest", level=os.environ.get("LOG_LEVEL", "INFO")),
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point. Clients are built once per execution environment."""
    global _DEPS
    if _DEPS is None:
        _DEPS = _deps_from_environment()
    return handle(event, _DEPS)
