#!/usr/bin/env python3
"""Replica timeline for n8n workers under KEDA's Redis list scaler (stdlib only).

This is a MODEL of the documented KEDA and HorizontalPodAutoscaler semantics,
not KEDA itself. It answers "what would the worker count do for this queue
shape with these ScaledObject settings?" before you change them in a cluster.

What it models:
  KEDA (every pollingInterval)
    - a trigger is active when its list length > activationListLength;
    - at 0 replicas and any trigger active: scale 0 -> max(minReplicaCount, 1);
    - at >0 replicas, no trigger active, and cooldownPeriod seconds since the
      last active poll: scale to minReplicaCount (0).
  HPA (every --hpa-sync-period, only while replicas > 0)
    - per trigger, AverageValue target: ceil(listLength_now / target), kept at
      the current count when within the HPA tolerance (default 10%);
    - the largest proposal across triggers wins, clamped to [max(min,1), max];
    - scale-down: the highest recommendation of the last
      stabilizationWindowSeconds, then the Percent policy per period;
    - scale-up: stabilization window (default 0), then the Pods policy per period.

What it does not model: pod start-up time, workers draining the queue (the
input is an observed queue depth, open loop), KEDA's metric caching, or
fallback. Input: CSV with header `t_seconds,wait` and an optional `active`
column (jobs in bull:jobs:active); each row holds until the next one.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

DISCLAIMER = "model of documented KEDA + HPA semantics, not KEDA itself"


@dataclass
class Settings:
    list_length: int = 10
    activation_list_length: int = 0
    min_replicas: int = 0
    max_replicas: int = 10
    polling_interval: int = 15
    cooldown_period: int = 300
    stabilization_window: int = 300
    scale_down_percent: int = 50
    scale_down_period: int = 60
    scale_up_stabilization: int = 0
    scale_up_pods: int = 4
    scale_up_period: int = 15
    # Target for the bull:jobs:active trigger (worker concurrency); 0 = no trigger.
    active_list_length: int = 10
    hpa_sync_period: int = 15
    tolerance: float = 0.1
    initial_replicas: int = 0

    def validate(self) -> None:
        if self.list_length < 1 or self.max_replicas < 1:
            raise ValueError("list_length and max_replicas must be >= 1")
        if self.min_replicas < 0 or self.min_replicas > self.max_replicas:
            raise ValueError("min_replicas must be between 0 and max_replicas")
        for name in ("polling_interval", "hpa_sync_period", "scale_down_period", "scale_up_period"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1 second")
        if not 0 <= self.initial_replicas <= self.max_replicas:
            raise ValueError("initial_replicas must be between 0 and max_replicas")


@dataclass
class Sample:
    t: int
    wait: int
    active: int = 0


@dataclass
class Event:
    t: int
    wait: int
    active: int
    before: int
    after: int
    actor: str
    reason: str

    def text(self) -> str:
        return (f"t={self.t:>5}s  wait={self.wait:>4} active={self.active:>3}  "
                f"{self.before:>2} -> {self.after:<2} {self.actor:<4} {self.reason}")


@dataclass
class Result:
    settings: Settings
    events: list[Event] = field(default_factory=list)
    timeline: list[tuple[int, int]] = field(default_factory=list)  # (t, replicas) every second
    end: int = 0

    @property
    def peak(self) -> int:
        return max((r for _, r in self.timeline), default=0)

    @property
    def replica_seconds(self) -> int:
        return sum(r for _, r in self.timeline)

    def replicas_at(self, t: int) -> int:
        return self.timeline[t][1]

    def scale_to_zero_count(self) -> int:
        return sum(1 for e in self.events if e.after == 0 and e.before > 0)


def load_csv(path_or_text: str | Path, *, is_text: bool = False) -> list[Sample]:
    text = path_or_text if is_text else Path(path_or_text).read_text()
    rows = list(csv.DictReader(line for line in str(text).splitlines() if line.strip() and not line.startswith("#")))
    if not rows:
        raise ValueError("no samples in CSV")
    if "t_seconds" not in rows[0] or "wait" not in rows[0]:
        raise ValueError("CSV header must include t_seconds and wait")
    samples = [Sample(int(r["t_seconds"]), int(r["wait"]), int(r.get("active") or 0)) for r in rows]
    for a, b in zip(samples, samples[1:]):
        if b.t <= a.t:
            raise ValueError(f"t_seconds must increase (row t={b.t} after t={a.t})")
    if samples[0].t != 0:
        raise ValueError("the first sample must be at t_seconds=0")
    if any(s.wait < 0 or s.active < 0 for s in samples):
        raise ValueError("list lengths cannot be negative")
    return samples


def _value_at(samples: list[Sample], t: int) -> Sample:
    current = samples[0]
    for s in samples:
        if s.t > t:
            break
        current = s
    return current


def _proposal(metric: int, target: int, current: int, tolerance: float) -> int:
    """HPA AverageValue proposal for one external metric."""
    if current > 0 and abs(metric / (target * current) - 1.0) <= tolerance:
        return current
    return math.ceil(metric / target)


def simulate(samples: list[Sample], settings: Settings, end: int | None = None) -> Result:
    settings.validate()
    end = samples[-1].t if end is None else end
    res = Result(settings=settings, end=end)
    replicas = settings.initial_replicas
    last_active: int | None = 0 if replicas > 0 else None
    history: list[tuple[int, int]] = []  # HPA recommendations (t, replicas)
    changes: list[tuple[int, int]] = []  # HPA scale changes (t, delta)
    hpa_min = max(settings.min_replicas, 1)

    def record(t, s, after, actor, reason):
        nonlocal replicas
        res.events.append(Event(t, s.wait, s.active, replicas, after, actor, reason))
        replicas = after

    for t in range(end + 1):
        s = _value_at(samples, t)

        if t % settings.polling_interval == 0:
            active_wait = s.wait > settings.activation_list_length
            active_run = settings.active_list_length > 0 and s.active > 0
            if active_wait or active_run:
                last_active = t
                if replicas == 0:
                    why = (f"wait {s.wait} > activationListLength {settings.activation_list_length}"
                           if active_wait else f"active {s.active} > 0")
                    record(t, s, hpa_min, "KEDA", f"activation ({why})")
                    history.clear()
                    changes.clear()
            elif replicas > 0 and settings.min_replicas == 0:
                idle_for = t - (last_active if last_active is not None else 0)
                if idle_for >= settings.cooldown_period:
                    record(t, s, 0, "KEDA", f"cooldown: idle {idle_for}s >= cooldownPeriod {settings.cooldown_period}s")
                    history.clear()
                    changes.clear()

        if replicas > 0 and t % settings.hpa_sync_period == 0:
            proposals = {"wait": _proposal(s.wait, settings.list_length, replicas, settings.tolerance)}
            if settings.active_list_length > 0:
                proposals["active"] = _proposal(s.active, settings.active_list_length, replicas, settings.tolerance)
            driver = max(proposals, key=proposals.get)
            raw = min(max(proposals[driver], hpa_min), settings.max_replicas)
            history.append((t, raw))
            history[:] = [(ht, hr) for ht, hr in history
                          if ht > t - max(settings.stabilization_window, settings.scale_up_stabilization, 1)]
            desired = raw
            reason = ""
            if raw < replicas:
                window = [hr for ht, hr in history if ht > t - settings.stabilization_window] or [raw]
                desired = min(replicas, max(window))
                deleted = -sum(d for ct, d in changes if ct > t - settings.scale_down_period and d < 0)
                start = replicas + deleted
                floor = math.ceil(start * (1 - settings.scale_down_percent / 100))
                desired = max(desired, floor, hpa_min)
                reason = f"HPA ceil({s.wait}/{settings.list_length})" if driver == "wait" else \
                    f"HPA ceil({s.active}/{settings.active_list_length}) active"
                if desired == max(window) and max(window) > raw:
                    reason += f", held by {settings.stabilization_window}s stabilization"
                elif desired == floor and floor > raw:
                    reason += f", limited to -{settings.scale_down_percent}%/{settings.scale_down_period}s"
            elif raw > replicas:
                if settings.scale_up_stabilization > 0:
                    window = [hr for ht, hr in history if ht > t - settings.scale_up_stabilization] or [raw]
                    desired = max(replicas, min(window))
                added = sum(d for ct, d in changes if ct > t - settings.scale_up_period and d > 0)
                cap = replicas - added + settings.scale_up_pods
                desired = min(desired, cap)
                reason = f"HPA ceil({s.wait}/{settings.list_length})" if driver == "wait" else \
                    f"HPA ceil({s.active}/{settings.active_list_length}) active"
                if desired == cap and cap < raw:
                    reason += f", limited to +{settings.scale_up_pods} pods/{settings.scale_up_period}s"
            if desired != replicas:
                changes.append((t, desired - replicas))
                record(t, s, desired, "HPA", reason[4:] if reason.startswith("HPA ") else reason)

        res.timeline.append((t, replicas))
    return res


def settings_from_values(path: str | Path) -> dict:
    """Read the keda/worker settings from a chart values file (yaml_lite subset)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import yaml_lite  # noqa: PLC0415

    values = yaml_lite.load_all(Path(path).read_text())[0]
    k = values.get("keda", {})
    out = {}
    mapping = {
        "listLength": "list_length", "activationListLength": "activation_list_length",
        "minReplicaCount": "min_replicas", "maxReplicaCount": "max_replicas",
        "pollingInterval": "polling_interval", "cooldownPeriod": "cooldown_period",
    }
    for src, dst in mapping.items():
        if src in k:
            out[dst] = int(k[src])
    down, up = k.get("scaleDown", {}), k.get("scaleUp", {})
    for src, dst, block in (("stabilizationWindowSeconds", "stabilization_window", down),
                            ("percentPerPeriod", "scale_down_percent", down),
                            ("periodSeconds", "scale_down_period", down),
                            ("stabilizationWindowSeconds", "scale_up_stabilization", up),
                            ("podsPerPeriod", "scale_up_pods", up),
                            ("periodSeconds", "scale_up_period", up)):
        if src in block:
            out[dst] = int(block[src])
    if "activeListTrigger" in k:
        out["active_list_length"] = int(values.get("worker", {}).get("concurrency", 10)) if k["activeListTrigger"] else 0
    return out


def render_text(res: Result, source: str) -> str:
    s = res.settings
    lines = [
        f"keda_scaling_sim: {DISCLAIMER}",
        f"input {source}: {res.end}s",
        (f"settings: listLength={s.list_length} activationListLength={s.activation_list_length} "
         f"min={s.min_replicas} max={s.max_replicas} pollingInterval={s.polling_interval}s "
         f"cooldownPeriod={s.cooldown_period}s scaleDown stabilization={s.stabilization_window}s "
         f"(-{s.scale_down_percent}%/{s.scale_down_period}s) scaleUp +{s.scale_up_pods}/{s.scale_up_period}s "
         f"activeTarget={s.active_list_length or 'off'}"),
    ]
    lines += [e.text() for e in res.events]
    always_on = s.max_replicas * (res.end + 1)
    pct = 100 * res.replica_seconds / always_on if always_on else 0
    lines.append(
        f"summary: peak {res.peak} replicas, {len(res.events)} scaling events, "
        f"{res.scale_to_zero_count()} scale-to-zero, {res.replica_seconds} worker-seconds "
        f"vs {always_on} at max always-on ({pct:.1f}%)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("csv", help="queue-depth CSV (t_seconds,wait[,active])")
    ap.add_argument("--values", help="read defaults from a chart values file (keda.*, worker.concurrency)")
    ap.add_argument("--end", type=int, help="simulate until this second (default: last sample)")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    flags = {f: t for f, t in (
        ("list-length", int), ("activation-list-length", int), ("min-replicas", int), ("max-replicas", int),
        ("polling-interval", int), ("cooldown-period", int), ("stabilization-window", int),
        ("scale-down-percent", int), ("scale-down-period", int), ("scale-up-stabilization", int),
        ("scale-up-pods", int), ("scale-up-period", int), ("active-list-length", int),
        ("hpa-sync-period", int), ("tolerance", float), ("initial-replicas", int))}
    for flag, typ in flags.items():
        ap.add_argument(f"--{flag}", type=typ)
    args = ap.parse_args(argv)

    try:
        params = settings_from_values(args.values) if args.values else {}
        for flag in flags:
            v = getattr(args, flag.replace("-", "_"))
            if v is not None:
                params[flag.replace("-", "_")] = v
        settings = Settings(**params)
        samples = load_csv(args.csv)
        res = simulate(samples, settings, args.end)
    except (OSError, ValueError) as exc:
        print(f"keda_scaling_sim: error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps({
            "note": DISCLAIMER, "settings": asdict(settings),
            "events": [asdict(e) for e in res.events],
            "peak": res.peak, "replica_seconds": res.replica_seconds,
            "scale_to_zero": res.scale_to_zero_count(),
        }, indent=2))
    else:
        print(render_text(res, args.csv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
