"""Append-only audit log, one JSON object per line.

Every run start, step transition, refusal and run end is written before the
tool moves on, flushed and fsynced, so the log survives a crash of the tool
itself. Lines carry the run id, so a resumed run's lines join its original
ones.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


class AuditLog:
    def __init__(self, path: Optional[Path]) -> None:
        self.path = Path(path) if path else None
        self.records: list[dict[str, Any]] = []

    def write(self, record: dict[str, Any]) -> None:
        self.records.append(record)
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
