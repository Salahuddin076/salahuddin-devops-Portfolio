"""JSONL readers/writers for logs, deploy events and alerts.

Each file is one JSON object per line. Timestamps are ISO-8601 (``Z`` or an
explicit offset); naive timestamps are rejected so bucketing in
``aiops.anomaly`` is never ambiguous about timezone.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import Alert, DeployEvent, LogEvent


class InputError(ValueError):
    """Raised for malformed input files; message includes file and line number."""


def parse_timestamp(value: str) -> datetime:
    text = (value or "").strip()
    if not text:
        raise ValueError("empty timestamp")
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp {value!r} has no timezone (expected Z or +HH:MM offset)")
    return dt.astimezone(timezone.utc)


def format_timestamp(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_jsonl(path: Path) -> Iterable[tuple[int, dict]]:
    path = Path(path)
    if not path.is_file():
        raise InputError(f"{path}: file not found")
    with path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield lineno, json.loads(raw)
            except json.JSONDecodeError as exc:
                raise InputError(f"{path}:{lineno}: invalid JSON: {exc}") from exc


def read_logs(path: Path | str) -> list[LogEvent]:
    path = Path(path)
    out: list[LogEvent] = []
    for lineno, row in _read_jsonl(path):
        try:
            out.append(
                LogEvent(
                    timestamp=parse_timestamp(row["timestamp"]),
                    service=str(row["service"]).strip(),
                    level=str(row.get("level", "INFO")).strip().upper(),
                    message=str(row.get("message", "")),
                )
            )
        except (KeyError, ValueError) as exc:
            raise InputError(f"{path}:{lineno}: {exc}") from exc
    return out


def read_deploys(path: Path | str) -> list[DeployEvent]:
    path = Path(path)
    out: list[DeployEvent] = []
    for lineno, row in _read_jsonl(path):
        try:
            out.append(
                DeployEvent(
                    timestamp=parse_timestamp(row["timestamp"]),
                    service=str(row["service"]).strip(),
                    version=str(row["version"]).strip(),
                    actor=str(row.get("actor", "")).strip(),
                )
            )
        except (KeyError, ValueError) as exc:
            raise InputError(f"{path}:{lineno}: {exc}") from exc
    return out


def read_alerts(path: Path | str) -> list[Alert]:
    path = Path(path)
    out: list[Alert] = []
    for lineno, row in _read_jsonl(path):
        try:
            out.append(
                Alert(
                    timestamp=parse_timestamp(row["timestamp"]),
                    service=str(row["service"]).strip(),
                    name=str(row["name"]).strip(),
                    severity=str(row.get("severity", "warning")).strip().lower(),
                )
            )
        except (KeyError, ValueError) as exc:
            raise InputError(f"{path}:{lineno}: {exc}") from exc
    return out


def write_logs(path: Path | str, events: Iterable[LogEvent]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps({
                "timestamp": format_timestamp(e.timestamp),
                "service": e.service,
                "level": e.level,
                "message": e.message,
            }, sort_keys=True) + "\n")


def write_deploys(path: Path | str, events: Iterable[DeployEvent]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for d in events:
            fh.write(json.dumps({
                "timestamp": format_timestamp(d.timestamp),
                "service": d.service,
                "version": d.version,
                "actor": d.actor,
            }, sort_keys=True) + "\n")


def write_alerts(path: Path | str, alerts: Iterable[Alert]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for a in alerts:
            fh.write(json.dumps({
                "timestamp": format_timestamp(a.timestamp),
                "service": a.service,
                "name": a.name,
                "severity": a.severity,
            }, sort_keys=True) + "\n")
