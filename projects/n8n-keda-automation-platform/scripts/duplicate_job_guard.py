#!/usr/bin/env python3
"""Idempotency guard for n8n workflow steps with side effects (stdlib only).

Queue mode gives at-least-once execution, not exactly-once. A worker can die
after it sent the e-mail but before the execution was saved as a success, and
the retry (n8n creates a *new* execution with `retryOf` set to the failed one)
runs the same node again with the same input. This module shows the pattern
that keeps that retry from sending twice:

1. Derive the key from what is stable across retries: the workflow, a business
   identifier from the trigger payload (event id, order id) or else the root
   execution id (follow `retryOf`), the node name and the item index. Never the
   current execution id: a retry has a new one.
2. Claim the key with a conditional insert (SQL `INSERT ... ON CONFLICT DO
   NOTHING`, DynamoDB `attribute_not_exists`, Redis `SET NX PX`). Exactly one
   claimer wins; the claim carries a lease.
3. Do the side effect, passing the key downstream as an idempotency key when
   the provider supports one, then mark the key done with the result.
4. A later attempt finds `done` and returns the stored result without sending.
   An attempt that finds an *expired* lease (the claimer crashed) takes it
   over and sends again with the same downstream key, so a provider that
   deduplicates turns "crashed after sending" into one delivery as well.

`python3 scripts/duplicate_job_guard.py demo` runs the crash-and-retry story
with and without the guard.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

ACQUIRED, DONE, BUSY = "acquired", "done", "busy"


def idempotency_key(workflow_id: str, node: str, *, business_key: str | None = None,
                    execution_id: str | None = None, retry_of: str | None = None, item_index: int = 0) -> str:
    """Key for one side effect of one item, stable across n8n retries."""
    anchor = business_key or retry_of or execution_id
    if not anchor:
        raise ValueError("need a business_key or an execution id")
    if not workflow_id or not node:
        raise ValueError("workflow_id and node are required")
    raw = "\x1f".join((workflow_id, anchor, node, str(item_index)))
    return "idem:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


@dataclass
class Claim:
    status: str          # acquired | done | busy
    result: str | None = None
    takeover: bool = False


class Store(Protocol):
    def claim(self, key: str, owner: str, now: float, lease_seconds: float) -> Claim: ...
    def complete(self, key: str, owner: str, result: str) -> bool: ...
    def release(self, key: str, owner: str) -> None: ...


class MemoryStore:
    """Dict + lock: the semantics of a conditional insert, for tests and the demo."""

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}
        self._lock = threading.Lock()

    def claim(self, key, owner, now, lease_seconds):
        with self._lock:
            row = self._rows.get(key)
            if row is None:
                self._rows[key] = {"state": "in_progress", "owner": owner, "lease_until": now + lease_seconds}
                return Claim(ACQUIRED)
            if row["state"] == "done":
                return Claim(DONE, row["result"])
            if row["lease_until"] <= now:
                row.update(owner=owner, lease_until=now + lease_seconds)
                return Claim(ACQUIRED, takeover=True)
            return Claim(BUSY)

    def complete(self, key, owner, result):
        with self._lock:
            row = self._rows.get(key)
            if not row or row["owner"] != owner or row["state"] != "in_progress":
                return False
            row.update(state="done", result=result)
            return True

    def release(self, key, owner):
        with self._lock:
            row = self._rows.get(key)
            if row and row["owner"] == owner and row["state"] == "in_progress":
                del self._rows[key]


class SqliteStore:
    """The same protocol on SQL: one conditional INSERT, one guarded UPDATE.

    The statements port as-is to Postgres (n8n's own database is a natural
    home for this table).
    """

    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS idempotency (
            key TEXT PRIMARY KEY, state TEXT NOT NULL, owner TEXT NOT NULL,
            lease_until REAL NOT NULL, result TEXT)""")
        self._lock = threading.Lock()

    def claim(self, key, owner, now, lease_seconds):
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO idempotency (key, state, owner, lease_until) VALUES (?, 'in_progress', ?, ?) "
                "ON CONFLICT(key) DO NOTHING", (key, owner, now + lease_seconds))
            if cur.rowcount == 1:
                return Claim(ACQUIRED)
            cur = self.db.execute(
                "UPDATE idempotency SET owner = ?, lease_until = ? "
                "WHERE key = ? AND state = 'in_progress' AND lease_until <= ?",
                (owner, now + lease_seconds, key, now))
            if cur.rowcount == 1:
                return Claim(ACQUIRED, takeover=True)
            state, result = self.db.execute("SELECT state, result FROM idempotency WHERE key = ?", (key,)).fetchone()
            return Claim(DONE, result) if state == "done" else Claim(BUSY)

    def complete(self, key, owner, result):
        with self._lock:
            cur = self.db.execute(
                "UPDATE idempotency SET state = 'done', result = ? WHERE key = ? AND owner = ? AND state = 'in_progress'",
                (result, key, owner))
            return cur.rowcount == 1

    def release(self, key, owner):
        with self._lock:
            self.db.execute("DELETE FROM idempotency WHERE key = ? AND owner = ? AND state = 'in_progress'", (key, owner))


class AlreadyInProgress(RuntimeError):
    """Another worker holds a live lease: back off and let Bull retry later."""


def guarded(store: Store, key: str, owner: str, side_effect: Callable[[str], str], *,
            lease_seconds: float = 300.0, clock: Callable[[], float] = time.time) -> tuple[str, bool]:
    """Run side_effect(key) at most once per key. Returns (result, executed_now)."""
    claim = store.claim(key, owner, clock(), lease_seconds)
    if claim.status == DONE:
        return claim.result or "", False
    if claim.status == BUSY:
        raise AlreadyInProgress(key)
    try:
        result = side_effect(key)
    except Exception:
        # The effect failed before completing: free the key so a retry can try again.
        store.release(key, owner)
        raise
    if not store.complete(key, owner, result):
        raise RuntimeError(f"lost the lease on {key} before completing; lease_seconds is too short")
    return result, True


# --- demo ------------------------------------------------------------------

class WorkerCrash(BaseException):
    """Simulated SIGKILL: the process is gone and nothing after this line runs.

    A BaseException, so guarded()'s `except Exception` cleanup does not run,
    exactly as no cleanup runs in a killed process: the claim stays
    in_progress until its lease expires.
    """


class FakeMailProvider:
    """A downstream API. With dedupe=True it honours an Idempotency-Key header."""

    def __init__(self, dedupe: bool) -> None:
        self.dedupe = dedupe
        self.delivered: list[str] = []
        self._seen: dict[str, str] = {}

    def send(self, to: str, idem_key: str | None = None) -> str:
        if self.dedupe and idem_key and idem_key in self._seen:
            return self._seen[idem_key]
        msg_id = f"msg-{len(self.delivered) + 1}"
        self.delivered.append(to)
        if idem_key:
            self._seen[idem_key] = msg_id
        return msg_id


def run_scenario(*, guard: bool, crash: str, provider_dedupe: bool = True) -> dict:
    """Execution 101 crashes (`before` or `after` the send); retry 102 has retryOf=101.

    crash: "before" the provider call, "after" it (sent, not recorded), or "none".
    """
    store, provider = MemoryStore(), FakeMailProvider(dedupe=provider_dedupe)
    t = [1000.0]
    clock = lambda: t[0]  # noqa: E731
    lease = 300.0

    def node(execution_id: str, retry_of: str | None, owner: str, crash_here: str) -> str:
        key = idempotency_key("wf-welcome", "Send welcome e-mail", business_key=None,
                              execution_id=execution_id, retry_of=retry_of)

        def effect(k: str | None) -> str:
            if crash_here == "before":
                raise WorkerCrash
            msg = provider.send("user@example.com", idem_key=k)
            if crash_here == "after":
                raise WorkerCrash
            return msg

        if not guard:
            # The naive node: no claim, and no idempotency key for the provider.
            return effect(None)
        try:
            result, _ = guarded(store, key, owner, effect, lease_seconds=lease, clock=clock)
        except AlreadyInProgress:
            return "skipped: another worker holds the lease"
        return result

    log = []
    try:
        log.append(("execution 101 (worker-a)", node("101", None, "worker-a", crash)))
    except WorkerCrash:
        log.append(("execution 101 (worker-a)", f"worker crashed {crash} the send"))
    t[0] += lease + 1  # n8n marks 101 crashed; someone retries it after the lease ran out
    log.append(("execution 102 retryOf=101 (worker-b)", node("102", "101", "worker-b", "none")))
    return {"delivered": len(provider.delivered), "log": log}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Idempotency guard demo for n8n side effects.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    demo = sub.add_parser("demo", help="crash-and-retry scenarios")
    demo.add_argument("--crash", choices=("before", "after", "none"), default="after")
    demo.add_argument("--no-guard", action="store_true", help="run without the guard")
    demo.add_argument("--provider-no-dedupe", action="store_true",
                      help="downstream ignores the idempotency key")
    key = sub.add_parser("key", help="print the key for one side effect")
    key.add_argument("workflow_id")
    key.add_argument("node")
    key.add_argument("--business-key")
    key.add_argument("--execution-id")
    key.add_argument("--retry-of")
    key.add_argument("--item-index", type=int, default=0)
    args = ap.parse_args(argv)

    if args.cmd == "key":
        try:
            print(idempotency_key(args.workflow_id, args.node, business_key=args.business_key,
                                  execution_id=args.execution_id, retry_of=args.retry_of,
                                  item_index=args.item_index))
        except ValueError as exc:
            print(f"duplicate_job_guard: error: {exc}", file=sys.stderr)
            return 2
        return 0

    out = run_scenario(guard=not args.no_guard, crash=args.crash, provider_dedupe=not args.provider_no_dedupe)
    mode = "without guard" if args.no_guard else "with guard"
    crash = "no crash" if args.crash == "none" else f"crash {args.crash} send"
    print(f"duplicate_job_guard demo ({mode}, {crash}, "
          f"provider dedupe {'off' if args.provider_no_dedupe else 'on'})")
    for who, what in out["log"]:
        print(f"  {who}: {what}")
    print(f"messages delivered: {out['delivered']}")
    return 0 if out["delivered"] <= 1 else 1


if __name__ == "__main__":
    sys.exit(main())
