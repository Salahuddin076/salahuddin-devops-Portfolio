"""Command-line interface: ``python3 -m finops <command> [options]``.

Exit codes: 0 success, 1 input/usage error, 2 argparse usage error,
3 budget breach (``budget`` command only).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

from . import allocation, budget, commitments, forecast, generator, report, rightsizing
from .io import InputError, read_billing, read_utilization, read_volumes
from .models import to_jsonable

DEFAULT_INPUT = "sample-data"


def _decimal(text: str) -> Decimal:
    try:
        return Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None


def _date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO date (YYYY-MM-DD): {text!r}") from None


def _thresholds(text: str) -> list[Decimal]:
    values = [_decimal(t) for t in text.split(",") if t.strip()]
    if not values or any(v <= 0 for v in values):
        raise argparse.ArgumentTypeError("thresholds must be positive numbers, e.g. 80,100")
    return values


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    base = Path(args.input)
    return (
        Path(args.billing) if args.billing else base / "billing.csv",
        Path(args.utilization) if args.utilization else base / "utilization.csv",
        Path(args.volumes) if args.volumes else base / "ebs_volumes.csv",
    )


def _emit(args: argparse.Namespace, result: object, blocks: list) -> None:
    if args.format == "json":
        print(json.dumps(to_jsonable(result), indent=2, sort_keys=True))
    elif args.format == "markdown":
        print(report.to_markdown(blocks), end="")
    else:
        print(report.to_text(blocks), end="")


def _add_common(p: argparse.ArgumentParser, needs: Sequence[str] = ("billing",)) -> None:
    g = p.add_argument_group("input")
    g.add_argument("--input", default=DEFAULT_INPUT, help="directory with billing.csv, utilization.csv, "
                   "ebs_volumes.csv (default: %(default)s)")
    g.add_argument("--billing", help="billing export CSV (overrides --input)")
    if "utilization" in needs:
        g.add_argument("--utilization", help="utilization CSV (overrides --input)")
        g.add_argument("--volumes", help="EBS volume inventory CSV (overrides --input)")
    p.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    p.add_argument("--cost-column", choices=("effective", "billed"), default="effective",
                   help="effective = amortised (default, for showback); billed = invoice view")
    p.set_defaults(utilization=None, volumes=None)


def _add_rightsize_opts(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("rightsizing")
    g.add_argument("--idle-cpu", type=_decimal, default=Decimal("5"), help="idle if p95 CPU below (%%)")
    g.add_argument("--downsize-cpu", type=_decimal, default=Decimal("40"), help="downsize if p95 CPU below (%%)")
    g.add_argument("--max-projected-cpu", type=_decimal, default=Decimal("70"),
                   help="ceiling for projected p95 CPU after downsizing (%%)")
    g.add_argument("--no-graviton", action="store_true", help="disable Graviton suggestions")


def _add_commit_opts(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("commitments")
    g.add_argument("--percentile", type=_decimal, default=commitments.DEFAULT_PERCENTILE,
                   help="percentile of hourly on-demand baseline to commit to (default: %(default)s)")
    g.add_argument("--discount", type=_decimal, default=commitments.DEFAULT_DISCOUNT,
                   help="illustrative commitment discount rate 0-1 (default: %(default)s)")
    g.add_argument("--eligible-service", action="append", dest="eligible",
                   help="ServiceName eligible for commitments (repeatable; default: Amazon EC2)")


def _add_budget_opts(p: argparse.ArgumentParser, required: bool) -> None:
    g = p.add_argument_group("budget")
    g.add_argument("--budget", type=_decimal, required=required, help="monthly budget in USD")
    g.add_argument("--thresholds", type=_thresholds, default=[Decimal(80), Decimal(100)],
                   help="comma-separated alert thresholds in %% (default: 80,100)")
    g.add_argument("--fail-at", type=_decimal, default=Decimal(100),
                   help="exit non-zero when the measure reaches this %% (default: %(default)s)")
    g.add_argument("--measure", choices=("forecast", "actual"), default="forecast")
    g.add_argument("--as-of", type=_date, help="evaluation date (default: last day in data)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m finops",
        description="Local FinOps toolkit over FOCUS-like billing exports (stdlib only).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="write deterministic synthetic sample data")
    p.add_argument("--out", default=DEFAULT_INPUT, help="output directory (default: %(default)s)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--start", type=_date, default=date(2026, 7, 1))
    p.add_argument("--days", type=int, default=90)

    p = sub.add_parser("allocate", help="cost by tag, untagged spend, top services")
    _add_common(p)
    p.add_argument("--keys", default="team,env,app", help="comma-separated tag keys (default: %(default)s)")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--no-normalise", action="store_true", help="do not lower-case/trim tag values")

    p = sub.add_parser("rightsize", help="downsize / Graviton / idle / unattached EBS recommendations")
    _add_common(p, needs=("billing", "utilization"))
    _add_rightsize_opts(p)

    p = sub.add_parser("commitments", help="Savings Plans / RI coverage and sizing")
    _add_common(p)
    _add_commit_opts(p)

    p = sub.add_parser("budget", help="month-to-date + forecast vs budget (CI gate)")
    _add_common(p)
    _add_budget_opts(p, required=True)
    p.add_argument("--lookback", type=int, default=30, help="days used for the forecast trend")

    p = sub.add_parser("forecast", help="linear-regression forecast of daily cost")
    _add_common(p)
    p.add_argument("--horizon", type=int, default=30)
    p.add_argument("--lookback", type=int, default=60, help="days of history to fit (0 = all)")

    p = sub.add_parser("report", help="write Markdown (+ optional HTML) report combining everything")
    _add_common(p, needs=("billing", "utilization"))
    _add_rightsize_opts(p)
    _add_commit_opts(p)
    _add_budget_opts(p, required=False)
    p.add_argument("--out", default="out", help="output directory (default: %(default)s)")
    p.add_argument("--html", action="store_true", help="also write a self-contained report.html")
    p.add_argument("--horizon", type=int, default=30)
    p.add_argument("--lookback", type=int, default=60)
    return parser


def _rightsize_config(args: argparse.Namespace) -> rightsizing.RightsizeConfig:
    return rightsizing.RightsizeConfig(
        idle_p95_cpu=args.idle_cpu,
        downsize_p95_cpu=args.downsize_cpu,
        max_projected_p95_cpu=args.max_projected_cpu,
        graviton=not args.no_graviton,
    )


def _commitments(args: argparse.Namespace, records) -> commitments.CommitmentResult:
    return commitments.analyze(
        records,
        percentile_value=args.percentile,
        discount=args.discount,
        eligible_services=tuple(args.eligible or commitments.DEFAULT_ELIGIBLE_SERVICES),
    )


def _run_rightsize(args, billing_path, util_path, vol_path, records):
    volumes = read_volumes(vol_path) if vol_path.is_file() else []
    return rightsizing.recommend(read_utilization(util_path), volumes, _rightsize_config(args), records)


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "generate":
        paths = generator.generate(args.out, seed=args.seed, start=args.start, days=args.days)
        for name, path in paths.items():
            print(f"wrote {name}: {path}")
        return 0

    billing_path, util_path, vol_path = _paths(args)
    records = read_billing(billing_path)
    if not records:
        raise InputError(f"{billing_path}: no rows")

    if args.command == "allocate":
        keys = [k.strip() for k in args.keys.split(",") if k.strip()]
        res = allocation.allocate(records, keys, args.top, args.cost_column, not args.no_normalise)
        _emit(args, res, report.allocation_blocks(res))
        return 0

    if args.command == "rightsize":
        res = _run_rightsize(args, billing_path, util_path, vol_path, records)
        _emit(args, res, report.rightsizing_blocks(res))
        return 0

    if args.command == "commitments":
        res = _commitments(args, records)
        _emit(args, res, report.commitments_blocks(res))
        return 0

    if args.command == "forecast":
        res = forecast.forecast(records, args.horizon, args.lookback or None, args.cost_column)
        _emit(args, res, report.forecast_blocks(res))
        return 0

    if args.command == "budget":
        res = budget.evaluate(records, args.budget, args.as_of, args.thresholds, args.fail_at,
                              args.measure, args.lookback, args.cost_column)
        _emit(args, res, report.budget_blocks(res))
        if res.breached:
            print(f"budget gate: {res.measure} {res.forecast_pct if res.measure == 'forecast' else res.actual_pct}% "
                  f">= {res.fail_at}% of budget", file=sys.stderr)
        return res.exit_code

    if args.command == "report":
        alloc = allocation.allocate(records, cost_column=args.cost_column)
        rs = _run_rightsize(args, billing_path, util_path, vol_path, records)
        cm = _commitments(args, records)
        fc = forecast.forecast(records, args.horizon, args.lookback or None, args.cost_column)
        bd = None
        if args.budget is not None:
            bd = budget.evaluate(records, args.budget, args.as_of, args.thresholds, args.fail_at,
                                 args.measure, cost_column=args.cost_column)
        blocks = report.build_report(alloc, rs, cm, fc, bd)
        summary = {"allocation": alloc, "rightsizing": rs, "commitments": cm, "forecast": fc, "budget": bd}
        for path in report.write_report(args.out, blocks, summary, args.html):
            print(f"wrote {path}")
        return 0

    raise AssertionError(f"unhandled command {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(argv)
    except (InputError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
