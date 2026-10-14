"""The state file: what this tool has done, so a re-run resumes instead of repeating.

One JSON document, written atomically (temp file + rename) after every step.
Keep it somewhere both operators can reach during an outage of either
region (in real use: an S3 bucket in a third region or the DR region, with
object lock on the audit log). This implementation writes a local path.

Shape:
  writer_region  region this tool last promoted (initially the primary)
  epoch          incremented on every promotion; a fencing token for workers
  fenced         {region: {...}} regions that must not run workers or take writes
  run            the current (unfinished) run, or null
  history        finished runs, newest last
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

STATE_VERSION = 1


def initial_state(global_cluster_id: str, primary_region: str) -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "global_cluster_id": global_cluster_id,
        "writer_region": primary_region,
        "epoch": 0,
        "fenced": {},
        "run": None,
        "history": [],
    }


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self, global_cluster_id: str, primary_region: str) -> dict[str, Any]:
        if not self.path.exists():
            return initial_state(global_cluster_id, primary_region)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != STATE_VERSION:
            raise ValueError(f"{self.path}: unsupported state version {data.get('version')!r}")
        if data.get("global_cluster_id") != global_cluster_id:
            raise ValueError(
                f"{self.path} belongs to global cluster {data.get('global_cluster_id')!r}, "
                f"not {global_cluster_id!r}"
            )
        return data

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".state-", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2, sort_keys=True)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


class MemoryStateStore:
    """For tests: same interface, keeps a deep copy so mutation bugs show up."""

    def __init__(self, state: Optional[dict[str, Any]] = None) -> None:
        self._raw = json.dumps(state) if state is not None else None

    def load(self, global_cluster_id: str, primary_region: str) -> dict[str, Any]:
        if self._raw is None:
            return initial_state(global_cluster_id, primary_region)
        return json.loads(self._raw)

    def save(self, state: dict[str, Any]) -> None:
        self._raw = json.dumps(state)

    @property
    def data(self) -> Optional[dict[str, Any]]:
        return json.loads(self._raw) if self._raw is not None else None
