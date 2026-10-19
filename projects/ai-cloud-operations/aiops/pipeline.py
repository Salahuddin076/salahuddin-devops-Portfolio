"""Wires the stages together: Inputs -> Analyze -> Summarize -> Act.

``run()`` is the only place that calls all four stages in order. It never
approves anything itself — it records each proposal to the audit log as
"proposed" and returns them for a human to approve or reject separately
(see ``aiops.audit.AuditLog.approve`` / ``.reject``, and the ``approve`` /
``reject`` CLI subcommands).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .anomaly import AnomalyConfig, detect
from .audit import AuditLog
from .correlation import CorrelationConfig, correlate
from .models import Alert, Correlation, DeployEvent, LogEvent, Proposal, Summary
from .remediation import RemediationConfig, propose
from .summarize import SummaryConfig, summarize


@dataclass(frozen=True)
class PipelineConfig:
    anomaly: AnomalyConfig = field(default_factory=AnomalyConfig)
    correlation: CorrelationConfig = field(default_factory=CorrelationConfig)
    summary: SummaryConfig = field(default_factory=SummaryConfig)
    remediation: RemediationConfig = field(default_factory=RemediationConfig)


@dataclass(frozen=True)
class PipelineItem:
    correlation: Correlation
    summary: Summary
    proposal: Proposal


@dataclass(frozen=True)
class PipelineResult:
    items: tuple[PipelineItem, ...]

    @property
    def proposals(self) -> tuple[Proposal, ...]:
        return tuple(item.proposal for item in self.items)


def run(
    logs: list[LogEvent],
    deploys: list[DeployEvent],
    alerts: list[Alert],
    config: PipelineConfig = PipelineConfig(),
    audit_log: AuditLog | None = None,
    now: datetime | None = None,
) -> PipelineResult:
    anomalies = detect(logs, config.anomaly)
    correlations = correlate(anomalies, deploys, alerts, config.correlation)

    items = []
    for correlation in correlations:
        summary = summarize(correlation, raw_log_excerpt="", config=config.summary)
        proposal = propose(correlation, config.remediation, now=now)
        if audit_log is not None:
            audit_log.record_proposal(proposal, now=now)
        items.append(PipelineItem(correlation=correlation, summary=summary, proposal=proposal))
    return PipelineResult(items=tuple(items))
