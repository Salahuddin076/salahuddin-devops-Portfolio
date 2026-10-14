#!/usr/bin/env python3
"""RPO/RTO report from AWS Backup job history.

Input: one JSON file holding the output of ``aws backup list-backup-jobs``,
``list-copy-jobs`` and ``list-restore-jobs`` (under ``backup_jobs``,
``copy_jobs`` and ``restore_jobs``), plus a ``resources`` inventory that
maps each resource ARN to a name and a tier (the value of its
``backup-policy`` tag, which the job APIs don't return). Targets come from
``policy/backup-policy.json`` (``targets.<tier>.rpo_hours`` and
``rto_hours``), the same file Terraform builds the plans from.

Per resource:

* **Last backup age**: now minus the creation time of the newest COMPLETED
  backup job, against the tier's RPO target.
* **DR copy age** and **copy lag**: the age of the newest recovery point that
  reached the DR vault, and how long its copy finished after its backup.
* **Last copy**: the state of the most recent copy job.
* **Restore tests**: passed / finished restore-testing jobs. A pass is a
  COMPLETED job whose ValidationStatus is SUCCESSFUL.
* **Worst restore**: the longest COMPLETED restore (test or manual), against
  the tier's RTO target. Restore jobs are tied to a resource through their
  recovery point ARN, via the backup and copy jobs that created it.

Output is a Markdown table plus findings. Exit codes: 0 no gold RPO breach,
1 at least one gold resource breaches its RPO, 2 bad input. Other findings
(failed copies, failed restore tests, RTO breaches) are reported but don't
change the exit code: the gate is deliberately about the one number that
means data loss. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_POLICY = Path(__file__).resolve().parent.parent / "policy" / "backup-policy.json"
GATED_TIER = "gold"
FINISHED_RESTORE_STATES = ("COMPLETED", "FAILED", "ABORTED")


class InputError(Exception):
    """Unreadable or malformed input (exit 2)."""


def parse_time(value: str) -> datetime:
    """Parse the ISO 8601 timestamps the AWS CLI prints (offset or Z)."""
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def hours_between(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 3600


def fmt_hours(hours: float | None) -> str:
    if hours is None:
        return "n/a"
    minutes = int(round(hours * 60))
    return f"{minutes // 60}h{minutes % 60:02d}m"


@dataclass
class ResourceReport:
    name: str
    resource_type: str
    tier: str
    rpo_hours: float
    rto_hours: float
    last_backup_age: float | None = None
    dr_copy_age: float | None = None
    copy_lag: float | None = None
    last_copy_state: str | None = None
    last_copy_message: str | None = None
    tests_passed: int = 0
    tests_finished: int = 0
    worst_restore: float | None = None
    findings: list[str] = field(default_factory=list)

    @property
    def rpo_breach(self) -> bool:
        return self.last_backup_age is None or self.last_backup_age > self.rpo_hours

    @property
    def rto_breach(self) -> bool:
        return self.worst_restore is not None and self.worst_restore > self.rto_hours

    @property
    def status(self) -> str:
        flags = []
        if self.rpo_breach:
            flags.append("RPO BREACH")
        if self.last_copy_state == "FAILED":
            flags.append("COPY FAILED")
        if self.tests_finished and self.tests_passed < self.tests_finished:
            flags.append("RESTORE TEST FAILED")
        if self.rto_breach:
            flags.append("RTO BREACH")
        return ", ".join(flags) if flags else "OK"


def _jobs(data: dict[str, Any], key: str, inner: str) -> list[dict[str, Any]]:
    block = data.get(key, {})
    jobs = block.get(inner, []) if isinstance(block, dict) else block
    if not isinstance(jobs, list):
        raise InputError(f"{key}.{inner} must be a list")
    return jobs


def build_report(data: dict[str, Any], policy: dict[str, Any], now: datetime) -> list[ResourceReport]:
    if not isinstance(data, dict) or not isinstance(data.get("resources"), list):
        raise InputError("job history must be an object with a 'resources' list")
    targets = policy.get("targets")
    if not isinstance(targets, dict):
        raise InputError("policy has no 'targets' object")

    try:
        # "As of" means as of: jobs created after ``now`` are not visible yet.
        backups, copies, restores = (
            [j for j in _jobs(data, key, inner) if parse_time(j["CreationDate"]) <= now]
            for key, inner in (("backup_jobs", "BackupJobs"), ("copy_jobs", "CopyJobs"), ("restore_jobs", "RestoreJobs"))
        )
        # recovery point ARN -> (resource ARN, point creation time)
        point_owner: dict[str, str] = {}
        backup_by_point: dict[str, dict[str, Any]] = {}
        for job in backups:
            if job.get("State") == "COMPLETED" and job.get("RecoveryPointArn"):
                point_owner[job["RecoveryPointArn"]] = job["ResourceArn"]
                backup_by_point[job["RecoveryPointArn"]] = job
        for job in copies:
            if job.get("State") == "COMPLETED" and job.get("DestinationRecoveryPointArn"):
                point_owner[job["DestinationRecoveryPointArn"]] = job["ResourceArn"]

        reports = []
        for res in data["resources"]:
            arn, tier = res["arn"], res["tier"]
            if tier not in targets:
                raise InputError(f"resource {res.get('name', arn)}: tier {tier!r} has no target in the policy")
            report = ResourceReport(
                name=res.get("name", arn),
                resource_type=res.get("type", "?"),
                tier=tier,
                rpo_hours=float(targets[tier]["rpo_hours"]),
                rto_hours=float(targets[tier]["rto_hours"]),
            )

            done = [j for j in backups if j["ResourceArn"] == arn and j.get("State") == "COMPLETED"]
            if done:
                newest = max(done, key=lambda j: parse_time(j["CreationDate"]))
                report.last_backup_age = hours_between(now, parse_time(newest["CreationDate"]))

            mine = sorted((j for j in copies if j["ResourceArn"] == arn), key=lambda j: parse_time(j["CreationDate"]))
            if mine:
                report.last_copy_state = mine[-1].get("State")
                report.last_copy_message = mine[-1].get("StatusMessage")
            copied = [j for j in mine if j.get("State") == "COMPLETED" and j.get("SourceRecoveryPointArn") in backup_by_point]
            if copied:
                best = max(copied, key=lambda j: parse_time(backup_by_point[j["SourceRecoveryPointArn"]]["CreationDate"]))
                source = backup_by_point[best["SourceRecoveryPointArn"]]
                report.dr_copy_age = hours_between(now, parse_time(source["CreationDate"]))
                report.copy_lag = hours_between(parse_time(best["CompletionDate"]), parse_time(source["CompletionDate"]))

            for job in restores:
                if point_owner.get(job.get("RecoveryPointArn")) != arn:
                    continue
                status = job.get("Status")
                if status == "COMPLETED" and job.get("CompletionDate"):
                    duration = hours_between(parse_time(job["CompletionDate"]), parse_time(job["CreationDate"]))
                    report.worst_restore = max(report.worst_restore or 0.0, duration)
                if (job.get("CreatedBy") or {}).get("RestoreTestingPlanArn") and status in FINISHED_RESTORE_STATES:
                    report.tests_finished += 1
                    if status == "COMPLETED" and job.get("ValidationStatus") == "SUCCESSFUL":
                        report.tests_passed += 1

            _findings(report, tier in policy.get("copy_required_tiers", [GATED_TIER]))
            reports.append(report)
    except (KeyError, TypeError, ValueError) as exc:
        raise InputError(f"malformed job record: {type(exc).__name__}: {exc}") from exc
    return reports


def _findings(r: ResourceReport, copy_required: bool) -> None:
    if r.last_backup_age is None:
        r.findings.append(f"{r.name}: no successful backup on record (RPO {fmt_hours(r.rpo_hours)})")
    elif r.rpo_breach:
        r.findings.append(f"{r.name}: last successful backup {fmt_hours(r.last_backup_age)} ago exceeds RPO {fmt_hours(r.rpo_hours)}")
    if r.last_copy_state == "FAILED":
        r.findings.append(f"{r.name}: latest copy to DR FAILED: {r.last_copy_message or 'no message'}")
    if copy_required and r.dr_copy_age is not None and r.dr_copy_age > r.rpo_hours:
        r.findings.append(f"{r.name}: newest DR recovery point is {fmt_hours(r.dr_copy_age)} old, beyond RPO {fmt_hours(r.rpo_hours)} for a regional loss")
    if copy_required and r.dr_copy_age is None:
        r.findings.append(f"{r.name}: no recovery point in the DR vault")
    if r.tests_finished and r.tests_passed < r.tests_finished:
        r.findings.append(f"{r.name}: {r.tests_finished - r.tests_passed} of {r.tests_finished} restore tests failed")
    if r.tests_finished == 0:
        r.findings.append(f"{r.name}: no restore test on record, RTO unproven")
    if r.rto_breach:
        r.findings.append(f"{r.name}: worst restore {fmt_hours(r.worst_restore)} exceeds RTO {fmt_hours(r.rto_hours)}")


def render_markdown(reports: list[ResourceReport], now: datetime) -> str:
    lines = [
        f"## RPO/RTO report (as of {now.strftime('%Y-%m-%dT%H:%M:%SZ')})",
        "",
        "| Resource | Type | Tier | Last backup age | RPO | DR copy age | Copy lag | Last copy | Restore tests | Worst restore | RTO | Status |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        tests = f"{r.tests_passed}/{r.tests_finished} ({100 * r.tests_passed // r.tests_finished}%)" if r.tests_finished else "none"
        lines.append(
            f"| {r.name} | {r.resource_type} | {r.tier} | {fmt_hours(r.last_backup_age)} | {fmt_hours(r.rpo_hours)} "
            f"| {fmt_hours(r.dr_copy_age)} | {fmt_hours(r.copy_lag)} | {r.last_copy_state or 'none'} | {tests} "
            f"| {fmt_hours(r.worst_restore)} | {fmt_hours(r.rto_hours)} | {r.status} |"
        )
    findings = [f for r in reports for f in r.findings]
    lines += ["", "### Findings", ""]
    lines += [f"- {f}" for f in findings] if findings else ["- none"]
    breaches = [r.name for r in reports if r.tier == GATED_TIER and r.rpo_breach]
    lines += [""]
    if breaches:
        lines.append(f"Result: FAIL ({len(breaches)} {GATED_TIER} resource(s) breach RPO: {', '.join(breaches)})")
    else:
        lines.append(f"Result: PASS (no {GATED_TIER} resource breaches RPO)")
    return "\n".join(lines) + "\n"


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except OSError as exc:
        raise InputError(f"cannot read {label} {path}: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"{label} {path}: invalid JSON: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RPO/RTO report from AWS Backup job history (Markdown).")
    parser.add_argument("jobs", help="job history JSON (see sample-data/jobs.json)")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY), help="backup policy with targets (default: policy/backup-policy.json)")
    parser.add_argument("--now", help="evaluate as of this ISO 8601 time (default: the file's as_of, else the current time)")
    parser.add_argument("-o", "--output", help="also write the Markdown to this file")
    args = parser.parse_args(argv)

    try:
        data = _load_json(Path(args.jobs), "job history")
        policy = _load_json(Path(args.policy), "policy")
        now_text = args.now or (data.get("as_of") if isinstance(data, dict) else None)
        now = parse_time(now_text) if now_text else datetime.now(timezone.utc)
        reports = build_report(data, policy, now)
    except (InputError, ValueError) as exc:
        print(f"rpo_rto_report: error: {exc}", file=sys.stderr)
        return 2

    markdown = render_markdown(reports, now)
    sys.stdout.write(markdown)
    if args.output:
        Path(args.output).write_text(markdown)
    return 1 if any(r.tier == GATED_TIER and r.rpo_breach for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
