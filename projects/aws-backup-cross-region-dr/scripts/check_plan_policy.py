#!/usr/bin/env python3
"""Gate the backup policy (policy/backup-policy.json) before Terraform sees it.

The policy file is the single source of truth: Terraform reads it with
``jsondecode(file())`` and passes the plans and vault-lock settings to the
backup-dr module. This checker runs in CI on every change and catches the
mistakes that ``terraform validate`` can't see or that only fail at backup
time, days after the apply:

  BKP-001  every rule in a copy-required tier (gold) copies to the DR vault
  BKP-002  retention meets the tier's minimum, in both vaults
  BKP-003  cold storage + 90 days <= delete, in both vaults
  BKP-004  the schedule is a valid AWS cron expression, at most hourly
  BKP-005  vault lock settings are coherent (mode, min <= max, grace period)
  BKP-006  every retention sits inside the vault lock range
  BKP-007  continuous backup (PITR) rules keep <= 35 days and no cold storage

Exit codes: 0 no findings, 1 findings, 2 unreadable or malformed policy.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_POLICY = Path(__file__).resolve().parent.parent / "policy" / "backup-policy.json"

COLD_TO_DELETE_MIN_DAYS = 90  # AWS Backup's minimum stay in cold storage
CONTINUOUS_MAX_DAYS = 35  # continuous backup retention ceiling
COMPLIANCE_MIN_GRACE_DAYS = 3  # ChangeableForDays minimum for compliance mode

CHECKS = {
    "BKP-001": "Every rule in a copy-required tier has a cross-region copy to the DR vault",
    "BKP-002": "Retention meets the tier minimum (primary and DR copies)",
    "BKP-003": "Cold storage transition is at least 90 days before deletion",
    "BKP-004": "Schedule is a valid AWS cron expression, at most once per hour",
    "BKP-005": "Vault lock: valid mode, 1 <= min <= max, compliance grace period >= 3 days",
    "BKP-006": "Every retention is inside the vault lock [min, max] range",
    "BKP-007": "Continuous backup rules keep <= 35 days and use no cold storage",
}


class PolicyError(Exception):
    """The policy file is structurally invalid (exit 2)."""


@dataclass(frozen=True)
class Finding:
    check: str
    where: str
    message: str


# --------------------------------------------------------------------------
# AWS cron: cron(Minutes Hours Day-of-month Month Day-of-week Year)
# --------------------------------------------------------------------------

MONTHS = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}
DAYS = {d: i for i, d in enumerate("SUN MON TUE WED THU FRI SAT".split(), 1)}
FIELDS = (
    ("minutes", 0, 59, {}),
    ("hours", 0, 23, {}),
    ("day-of-month", 1, 31, {}),
    ("month", 1, 12, MONTHS),
    ("day-of-week", 1, 7, DAYS),
    ("year", 1970, 2199, {}),
)
CRON_RE = re.compile(r"^cron\((.*)\)$")


def _value(token: str, lo: int, hi: int, names: dict[str, int]) -> int:
    if token.upper() in names:
        return names[token.upper()]
    if not token.isdigit():
        raise ValueError(f"{token!r} is not a number")
    value = int(token)
    if not lo <= value <= hi:
        raise ValueError(f"{value} outside {lo}-{hi}")
    return value


def _check_field(text: str, name: str, lo: int, hi: int, names: dict[str, int]) -> None:
    for part in text.split(","):
        if name == "day-of-month" and re.fullmatch(r"L|LW|\d{1,2}W", part):
            if part.endswith("W") and part != "LW":
                _value(part[:-1], lo, hi, {})
            continue
        if name == "day-of-week" and re.fullmatch(r"L|\dL|[A-Za-z]{3}L|\d#[1-5]|[A-Za-z]{3}#[1-5]", part):
            _value(re.split(r"[#L]", part)[0] or "1", lo, hi, names)
            continue
        base, _, step = part.partition("/")
        if step and (not step.isdigit() or int(step) == 0):
            raise ValueError(f"bad step in {part!r}")
        if base == "*":
            continue
        start, _, end = base.partition("-")
        first = _value(start, lo, hi, names)
        if end:
            last = _value(end, lo, hi, names)
            if last < first:
                raise ValueError(f"range {base!r} runs backwards")


def cron_error(expression: Any) -> str | None:
    """Return why ``expression`` is not a valid AWS Backup cron, or None."""
    if not isinstance(expression, str):
        return "schedule is not a string"
    match = CRON_RE.match(expression.strip())
    if not match:
        return "schedule must look like cron(min hour day-of-month month day-of-week year)"
    fields = match.group(1).split()
    if len(fields) != 6:
        return f"cron needs 6 fields, got {len(fields)}"
    dom, dow = fields[2], fields[4]
    if (dom == "?") == (dow == "?"):
        return "exactly one of day-of-month and day-of-week must be '?'"
    for text, (name, lo, hi, names) in zip(fields, FIELDS):
        if text == "?" and name in ("day-of-month", "day-of-week"):
            continue
        try:
            _check_field(text, name, lo, hi, names)
        except ValueError as exc:
            return f"{name} field {text!r}: {exc}"
    if not fields[0].isdigit():
        return "minutes must be a single value: AWS Backup runs a rule at most once per hour"
    return None


# --------------------------------------------------------------------------
# Policy checks
# --------------------------------------------------------------------------


def _int_or_none(rule: dict[str, Any], key: str, where: str) -> int | None:
    value = rule.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise PolicyError(f"{where}: {key} must be a positive integer or null, got {value!r}")
    return value


def _require(obj: dict[str, Any], key: str, kind: type, where: str) -> Any:
    if key not in obj or not isinstance(obj[key], kind):
        raise PolicyError(f"{where}: missing or invalid {key!r} (expected {kind.__name__})")
    return obj[key]


def evaluate(policy: dict[str, Any]) -> tuple[list[Finding], dict[str, int]]:
    if not isinstance(policy, dict):
        raise PolicyError("policy must be a JSON object")
    plans = _require(policy, "plans", dict, "policy")
    lock = _require(policy, "vault_lock", dict, "policy")
    minimums = _require(policy, "retention_minimums_days", dict, "policy")
    copy_tiers = set(policy.get("copy_required_tiers", ["gold"]))
    findings: list[Finding] = []

    # BKP-005 vault lock coherence
    mode = lock.get("mode")
    lock_min, lock_max = lock.get("min_retention_days"), lock.get("max_retention_days")
    lock_ok = isinstance(lock_min, int) and isinstance(lock_max, int)
    if mode not in ("governance", "compliance"):
        findings.append(Finding("BKP-005", "vault_lock", f"mode must be governance or compliance, got {mode!r}"))
    if not lock_ok:
        findings.append(Finding("BKP-005", "vault_lock", "min_retention_days and max_retention_days must be integers"))
    else:
        if lock_min < 1:
            findings.append(Finding("BKP-005", "vault_lock", f"min_retention_days {lock_min} must be >= 1"))
        if lock_min > lock_max:
            findings.append(Finding("BKP-005", "vault_lock", f"min_retention_days {lock_min} > max_retention_days {lock_max}"))
    if mode == "compliance":
        grace = lock.get("changeable_for_days")
        if not isinstance(grace, int) or grace < COMPLIANCE_MIN_GRACE_DAYS:
            findings.append(Finding("BKP-005", "vault_lock", f"compliance mode needs changeable_for_days >= {COMPLIANCE_MIN_GRACE_DAYS}, got {grace!r}"))

    rule_count = 0
    for tier, plan in plans.items():
        rules = _require(plan, "rules", list, f"plans.{tier}")
        tier_minimums = minimums.get(tier)
        if not isinstance(tier_minimums, dict):
            raise PolicyError(f"retention_minimums_days has no entry for tier {tier!r}")
        names = [r.get("name") for r in rules if isinstance(r, dict)]
        if len(set(names)) != len(names):
            raise PolicyError(f"plans.{tier}: duplicate rule names")
        for rule in rules:
            rule_count += 1
            if not isinstance(rule, dict):
                raise PolicyError(f"plans.{tier}: every rule must be an object")
            name = _require(rule, "name", str, f"plans.{tier}")
            where = f"{tier}/{name}"
            frequency = _require(rule, "frequency", str, where)
            delete = _int_or_none(rule, "delete_after_days", where)
            if delete is None:
                raise PolicyError(f"{where}: delete_after_days is required")
            cold = _int_or_none(rule, "cold_storage_after_days", where)
            copy = rule.get("copy_to_dr") is True
            dr_delete = _int_or_none(rule, "dr_delete_after_days", where)
            dr_cold = _int_or_none(rule, "dr_cold_storage_after_days", where)
            if copy and dr_delete is None:
                raise PolicyError(f"{where}: copy_to_dr needs dr_delete_after_days")

            # BKP-001
            if tier in copy_tiers and not copy:
                findings.append(Finding("BKP-001", where, "no cross-region copy to the DR vault (copy_to_dr is not true)"))

            # BKP-002
            minimum = tier_minimums.get(frequency)
            if not isinstance(minimum, int):
                raise PolicyError(f"retention_minimums_days.{tier} has no {frequency!r} entry")
            if delete < minimum:
                findings.append(Finding("BKP-002", where, f"primary retention {delete}d < minimum {minimum}d for {tier} {frequency}"))
            if copy and dr_delete < minimum:
                findings.append(Finding("BKP-002", where, f"DR copy retention {dr_delete}d < minimum {minimum}d for {tier} {frequency}"))

            # BKP-003
            for label, c, d in (("primary", cold, delete), ("DR copy", dr_cold, dr_delete if copy else None)):
                if c is not None and d is not None and c + COLD_TO_DELETE_MIN_DAYS > d:
                    findings.append(Finding("BKP-003", where, f"{label}: cold storage at {c}d + {COLD_TO_DELETE_MIN_DAYS}d = {c + COLD_TO_DELETE_MIN_DAYS}d > delete at {d}d"))

            # BKP-004
            error = cron_error(rule.get("schedule"))
            if error:
                findings.append(Finding("BKP-004", where, f"{rule.get('schedule')!r}: {error}"))

            # BKP-006 (only meaningful when the lock itself is coherent)
            if lock_ok and lock_min <= lock_max:
                for label, d in (("primary", delete), ("DR copy", dr_delete if copy else None)):
                    if d is not None and not lock_min <= d <= lock_max:
                        findings.append(Finding("BKP-006", where, f"{label} retention {d}d outside vault lock range {lock_min}-{lock_max}d: backup jobs would fail"))

            # BKP-007
            if rule.get("continuous") is True:
                if delete > CONTINUOUS_MAX_DAYS:
                    findings.append(Finding("BKP-007", where, f"continuous backup retention {delete}d > {CONTINUOUS_MAX_DAYS}d"))
                if cold is not None:
                    findings.append(Finding("BKP-007", where, "continuous backup rule must not transition to cold storage"))

    return findings, {"plans": len(plans), "rules": rule_count}


def load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except OSError as exc:
        raise PolicyError(f"cannot read {path}: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyError(f"{path}: invalid JSON: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("policy", nargs="?", default=str(DEFAULT_POLICY), help="policy JSON (default: policy/backup-policy.json)")
    parser.add_argument("--list-checks", action="store_true", help="print the check catalogue and exit")
    args = parser.parse_args(argv)

    if args.list_checks:
        for check_id, text in CHECKS.items():
            print(f"{check_id}  {text}")
        return 0

    try:
        findings, stats = evaluate(load(Path(args.policy)))
    except PolicyError as exc:
        print(f"check_plan_policy: error: {exc}", file=sys.stderr)
        return 2

    print(f"check_plan_policy: {args.policy}: {stats['plans']} plans, {stats['rules']} rules, {len(CHECKS)} checks")
    failed = {f.check for f in findings}
    for check_id, text in CHECKS.items():
        print(f"{'FAIL' if check_id in failed else 'PASS'} {check_id}  {text}")
        for finding in (f for f in findings if f.check == check_id):
            print(f"       {finding.where}: {finding.message}")
    print(f"Summary: {len(findings)} finding(s) in {len(failed)} check(s). Result: {'FAIL' if findings else 'PASS'}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
