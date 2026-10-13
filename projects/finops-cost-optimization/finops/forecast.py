"""Explainable spend forecast: ordinary least-squares line through daily cost.

Deliberately simple. A straight line can be explained in one sentence to a
finance partner and audited by hand. Known limitations (also in docs):

* no seasonality (weekday/weekend, month-end batch, holiday peaks)
* step changes (a new cluster, a commitment purchase) bend the fit until the
  lookback window has moved past them
* the +/- band is residual standard deviation, not a calibrated interval
* garbage in, garbage out: partial final days in an export depress the trend
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Sequence

from .models import CostRecord, money


@dataclass(frozen=True)
class LinearFit:
    slope: float
    intercept: float
    r_squared: float
    residual_std: float
    n: int

    def predict(self, x: float) -> float:
        return self.intercept + self.slope * x


@dataclass(frozen=True)
class DailyPoint:
    day: date
    cost: Decimal


@dataclass(frozen=True)
class ForecastPoint:
    day: date
    cost: Decimal
    low: Decimal
    high: Decimal


@dataclass(frozen=True)
class ForecastResult:
    fit: LinearFit
    history_start: date
    history_end: date
    lookback_days: int
    predictions: list[ForecastPoint]

    @property
    def total(self) -> Decimal:
        return money(sum((p.cost for p in self.predictions), Decimal("0")))

    @property
    def slope_per_day(self) -> Decimal:
        return money(self.fit.slope)


def daily_totals(records: Iterable[CostRecord], cost_column: str = "effective") -> list[DailyPoint]:
    """Sum cost per calendar day (of ChargePeriodStart), filling gaps with zero."""
    totals: dict[date, Decimal] = defaultdict(Decimal)
    for r in records:
        totals[r.charge_date] += r.cost(cost_column)
    if not totals:
        return []
    first, last = min(totals), max(totals)
    out = []
    d = first
    while d <= last:
        out.append(DailyPoint(d, totals.get(d, Decimal("0"))))
        d += timedelta(days=1)
    return out


def linear_fit(ys: Sequence[float]) -> LinearFit:
    """OLS fit of ys against x = 0..n-1."""
    n = len(ys)
    if n == 0:
        raise ValueError("cannot fit a line to zero points")
    if n == 1:
        return LinearFit(0.0, float(ys[0]), 1.0, 0.0, 1)
    xs = range(n)
    mean_x = (n - 1) / 2
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    if ss_tot == 0:
        r2 = 1.0 if ss_res < 1e-12 else 0.0
    else:
        r2 = max(0.0, 1 - ss_res / ss_tot)
    dof = max(1, n - 2)
    residual_std = math.sqrt(ss_res / dof) if ss_res > 1e-18 else 0.0
    return LinearFit(slope, intercept, r2, residual_std, n)


def forecast_series(
    history: Sequence[DailyPoint],
    horizon_days: int,
    lookback_days: int | None = None,
) -> ForecastResult:
    if not history:
        raise ValueError("no cost history to forecast from")
    window = list(history[-lookback_days:]) if lookback_days else list(history)
    fit = linear_fit([float(p.cost) for p in window])
    last = window[-1].day
    preds = []
    for k in range(1, horizon_days + 1):
        x = len(window) - 1 + k
        y = max(0.0, fit.predict(x))
        band = fit.residual_std
        preds.append(
            ForecastPoint(
                day=last + timedelta(days=k),
                cost=money(y),
                low=money(max(0.0, y - band)),
                high=money(y + band),
            )
        )
    return ForecastResult(
        fit=fit,
        history_start=window[0].day,
        history_end=last,
        lookback_days=len(window),
        predictions=preds,
    )


def forecast(
    records: Iterable[CostRecord],
    horizon_days: int = 30,
    lookback_days: int | None = 60,
    cost_column: str = "effective",
) -> ForecastResult:
    return forecast_series(daily_totals(records, cost_column), horizon_days, lookback_days)
