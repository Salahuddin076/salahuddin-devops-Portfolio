"""Deterministic synthetic sample data: logs, deploy events and alerts.

Same idea as ``finops.generator`` in the sibling FinOps project: a fixed
seed produces byte-identical files, so the committed ``sample-data/`` can
always be regenerated and diffed in CI. Three services get ~4 hours of
5-minute-bucketed log traffic with a small amount of random jitter around a
flat baseline error rate; one service gets an injected anomaly bucket
immediately after a deploy, and a paired alert, so the sample data
exercises detection, correlation and the rollback proposal path end to end.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .io import write_alerts, write_deploys, write_logs
from .models import Alert, DeployEvent, LogEvent

SERVICES: tuple[str, ...] = ("checkout-api", "payments-api", "search-api")
WINDOW_MINUTES = 5
BUCKETS = 48  # 4 hours per service
BASELINE_ERROR_RATE = 0.02
EVENTS_PER_BUCKET = 50
ANOMALY_BUCKET = 30
ANOMALY_SERVICE = "checkout-api"
ANOMALY_ERROR_RATE = 0.40

MESSAGES_OK = (
    "request completed",
    "cache hit for key",
    "healthcheck ok",
    "processed item",
)
MESSAGES_ERROR = (
    "upstream timeout calling inventory-service from user=alice@example.com at 203.0.113.42",
    "500 Internal Server Error: nil pointer in checkout handler",
    "database connection pool exhausted",
    "failed auth: token=sk-abcdef1234567890 rejected by upstream",
)


def _generate_events(seed: int, start: datetime) -> list[LogEvent]:
    rng = random.Random(seed)
    events: list[LogEvent] = []
    window = timedelta(minutes=WINDOW_MINUTES)
    for service in SERVICES:
        for bucket in range(BUCKETS):
            bucket_start = start + bucket * window
            if service == ANOMALY_SERVICE and bucket == ANOMALY_BUCKET:
                rate = ANOMALY_ERROR_RATE
            else:
                rate = max(0.0, BASELINE_ERROR_RATE + rng.uniform(-0.01, 0.01))
            n = EVENTS_PER_BUCKET
            n_errors = round(n * rate)
            for i in range(n):
                offset = window * i / n
                level = "ERROR" if i < n_errors else "INFO"
                message = rng.choice(MESSAGES_ERROR) if level == "ERROR" else rng.choice(MESSAGES_OK)
                events.append(LogEvent(timestamp=bucket_start + offset, service=service, level=level, message=message))
    return sorted(events, key=lambda e: (e.timestamp, e.service))


def _generate_deploys(start: datetime) -> list[DeployEvent]:
    window = timedelta(minutes=WINDOW_MINUTES)
    # A deploy lands one bucket before the injected anomaly bucket, for the
    # service that gets the anomaly, so correlation + the rollback proposal
    # path both have something to find in the sample data.
    deploy_time = start + (ANOMALY_BUCKET - 1) * window + timedelta(minutes=2)
    return [DeployEvent(timestamp=deploy_time, service=ANOMALY_SERVICE, version="v1.42.0", actor="ci-bot")]


def _generate_alerts(start: datetime) -> list[Alert]:
    window = timedelta(minutes=WINDOW_MINUTES)
    alert_time = start + ANOMALY_BUCKET * window + timedelta(minutes=3)
    return [Alert(timestamp=alert_time, service=ANOMALY_SERVICE, name="HighErrorRate", severity="critical")]


def generate(out_dir: Path | str, seed: int = 11, start: datetime | None = None) -> dict[str, Path]:
    start = start or datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    out = Path(out_dir)
    logs = _generate_events(seed, start)
    deploys = _generate_deploys(start)
    alerts = _generate_alerts(start)

    logs_path = out / "logs.jsonl"
    deploys_path = out / "deploys.jsonl"
    alerts_path = out / "alerts.jsonl"
    write_logs(logs_path, logs)
    write_deploys(deploys_path, deploys)
    write_alerts(alerts_path, alerts)
    return {"logs": logs_path, "deploys": deploys_path, "alerts": alerts_path}
