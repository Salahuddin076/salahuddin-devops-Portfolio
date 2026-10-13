"""CSV readers and writers for billing, utilization and volume inventory files.

The billing reader understands a FOCUS-like export. Only the columns needed by
the analyses are mandatory; optional columns fall back to sensible defaults so
that a real FOCUS 1.x export (which has no ``x_InstanceType``) still loads.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from .models import (
    BILLING_COLUMNS,
    UTILIZATION_COLUMNS,
    VOLUME_COLUMNS,
    CostRecord,
    UtilizationRecord,
    VolumeRecord,
)

REQUIRED_BILLING = (
    "ChargePeriodStart",
    "ChargePeriodEnd",
    "ServiceName",
    "BilledCost",
    "EffectiveCost",
)


class InputError(ValueError):
    """Raised for malformed input files; message includes file and line."""


def parse_timestamp(value: str) -> datetime:
    """Parse ISO-8601 (``Z`` suffix, offset, or naive) into naive UTC."""
    text = value.strip()
    if not text:
        raise ValueError("empty timestamp")
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def format_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _decimal(value: str, default: Decimal | None = None) -> Decimal | None:
    text = (value or "").strip()
    if not text:
        return default
    return Decimal(text)


def parse_tags(raw: str) -> dict[str, str]:
    """Parse the FOCUS ``Tags`` JSON object. Empty/``{}``/``null`` -> no tags."""
    text = (raw or "").strip()
    if not text or text == "null":
        return {}
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Tags must be a JSON object")
    return {str(k): "" if v is None else str(v) for k, v in parsed.items()}


def _open_rows(path: Path, required: Iterable[str]) -> tuple[list[dict[str, str]], Path]:
    path = Path(path)
    if not path.is_file():
        raise InputError(f"{path}: file not found")
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        missing = [c for c in required if c not in header]
        if missing:
            raise InputError(f"{path}: missing required column(s): {', '.join(missing)}")
        return list(reader), path


def read_billing(path: Path | str) -> list[CostRecord]:
    rows, path = _open_rows(Path(path), REQUIRED_BILLING)
    records: list[CostRecord] = []
    for lineno, row in enumerate(rows, start=2):
        try:
            start = parse_timestamp(row["ChargePeriodStart"])
            end = parse_timestamp(row["ChargePeriodEnd"])
            if end <= start:
                raise ValueError("ChargePeriodEnd must be after ChargePeriodStart")
            bps = row.get("BillingPeriodStart") or ""
            records.append(
                CostRecord(
                    charge_period_start=start,
                    charge_period_end=end,
                    service_name=row["ServiceName"].strip(),
                    billed_cost=_decimal(row["BilledCost"], Decimal("0")),
                    effective_cost=_decimal(row["EffectiveCost"], Decimal("0")),
                    list_cost=_decimal(row.get("ListCost", "")),
                    charge_category=(row.get("ChargeCategory") or "Usage").strip(),
                    pricing_category=(row.get("PricingCategory") or "On-Demand").strip(),
                    billing_period_start=parse_timestamp(bps) if bps.strip() else None,
                    resource_id=(row.get("ResourceId") or "").strip(),
                    resource_type=(row.get("ResourceType") or "").strip(),
                    region_id=(row.get("RegionId") or "").strip(),
                    instance_type=(row.get("x_InstanceType") or "").strip(),
                    # FOCUS 1.0 renamed UsageQuantity to ConsumedQuantity; accept both.
                    usage_quantity=_decimal(
                        row.get("UsageQuantity") or row.get("ConsumedQuantity") or "", Decimal("0")
                    ),
                    pricing_unit=(row.get("PricingUnit") or "").strip(),
                    tags=parse_tags(row.get("Tags", "")),
                )
            )
        except (ValueError, InvalidOperation, json.JSONDecodeError) as exc:
            raise InputError(f"{path}:{lineno}: {exc}") from exc
    return records


def write_billing(path: Path | str, records: Iterable[CostRecord]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(BILLING_COLUMNS)
        for r in records:
            writer.writerow(
                [
                    format_timestamp(r.billing_period_start) if r.billing_period_start else "",
                    format_timestamp(r.charge_period_start),
                    format_timestamp(r.charge_period_end),
                    r.service_name,
                    r.resource_id,
                    r.resource_type,
                    r.region_id,
                    r.instance_type,
                    str(r.usage_quantity),
                    r.pricing_unit,
                    "" if r.list_cost is None else str(r.list_cost),
                    str(r.billed_cost),
                    str(r.effective_cost),
                    r.charge_category,
                    r.pricing_category,
                    json.dumps(r.tags, sort_keys=True, separators=(",", ":")) if r.tags else "",
                ]
            )


def read_utilization(path: Path | str) -> list[UtilizationRecord]:
    rows, path = _open_rows(Path(path), UTILIZATION_COLUMNS)
    out: list[UtilizationRecord] = []
    for lineno, row in enumerate(rows, start=2):
        try:
            out.append(
                UtilizationRecord(
                    resource_id=row["resource_id"].strip(),
                    instance_type=row["instance_type"].strip(),
                    region=row["region"].strip(),
                    avg_cpu_pct=Decimal(row["avg_cpu_pct"]),
                    p95_cpu_pct=Decimal(row["p95_cpu_pct"]),
                    avg_mem_pct=Decimal(row["avg_mem_pct"]),
                    observed_hours=Decimal(row["observed_hours"]),
                    running_hours=Decimal(row["running_hours"]),
                )
            )
        except (InvalidOperation, KeyError) as exc:
            raise InputError(f"{path}:{lineno}: invalid value ({exc!r})") from exc
    return out


def write_utilization(path: Path | str, records: Iterable[UtilizationRecord]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(UTILIZATION_COLUMNS)
        for u in records:
            writer.writerow(
                [
                    u.resource_id,
                    u.instance_type,
                    u.region,
                    str(u.avg_cpu_pct),
                    str(u.p95_cpu_pct),
                    str(u.avg_mem_pct),
                    str(u.observed_hours),
                    str(u.running_hours),
                ]
            )


def read_volumes(path: Path | str) -> list[VolumeRecord]:
    rows, path = _open_rows(Path(path), VOLUME_COLUMNS)
    out: list[VolumeRecord] = []
    for lineno, row in enumerate(rows, start=2):
        try:
            out.append(
                VolumeRecord(
                    volume_id=row["volume_id"].strip(),
                    volume_type=row["volume_type"].strip(),
                    size_gb=Decimal(row["size_gb"]),
                    state=row["state"].strip().lower(),
                    attached_instance=row["attached_instance"].strip(),
                    region=row["region"].strip(),
                    days_in_state=int(row["days_in_state"]),
                )
            )
        except (InvalidOperation, ValueError) as exc:
            raise InputError(f"{path}:{lineno}: invalid value ({exc})") from exc
    return out


def write_volumes(path: Path | str, records: Iterable[VolumeRecord]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(VOLUME_COLUMNS)
        for v in records:
            writer.writerow(
                [
                    v.volume_id,
                    v.volume_type,
                    str(v.size_gb),
                    v.state,
                    v.attached_instance,
                    v.region,
                    str(v.days_in_state),
                ]
            )
