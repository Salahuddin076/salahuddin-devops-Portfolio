"""Month-to-date budget check with a linear month-end forecast.

Designed as a CI gate: ``python3 -m finops budget ...`` exits with
``EXIT_BREACH`` when the chosen measure (actual or forecast) reaches the
``fail_at`` percentage of the budget. Lower thresholds (e.g. 80%) are reported
as warnings without failing the build.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Sequence

from .forecast import daily_totals, forecast_series
from .models import CostRecord, money, pct

EXIT_OK = 0
EXIT_BREACH = 3


@dataclass(frozen=True)
class ThresholdStatus:
    threshold_pct: Decimal
    actual_crossed: bool
    forecast_crossed: bool


@dataclass(frozen=True)
class BudgetResult:
    budget: Decimal
    month: str
    as_of: date
    days_elapsed: int
    days_in_month: int
    month_to_date: Decimal
    forecast_remaining: Decimal
    forecast_month_end: Decimal
    actual_pct: Decimal
    forecast_pct: Decimal
    thresholds: list[ThresholdStatus]
    measure: str
    fail_at: Decimal
    breached: bool

    @property
    def exit_code(self) -> int:
        return EXIT_BREACH if self.breached else EXIT_OK


def evaluate(
    records: Iterable[CostRecord],
    budget: Decimal | int | str,
    as_of: date | None = None,
    thresholds: Sequence[Decimal | int] = (80, 100),
    fail_at: Decimal | int = 100,
    measure: str = "forecast",
    lookback_days: int = 30,
    cost_column: str = "effective",
) -> BudgetResult:
    budget = Decimal(str(budget))
    if budget <= 0:
        raise ValueError("budget must be positive")
    if measure not in ("actual", "forecast"):
        raise ValueError("measure must be 'actual' or 'forecast'")
    history = daily_totals(records, cost_column)
    if not history:
        raise ValueError("no billing data")
    as_of = as_of or history[-1].day
    history = [p for p in history if p.day <= as_of]
    if not history:
        raise ValueError(f"no billing data on or before {as_of}")

    month_start = as_of.replace(day=1)
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    mtd = sum((p.cost for p in history if p.day >= month_start), Decimal("0"))
    remaining_days = days_in_month - as_of.day
    if remaining_days > 0:
        remaining = forecast_series(history, remaining_days, lookback_days).total
    else:
        remaining = Decimal("0")
    month_end = mtd + remaining

    actual_pct = pct(mtd, budget)
    forecast_pct = pct(month_end, budget)
    statuses = [
        ThresholdStatus(Decimal(str(t)), actual_pct >= Decimal(str(t)), forecast_pct >= Decimal(str(t)))
        for t in sorted(Decimal(str(t)) for t in thresholds)
    ]
    measured = actual_pct if measure == "actual" else forecast_pct
    fail_at = Decimal(str(fail_at))

    return BudgetResult(
        budget=money(budget),
        month=f"{as_of.year:04d}-{as_of.month:02d}",
        as_of=as_of,
        days_elapsed=as_of.day,
        days_in_month=days_in_month,
        month_to_date=money(mtd),
        forecast_remaining=money(remaining),
        forecast_month_end=money(month_end),
        actual_pct=actual_pct,
        forecast_pct=forecast_pct,
        thresholds=statuses,
        measure=measure,
        fail_at=fail_at,
        breached=measured >= fail_at,
    )
