"""Command line: status, plan, execute.

  python3 -m failover status [--json]
  python3 -m failover plan    --mode planned|unplanned [--target REGION]
  python3 -m failover execute --mode planned|unplanned --confirm <global-cluster-id>
                              [--target REGION] [--rebuild-confirmed]

Adapters default to the in-memory fakes (`--adapters fake`): nothing touches
AWS unless `--adapters aws` and a real `--config` are given. With fakes,
`--scenario` picks the starting world and `--fake-world FILE` persists it
between invocations.

Exit codes: 0 ok; 1 other error; 2 usage or confirm-token mismatch;
3 refused by a guard (split brain, failback, conflicting run);
4 pre-check failed (nothing changed); 5 a step failed (re-run to resume).
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import textwrap
from pathlib import Path
from typing import Any, Optional, Sequence

from failover.audit import AuditLog
from failover.config import ConfigError, load_config
from failover.fakes import SCENARIOS, FakeCloud
from failover.orchestrator import MODES, FailoverError, Orchestrator, Plan
from failover.ports import Adapters
from failover.state import StateStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "failover.example.json"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python3 -m failover",
                                description="Warm-standby failover orchestrator (Aurora Global Database + EKS + Route 53)")
    p.add_argument("--config", type=Path, help="config JSON (default with fakes: config/failover.example.json)")
    p.add_argument("--adapters", choices=("fake", "aws"), default="fake",
                   help="fake (default, in-memory) or aws (boto3 + helm/kubectl)")
    p.add_argument("--scenario", choices=SCENARIOS, default="healthy", help="starting world for --adapters fake")
    p.add_argument("--fake-world", type=Path, help="load/save the fake world here so runs build on each other")
    p.add_argument("--state-file", type=Path, default=Path(".failover/state.json"))
    p.add_argument("--audit-log", type=Path, default=Path(".failover/audit.jsonl"))
    p.add_argument("--actor", default=None, help="name recorded in the audit log (default: $USER)")
    sub = p.add_subparsers(dest="command", required=True)

    st = sub.add_parser("status", help="health, writer, lag, DNS and workers per region")
    st.add_argument("--json", action="store_true")

    pl = sub.add_parser("plan", help="print the ordered steps without executing them")
    pl.add_argument("--mode", choices=MODES, required=True)
    pl.add_argument("--target", help="region to promote (default: the region that is not the writer)")

    ex = sub.add_parser("execute", help="run (or resume) the failover")
    ex.add_argument("--mode", choices=MODES, required=True)
    ex.add_argument("--confirm", required=True, help="must equal the global cluster id")
    ex.add_argument("--target", help="region to promote (default: the region that is not the writer)")
    ex.add_argument("--rebuild-confirmed", action="store_true",
                    help="failback only: the fenced region was rebuilt as a secondary")
    return p


def _adapters(args: argparse.Namespace, config) -> tuple[Adapters, Optional[FakeCloud]]:
    if args.adapters == "aws":
        from failover.aws import build_aws_adapters  # boto3 stays lazy even here

        return build_aws_adapters(config), None
    if args.fake_world and args.fake_world.exists():
        world = FakeCloud.load(args.fake_world)
    else:
        world = FakeCloud.scenario(args.scenario, config.primary_region, config.dr_region)
    return Adapters(health=world, db=world, workload=world, dns=world), world


def _num(v: Any) -> str:
    return "-" if v is None else str(v)


def render_status(s: dict[str, Any]) -> str:
    lines = [
        f"Global cluster {s['global_cluster_id']}  record {s['record_name']}",
        f"Aurora global writer: {s['global_writer']}   writers now: {', '.join(s['writers']) or 'none'}   "
        f"DNS PRIMARY: {s['dns_primary'] or 'n/a'}   state: writer {s['state_writer']}, epoch {s['epoch']}",
        "",
        f"{'REGION':<11} {'DEPLOYED AS':<12} {'HEALTH':<12} {'AURORA':<19} {'LAG':<7} {'DNS':<10} "
        f"{'WORKERS':<8} {'API MIN':<8} FENCED",
    ]
    for r in s["regions"]:
        lag = "-" if r["replication_lag_seconds"] is None else f"{r['replication_lag_seconds']:.1f}s"
        lines.append(
            f"{r['region']:<11} {r['deploy_role']:<12} {r['health']:<12} {r['db_role']:<19} {lag:<7} "
            f"{r['dns']:<10} {_num(r['workers']):<8} {_num(r['api_min_replicas']):<8} "
            f"{'yes' if r['fenced'] else 'no'}"
        )
    lines.append("")
    if s["warnings"]:
        lines.append("Warnings:")
        lines.extend(f"  ! {w}" for w in s["warnings"])
    else:
        lines.append("Warnings: none")
    return "\n".join(lines)


def render_plan(plan: Plan, global_cluster_id: str) -> str:
    kind = "failback" if plan.failback else "failover"
    lines = [f"Plan: {plan.mode} {kind} {plan.source} -> {plan.target}  (global cluster {global_cluster_id})"]
    if plan.resumes_run:
        lines.append(f"Resumes unfinished run {plan.resumes_run}")
    for s in plan.steps:
        mark = "" if s.state == "pending" else f" [{s.state} earlier]"
        head = f"  {s.number}. {s.id:<16}"
        body = textwrap.wrap(s.detail + mark, width=76, break_on_hyphens=False)
        lines.append(head + body[0])
        lines.extend(" " * len(head) + b for b in body[1:])
    lines.append("Notes:")
    for n in plan.notes:
        wrapped = textwrap.wrap(n, width=90, break_on_hyphens=False)
        lines.append("  - " + wrapped[0])
        lines.extend("    " + w for w in wrapped[1:])
    lines.append("Nothing was executed.")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    config_path = args.config
    if config_path is None:
        if args.adapters == "aws":
            print("error: --adapters aws needs an explicit --config", file=sys.stderr)
            return 2
        config_path = EXAMPLE_CONFIG
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    adapters, world = _adapters(args, config)
    orch = Orchestrator(
        config,
        adapters,
        StateStore(args.state_file),
        AuditLog(args.audit_log if args.command == "execute" else None),
        actor=args.actor or getpass.getuser(),
        progress=print,
    )
    code = 0
    try:
        if args.command == "status":
            s = orch.status()
            print(json.dumps(s, indent=2) if args.json else render_status(s))
        elif args.command == "plan":
            print(render_plan(orch.plan(args.mode, args.target), config.global_cluster_id))
        else:
            orch.execute(args.mode, args.confirm, args.target, args.rebuild_confirmed)
    except FailoverError as exc:
        print(f"error: {exc}", file=sys.stderr)
        code = exc.exit_code
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        code = 2
    finally:
        if world is not None and args.fake_world:
            world.save(args.fake_world)
    return code
