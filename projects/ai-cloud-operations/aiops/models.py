"""Core data structures shared across the pipeline.

Everything here is a frozen dataclass so that an ``Anomaly``, ``Correlation``
or ``Proposal`` can be hashed, compared and safely passed between stages
without mutation. ``to_jsonable`` mirrors the convention used elsewhere in
this monorepo (see ``projects/finops-cost-optimization/finops/models.py``).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class LogEvent:
    """One log line, already structured (service, level, message)."""

    timestamp: datetime
    service: str
    level: str  # DEBUG | INFO | WARN | ERROR
    message: str


@dataclass(frozen=True)
class DeployEvent:
    timestamp: datetime
    service: str
    version: str
    actor: str = ""


@dataclass(frozen=True)
class Alert:
    timestamp: datetime
    service: str
    name: str
    severity: str = "warning"  # info | warning | critical


@dataclass(frozen=True)
class Anomaly:
    """A single time bucket whose metric broke the rolling baseline."""

    service: str
    metric: str  # e.g. "error_rate"
    window_start: datetime
    window_end: datetime
    observed_value: float
    baseline_mean: float
    baseline_stddev: float
    z_score: float
    sample_size: int  # events observed in the window


@dataclass(frozen=True)
class Correlation:
    """An anomaly plus any deploys/alerts for the same service nearby in time."""

    anomaly: Anomaly
    deploys: tuple[DeployEvent, ...] = field(default_factory=tuple)
    alerts: tuple[Alert, ...] = field(default_factory=tuple)

    @property
    def has_deploy(self) -> bool:
        return len(self.deploys) > 0

    @property
    def has_alert(self) -> bool:
        return len(self.alerts) > 0


@dataclass(frozen=True)
class Summary:
    text: str
    source: str  # "template" or "llm:<provider-name>"
    redacted_input: bool  # whether redaction ran before this summary was produced


@dataclass(frozen=True)
class Proposal:
    """A candidate remediation action. Never executed by this codebase.

    ``allowed`` is False when the chosen action is not on the remediation
    allow-list; such a proposal can never be approved (see
    ``aiops.audit.AuditLog.approve``), it can only be reported.
    """

    id: str
    service: str
    action: str
    rationale: str
    allowed: bool
    created_at: datetime
    correlation: Correlation


@dataclass(frozen=True)
class AuditEntry:
    """One line of the append-only audit log."""

    timestamp: datetime
    actor: str
    event: str  # "proposed" | "approved" | "rejected"
    proposal_id: str
    service: str
    action: str
    details: dict[str, Any] = field(default_factory=dict)


def to_jsonable(obj: Any) -> Any:
    """Convert dataclasses / datetimes / tuples into JSON-serialisable values."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj
