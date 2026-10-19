"""Allow-listed remediation proposals. Nothing here ever executes anything.

``propose()`` only ever returns a :class:`~aiops.models.Proposal` — a plain
data object describing a *candidate* action, a human-readable rationale,
and whether the action is on the allow-list. The analysis process holds no
credentials to restart a pod, scale a service or trigger a rollback; it
cannot act even if it wanted to. Turning a proposal into a real action is
entirely out of scope for this codebase and would live in a separate
system with its own authentication and its own audit trail.

Allow-list
----------
``ALLOWED_ACTIONS`` is the complete set of action *names* this pipeline
will ever propose. If the selection logic ever produces something outside
that set, the resulting ``Proposal.allowed`` is ``False`` and
``aiops.audit.AuditLog.approve`` refuses to approve it — it can only be
reported, never approved.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import Correlation, Proposal

ALLOWED_ACTIONS: dict[str, str] = {
    "rollback-deploy": "Roll back the affected service to its previous known-good deploy.",
    "restart-pod": "Restart the affected service's pods/containers to clear transient state.",
    "scale-up": "Add capacity to the affected service while the cause is investigated.",
    "escalate": "No automated action applies; page/notify a human with the correlated context.",
}


@dataclass(frozen=True)
class RemediationConfig:
    # Require at least this many correlated alerts before proposing scale-up
    # instead of merely escalating.
    scale_up_alert_threshold: int = 1


def _proposal_id(correlation: Correlation, action: str) -> str:
    """Deterministic id so re-running analysis on the same anomaly is idempotent."""
    a = correlation.anomaly
    key = f"{a.service}|{a.metric}|{a.window_start.isoformat()}|{action}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _choose_action(correlation: Correlation, config: RemediationConfig) -> tuple[str, str]:
    """Pick an action name and rationale. Must only ever return names in ALLOWED_ACTIONS."""
    a = correlation.anomaly
    if correlation.has_deploy:
        versions = ", ".join(d.version for d in correlation.deploys)
        return (
            "rollback-deploy",
            f"Anomaly window for {a.service} overlaps deploy(s) {versions}; "
            "rolling back is the highest-confidence mitigation.",
        )
    if len(correlation.alerts) >= config.scale_up_alert_threshold and correlation.has_alert:
        return (
            "scale-up",
            f"No recent deploy correlated, but {len(correlation.alerts)} alert(s) fired "
            f"alongside the {a.metric} spike; adding capacity is a safe first mitigation.",
        )
    if a.z_score < 5.0:
        return (
            "restart-pod",
            f"Isolated {a.metric} anomaly (z={a.z_score:.2f}) with no correlated deploy or "
            "alert; a restart is proposed to clear possible transient state.",
        )
    return (
        "escalate",
        f"Severe {a.metric} anomaly (z={a.z_score:.2f}) with no correlated deploy or alert; "
        "no automated action is confident enough, escalate to a human.",
    )


def propose(
    correlation: Correlation,
    config: RemediationConfig = RemediationConfig(),
    now: datetime | None = None,
) -> Proposal:
    action, rationale = _choose_action(correlation, config)
    allowed = action in ALLOWED_ACTIONS
    return Proposal(
        id=_proposal_id(correlation, action),
        service=correlation.anomaly.service,
        action=action,
        rationale=rationale,
        allowed=allowed,
        created_at=now or datetime.now(timezone.utc),
        correlation=correlation,
    )
