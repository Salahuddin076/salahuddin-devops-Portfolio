"""Append-only audit log for proposals and human decisions.

Every proposal the pipeline produces, and every approve/reject decision a
human makes, is written here as one JSON line with a timestamp and an
actor. The log is opened in append ("a") mode only — this module never
seeks, truncates or rewrites it. Replaying it end-to-end is the record of
what was proposed and who approved or rejected it; nothing is ever deleted
from it by this codebase.

``approve()`` refuses to approve a proposal whose action is not on the
remediation allow-list (``Proposal.allowed is False``): such a proposal can
only be rejected or left pending, matching the "anything else is reported,
not proposed" rule.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import AuditEntry, Proposal, to_jsonable


class RemediationNotAllowed(ValueError):
    """Raised by approve() when the proposal's action is not on the allow-list."""


class AuditLog:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def _append(self, entry: AuditEntry) -> AuditEntry:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(to_jsonable(entry), sort_keys=True))
            fh.write("\n")
        return entry

    def record_proposal(self, proposal: Proposal, actor: str = "aiops-pipeline",
                         now: datetime | None = None) -> AuditEntry:
        entry = AuditEntry(
            timestamp=now or datetime.now(timezone.utc),
            actor=actor,
            event="proposed",
            proposal_id=proposal.id,
            service=proposal.service,
            action=proposal.action,
            details={"allowed": proposal.allowed, "rationale": proposal.rationale},
        )
        return self._append(entry)

    def approve(self, proposal: Proposal, actor: str, now: datetime | None = None) -> AuditEntry:
        return self.approve_fields(
            proposal_id=proposal.id, service=proposal.service, action=proposal.action,
            allowed=proposal.allowed, actor=actor, now=now,
        )

    def reject(self, proposal: Proposal, actor: str, reason: str = "",
               now: datetime | None = None) -> AuditEntry:
        return self.reject_fields(
            proposal_id=proposal.id, service=proposal.service, action=proposal.action,
            actor=actor, reason=reason, now=now,
        )

    def approve_fields(self, proposal_id: str, service: str, action: str, allowed: bool,
                        actor: str, now: datetime | None = None) -> AuditEntry:
        """Core of ``approve()``, usable without a full ``Proposal`` object

        (e.g. the CLI's ``approve`` subcommand, which only has the pending
        proposal's serialised fields, not an in-memory ``Correlation``).
        """
        if not allowed:
            raise RemediationNotAllowed(
                f"action {action!r} is not on the remediation allow-list; "
                "it can be reported but never approved"
            )
        entry = AuditEntry(
            timestamp=now or datetime.now(timezone.utc),
            actor=actor,
            event="approved",
            proposal_id=proposal_id,
            service=service,
            action=action,
            details={},
        )
        return self._append(entry)

    def reject_fields(self, proposal_id: str, service: str, action: str, actor: str,
                       reason: str = "", now: datetime | None = None) -> AuditEntry:
        entry = AuditEntry(
            timestamp=now or datetime.now(timezone.utc),
            actor=actor,
            event="rejected",
            proposal_id=proposal_id,
            service=service,
            action=action,
            details={"reason": reason} if reason else {},
        )
        return self._append(entry)

    def read_all(self) -> list[dict]:
        if not self.path.is_file():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def iter_entries(self) -> Iterator[dict]:
        yield from self.read_all()
