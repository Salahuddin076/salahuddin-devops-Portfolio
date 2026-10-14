"""Shared builders for the test suite. Puts ``src/`` on the import path the
same way the Lambda runtime does (handler modules at the zip root)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from adapters import InMemoryEventBus, InMemoryQueue, InMemoryStore  # noqa: E402
from idempotency import IdempotencyGuard  # noqa: E402
from ingest import IngestDeps  # noqa: E402
from logging_utils import JsonLogger  # noqa: E402
from process import ProcessDeps  # noqa: E402

BUS_NAME = "orders-test-bus"
START = 1_790_000_000.0  # a fixed instant, 2026-09-21


class FakeClock:
    def __init__(self, start: float = START) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def valid_order(**overrides: Any) -> dict[str, Any]:
    order = {
        "customerId": "cus_demo0001",
        "currency": "USD",
        "items": [
            {"sku": "TSHIRT-M", "quantity": 2, "unitPriceCents": 1500},
            {"sku": "MUG-01", "quantity": 1, "unitPriceCents": 900},
        ],
    }
    order.update(overrides)
    return order


def api_event(body: Any = None, *, key: str | None = "key-00000001", correlation_id: str | None = None, raw: str | None = None) -> dict[str, Any]:
    headers = {"content-type": "application/json"}
    if key is not None:
        headers["idempotency-key"] = key
    if correlation_id is not None:
        headers["x-correlation-id"] = correlation_id
    if raw is None:
        raw = json.dumps(valid_order() if body is None else body)
    return {
        "version": "2.0",
        "routeKey": "POST /orders",
        "rawPath": "/orders",
        "headers": headers,
        "body": raw,
        "isBase64Encoded": False,
    }


def log_records(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


class Harness:
    """Wires ingest and process against shared in-memory fakes."""

    def __init__(self, *, max_receive_count: int = 3, bus_failures: int = 0, queue_send_failures: int = 0) -> None:
        self.clock = FakeClock()
        self.log_stream = io.StringIO()
        self.queue = InMemoryQueue(max_receive_count=max_receive_count, fail_sends=queue_send_failures)
        self.store = InMemoryStore()
        self.bus = InMemoryEventBus(fail_next=bus_failures)
        ids = iter(f"corr-{n:04d}" for n in range(1, 10_000))
        self.ingest_deps = IngestDeps(
            queue=self.queue,
            logger=JsonLogger("orders-ingest", stream=self.log_stream, clock=self.clock),
            clock=self.clock,
            new_correlation_id=lambda: next(ids),
        )
        self.guard = IdempotencyGuard(self.store, ttl_seconds=3600, lock_seconds=60, clock=self.clock)
        self.process_deps = ProcessDeps(
            store=self.store,
            bus=self.bus,
            guard=self.guard,
            logger=JsonLogger("orders-process", stream=self.log_stream, clock=self.clock),
            bus_name=BUS_NAME,
            clock=self.clock,
        )

    def logs(self) -> list[dict[str, Any]]:
        return log_records(self.log_stream)
