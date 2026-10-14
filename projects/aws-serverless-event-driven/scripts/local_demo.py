#!/usr/bin/env python3
"""Run the order pipeline in-process against the in-memory fakes.

    python3 scripts/local_demo.py              # readable trace
    python3 scripts/local_demo.py --show-logs  # plus the structured JSON logs

Same handler code as the Lambdas; only the adapters differ. The clock and ID
factories are fixed, so the output is identical on every run.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import ingest  # noqa: E402
import process  # noqa: E402
from adapters import InMemoryEventBus, InMemoryQueue, InMemoryStore  # noqa: E402
from events import EVENT_SOURCE, ORDER_ACCEPTED  # noqa: E402
from idempotency import IdempotencyGuard  # noqa: E402
from logging_utils import JsonLogger  # noqa: E402

BUS_NAME = "orders-demo-bus"
MAX_RECEIVE_COUNT = 3
# EventBridge rule pattern deployed by terraform/modules/order-pipeline.
RULE_PATTERN = {"source": [EVENT_SOURCE], "detail-type": [ORDER_ACCEPTED]}


class StepClock:
    """Fixed start, advanced explicitly, so the trace is reproducible."""

    def __init__(self, start: float = 1_790_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float = 1.0) -> None:
        self.now += seconds


def rule_matches(entry: dict) -> bool:
    return entry["Source"] in RULE_PATTERN["source"] and entry["DetailType"] in RULE_PATTERN["detail-type"]


def api_request(order: object, *, key: str | None, correlation_id: str | None = None) -> dict:
    headers = {"content-type": "application/json"}
    if key:
        headers["idempotency-key"] = key
    if correlation_id:
        headers["x-correlation-id"] = correlation_id
    return {"version": "2.0", "routeKey": "POST /orders", "headers": headers, "body": json.dumps(order), "isBase64Encoded": False}


ORDER = {
    "customerId": "cus_demo0001",
    "currency": "USD",
    "items": [
        {"sku": "TSHIRT-M", "quantity": 2, "unitPriceCents": 1500},
        {"sku": "MUG-01", "quantity": 1, "unitPriceCents": 900},
    ],
}
SECOND_ORDER = {"customerId": "cus_demo0002", "currency": "EUR", "items": [{"sku": "BOOK-42", "quantity": 1, "unitPriceCents": 2450}]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show-logs", action="store_true", help="print the structured JSON log lines at the end")
    args = parser.parse_args(argv)

    clock = StepClock()
    logs = io.StringIO()
    correlation_ids = iter(f"gen-{n:04d}" for n in range(1, 1000))
    queue = InMemoryQueue(max_receive_count=MAX_RECEIVE_COUNT)
    store = InMemoryStore()
    bus = InMemoryEventBus()
    ingest_deps = ingest.IngestDeps(
        queue=queue,
        logger=JsonLogger("orders-ingest", stream=logs, clock=clock),
        clock=clock,
        new_correlation_id=lambda: next(correlation_ids),
    )
    process_deps = process.ProcessDeps(
        store=store,
        bus=bus,
        guard=IdempotencyGuard(store, ttl_seconds=86_400, lock_seconds=60, clock=clock),
        logger=JsonLogger("orders-process", stream=logs, clock=clock),
        bus_name=BUS_NAME,
        clock=clock,
    )

    print("== 1. API Gateway -> ingest Lambda ==")
    requests = [
        ("new order", api_request(ORDER, key="demo-key-0001", correlation_id="req-demo-001")),
        ("client retry, same key", api_request(ORDER, key="demo-key-0001", correlation_id="req-demo-001")),
        ("second order, no correlation id", api_request(SECOND_ORDER, key="demo-key-0002")),
        ("missing Idempotency-Key", api_request(ORDER, key=None)),
        ("invalid body", api_request({"customerId": "bob", "currency": "JPY", "items": []}, key="demo-key-0003")),
    ]
    status_counts: dict[int, int] = {}
    for label, request in requests:
        response = ingest.handle(request, ingest_deps)
        status_counts[response["statusCode"]] = status_counts.get(response["statusCode"], 0) + 1
        body = json.loads(response["body"])
        if response["statusCode"] == 202:
            detail = f"orderId={body['orderId']} correlationId={body['correlationId']}"
        else:
            detail = "; ".join(f"{d['field']}: {d['message']}" for d in body.get("details", []))
        print(f"POST /orders  {label:<32} -> {response['statusCode']}  {detail}")
        clock.tick()

    poison_id = queue.inject_raw('{"schemaVersion": 1, "orderId": "ord_trunc', {"correlationId": "req-poison-1"})
    print(f"(a buggy producer writes a truncated message straight to the queue: {poison_id})")
    print(f"queue depth: {len(queue.messages)} messages")

    print()
    print(f"== 2. SQS -> process Lambda (ReportBatchItemFailures, maxReceiveCount={MAX_RECEIVE_COUNT}) ==")
    poll = 0
    duplicates = 0
    while queue.messages:
        poll += 1
        records = queue.receive_batch(10)
        batch = process.process_batch({"Records": records}, process_deps)
        response = batch.lambda_response()
        print(f"poll {poll}: {len(records)} record(s)")
        for result in batch.records:
            if result.status == "processed":
                outcome = f"processed  orderId={result.result['orderId']} totalCents={result.result['totalCents']}"
            elif result.status == "duplicate":
                duplicates += 1
                outcome = f"duplicate  skipped, stored result orderId={result.result['orderId']}"
            else:
                kind = "poison" if result.retryable is False else "retryable"
                outcome = f"failed     ({kind}) {result.reason}"
            print(f"  {result.message_id} [{result.correlation_id}] {outcome}")
        failed = {item["itemIdentifier"] for item in response["batchItemFailures"]}
        print(f"  batchItemFailures: {sorted(failed)}")
        report = queue.settle(records, failed)
        if report.redriven_to_dlq:
            print(f"  redrive policy: {report.redriven_to_dlq} moved to DLQ after {MAX_RECEIVE_COUNT} receives")
        clock.tick(30)

    print()
    print("== 3. EventBridge bus -> rule -> SNS ==")
    for entry in bus.entries:
        detail = json.loads(entry["Detail"])
        target = "SNS orders-notifications" if rule_matches(entry) else "no target"
        print(f"{entry['DetailType']} on {entry['EventBusName']} -> {target}")
        print("  detail: " + json.dumps(detail, sort_keys=True))

    print()
    print("== 4. Summary ==")
    orders = sorted(pk for pk in store.items if pk.startswith(process.ORDER_PREFIX))
    by_status = ", ".join(f"{code}: {count}" for code, count in sorted(status_counts.items()))
    print(f"API requests: {len(requests)} ({by_status})   messages enqueued: {queue.sent_count} (incl. 1 injected)")
    print(f"orders recorded: {len(orders)}   events published: {len(bus.entries)}   duplicates skipped: {duplicates}")
    print(f"DLQ depth: {len(queue.dlq)} -> CloudWatch alarm '<prefix>-dlq-not-empty' would fire")

    log_lines = logs.getvalue().splitlines()
    traced = [json.loads(line) for line in log_lines if json.loads(line).get("correlation_id") == "req-demo-001"]
    print(f"log records for correlation_id=req-demo-001: {', '.join(r['message'] for r in traced)}")

    if args.show_logs:
        print()
        print("== Structured logs ==")
        for line in log_lines:
            print(line)

    # Self-check, so CI fails if the demo stops demonstrating what it claims.
    assert len(bus.entries) == 2, "expected exactly two OrderAccepted events"
    assert duplicates == 1, "the retried request should be skipped as a duplicate"
    assert [m.message_id for m in queue.dlq] == [poison_id], "poison message should be in the DLQ"
    return 0


if __name__ == "__main__":
    sys.exit(main())
