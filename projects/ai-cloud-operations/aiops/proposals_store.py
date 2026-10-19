"""A small, mutable JSON registry of *pending* proposals.

This is a convenience cache for the CLI only — it is NOT the audit trail.
``aiops run`` writes the proposals it generated here so a later, separate
``aiops approve``/``aiops reject`` invocation can look one up by id without
re-running analysis. Unlike the audit log, this file is freely rewritten;
the append-only guarantee lives entirely in ``aiops.audit.AuditLog``.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Proposal, to_jsonable


def write(path: Path | str, proposals: list[Proposal]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "id": p.id,
            "service": p.service,
            "action": p.action,
            "rationale": p.rationale,
            "allowed": p.allowed,
            "created_at": to_jsonable(p.created_at),
            "status": "pending",
        }
        for p in proposals
    ]
    path.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load(path: Path | str) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def find(path: Path | str, proposal_id: str) -> dict | None:
    for record in load(path):
        if record["id"] == proposal_id:
            return record
    return None


def set_status(path: Path | str, proposal_id: str, status: str) -> None:
    records = load(path)
    for record in records:
        if record["id"] == proposal_id:
            record["status"] = status
    Path(path).write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
