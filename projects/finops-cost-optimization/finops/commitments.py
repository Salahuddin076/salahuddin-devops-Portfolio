"""Savings Plans / Reserved Instance coverage and commitment sizing.

Why size from a low percentile of the hourly on-demand *baseline* rather than
the mean (see docs/decisions/0002-baseline-percentile-commitments.md):

A commitment is a fixed $/hour you pay whether or not you use it. Any hour in
which eligible usage falls below the commitment wastes the gap. Sizing to the
mean guarantees that roughly half of all hours are under-utilised, and the
waste in those hours eats into the discount earned in the others. Sizing to a
low percentile (e.g. P20 -> usage is at or above the line 80% of the time)
keeps utilisation near 100%; the remaining peak stays on-demand, which is the
right price for spiky usage. ``sweep()`` makes this trade-off visible.

Daily-granularity exports are spread evenly across the 24 hours of each day,
which smooths intra-day peaks. Use an hourly export for production sizing.

The default discount is ILLUSTRATIVE. Real Savings Plans rates depend on term,
payment option, instance family and region - verify with AWS Cost Explorer.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Sequence

from .models import CostRecord, money, pct
from .pricing import HOURS_PER_MONTH

DEFAULT_ELIGIBLE_SERVICES: tuple[str, ...] = ("Amazon EC2",)
DEFAULT_DISCOUNT = Decimal("0.28")  # illustrative
DEFAULT_PERCENTILE = Decimal("20")


@dataclass(frozen=True)
class SimulationRow:
    label: str
    od_equivalent_hourly: Decimal  # on-demand $/h the commitment covers
    commitment_hourly: Decimal  # what you actually commit to ($/h, discounted)
    utilization_pct: Decimal
    monthly_net_savings: Decimal


@dataclass(frozen=True)
class CommitmentResult:
    eligible_services: tuple[str, ...]
    hours: int
    covered_list_cost: Decimal
    on_demand_list_cost: Decimal
    coverage_pct: Decimal
    percentile: Decimal
    discount: Decimal
    mean_od_hourly: Decimal
    recommended: SimulationRow
    sweep: list[SimulationRow]
    # A marginal $1/h of commitment costs (1 - discount) every hour but only saves
    # $1 in hours where usage reaches it, so it pays off only if usage is at or
    # above that level more than (1 - discount) of the time: levels above the
    # discount-rate percentile lose money in expectation on historical data.
    breakeven_percentile: Decimal


def _label(p: Decimal) -> str:
    return str(int(p)) if p == p.to_integral_value() else format(p.normalize(), "f")


def percentile(values: Sequence[Decimal], p: Decimal | float | int) -> Decimal:
    """Linear-interpolated percentile (same as numpy's default 'linear' method)."""
    if not values:
        raise ValueError("percentile of empty sequence")
    p = Decimal(str(p))
    if p < 0 or p > 100:
        raise ValueError("percentile must be within 0..100")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (Decimal(len(ordered) - 1) * p) / 100
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


def _is_eligible(r: CostRecord, services: Sequence[str]) -> bool:
    return r.charge_category == "Usage" and r.service_name in services


def hourly_on_demand_series(
    records: Iterable[CostRecord],
    eligible_services: Sequence[str] = DEFAULT_ELIGIBLE_SERVICES,
) -> list[Decimal]:
    """On-demand eligible cost per hour, spreading each row over its charge period.

    Hours between the first and last observed hour with no on-demand usage are
    included as zero so idle hours pull the baseline down, as they should.
    """
    buckets: dict[datetime, Decimal] = defaultdict(Decimal)
    seen: set[datetime] = set()
    for r in records:
        if not _is_eligible(r, eligible_services):
            continue
        start = r.charge_period_start.replace(minute=0, second=0, microsecond=0)
        hours = max(1, int((r.charge_period_end - start).total_seconds() // 3600))
        share = r.effective_cost / hours if r.pricing_category != "Committed" else Decimal("0")
        for h in range(hours):
            slot = start + timedelta(hours=h)
            seen.add(slot)
            if share:
                buckets[slot] += share
    if not seen:
        return []
    first, last = min(seen), max(seen)
    n = int((last - first).total_seconds() // 3600) + 1
    return [buckets.get(first + timedelta(hours=i), Decimal("0")) for i in range(n)]


def simulate(series: Sequence[Decimal], od_equivalent_hourly: Decimal, discount: Decimal, label: str) -> SimulationRow:
    """Net savings of committing to cover ``od_equivalent_hourly`` of on-demand spend per hour."""
    commitment = od_equivalent_hourly * (1 - discount)
    used = sum((min(u, od_equivalent_hourly) for u in series), Decimal("0"))
    baseline_cost = sum(series, Decimal("0"))
    with_plan = commitment * len(series) + (baseline_cost - used)
    hours = len(series) or 1
    net_monthly = (baseline_cost - with_plan) / hours * HOURS_PER_MONTH
    capacity = od_equivalent_hourly * len(series)
    utilization = pct(used, capacity) if capacity else Decimal("0.0")
    return SimulationRow(
        label=label,
        od_equivalent_hourly=od_equivalent_hourly.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        commitment_hourly=commitment.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        utilization_pct=utilization,
        monthly_net_savings=money(net_monthly),
    )


def analyze(
    records: Iterable[CostRecord],
    percentile_value: Decimal | float | int = DEFAULT_PERCENTILE,
    discount: Decimal | float | str = DEFAULT_DISCOUNT,
    eligible_services: Sequence[str] = DEFAULT_ELIGIBLE_SERVICES,
) -> CommitmentResult:
    records = list(records)
    discount = Decimal(str(discount))
    if not (Decimal("0") < discount < Decimal("1")):
        raise ValueError("discount must be between 0 and 1 (exclusive)")
    p = Decimal(str(percentile_value))

    covered = Decimal("0")
    on_demand = Decimal("0")
    for r in records:
        if not _is_eligible(r, eligible_services):
            continue
        if r.pricing_category == "Committed":
            covered += r.list_cost if r.list_cost is not None else r.effective_cost / (1 - discount)
        else:
            on_demand += r.cost("list")

    series = hourly_on_demand_series(records, eligible_services)
    if not series:
        raise ValueError(f"no eligible usage for services {list(eligible_services)}")
    mean = sum(series, Decimal("0")) / len(series)

    sweep_points: list[tuple[str, Decimal]] = [
        (f"P{q}", percentile(series, q)) for q in (0, 10, 20, 30, 50, 75)
    ]
    sweep_points.append(("mean", mean))
    sweep_points.sort(key=lambda item: item[1])
    sweep = [simulate(series, level, discount, label) for label, level in sweep_points]
    recommended = simulate(series, percentile(series, p), discount, f"P{_label(p)}")

    return CommitmentResult(
        eligible_services=tuple(eligible_services),
        hours=len(series),
        covered_list_cost=money(covered),
        on_demand_list_cost=money(on_demand),
        coverage_pct=pct(covered, covered + on_demand),
        percentile=p,
        discount=discount,
        mean_od_hourly=mean.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        recommended=recommended,
        sweep=sweep,
        breakeven_percentile=discount * 100,
    )
