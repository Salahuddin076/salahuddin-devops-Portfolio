"""Command-line interface: ``python3 -m aiops <command> [options]``.

Exit codes: 0 success, 1 input/usage error, 2 argparse usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import generator, proposals_store, report
from .anomaly import AnomalyConfig
from .audit import AuditLog, RemediationNotAllowed
from .correlation import CorrelationConfig
from .io import InputError, read_alerts, read_deploys, read_logs
from .pipeline import PipelineConfig, run as run_pipeline
from .remediation import RemediationConfig

DEFAULT_INPUT = "sample-data"
DEFAULT_OUT = "out"


def _add_input_opts(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("input")
    g.add_argument("--input", default=DEFAULT_INPUT, help="directory with logs/deploys/alerts "
                   "JSONL files (default: %(default)s)")
    g.add_argument("--logs", help="logs JSONL (overrides --input)")
    g.add_argument("--deploys", help="deploy events JSONL (overrides --input)")
    g.add_argument("--alerts", help="alerts JSONL (overrides --input)")


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    base = Path(args.input)
    return (
        Path(args.logs) if args.logs else base / "logs.jsonl",
        Path(args.deploys) if args.deploys else base / "deploys.jsonl",
        Path(args.alerts) if args.alerts else base / "alerts.jsonl",
    )


def _add_detection_opts(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("anomaly detection")
    g.add_argument("--window-minutes", type=int, default=AnomalyConfig().window_minutes)
    g.add_argument("--baseline-windows", type=int, default=AnomalyConfig().baseline_windows)
    g.add_argument("--z-threshold", type=float, default=AnomalyConfig().z_threshold)
    g.add_argument("--min-events", type=int, default=AnomalyConfig().min_events)
    g.add_argument("--correlation-window-minutes", type=int, default=CorrelationConfig().window_minutes)


def _add_llm_opts(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("summarization")
    g.add_argument("--use-llm", action="store_true",
                   help="enable the optional LLM summary step (default provider is a no-op: "
                        "still produces the template summary, zero network calls)")
    g.add_argument("--token-budget", type=int, default=400)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m aiops",
        description="Deterministic log-anomaly detection with guardrailed, human-approved remediation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="write deterministic synthetic sample data")
    p.add_argument("--out", default=DEFAULT_INPUT)
    p.add_argument("--seed", type=int, default=11)

    p = sub.add_parser("run", help="run the full pipeline: analyze, correlate, summarize, propose")
    _add_input_opts(p)
    _add_detection_opts(p)
    _add_llm_opts(p)
    p.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    p.add_argument("--out", default=DEFAULT_OUT, help="directory for audit.jsonl and proposals.json")

    p = sub.add_parser("approve", help="approve a pending proposal (writes to the audit log)")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--id", required=True, dest="proposal_id")
    p.add_argument("--actor", required=True, help="the human approving the action, e.g. an email or username")

    p = sub.add_parser("reject", help="reject a pending proposal (writes to the audit log)")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--id", required=True, dest="proposal_id")
    p.add_argument("--actor", required=True)
    p.add_argument("--reason", default="")

    p = sub.add_parser("audit", help="print the append-only audit log")
    p.add_argument("--out", default=DEFAULT_OUT)

    return parser


def _pipeline_config(args: argparse.Namespace) -> PipelineConfig:
    return PipelineConfig(
        anomaly=AnomalyConfig(
            window_minutes=args.window_minutes,
            baseline_windows=args.baseline_windows,
            z_threshold=args.z_threshold,
            min_events=args.min_events,
        ),
        correlation=CorrelationConfig(window_minutes=args.correlation_window_minutes),
        remediation=RemediationConfig(),
    )


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "generate":
        paths = generator.generate(args.out, seed=args.seed)
        for name, path in paths.items():
            print(f"wrote {name}: {path}")
        return 0

    out_dir = Path(args.out)
    audit_path = out_dir / "audit.jsonl"
    proposals_path = out_dir / "proposals.json"

    if args.command == "run":
        logs_path, deploys_path, alerts_path = _paths(args)
        logs = read_logs(logs_path)
        deploys = read_deploys(deploys_path)
        alerts = read_alerts(alerts_path)
        config = _pipeline_config(args)
        audit_log = AuditLog(audit_path)
        result = run_pipeline(logs, deploys, alerts, config=config, audit_log=audit_log)
        proposals_store.write(proposals_path, list(result.proposals))

        if args.format == "json":
            print(report.to_json(result))
        elif args.format == "markdown":
            print(report.to_markdown(result), end="")
        else:
            print(report.to_text(result), end="")
        print(f"wrote {audit_path}", file=sys.stderr)
        print(f"wrote {proposals_path}", file=sys.stderr)
        return 0

    if args.command == "approve":
        record = proposals_store.find(proposals_path, args.proposal_id)
        if record is None:
            raise InputError(f"no pending proposal {args.proposal_id!r} in {proposals_path}")
        audit_log = AuditLog(audit_path)
        try:
            audit_log.approve_fields(
                proposal_id=record["id"], service=record["service"], action=record["action"],
                allowed=record["allowed"], actor=args.actor,
            )
        except RemediationNotAllowed as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        proposals_store.set_status(proposals_path, args.proposal_id, "approved")
        print(f"approved {args.proposal_id} ({record['action']}) by {args.actor}; appended to {audit_path}")
        return 0

    if args.command == "reject":
        record = proposals_store.find(proposals_path, args.proposal_id)
        if record is None:
            raise InputError(f"no pending proposal {args.proposal_id!r} in {proposals_path}")
        audit_log = AuditLog(audit_path)
        audit_log.reject_fields(
            proposal_id=record["id"], service=record["service"], action=record["action"],
            actor=args.actor, reason=args.reason,
        )
        proposals_store.set_status(proposals_path, args.proposal_id, "rejected")
        print(f"rejected {args.proposal_id} ({record['action']}) by {args.actor}; appended to {audit_path}")
        return 0

    if args.command == "audit":
        audit_log = AuditLog(audit_path)
        for entry in audit_log.read_all():
            print(f"{entry['timestamp']} {entry['event']:<9} actor={entry['actor']!r} "
                  f"service={entry['service']!r} action={entry['action']!r} id={entry['proposal_id']}")
        return 0

    raise AssertionError(f"unhandled command {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(argv)
    except (InputError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
