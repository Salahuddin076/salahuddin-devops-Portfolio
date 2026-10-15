#!/usr/bin/env python3
"""slogen: SLOs as code -> Prometheus rules, PrometheusRule CRDs, Grafana dashboards, error-budget reports.

Stdlib only. Reads `slo/*.json` and writes deterministic files to `generated/`:

  generated/prometheus/<service>.rules.yml        plain Prometheus rule files
  generated/prometheus/meta.rules.yml             the Watchdog (dead man's switch)
  generated/kubernetes/<service>.prometheusrule.yaml  the same rules as PrometheusRule CRDs
  generated/grafana/<service>.dashboard.json      one dashboard per service
  generated/reports/<service>-<slo>.txt           error-budget report on the SLO's sample CSV

Alerting follows the multi-window, multi-burn-rate approach from the Google SRE
workbook ("Alerting on SLOs"): an alert fires only when the error ratio is above
`factor x error budget` over BOTH a long window (is it significant?) and a short
window (is it still happening?).

Commands:
  generate [--check]             write generated/ (or fail if it differs)
  explain                        print the burn-rate math for every SLO tier
  report CSV --slo FILE --name N error-budget report for hourly good/total counts
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SLI_WINDOWS = ("5m", "30m", "1h", "2h", "6h", "1d", "3d")
RUNBOOK_BASE = ("https://github.com/Salahuddin076/salahuddin-devops-Portfolio/blob/main/"
                "projects/observability-sre-platform/runbooks/")
NAMESPACE = "observability"
CRD_LABELS = {
    "app.kubernetes.io/part-of": "observability-sre-platform",
    "app.kubernetes.io/managed-by": "slogen",
    "prometheus": "platform",
    "role": "slo-rules",
}
SLUG = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")
_DURATION = re.compile(r"^([1-9][0-9]*)([mhd])$")
_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}


class SLOError(ValueError):
    """An SLO file is invalid."""


@dataclass(frozen=True)
class Tier:
    name: str
    severity: str
    factor: Decimal
    long: str
    short: str
    for_: str
    speed: str  # "fast" (page) or "slow" (ticket): selects the runbook


# The SRE workbook's recommended starting points (for a 30-day window):
# 2% of the budget in 1h, 5% in 6h page; 10% in 1d, 10% in 3d open a ticket.
TIERS = (
    Tier("page-1h", "page", Decimal("14.4"), "1h", "5m", "2m", "fast"),
    Tier("page-6h", "page", Decimal("6"), "6h", "30m", "2m", "fast"),
    Tier("ticket-1d", "ticket", Decimal("3"), "1d", "2h", "15m", "slow"),
    Tier("ticket-3d", "ticket", Decimal("1"), "3d", "6h", "15m", "slow"),
)
TIERS_BY_NAME = {t.name: t for t in TIERS}


# ---------------------------------------------------------------- math

def seconds(duration: str) -> int:
    m = _DURATION.match(duration)
    if not m:
        raise SLOError(f"bad duration {duration!r} (use e.g. 5m, 6h, 30d)")
    return int(m.group(1)) * _UNIT_SECONDS[m.group(2)]


def error_budget(objective: Decimal) -> Decimal:
    """Allowed error ratio: 99.9 (%) -> 0.001."""
    return (Decimal(100) - objective) / Decimal(100)


def budget_consumed(burn_rate, window: str, slo_window: str) -> Fraction:
    """Fraction of the SLO-window budget a constant burn uses up in `window`: rate x window / SLO window."""
    return Fraction(Decimal(str(burn_rate))) * Fraction(seconds(window), seconds(slo_window))


def time_to_exhaustion(burn_rate, slo_window: str) -> Fraction:
    """Seconds until a full budget is gone at a constant burn rate."""
    return Fraction(seconds(slo_window)) / Fraction(Decimal(str(burn_rate)))


def burn_threshold(factor: Decimal, objective: Decimal) -> Decimal:
    """Error ratio at which a tier fires: factor x error budget."""
    return factor * error_budget(objective)


def dec(d: Decimal) -> str:
    """Decimal without exponent or trailing zeros: 14.40 -> 14.4, 6.0 -> 6, 0.0010 -> 0.001."""
    return format(d.normalize(), "f")


def pct(frac, places: int = 2) -> str:
    s = f"{float(frac) * 100:.{places}f}".rstrip("0").rstrip(".")
    return s or "0"


def days(sec) -> str:
    return f"{float(sec) / 86400:.1f}d"


# ---------------------------------------------------------------- SLO files

def load_service(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SLOError(f"{path}: {exc}") from exc

    def fail(msg: str):
        raise SLOError(f"{path}: {msg}")

    if not isinstance(data, dict):
        fail("top level must be an object")
    for key in ("service", "team", "slos"):
        if key not in data:
            fail(f"missing `{key}`")
    if not SLUG.match(str(data["service"])):
        fail(f"service {data['service']!r} is not a lowercase slug")
    if not isinstance(data["slos"], list) or not data["slos"]:
        fail("`slos` must be a non-empty list")
    seen = set()
    for slo in data["slos"]:
        name = slo.get("name", "")
        if not SLUG.match(str(name)):
            fail(f"SLO name {name!r} is not a lowercase slug")
        if name in seen:
            fail(f"duplicate SLO name {name!r}")
        seen.add(name)
        obj = slo.get("objective")
        if isinstance(obj, bool) or not isinstance(obj, (int, float)) or not 0 < obj < 100:
            fail(f"{name}: objective must be a percentage between 0 and 100, got {obj!r}")
        slo["objective"] = Decimal(str(obj))
        if seconds(slo.get("window", "")) < 86400:
            fail(f"{name}: window must be at least 1d")
        sli = slo.get("sli") or {}
        for part in ("good", "total"):
            if "$window" not in str(sli.get(part, "")):
                fail(f"{name}: sli.{part} must be a PromQL string containing [$window]")
        alerting = slo.get("alerting") or {}
        tiers = alerting.get("tiers") or []
        if not tiers:
            fail(f"{name}: alerting.tiers must list at least one of {sorted(TIERS_BY_NAME)}")
        for t in tiers:
            if t not in TIERS_BY_NAME:
                fail(f"{name}: unknown tier {t!r}; known: {sorted(TIERS_BY_NAME)}")
        if not SLUG.match(str(alerting.get("runbook", ""))):
            fail(f"{name}: alerting.runbook must be a slug (runbooks/<slug>-fast-burn.md)")
    return data


def load_all(slo_dir: Path) -> list[dict]:
    files = sorted(Path(slo_dir).glob("*.json"))
    if not files:
        raise SLOError(f"{slo_dir}: no *.json SLO files")
    services = [load_service(f) for f in files]
    names = [s["service"] for s in services]
    if len(set(names)) != len(names):
        raise SLOError(f"duplicate service names in {slo_dir}")
    return services


# ---------------------------------------------------------------- rules

def camel(*parts: str) -> str:
    return "".join(w.capitalize() for p in parts for w in re.split(r"[-_]", p))


def selector(service: str, slo: dict) -> str:
    return f'{{service="{service}",slo="{slo["name"]}"}}'


def sli_error_expr(slo: dict, window: str) -> str:
    good = slo["sli"]["good"].replace("$window", window)
    total = slo["sli"]["total"].replace("$window", window)
    # `or vector(0)`: when every request fails, the good series may not exist at all;
    # without this the ratio would be empty and nothing would alert.
    return f"1 - (\n  ({good} or vector(0))\n  /\n  {total}\n)"


def alert_name(service: str, slo: dict, tier: Tier) -> str:
    return camel(service, slo["name"], "burn", tier.severity, tier.long)


def runbook_url(slo: dict, tier: Tier) -> str:
    return f"{RUNBOOK_BASE}{slo['alerting']['runbook']}-{tier.speed}-burn.md"


def sli_group(service: dict, slo: dict) -> dict:
    svc = service["service"]
    labels = {"service": svc, "slo": slo["name"]}
    sel = selector(svc, slo)
    budget = dec(error_budget(slo["objective"]))
    window = slo["window"]
    rules = [{"record": f"slo:sli_error:ratio_rate{w}", "expr": sli_error_expr(slo, w), "labels": dict(labels)}
             for w in SLI_WINDOWS]
    rules += [
        {"record": "slo:objective:ratio", "expr": f"vector({dec(slo['objective'] / 100)})", "labels": dict(labels)},
        {"record": "slo:error_budget:ratio", "expr": f"vector({budget})", "labels": dict(labels)},
        # Unweighted mean of the 5m ratios over the SLO window: cheap, and close to the
        # request-weighted ratio when traffic is steady (docs/operations.md).
        {"record": f"slo:sli_error:ratio_rate{window}",
         "expr": f"avg_over_time(slo:sli_error:ratio_rate5m{sel}[{window}])", "labels": dict(labels)},
        {"record": "slo:period_error_budget_remaining:ratio",
         "expr": f"1 - (slo:sli_error:ratio_rate{window}{sel} / {budget})", "labels": dict(labels)},
    ]
    return {"name": f"slo-{svc}-{slo['name']}-sli", "rules": rules}


def alert_rule(service: dict, slo: dict, tier: Tier) -> dict:
    svc = service["service"]
    sel = selector(svc, slo)
    obj, window = slo["objective"], slo["window"]
    budget = dec(error_budget(obj))
    threshold = f"({dec(tier.factor)} * {budget})"
    consumed = budget_consumed(tier.factor, tier.long, window)
    tte = time_to_exhaustion(tier.factor, window)
    return {
        "alert": alert_name(svc, slo, tier),
        "expr": (f"(\n  slo:sli_error:ratio_rate{tier.long}{sel} > {threshold}\n)\nand\n"
                 f"(\n  slo:sli_error:ratio_rate{tier.short}{sel} > {threshold}\n)"),
        "for": tier.for_,
        "labels": {
            "severity": tier.severity,
            "team": service["team"],
            "tier": tier.name,
            "burn_rate": dec(tier.factor),
            "long_window": tier.long,
            "short_window": tier.short,
        },
        "annotations": {
            "summary": (f"{svc} {slo['name']} SLO: error budget burning at {dec(tier.factor)}x or faster "
                        f"({tier.long} and {tier.short} windows)"),
            "description": (f"The {tier.long} error ratio is {{{{ $value | humanizePercentage }}}} against an error "
                            f"budget of {pct(error_budget(obj), 3)}% (objective {dec(obj)}% over {window}). "
                            f"A sustained {dec(tier.factor)}x burn consumes {pct(consumed)}% of the {window} budget "
                            f"every {tier.long} and exhausts it in {days(tte)}."),
            "runbook_url": runbook_url(slo, tier),
        },
    }


def alert_group(service: dict, slo: dict) -> dict:
    tiers = [TIERS_BY_NAME[t] for t in slo["alerting"]["tiers"]]
    tiers.sort(key=lambda t: TIERS.index(t))
    return {"name": f"slo-{service['service']}-{slo['name']}-alerts",
            "rules": [alert_rule(service, slo, t) for t in tiers]}


def service_rules(service: dict) -> dict:
    groups = []
    for slo in service["slos"]:
        groups += [sli_group(service, slo), alert_group(service, slo)]
    return {"groups": groups}


def meta_rules() -> dict:
    return {"groups": [{"name": "slo-meta", "rules": [{
        "alert": "Watchdog",
        "expr": "vector(1)",
        "labels": {"severity": "none"},
        "annotations": {
            "summary": "Dead man's switch: always firing while the alerting pipeline works.",
            "description": ("Routed to an external heartbeat receiver every minute. If the heartbeat stops, "
                            "Prometheus, rule evaluation or Alertmanager is broken and the receiver pages."),
            "runbook_url": f"{RUNBOOK_BASE}watchdog.md",
        },
    }]}]}


def prometheus_rule(name: str, rules: dict) -> dict:
    return {
        "apiVersion": "monitoring.coreos.com/v1",
        "kind": "PrometheusRule",
        "metadata": {"name": name, "namespace": NAMESPACE, "labels": dict(CRD_LABELS)},
        "spec": rules,
    }


# ---------------------------------------------------------------- dashboards

def _panel(pid, ptype, title, desc, grid, targets, defaults, options):
    return {
        "id": pid,
        "type": ptype,
        "title": title,
        "description": desc,
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "gridPos": grid,
        "targets": [{"refId": chr(ord("A") + i), "datasource": {"type": "prometheus", "uid": "${datasource}"},
                     "expr": expr, "legendFormat": legend} for i, (expr, legend) in enumerate(targets)],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": options,
    }


def dashboard(service: dict) -> dict:
    svc = service["service"]
    panels, pid, y = [], 1, 0
    stat_opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                 "colorMode": "value", "graphMode": "area", "textMode": "auto", "orientation": "auto"}
    ts_opts = {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
               "tooltip": {"mode": "multi", "sort": "desc"}}
    for slo in service["slos"]:
        sel, window = selector(svc, slo), slo["window"]
        budget = dec(error_budget(slo["objective"]))
        objective = float(slo["objective"] / 100)
        panels.append({"id": pid, "type": "row", "title": f"{slo['name']} ({dec(slo['objective'])}% over {window})",
                       "collapsed": False, "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": []})
        pid, y = pid + 1, y + 1
        panels.append(_panel(
            pid, "stat", f"SLI ({window})", slo.get("description", ""), {"h": 8, "w": 6, "x": 0, "y": y},
            [(f"1 - slo:sli_error:ratio_rate{window}{sel}", "SLI")],
            {"unit": "percentunit", "decimals": 3, "color": {"mode": "thresholds"},
             "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None},
                                                          {"color": "green", "value": objective}]}},
            stat_opts))
        panels.append(_panel(
            pid + 1, "stat", "Error budget remaining", f"1 - (error ratio over {window} / {budget})",
            {"h": 8, "w": 6, "x": 6, "y": y},
            [(f"slo:period_error_budget_remaining:ratio{sel}", "remaining")],
            {"unit": "percentunit", "decimals": 1, "color": {"mode": "thresholds"},
             "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None},
                                                          {"color": "orange", "value": 0.25},
                                                          {"color": "green", "value": 0.5}]}},
            stat_opts))
        panels.append(_panel(
            pid + 2, "timeseries", "Burn rate", "Error ratio / error budget. Dashed lines: 1x, 3x, 6x, 14.4x.",
            {"h": 8, "w": 12, "x": 12, "y": y},
            [(f"slo:sli_error:ratio_rate{w}{sel} / {budget}", w) for w in ("5m", "1h", "6h", "1d", "3d")],
            {"unit": "suffix:x", "min": 0, "color": {"mode": "palette-classic"},
             "custom": {"thresholdsStyle": {"mode": "dashed"}, "lineWidth": 1, "fillOpacity": 0},
             "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None},
                                                          {"color": "yellow", "value": 1},
                                                          {"color": "orange", "value": 3},
                                                          {"color": "red", "value": 6},
                                                          {"color": "dark-red", "value": 14.4}]}},
            ts_opts))
        pid, y = pid + 3, y + 8
    return {
        "annotations": {"list": []},
        "description": f"Generated by slogen from slo/{svc}.json. Do not edit by hand.",
        "editable": False,
        "graphTooltip": 1,
        "panels": panels,
        "refresh": "1m",
        "schemaVersion": 39,
        "tags": ["slo", "generated", svc],
        "templating": {"list": [{"name": "datasource", "label": "Prometheus", "type": "datasource",
                                 "query": "prometheus", "current": {}, "hide": 0, "refresh": 1,
                                 "options": [], "regex": ""}]},
        "time": {"from": "now-7d", "to": "now"},
        "timepicker": {},
        "timezone": "utc",
        "title": f"SLO / {svc}",
        "uid": f"slo-{svc}",
        "version": 1,
    }


# ---------------------------------------------------------------- YAML out

def _scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return json.dumps(str(v))


def to_yaml(obj, indent: int = 0) -> list[str]:
    pad = " " * indent
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:")
                out += to_yaml(v, indent + 2)
            elif isinstance(v, str) and "\n" in v:
                out.append(f"{pad}{k}: |-")
                out += [f"{pad}  {line}" for line in v.split("\n")]
            elif isinstance(v, (dict, list)):
                out.append(f"{pad}{k}: {'{}' if isinstance(v, dict) else '[]'}")
            else:
                out.append(f"{pad}{k}: {_scalar(v)}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                sub = to_yaml(item, indent + 2)
                out.append(f"{pad}- {sub[0].lstrip()}")
                out += sub[1:]
            else:
                out.append(f"{pad}- {_scalar(item)}")
    else:
        out.append(pad + _scalar(obj))
    return out


def yaml_doc(obj, source: str, document_start: bool = False) -> str:
    header = f"# Generated by generator/slogen.py from {source}. Do not edit by hand.\n"
    # Kubernetes manifests start with `---` so they can be concatenated safely.
    return header + ("---\n" if document_start else "") + "\n".join(to_yaml(obj)) + "\n"


# ---------------------------------------------------------------- error-budget report

def read_hourly_csv(path: Path) -> list[tuple[datetime, int, int]]:
    rows = []
    try:
        fh = open(path, newline="")
    except OSError as exc:
        raise SLOError(f"{path}: {exc.strerror}") from exc
    with fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != ["timestamp", "good", "total"]:
            raise SLOError(f"{path}: header must be timestamp,good,total, got {reader.fieldnames}")
        for n, r in enumerate(reader, start=2):
            try:
                ts = datetime.strptime(r["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                good, total = int(r["good"]), int(r["total"])
            except (TypeError, ValueError) as exc:
                raise SLOError(f"{path}:{n}: {exc}") from exc
            if not 0 <= good <= total:
                raise SLOError(f"{path}:{n}: need 0 <= good <= total, got good={good} total={total}")
            if rows and ts - rows[-1][0] != timedelta(hours=1):
                raise SLOError(f"{path}:{n}: rows must be consecutive hours ({rows[-1][0]:%FT%TZ} -> {ts:%FT%TZ})")
            rows.append((ts, good, total))
    if not rows:
        raise SLOError(f"{path}: no data rows")
    return rows


def _window_hours(window: str) -> int:
    # Hourly data can't resolve 5m or 30m: those use the latest hour.
    return max(1, seconds(window) // 3600)


def error_budget_report(rows, slo: dict) -> dict:
    """Replay the SLO's alert tiers over hourly good/total counts.

    Each row is one hour ending at its timestamp. Windows use the data available
    (like rate() on a short history). Comparisons are exact (fractions).
    """
    budget = Fraction(error_budget(slo["objective"]))
    bad = [t - g for _, g, t in rows]
    total = [t for _, _, t in rows]
    pre_bad, pre_total = [0], [0]
    for b, t in zip(bad, total):
        pre_bad.append(pre_bad[-1] + b)
        pre_total.append(pre_total[-1] + t)

    def ratio(i: int, window: str) -> Fraction:
        lo = max(0, i + 1 - _window_hours(window))
        t = pre_total[i + 1] - pre_total[lo]
        return Fraction(pre_bad[i + 1] - pre_bad[lo], t) if t else Fraction(0)

    def burn(i: int, window: str) -> Fraction:
        return ratio(i, window) / budget

    tiers = sorted((TIERS_BY_NAME[t] for t in slo["alerting"]["tiers"]), key=TIERS.index)
    alerts = []
    for tier in tiers:
        threshold = Fraction(tier.factor)
        start, peak = None, Fraction(0)
        for i, (ts, _, _) in enumerate(rows):
            firing = burn(i, tier.long) > threshold and burn(i, tier.short) > threshold
            if firing:
                if start is None:
                    start, peak = ts, Fraction(0)
                peak = max(peak, burn(i, tier.long))
            elif start is not None:
                alerts.append({"tier": tier.name, "severity": tier.severity, "factor": dec(tier.factor),
                               "long": tier.long, "short": tier.short, "fired": start, "resolved": ts,
                               "peak_long_burn": float(peak)})
                start = None
        if start is not None:
            alerts.append({"tier": tier.name, "severity": tier.severity, "factor": dec(tier.factor),
                           "long": tier.long, "short": tier.short, "fired": start, "resolved": None,
                           "peak_long_burn": float(peak)})
    alerts.sort(key=lambda a: (a["fired"], TIERS.index(TIERS_BY_NAME[a["tier"]])))
    window_h = seconds(slo["window"]) // 3600
    consumed = sum(burn(i, "1h") for i in range(len(rows))) / window_h
    last = len(rows) - 1
    return {
        "objective": dec(slo["objective"]),
        "window": slo["window"],
        "error_budget": float(budget),
        "hours": len(rows),
        "first": rows[0][0],
        "last": rows[-1][0],
        "requests": pre_total[-1],
        "errors": pre_bad[-1],
        "budget_consumed": float(consumed),
        "budget_remaining": float(1 - consumed),
        "burn_at_end": {w: float(burn(last, w)) for w in ("1h", "6h", "1d", "3d")},
        "alerts": alerts,
    }


def _ts(t: datetime | None) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else "-"


def render_report(rep: dict, service: str, slo_name: str, source: str) -> str:
    lines = [
        f"error-budget report: {service}/{slo_name} (objective {rep['objective']}%, window {rep['window']}, "
        f"budget {pct(rep['error_budget'], 3)}%)",
        f"input {source}: {rep['hours']} hourly rows, {_ts(rep['first'] - timedelta(hours=1))} .. {_ts(rep['last'])} "
        f"({rep['hours'] / 24:.1f}d of the {rep['window']} window)",
        "note: hourly data, so the 5m and 30m short windows use the latest hour, and `for:` is not modelled",
        f"requests {rep['requests']}, errors {rep['errors']}, error ratio {pct(Fraction(rep['errors'], rep['requests']), 4)}%",
        f"budget consumed {rep['budget_consumed'] * 100:.2f}% (sum of hourly burn rate x 1h / {rep['window']}), "
        f"remaining {rep['budget_remaining'] * 100:.2f}%",
        "burn rate at end: " + "  ".join(f"{w} {v:.2f}x" for w, v in rep["burn_at_end"].items()),
        "alerts that would have fired:",
    ]
    for a in rep["alerts"]:
        resolved = _ts(a["resolved"]) if a["resolved"] else "still firing"
        dur = f"{int((a['resolved'] - a['fired']).total_seconds() // 3600)}h" if a["resolved"] else "-"
        lines.append(f"  {a['tier']:<9} {a['severity']:<6} >{a['factor']}x over {a['long']} and {a['short']}: "
                     f"fired {_ts(a['fired'])}  resolved {resolved}  ({dur}, peak {a['long']} burn "
                     f"{a['peak_long_burn']:.2f}x)")
    if not rep["alerts"]:
        lines.append("  none")
    pages = sum(a["severity"] == "page" for a in rep["alerts"])
    lines.append(f"summary: {len(rep['alerts'])} firing interval(s): {pages} page, {len(rep['alerts']) - pages} "
                 f"ticket; tickets that overlap a page for the same SLO are inhibited in Alertmanager")
    return "\n".join(lines) + "\n"


def report_json(rep: dict) -> dict:
    out = dict(rep)
    out["first"], out["last"] = _ts(rep["first"]), _ts(rep["last"])
    out["alerts"] = [{**a, "fired": _ts(a["fired"]), "resolved": _ts(a["resolved"]) if a["resolved"] else None}
                     for a in rep["alerts"]]
    return out


# ---------------------------------------------------------------- generate

def render_all(services: list[dict], project: Path = PROJECT) -> dict[str, str]:
    """Every generated file: relative path -> content. Pure and deterministic."""
    files: dict[str, str] = {}
    for svc in services:
        name = svc["service"]
        source = f"slo/{name}.json"
        rules = service_rules(svc)
        files[f"prometheus/{name}.rules.yml"] = yaml_doc(rules, source)
        files[f"kubernetes/{name}.prometheusrule.yaml"] = yaml_doc(prometheus_rule(f"slo-{name}", rules), source, True)
        files[f"grafana/{name}.dashboard.json"] = json.dumps(dashboard(svc), indent=2) + "\n"
        for slo in svc["slos"]:
            if slo.get("sample_data"):
                rows = read_hourly_csv(project / slo["sample_data"])
                rep = error_budget_report(rows, slo)
                files[f"reports/{name}-{slo['name']}.txt"] = render_report(rep, name, slo["name"], slo["sample_data"])
    meta = meta_rules()
    files["prometheus/meta.rules.yml"] = yaml_doc(meta, "the built-in Watchdog rule (meta_rules)")
    files["kubernetes/meta.prometheusrule.yaml"] = yaml_doc(prometheus_rule("slo-meta", meta),
                                                            "the built-in Watchdog rule (meta_rules)", True)
    return dict(sorted(files.items()))


def generate(slo_dir: Path, out_dir: Path, check: bool, project: Path = PROJECT) -> tuple[int, list[str]]:
    files = render_all(load_all(slo_dir), project)
    drift: list[str] = []
    existing = {p.relative_to(out_dir).as_posix() for p in out_dir.rglob("*") if p.is_file()} if out_dir.exists() else set()
    for rel, content in files.items():
        path = out_dir / rel
        current = path.read_text() if path.is_file() else None
        if current == content:
            continue
        drift.append(f"{'changed' if current is not None else 'missing'}: {rel}")
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    for rel in sorted(existing - set(files)):
        drift.append(f"stale: {rel}")
        if not check:
            (out_dir / rel).unlink()
    return len(files), drift


def count_rules(services: list[dict]) -> list[str]:
    lines = []
    for svc in services:
        rules = [r for g in service_rules(svc)["groups"] for r in g["rules"]]
        rec = sum("record" in r for r in rules)
        lines.append(f"{svc['service']}: {len(svc['slos'])} SLO(s), {rec} recording rules, "
                     f"{len(rules) - rec} alerts, 1 dashboard")
    return lines


def explain(services: list[dict]) -> list[str]:
    lines = []
    for svc in services:
        for slo in svc["slos"]:
            obj, window = slo["objective"], slo["window"]
            lines.append(f"{svc['service']}/{slo['name']}: objective {dec(obj)}% over {window}, "
                         f"error budget {pct(error_budget(obj), 3)}%")
            for t in sorted((TIERS_BY_NAME[n] for n in slo["alerting"]["tiers"]), key=TIERS.index):
                lines.append(
                    f"  {t.name:<9} {t.severity:<6} burn >{dec(t.factor):>4}x over {t.long:>2} and {t.short:>3}: "
                    f"error ratio > {pct(burn_threshold(t.factor, obj), 3)}%, "
                    f"{pct(budget_consumed(t.factor, t.long, window))}% of budget per {t.long}, "
                    f"empty in {days(time_to_exhaustion(t.factor, window))}")
    return lines


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="slogen", description="SLOs as code: rules, dashboards, error-budget reports")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="write generated/ from slo/*.json")
    g.add_argument("--slo-dir", type=Path, default=PROJECT / "slo")
    g.add_argument("--out", type=Path, default=PROJECT / "generated")
    g.add_argument("--check", action="store_true", help="write nothing; exit 1 if generated/ would change")
    e = sub.add_parser("explain", help="print the burn-rate math per SLO tier")
    e.add_argument("--slo-dir", type=Path, default=PROJECT / "slo")
    r = sub.add_parser("report", help="error-budget report for an hourly good,total CSV")
    r.add_argument("csv", type=Path)
    r.add_argument("--slo", type=Path, required=True, help="SLO file, e.g. slo/checkout-api.json")
    r.add_argument("--name", required=True, help="SLO name in that file, e.g. availability")
    r.add_argument("--format", choices=("text", "json"), default="text")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "generate":
            services = load_all(args.slo_dir)
            n, drift = generate(args.slo_dir, args.out, args.check)
            for line in count_rules(services):
                print(line)
            if args.check:
                for d in drift:
                    print(d)
                print(f"slogen: {n} files, {'up to date' if not drift else f'{len(drift)} out of date'}")
                return 1 if drift else 0
            print(f"slogen: {n} files in {display(args.out)}, {len(drift)} written")
            return 0
        if args.cmd == "explain":
            print("\n".join(explain(load_all(args.slo_dir))))
            return 0
        service = load_service(args.slo)
        slo = next((s for s in service["slos"] if s["name"] == args.name), None)
        if slo is None:
            raise SLOError(f"{args.slo}: no SLO named {args.name!r}")
        rep = error_budget_report(read_hourly_csv(args.csv), slo)
        if args.format == "json":
            print(json.dumps(report_json(rep), indent=2))
        else:
            sys.stdout.write(render_report(rep, service["service"], slo["name"], display(args.csv)))
        return 0
    except SLOError as exc:
        print(f"slogen: error: {exc}", file=sys.stderr)
        return 2


def display(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    sys.exit(main())
