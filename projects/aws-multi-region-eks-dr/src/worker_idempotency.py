"""Duplicate-processing guard for the order worker (logic stub, stdlib only).

Why it exists: around a failover the same job can be delivered twice. The
queue is at-least-once; the promoted region's workers start from whatever
the replicated job table says is pending; an operator may replay a window
of jobs to be safe. Fencing (workers at 0 in the old region) stops two
regions processing at the same time, but it can't stop a replay of a job
that already finished. This check does.

How it works: every job carries an idempotency key. Before doing any work
the worker claims the key in the `processed_jobs` table, which lives in
Aurora and is therefore replicated to the DR region with the data it
protects. The claim is a single statement, so two workers can't both win:

    INSERT INTO processed_jobs (idempotency_key, status, region, epoch, lease_expires_at)
    VALUES (%(key)s, 'in_progress', %(region)s, %(epoch)s, now() + %(lease)s)
    ON CONFLICT (idempotency_key) DO UPDATE
       SET status = 'in_progress', region = EXCLUDED.region, epoch = EXCLUDED.epoch,
           lease_expires_at = EXCLUDED.lease_expires_at
     WHERE processed_jobs.status = 'in_progress'
       AND processed_jobs.lease_expires_at < now()
    RETURNING idempotency_key;

No row returned = someone else holds it (done, or in progress with a live
lease) = skip. Completion only counts if the row still carries our epoch,
so a worker from before the failover that wakes up late can't overwrite
the new region's result:

    UPDATE processed_jobs SET status = 'done', completed_at = now(), result_ref = %(ref)s
     WHERE idempotency_key = %(key)s AND epoch = %(epoch)s AND status = 'in_progress';

What it does not cover: a claim or completion written in the old primary
in the last moments before an unplanned failover, and not yet replicated,
is lost with the rest of the un-replicated writes (RPO). The job then runs
again in DR. Downstream side effects must carry the same idempotency key
(payment provider, email service) so that second run is harmless. The
tests pin this gap down rather than hide it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Protocol

CLAIMED = "claimed"
DUPLICATE = "duplicate"          # already done: skip
IN_PROGRESS = "in_progress"      # someone else holds a live lease: skip for now


class FencedRegion(Exception):
    """This worker's region is not the writer: it must not process jobs."""


class MissingIdempotencyKey(ValueError):
    pass


class IdempotencyStore(Protocol):
    def claim(self, key: str, region: str, epoch: int, now: datetime, lease: timedelta) -> str:
        """CLAIMED, DUPLICATE or IN_PROGRESS (the INSERT ... ON CONFLICT above)."""

    def complete(self, key: str, epoch: int, result_ref: str, now: datetime) -> bool:
        """True if recorded; False if the claim was taken over by a newer epoch."""

    def release(self, key: str, epoch: int) -> None:
        """Give the claim back after a handler failure so a retry can run."""


@dataclass
class _Row:
    status: str
    region: str
    epoch: int
    lease_expires_at: datetime
    result_ref: Optional[str] = None


class InMemoryStore:
    """Mirrors the SQL semantics. In tests one instance stands in for the
    replicated table (both regions see it); `copy()` stands in for a replica
    that missed the last writes."""

    def __init__(self) -> None:
        self.rows: dict[str, _Row] = {}

    def copy(self) -> "InMemoryStore":
        other = InMemoryStore()
        other.rows = {k: _Row(**vars(v)) for k, v in self.rows.items()}
        return other

    def claim(self, key: str, region: str, epoch: int, now: datetime, lease: timedelta) -> str:
        row = self.rows.get(key)
        if row is None or (row.status == "in_progress" and row.lease_expires_at < now):
            self.rows[key] = _Row("in_progress", region, epoch, now + lease)
            return CLAIMED
        return DUPLICATE if row.status == "done" else IN_PROGRESS

    def complete(self, key: str, epoch: int, result_ref: str, now: datetime) -> bool:
        row = self.rows.get(key)
        if row is None or row.epoch != epoch or row.status != "in_progress":
            return False
        row.status = "done"
        row.result_ref = result_ref
        return True

    def release(self, key: str, epoch: int) -> None:
        row = self.rows.get(key)
        if row is not None and row.epoch == epoch and row.status == "in_progress":
            del self.rows[key]


@dataclass(frozen=True)
class Outcome:
    key: str
    action: str  # "processed" | "skipped-duplicate" | "skipped-in-progress" | "discarded-stale"
    detail: str = ""


class Worker:
    """Processes one job at a time, exactly once per idempotency key as far as
    the replicated table knows.

    region / epoch: where this worker runs and the failover epoch it was
    started with (the orchestrator's state epoch, passed in at deploy time).
    is_writer_region: asked before every job; False means the region is
    fenced, and the worker stops instead of processing.
    """

    def __init__(self, store: IdempotencyStore, region: str, epoch: int,
                 is_writer_region: Callable[[], bool],
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 lease: timedelta = timedelta(minutes=5)) -> None:
        self.store = store
        self.region = region
        self.epoch = epoch
        self.is_writer_region = is_writer_region
        self.clock = clock
        self.lease = lease

    def process(self, job: dict[str, Any], handler: Callable[[dict[str, Any]], str]) -> Outcome:
        key = job.get("idempotency_key")
        if not key or not isinstance(key, str):
            raise MissingIdempotencyKey(f"job {job.get('id', '?')} has no idempotency_key; refusing to process")
        if not self.is_writer_region():
            raise FencedRegion(f"{self.region} is fenced; not processing {key}")

        claim = self.store.claim(key, self.region, self.epoch, self.clock(), self.lease)
        if claim == DUPLICATE:
            return Outcome(key, "skipped-duplicate", "already processed (replayed or redelivered job)")
        if claim == IN_PROGRESS:
            return Outcome(key, "skipped-in-progress", "another worker holds a live lease")

        try:
            result_ref = handler(job)
        except Exception:
            self.store.release(key, self.epoch)
            raise
        if not self.store.complete(key, self.epoch, result_ref, self.clock()):
            return Outcome(key, "discarded-stale", "claim was taken over by a newer epoch; result not recorded")
        return Outcome(key, "processed", result_ref)
