#!/usr/bin/env python3
"""Lint per-environment blue/green settings before Terraform reads them.

The files in config/environments/*.json are the single source of truth: the
Terraform environment roots `jsondecode()` the same file, so what this lint
passes is exactly what gets deployed.

Rules:
  BG000  file is valid JSON with the required keys and types
  BG001  prod must not use an all-at-once deployment config
  BG002  prod must have CloudWatch alarms configured (enabled, thresholds > 0)
  BG003  auto-rollback must be on for DEPLOYMENT_FAILURE, and for
         DEPLOYMENT_STOP_ON_ALARM whenever alarms are enabled
  BG004  termination_wait_minutes must be > 0 (blue stays up to roll back to)
  BG005  test listener CIDRs must be non-empty, valid, and never 0.0.0.0/0 or ::/0
  BG006  deployment_config_name must be a known CodeDeploy ECS config
  BG007  manual reroute needs reroute_wait_minutes between 1 and 2880

Exit codes: 0 all files pass, 1 at least one fails, 2 usage error.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from traffic_shift_sim import KNOWN_CONFIGS, SimulationError, parse_config

PROJECT = Path(__file__).resolve().parent.parent
DEFAULT_GLOB = "config/environments/*.json"
PROD_NAMES = {"prod", "production"}
REQUIRED_EVENTS = ("DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM")

# key -> expected type(s); nested dicts are checked one level down.
SCHEMA: dict[str, object] = {
    "environment": str,
    "host_header": str,
    "test_listener_port": int,
    "test_listener_cidrs": list,
    "deployment_config_name": str,
    "manual_reroute": bool,
    "reroute_wait_minutes": int,
    "termination_wait_minutes": int,
    "auto_rollback": {"enabled": bool, "events": list},
    "alarms": {
        "enabled": bool,
        "target_5xx_threshold": (int, float),
        "p95_latency_threshold_seconds": (int, float),
        "evaluation_periods": int,
    },
    "task": {"cpu": int, "memory": int, "cpu_architecture": str, "log_retention_days": int},
    "capacity": {"on_demand_base": int, "on_demand_weight": int, "spot_weight": int},
    "scaling": {
        "desired_count": int,
        "min_capacity": int,
        "max_capacity": int,
        "cpu_target_percent": (int, float),
        "requests_per_target": int,
    },
    "deregistration_delay_seconds": int,
    "smoke": {"requests": int, "p95_budget_ms": (int, float), "request_timeout_seconds": (int, float)},
}


@dataclass
class Report:
    path: str
    findings: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def add(self, rule: str, message: str) -> None:
        self.findings.append((rule, message))


def _type_ok(value: object, expected: object) -> bool:
    # bool is a subclass of int; never accept it where a number is expected.
    if isinstance(value, bool) and expected is not bool and expected != (bool,):
        return False
    return isinstance(value, expected)  # type: ignore[arg-type]


def _check_schema(data: object, report: Report) -> bool:
    if not isinstance(data, dict):
        report.add("BG000", "top level must be a JSON object")
        return False
    ok = True
    for key, expected in SCHEMA.items():
        if key not in data:
            report.add("BG000", f"missing required key '{key}'")
            ok = False
            continue
        value = data[key]
        if isinstance(expected, dict):
            if not isinstance(value, dict):
                report.add("BG000", f"'{key}' must be an object")
                ok = False
                continue
            for sub, sub_type in expected.items():
                if sub not in value:
                    report.add("BG000", f"missing required key '{key}.{sub}'")
                    ok = False
                elif not _type_ok(value[sub], sub_type):
                    report.add("BG000", f"'{key}.{sub}' has the wrong type")
                    ok = False
        elif not _type_ok(value, expected):
            report.add("BG000", f"'{key}' has the wrong type")
            ok = False
    return ok


def check_settings(data: object, path: str = "<memory>") -> Report:
    report = Report(path)
    if not _check_schema(data, report):
        return report
    assert isinstance(data, dict)
    env = data["environment"].strip().lower()
    is_prod = env in PROD_NAMES
    config_name = data["deployment_config_name"]

    try:
        shift = parse_config(config_name)
    except SimulationError:
        shift = None
    if config_name not in KNOWN_CONFIGS:
        report.add("BG006", f"deployment_config_name '{config_name}' is not one of {', '.join(KNOWN_CONFIGS)}")

    if is_prod and shift is not None and shift.kind == "all_at_once":
        report.add("BG001", f"prod uses '{config_name}'; use a canary or linear config so alarms can stop a partial shift")

    alarms = data["alarms"]
    if is_prod:
        if not alarms["enabled"]:
            report.add("BG002", "prod must have alarms.enabled = true (5xx and p95 latency on the green target group)")
        else:
            for key in ("target_5xx_threshold", "p95_latency_threshold_seconds", "evaluation_periods"):
                if alarms[key] <= 0:
                    report.add("BG002", f"prod alarms.{key} must be > 0, got {alarms[key]}")

    rollback = data["auto_rollback"]
    events = set(rollback["events"])
    if not rollback["enabled"]:
        report.add("BG003", "auto_rollback.enabled must be true")
    else:
        if "DEPLOYMENT_FAILURE" not in events:
            report.add("BG003", "auto_rollback.events must include DEPLOYMENT_FAILURE")
        if alarms["enabled"] and "DEPLOYMENT_STOP_ON_ALARM" not in events:
            report.add("BG003", "alarms are enabled but auto_rollback.events lacks DEPLOYMENT_STOP_ON_ALARM")
        unknown = sorted(events - set(REQUIRED_EVENTS) - {"DEPLOYMENT_STOP_ON_REQUEST"})
        if unknown:
            report.add("BG003", f"unknown auto_rollback.events: {', '.join(map(str, unknown))}")

    if data["termination_wait_minutes"] <= 0:
        report.add("BG004", f"termination_wait_minutes must be > 0, got {data['termination_wait_minutes']}; "
                            "blue would be gone before anyone could roll back")

    cidrs = data["test_listener_cidrs"]
    if not cidrs:
        report.add("BG005", "test_listener_cidrs is empty; the hook Lambda (via NAT) and testers need an allowed range")
    for cidr in cidrs:
        try:
            network = ipaddress.ip_network(str(cidr), strict=True)
        except ValueError:
            report.add("BG005", f"test_listener_cidrs entry {cidr!r} is not a valid CIDR")
            continue
        if network.prefixlen == 0:
            report.add("BG005", f"test listener open to the internet ({cidr}); restrict it to known ranges")

    if data["manual_reroute"] and not 1 <= data["reroute_wait_minutes"] <= 2880:
        report.add("BG007", f"manual_reroute needs reroute_wait_minutes in 1..2880, got {data['reroute_wait_minutes']}")

    return report


def check_file(path: Path) -> Report:
    display = str(path)
    try:
        data = json.loads(path.read_text())
    except OSError as exc:
        report = Report(display)
        report.add("BG000", f"cannot read: {exc.strerror or exc}")
        return report
    except json.JSONDecodeError as exc:
        report = Report(display)
        report.add("BG000", f"not valid JSON: line {exc.lineno} column {exc.colno}: {exc.msg}")
        return report
    return check_settings(data, display)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint blue/green environment settings.")
    parser.add_argument("files", nargs="*", help=f"settings files (default: {DEFAULT_GLOB})")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if args.files:
        paths = [Path(f) for f in args.files]
    else:
        paths = sorted(PROJECT.glob(DEFAULT_GLOB))
        paths = [p.relative_to(PROJECT) if Path.cwd() == PROJECT else p for p in paths]
    if not paths:
        print("error: no settings files found", file=sys.stderr)
        return 2

    reports = [check_file(p) for p in paths]
    passed = sum(r.ok for r in reports)
    if args.json:
        print(json.dumps([{"path": r.path, "ok": r.ok,
                           "findings": [{"rule": a, "message": b} for a, b in r.findings]}
                          for r in reports], indent=2))
    else:
        for r in reports:
            print(f"{'PASS' if r.ok else 'FAIL'} {r.path}")
            for rule, message in r.findings:
                print(f"  [{rule}] {message}")
        print(f"{passed}/{len(reports)} environment file(s) passed")
    return 0 if passed == len(reports) else 1


if __name__ == "__main__":
    sys.exit(main())
