#!/usr/bin/env python3
"""Check the spoke VPC address plan (policy/cidr-plan.json).

The plan is a small IPAM-like document: ``allowed_ranges`` that spokes are
carved from, a required ``spoke_prefix_length``, ``reserved`` blocks (egress
VPC, future on-premises range) and ``spokes`` (name -> cidr, environment,
account). The Terraform environments read the same file, so this check runs
on exactly what would be deployed.

Rules:
  CIDR-001  every CIDR parses and has no host bits set
  CIDR-002  every CIDR is inside RFC 1918 and inside allowed_ranges
  CIDR-003  every spoke has the required prefix length
  CIDR-004  no two blocks (spokes and reserved) overlap
  CIDR-005  every spoke environment is prod, nonprod or shared

Exit codes: 0 plan is valid, 1 findings, 2 unreadable plan.

Standard library only.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DEFAULT_PLAN = PROJECT / "policy" / "cidr-plan.json"

RFC1918 = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
ENVIRONMENTS = ("prod", "nonprod", "shared")

Network = ipaddress.IPv4Network


class InputError(Exception):
    """Unusable plan: exit code 2."""


@dataclass
class Finding:
    rule_id: str
    subject: str
    message: str


@dataclass
class Block:
    name: str
    kind: str          # "spoke" or "reserved"
    cidr: str
    environment: str | None
    network: Network | None


@dataclass
class Report:
    blocks: list[Block]
    findings: list[Finding]
    next_free: Network | None

    @property
    def failed(self) -> bool:
        return bool(self.findings)


def load_plan(path: Path) -> dict:
    try:
        plan = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"cannot read plan {path}: {exc}") from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("spokes"), dict):
        raise InputError(f"{path}: plan must be an object with a 'spokes' map")
    return plan


def in_rfc1918(net: Network) -> bool:
    return any(net.subnet_of(r) for r in RFC1918)


def check(plan: dict) -> Report:
    findings: list[Finding] = []
    blocks: list[Block] = []
    prefix = plan.get("spoke_prefix_length")
    try:
        allowed = [ipaddress.ip_network(r) for r in plan.get("allowed_ranges", [str(r) for r in RFC1918])]
    except ValueError as exc:
        raise InputError(f"bad allowed_ranges: {exc}") from exc

    entries = [(n, "reserved", {"cidr": c}) for n, c in (plan.get("reserved") or {}).items()]
    entries += [(n, "spoke", s) for n, s in plan["spokes"].items()]

    for name, kind, spec in entries:
        cidr = str(spec.get("cidr", ""))
        env = spec.get("environment") if kind == "spoke" else None
        net: Network | None = None
        try:
            net = ipaddress.IPv4Network(cidr, strict=True)
        except ValueError as exc:
            findings.append(Finding("CIDR-001", name, f"{cidr!r} is not a valid network: {exc}"))
        if net is not None:
            if not in_rfc1918(net):
                findings.append(Finding("CIDR-002", name, f"{cidr} is outside RFC 1918"))
            elif not any(net.subnet_of(a) for a in allowed):
                findings.append(Finding("CIDR-002", name, f"{cidr} is outside allowed_ranges {[str(a) for a in allowed]}"))
            if kind == "spoke" and prefix is not None and net.prefixlen != prefix:
                findings.append(Finding("CIDR-003", name, f"{cidr} is a /{net.prefixlen}, spokes must be /{prefix}"))
        if kind == "spoke" and env not in ENVIRONMENTS:
            findings.append(Finding("CIDR-005", name, f"environment {env!r} is not one of {', '.join(ENVIRONMENTS)}"))
        blocks.append(Block(name, kind, cidr, env, net))

    valid = [b for b in blocks if b.network is not None]
    for i, a in enumerate(valid):
        for b in valid[i + 1:]:
            if a.network.overlaps(b.network):
                findings.append(Finding("CIDR-004", f"{a.name}/{b.name}", f"{a.cidr} overlaps {b.cidr}"))

    next_free = None
    if prefix is not None:
        used = [b.network for b in valid]
        for rng in allowed:
            if rng.prefixlen > prefix:
                continue
            next_free = next((c for c in rng.subnets(new_prefix=prefix)
                              if not any(c.overlaps(u) for u in used)), None)
            if next_free is not None:
                break
    return Report(blocks, findings, next_free)


def format_text(report: Report, plan_path: Path) -> str:
    spokes = [b for b in report.blocks if b.kind == "spoke"]
    lines = [f"cidr_plan: {plan_path.name}: {len(spokes)} spokes, {len(report.blocks) - len(spokes)} reserved"]
    for b in report.blocks:
        label = b.environment if b.kind == "spoke" else "reserved"
        lines.append(f"  {b.name:<20} {b.cidr:<18} {label}")
    for f in report.findings:
        lines.append(f"FAIL {f.rule_id}  {f.subject}: {f.message}")
    if report.next_free is not None:
        lines.append(f"Next free spoke block: {report.next_free}")
    lines.append(f"Summary: {len(report.findings)} finding(s). Result: {'FAIL' if report.failed else 'PASS'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the spoke CIDR plan for overlaps and RFC 1918 compliance.")
    parser.add_argument("plan", nargs="?", type=Path, default=DEFAULT_PLAN, help="plan JSON (default: policy/cidr-plan.json)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    try:
        report = check(load_plan(args.plan))
    except InputError as exc:
        print(f"cidr_plan: error: {exc}", file=sys.stderr)
        return 2
    print(format_text(report, args.plan))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
