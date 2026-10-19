"""Deterministic anomaly detection: rolling-baseline z-score over error rate.

Method
------
1. Log events for a service are bucketed into fixed-width time windows
   (``window_minutes``).
2. Each bucket's ``error_rate`` = ERROR-level events / total events in the
   bucket (0.0 when the bucket has no events).
3. For every bucket that has at least ``baseline_windows`` of *prior*
   buckets, compute the mean and population standard deviation of
   ``error_rate`` over those trailing buckets (the "rolling baseline").
4. ``z_score = (observed - mean) / stddev``. When the baseline is
   perfectly flat (``stddev == 0``), a configurable floor
   (``min_stddev``) is substituted so a single noisy bucket doesn't
   produce an infinite z-score; this is documented, not hidden.
5. A bucket is an ``Anomaly`` when ``z_score >= z_threshold`` AND the
   bucket has at least ``min_events`` samples (so a single stray error in
   an otherwise-quiet window isn't reported as a rate anomaly).

This is intentionally a simple, auditable statistical method — no ML, no
external calls. It is cheap enough to run on every ingest and its
threshold is a single documented number instead of a trained model nobody
can explain during an incident review.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Anomaly, LogEvent

ERROR_LEVELS = frozenset({"ERROR", "CRITICAL", "FATAL"})


@dataclass(frozen=True)
class AnomalyConfig:
    window_minutes: int = 5
    baseline_windows: int = 12  # trailing windows used for mean/stddev (1h at 5-min buckets)
    z_threshold: float = 3.0
    min_events: int = 5  # minimum events in a bucket before it is scored
    min_stddev: float = 0.01  # floor substituted when the baseline has zero variance


@dataclass(frozen=True)
class _Bucket:
    service: str
    start: datetime
    end: datetime
    total: int
    errors: int

    @property
    def error_rate(self) -> float:
        return self.errors / self.total if self.total else 0.0


def _bucket_index(ts: datetime, epoch: datetime, window: timedelta) -> int:
    return (ts - epoch) // window


def _bucketize(events: list[LogEvent], window_minutes: int) -> dict[str, list[_Bucket]]:
    """Group events per service into contiguous, gap-filled time buckets."""
    by_service: dict[str, list[LogEvent]] = {}
    for e in events:
        by_service.setdefault(e.service, []).append(e)

    window = timedelta(minutes=window_minutes)
    out: dict[str, list[_Bucket]] = {}
    for service, evs in by_service.items():
        evs = sorted(evs, key=lambda e: e.timestamp)
        epoch = evs[0].timestamp
        first_idx = 0
        last_idx = _bucket_index(evs[-1].timestamp, epoch, window)
        counts: dict[int, tuple[int, int]] = {}
        for e in evs:
            idx = _bucket_index(e.timestamp, epoch, window)
            total, errors = counts.get(idx, (0, 0))
            counts[idx] = (total + 1, errors + (1 if e.level.upper() in ERROR_LEVELS else 0))
        buckets = []
        for idx in range(first_idx, last_idx + 1):
            total, errors = counts.get(idx, (0, 0))
            start = epoch + idx * window
            buckets.append(_Bucket(service=service, start=start, end=start + window, total=total, errors=errors))
        out[service] = buckets
    return out


def detect(events: list[LogEvent], config: AnomalyConfig = AnomalyConfig()) -> list[Anomaly]:
    """Return anomalies found across all services, sorted by time then service."""
    anomalies: list[Anomaly] = []
    for service, buckets in _bucketize(events, config.window_minutes).items():
        for i in range(config.baseline_windows, len(buckets)):
            window = buckets[i]
            if window.total < config.min_events:
                continue
            history = buckets[i - config.baseline_windows : i]
            rates = [b.error_rate for b in history]
            mean = statistics.fmean(rates)
            stddev = statistics.pstdev(rates) or config.min_stddev
            z = (window.error_rate - mean) / stddev
            if z >= config.z_threshold:
                anomalies.append(
                    Anomaly(
                        service=service,
                        metric="error_rate",
                        window_start=window.start,
                        window_end=window.end,
                        observed_value=window.error_rate,
                        baseline_mean=mean,
                        baseline_stddev=stddev,
                        z_score=z,
                        sample_size=window.total,
                    )
                )
    return sorted(anomalies, key=lambda a: (a.window_start, a.service))
