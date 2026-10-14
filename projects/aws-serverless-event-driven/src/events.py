"""Domain events published to the custom EventBridge bus.

The envelope is versioned and self-describing so consumers can evolve
independently: ``version`` changes only on a breaking change, ``id`` is
deterministic per order (consumers dedupe on it, because the processor
publishes at least once), and ``metadata.correlationId`` carries the ID
that started at the API so one query can follow a request end to end.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from logging_utils import iso_timestamp

EVENT_SOURCE = "com.example.orders"
ORDER_ACCEPTED = "OrderAccepted"
SCHEMA_VERSION = "1"

# Fixed namespace so the same order always yields the same event id.
_EVENT_NAMESPACE = uuid.UUID("5b0c1f9e-8d4a-4c3e-9f57-2d6a1e0b7c11")


def event_id_for(order_id: str, detail_type: str = ORDER_ACCEPTED) -> str:
    return str(uuid.uuid5(_EVENT_NAMESPACE, f"{detail_type}:{order_id}"))


def order_accepted_detail(
    *,
    order_id: str,
    customer_id: str,
    currency: str,
    total_cents: int,
    item_count: int,
    correlation_id: str,
    occurred_at: float,
) -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "id": event_id_for(order_id),
        "occurredAt": iso_timestamp(occurred_at),
        "data": {
            "orderId": order_id,
            "customerId": customer_id,
            "currency": currency,
            "totalCents": total_cents,
            "itemCount": item_count,
        },
        "metadata": {"correlationId": correlation_id},
    }


def to_put_events_entry(detail: dict[str, Any], *, bus_name: str, source: str = EVENT_SOURCE) -> dict[str, Any]:
    """Wrap a detail payload in the shape ``events:PutEvents`` expects."""
    return {
        "Source": source,
        "DetailType": ORDER_ACCEPTED,
        "Detail": json.dumps(detail, sort_keys=True),
        "EventBusName": bus_name,
    }
