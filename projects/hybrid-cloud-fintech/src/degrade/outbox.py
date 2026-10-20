"""The outbox: where deferred on-prem-dependent work waits for the link.

Two implementations share one shape (``OutboxPort``, informally -- this is
stdlib Python, no typing.Protocol import needed for two concrete classes):

* ``InMemoryOutbox`` -- for tests and for processes that replay within the
  same run.
* ``FileOutbox`` -- a small JSON file on local disk, the reference
  persistence for a single customer-facing instance. It rewrites the whole
  file on every mutation, which is the right trade for a portfolio-scale
  reference (readable, inspectable, no extra dependency) and the wrong one
  past a few thousand pending entries -- see docs/architecture.md for what
  a production version would use instead (SQS, or a local SQLite queue).
"""

from __future__ import annotations

import enum
import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable


class OutboxStatus(str, enum.Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"  # exhausted its retry budget; kept for audit, not retried automatically


@dataclass
class OutboxEntry:
    id: str
    operation: str
    payload: dict[str, Any]
    created_at: float
    status: OutboxStatus = OutboxStatus.PENDING
    attempts: int = 0
    last_error: str | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OutboxEntry":
        d = dict(d)
        d["status"] = OutboxStatus(d["status"])
        return cls(**d)


class InMemoryOutbox:
    """Outbox backed by a plain dict. Not persisted across process restarts."""

    def __init__(self, *, clock: Callable[[], float] = time.time, id_factory: Callable[[], str] | None = None) -> None:
        self._clock = clock
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._entries: dict[str, OutboxEntry] = {}

    def append(self, operation: str, payload: dict[str, Any]) -> OutboxEntry:
        entry = OutboxEntry(
            id=self._id_factory(),
            operation=operation,
            payload=payload,
            created_at=self._clock(),
        )
        self._entries[entry.id] = entry
        return entry

    def get(self, entry_id: str) -> OutboxEntry:
        return self._entries[entry_id]

    def pending(self) -> list[OutboxEntry]:
        return [e for e in self._entries.values() if e.status == OutboxStatus.PENDING]

    def all(self) -> list[OutboxEntry]:
        return list(self._entries.values())

    def mark_done(self, entry_id: str) -> OutboxEntry:
        entry = self._entries[entry_id]
        entry.status = OutboxStatus.DONE
        entry.completed_at = self._clock()
        return entry

    def mark_attempt_failed(self, entry_id: str, error: str, *, max_attempts: int) -> OutboxEntry:
        entry = self._entries[entry_id]
        entry.attempts += 1
        entry.last_error = error
        if entry.attempts >= max_attempts:
            entry.status = OutboxStatus.FAILED
        return entry


class FileOutbox:
    """Outbox persisted as a single JSON file: ``{"entries": {id: entry, ...}}``.

    Every mutation reads the whole file, applies the change, and writes it
    back via a temp-file-plus-rename so a crash mid-write never corrupts the
    file (the rename is atomic on the same filesystem). This is explicitly
    not safe for multiple processes writing the same file concurrently --
    one customer-facing instance owns one outbox file; see
    docs/architecture.md for the fan-in design past a single instance.
    """

    def __init__(self, path: str | Path, *, clock: Callable[[], float] = time.time, id_factory: Callable[[], str] | None = None) -> None:
        self._path = Path(path)
        self._clock = clock
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        if not self._path.exists():
            self._write({})

    def _read(self) -> dict[str, OutboxEntry]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text() or "{}")
        return {k: OutboxEntry.from_dict(v) for k, v in raw.get("entries", {}).items()}

    def _write(self, entries: dict[str, OutboxEntry]) -> None:
        payload = {"entries": {k: v.to_dict() for k, v in entries.items()}}
        fd, tmp_name = tempfile.mkstemp(dir=str(self._path.parent) or ".", prefix=".outbox-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            os.replace(tmp_name, self._path)
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)

    def append(self, operation: str, payload: dict[str, Any]) -> OutboxEntry:
        entries = self._read()
        entry = OutboxEntry(
            id=self._id_factory(),
            operation=operation,
            payload=payload,
            created_at=self._clock(),
        )
        entries[entry.id] = entry
        self._write(entries)
        return entry

    def get(self, entry_id: str) -> OutboxEntry:
        return self._read()[entry_id]

    def pending(self) -> list[OutboxEntry]:
        return [e for e in self._read().values() if e.status == OutboxStatus.PENDING]

    def all(self) -> list[OutboxEntry]:
        return list(self._read().values())

    def mark_done(self, entry_id: str) -> OutboxEntry:
        entries = self._read()
        entry = entries[entry_id]
        entry.status = OutboxStatus.DONE
        entry.completed_at = self._clock()
        self._write(entries)
        return entry

    def mark_attempt_failed(self, entry_id: str, error: str, *, max_attempts: int) -> OutboxEntry:
        entries = self._read()
        entry = entries[entry_id]
        entry.attempts += 1
        entry.last_error = error
        if entry.attempts >= max_attempts:
            entry.status = OutboxStatus.FAILED
        self._write(entries)
        return entry
