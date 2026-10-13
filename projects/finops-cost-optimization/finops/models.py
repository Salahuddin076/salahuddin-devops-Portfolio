"""Core data structures and money helpers."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")

# FOCUS column names written by the generator and understood by the reader.
# Columns prefixed with ``x_`` are FOCUS-style provider/custom extensions.
BILLING_COLUMNS: tuple[str, ...] = (
    "BillingPeriodStart",
    "ChargePeriodStart",
    "ChargePeriodEnd",
    "ServiceName",
    "ResourceId",
    "ResourceType",
    "RegionId",
    "x_InstanceType",
    "UsageQuantity",
    "PricingUnit",
    "ListCost",
    "BilledCost",
    "EffectiveCost",
    "ChargeCategory",
    "PricingCategory",
    "Tags",
)

UTILIZATION_COLUMNS: tuple[str, ...] = (
    "resource_id",
    "instance_type",
    "region",
    "avg_cpu_pct",
    "p95_cpu_pct",
    "avg_mem_pct",
    "observed_hours",
    "running_hours",
)

VOLUME_COLUMNS: tuple[str, ...] = (
    "volume_id",
    "volume_type",
    "size_gb",
    "state",
    "attached_instance",
    "region",
    "days_in_state",
)


def money(value: Decimal | int | float | str) -> Decimal:
    """Round to cents, half-up (the convention most finance teams expect)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def pct(part: Decimal, whole: Decimal) -> Decimal:
    """Percentage rounded to one decimal place; 0 when ``whole`` is zero."""
    if whole == 0:
        return Decimal("0.0")
    return (part * 100 / whole).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CostRecord:
    """One row of a FOCUS-like billing export."""

    charge_period_start: datetime
    charge_period_end: datetime
    service_name: str
    billed_cost: Decimal
    effective_cost: Decimal
    charge_category: str = "Usage"
    pricing_category: str = "On-Demand"
    list_cost: Decimal | None = None
    billing_period_start: datetime | None = None
    resource_id: str = ""
    resource_type: str = ""
    region_id: str = ""
    instance_type: str = ""
    usage_quantity: Decimal = Decimal("0")
    pricing_unit: str = ""
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def charge_date(self) -> date:
        return self.charge_period_start.date()

    def cost(self, column: str) -> Decimal:
        if column == "billed":
            return self.billed_cost
        if column == "effective":
            return self.effective_cost
        if column == "list":
            return self.list_cost if self.list_cost is not None else self.effective_cost
        raise ValueError(f"unknown cost column {column!r}")


@dataclass(frozen=True)
class UtilizationRecord:
    resource_id: str
    instance_type: str
    region: str
    avg_cpu_pct: Decimal
    p95_cpu_pct: Decimal
    avg_mem_pct: Decimal
    observed_hours: Decimal
    running_hours: Decimal


@dataclass(frozen=True)
class VolumeRecord:
    volume_id: str
    volume_type: str
    size_gb: Decimal
    state: str
    attached_instance: str
    region: str
    days_in_state: int


def to_jsonable(obj: Any) -> Any:
    """Convert dataclasses / Decimals / dates into JSON-serialisable values."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj
