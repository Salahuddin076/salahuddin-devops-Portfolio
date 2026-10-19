"""Correlate anomalies with deploy events and alerts.

Matching rule: same ``service`` AND the deploy/alert timestamp falls
within ``window_minutes`` of the anomaly's window (before *or* after —
a deploy just before the anomaly window is the common "bad rollout"
case, but alerts can also fire a little after the anomaly window starts
once a downstream monitor trips).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .models import Alert, Anomaly, Correlation, DeployEvent


@dataclass(frozen=True)
class CorrelationConfig:
    window_minutes: int = 15


def correlate(
    anomalies: list[Anomaly],
    deploys: list[DeployEvent],
    alerts: list[Alert],
    config: CorrelationConfig = CorrelationConfig(),
) -> list[Correlation]:
    pad = timedelta(minutes=config.window_minutes)
    results: list[Correlation] = []
    for anomaly in anomalies:
        lo = anomaly.window_start - pad
        hi = anomaly.window_end + pad
        matched_deploys = tuple(
            sorted(
                (d for d in deploys if d.service == anomaly.service and lo <= d.timestamp <= hi),
                key=lambda d: d.timestamp,
            )
        )
        matched_alerts = tuple(
            sorted(
                (a for a in alerts if a.service == anomaly.service and lo <= a.timestamp <= hi),
                key=lambda a: a.timestamp,
            )
        )
        results.append(Correlation(anomaly=anomaly, deploys=matched_deploys, alerts=matched_alerts))
    return results
