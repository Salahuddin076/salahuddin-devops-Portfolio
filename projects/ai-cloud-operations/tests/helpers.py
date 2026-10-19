from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from aiops.models import Alert, DeployEvent, LogEvent  # noqa: E402

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_logs(service: str, start: datetime, bucket_minutes: int, rates: list[float],
              events_per_bucket: int = 20) -> list[LogEvent]:
    """Build events for ``len(rates)`` consecutive buckets with the given error rates."""
    events: list[LogEvent] = []
    window = timedelta(minutes=bucket_minutes)
    for i, rate in enumerate(rates):
        bucket_start = start + i * window
        n_errors = round(events_per_bucket * rate)
        for j in range(events_per_bucket):
            level = "ERROR" if j < n_errors else "INFO"
            offset = window * j / events_per_bucket
            events.append(LogEvent(timestamp=bucket_start + offset, service=service, level=level,
                                    message="error happened" if level == "ERROR" else "ok"))
    return events


def deploy(service: str, ts: datetime, version: str = "v1.0.0", actor: str = "ci") -> DeployEvent:
    return DeployEvent(timestamp=ts, service=service, version=version, actor=actor)


def alert(service: str, ts: datetime, name: str = "HighErrorRate", severity: str = "critical") -> Alert:
    return Alert(timestamp=ts, service=service, name=name, severity=severity)
