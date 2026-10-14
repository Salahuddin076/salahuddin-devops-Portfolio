"""Idempotency guard built on a single conditional write.

The processor calls ``claim`` before doing any work. One conditional
``PutItem`` decides the outcome atomically, so two concurrent deliveries of
the same message cannot both win:

* ``FIRST_SEEN`` - this invocation now holds the key and must do the work,
  then call ``complete`` (or ``release`` if the work failed).
* ``DUPLICATE_IN_PROGRESS`` - another invocation holds an unexpired lock.
  The caller should retry later rather than do the work twice.
* ``DUPLICATE_COMPLETED`` - the work already happened; the stored result is
  returned so the caller can answer exactly as the first time.
* ``PAYLOAD_MISMATCH`` - the key was reused with a different request body.
  That is a client bug, and replaying the old result would hide it.

Records expire through DynamoDB TTL (``expires_at``), which bounds both the
table size and the window in which a retry is recognised.
"""

from __future__ import annotations

import enum
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from adapters import COMPLETED, IN_PROGRESS, StorePort

KEY_PREFIX = "IDEMPOTENCY#"


class Outcome(enum.Enum):
    FIRST_SEEN = "first_seen"
    DUPLICATE_IN_PROGRESS = "duplicate_in_progress"
    DUPLICATE_COMPLETED = "duplicate_completed"
    PAYLOAD_MISMATCH = "payload_mismatch"


@dataclass(frozen=True)
class Claim:
    outcome: Outcome
    stored_result: dict[str, Any] | None = None


def payload_hash(payload: Any) -> str:
    """Stable hash of a JSON-compatible payload (key order does not matter)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IdempotencyGuard:
    def __init__(
        self,
        store: StorePort,
        *,
        ttl_seconds: int = 24 * 3600,
        lock_seconds: int = 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if ttl_seconds <= lock_seconds:
            raise ValueError("ttl_seconds must exceed lock_seconds")
        self._store = store
        self._ttl = ttl_seconds
        self._lock = lock_seconds
        self._clock = clock

    @staticmethod
    def record_key(idempotency_key: str) -> str:
        return KEY_PREFIX + idempotency_key

    def claim(self, idempotency_key: str, request_hash: str) -> Claim:
        now = int(self._clock())
        item = {
            "pk": self.record_key(idempotency_key),
            "status": IN_PROGRESS,
            "request_hash": request_hash,
            "lock_expires_at": now + self._lock,
            "expires_at": now + self._ttl,
        }
        written, existing = self._store.put_if_claimable(item, now)
        if written:
            return Claim(Outcome.FIRST_SEEN)

        existing = existing or {}
        if existing.get("request_hash") != request_hash:
            return Claim(Outcome.PAYLOAD_MISMATCH)
        if existing.get("status") == COMPLETED:
            stored = existing.get("result")
            return Claim(Outcome.DUPLICATE_COMPLETED, json.loads(stored) if stored else None)
        return Claim(Outcome.DUPLICATE_IN_PROGRESS)

    def complete(self, idempotency_key: str, result: dict[str, Any]) -> None:
        """Mark the key done and store the result returned to later duplicates."""
        self._store.update(
            self.record_key(idempotency_key),
            {
                "status": COMPLETED,
                # Stored as a JSON string so no type mapping (floats, Decimal)
                # is needed between Python and DynamoDB.
                "result": json.dumps(result, sort_keys=True),
                "expires_at": int(self._clock()) + self._ttl,
            },
        )

    def release(self, idempotency_key: str) -> None:
        """Drop the lock after a failure so a redelivery can retry at once."""
        self._store.delete(self.record_key(idempotency_key))
