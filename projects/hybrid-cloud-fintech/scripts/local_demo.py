#!/usr/bin/env python3
"""Demonstrate the graceful-degradation pattern end to end, in-process.

    python3 scripts/local_demo.py

Simulates a payment service posting ledger entries to an on-prem core
banking system over the hybrid link. The link goes down for 3 requests,
comes back, and a replay run drains what was queued while it was down. No
network calls, no AWS, no on-prem system: the "transport" is a small
deterministic fake with a scripted up/down sequence, so the output below is
exactly reproducible.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from degrade import DegradingClient, InMemoryOutbox, OnPremUnavailableError, replay_pending  # noqa: E402


class FlakyLedgerTransport:
    """Fails with OnPremUnavailableError while ``down`` is True."""

    def __init__(self) -> None:
        self.down = False
        self.calls = 0

    def __call__(self, payload: dict) -> dict:
        self.calls += 1
        if self.down:
            raise OnPremUnavailableError("VPN tunnel flapping: no ACK from onprem-dc1-fw within 2000ms")
        return {"ledger_entry_id": f"LE-{self.calls:04d}", "status": "posted"}


class FixedClock:
    def __init__(self, start: float = 1_792_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float = 1.0) -> None:
        self.now += seconds


def main() -> int:
    clock = FixedClock()
    transport = FlakyLedgerTransport()
    counter = {"n": 0}

    def next_id() -> str:
        counter["n"] += 1
        return f"obx-{counter['n']:04d}"

    outbox = InMemoryOutbox(clock=clock, id_factory=next_id)
    degrade_log: list[str] = []
    client = DegradingClient(
        transport,
        outbox,
        clock=clock,
        on_degrade=lambda op, payload, exc: degrade_log.append(
            f"DEGRADED operation={op} account={payload['account']} reason={exc}"
        ),
    )

    payments = [
        {"account": "acct-0001", "amount_cents": 125_00},
        {"account": "acct-0002", "amount_cents": 4_599},
        {"account": "acct-0003", "amount_cents": 99_00},
        {"account": "acct-0004", "amount_cents": 250_00},
        {"account": "acct-0005", "amount_cents": 12_00},
    ]

    print("=== Requests arriving while the on-prem link is healthy, then drops, then recovers ===")
    for i, payment in enumerate(payments):
        if i == 1:
            transport.down = True
            print("--- on-prem link goes down ---")
        if i == 3:
            transport.down = False
            print("--- on-prem link recovers ---")
        clock.tick()
        result = client.call_or_queue("post_ledger_entry", payment)
        if result.queued:
            print(f"account={payment['account']:<10} HTTP 202 Accepted (queued) outbox_id={result.outbox_entry.id}")
        else:
            print(f"account={payment['account']:<10} HTTP 200 OK            ledger_entry_id={result.result['ledger_entry_id']}")

    print()
    print("=== Degrade events emitted to the log/metric hook ===")
    for line in degrade_log:
        print(line)

    print()
    print(f"=== Outbox state before replay: {len(outbox.pending())} pending ===")
    for entry in outbox.pending():
        print(f"{entry.id} operation={entry.operation} account={entry.payload['account']} attempts={entry.attempts}")

    print()
    print("=== Replay run (link is healthy again) ===")
    summary = replay_pending(outbox, transport, max_attempts=5)
    print(json.dumps({
        "attempted": summary.attempted,
        "succeeded": summary.succeeded,
        "still_pending": summary.still_pending,
        "permanently_failed": summary.permanently_failed,
    }, indent=2))

    print()
    print(f"=== Outbox state after replay: {len(outbox.pending())} pending, all_drained={summary.all_drained} ===")
    return 0 if summary.all_drained else 1


if __name__ == "__main__":
    raise SystemExit(main())
