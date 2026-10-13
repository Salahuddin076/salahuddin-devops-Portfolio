"""Tiny hand-built fixtures shared by the tests."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from finops.models import CostRecord, UtilizationRecord, VolumeRecord  # noqa: E402

D = Decimal


def rec(
    cost: str | int,
    *,
    service: str = "Amazon EC2",
    tags: dict | None = None,
    day: date = date(2026, 9, 1),
    committed: bool = False,
    category: str = "Usage",
    list_cost: str | None = None,
    resource_id: str = "r-1",
    hours: int = 24,
) -> CostRecord:
    start = datetime(day.year, day.month, day.day)
    cost = D(str(cost))
    return CostRecord(
        charge_period_start=start,
        charge_period_end=start + timedelta(hours=hours),
        service_name=service,
        billed_cost=D("0") if committed else cost,
        effective_cost=cost,
        list_cost=D(list_cost) if list_cost is not None else cost,
        charge_category=category,
        pricing_category="Committed" if committed else "On-Demand",
        resource_id=resource_id,
        tags=dict(tags or {}),
    )


def util(
    instance_type: str,
    p95: str | int,
    mem: str | int,
    *,
    avg: str | int = 1,
    observed: int = 720,
    running: int | None = None,
    resource_id: str = "i-test",
) -> UtilizationRecord:
    return UtilizationRecord(
        resource_id=resource_id,
        instance_type=instance_type,
        region="us-east-1",
        avg_cpu_pct=D(str(avg)),
        p95_cpu_pct=D(str(p95)),
        avg_mem_pct=D(str(mem)),
        observed_hours=D(observed),
        running_hours=D(observed if running is None else running),
    )


def volume(state: str, size: int = 100, vtype: str = "gp2", days: int = 60, vid: str = "vol-1") -> VolumeRecord:
    return VolumeRecord(vid, vtype, D(size), state, "" if state == "available" else "i-x", "us-east-1", days)


def daily(costs: list, start: date = date(2026, 9, 1), service: str = "Amazon EC2") -> list[CostRecord]:
    return [rec(c, day=start + timedelta(days=i), service=service) for i, c in enumerate(costs)]
