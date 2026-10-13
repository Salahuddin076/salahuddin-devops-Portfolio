"""Deterministic synthetic data generator.

Produces three files that look like what a FinOps pipeline would collect:

* ``billing.csv``      - a FOCUS-like daily billing export
* ``utilization.csv``  - per-instance CPU/memory summary (CloudWatch-style)
* ``ebs_volumes.csv``  - EBS volume inventory (DescribeVolumes-style)

Everything is driven by ``random.Random(seed)`` and fixed resource definitions,
so the same seed, start date and day count always produce byte-identical files.

The scenario is fictional. Prices come from :mod:`finops.pricing` and are
illustrative, approximate us-east-1 on-demand list prices.

Savings Plans modelling follows FOCUS conventions: usage covered by the plan
has ``BilledCost = 0`` and ``EffectiveCost`` = amortised (discounted) cost,
while a separate ``Purchase`` row carries the plan fee as ``BilledCost`` with
``EffectiveCost = 0``. Summing EffectiveCost therefore never double counts.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from . import pricing
from .io import write_billing, write_utilization, write_volumes
from .models import CostRecord, UtilizationRecord, VolumeRecord

REGION = "us-east-1"
EXISTING_SP_DISCOUNT = Decimal("0.28")  # illustrative Compute Savings Plan discount
Q6 = Decimal("0.000001")


@dataclass(frozen=True)
class InstanceSpec:
    key: str
    instance_type: str
    tags: dict[str, str]
    avg_cpu: float
    p95_cpu: float
    avg_mem: float
    schedule: str  # "24x7" | "business" | "scale-out"
    committed: bool = False
    start_day: int = 0


@dataclass(frozen=True)
class VolumeSpec:
    key: str
    volume_type: str
    size_gb: int
    attached_to: str  # InstanceSpec.key, or "" when unattached
    tags: dict[str, str]
    days_in_state: int


def _t(team: str, env: str, app: str) -> dict[str, str]:
    return {"team": team, "env": env, "app": app}


INSTANCES: tuple[InstanceSpec, ...] = (
    InstanceSpec("pay-api-1", "m5.2xlarge", _t("payments", "prod", "api"), 14, 24, 35, "24x7", committed=True),
    InstanceSpec("pay-api-2", "m5.2xlarge", _t("payments", "prod", "api"), 15, 26, 36, "24x7", committed=True),
    InstanceSpec("pay-wrk-1", "c5.xlarge", _t("payments", "prod", "worker"), 38, 62, 40, "24x7"),
    InstanceSpec("pay-wrk-2", "c5.xlarge", _t("payments", "prod", "worker"), 36, 60, 41, "24x7"),
    InstanceSpec("pay-batch-1", "c5.4xlarge", _t("payments", "prod", "batch"), 55, 82, 45, "business"),
    InstanceSpec("srch-os-1", "r5.2xlarge", _t("search", "prod", "opensearch"), 30, 52, 78, "24x7"),
    # Deliberate casing drift ("Search") to exercise tag normalisation.
    InstanceSpec("srch-os-2", "r5.2xlarge", _t("Search", "prod", "opensearch"), 31, 54, 77, "24x7"),
    InstanceSpec("srch-qry-1", "m7g.xlarge", _t("search", "prod", "query"), 35, 58, 50, "24x7"),
    InstanceSpec("srch-qry-2", "m7g.xlarge", _t("search", "prod", "query"), 34, 57, 49, "24x7"),
    InstanceSpec("plat-node-1", "m5.xlarge", _t("platform", "prod", "eks-nodes"), 28, 44, 52, "24x7", committed=True),
    InstanceSpec("plat-node-2", "m5.xlarge", _t("platform", "prod", "eks-nodes"), 27, 45, 51, "24x7", committed=True),
    InstanceSpec("plat-node-3", "m5.xlarge", _t("platform", "prod", "eks-nodes"), 22, 36, 48, "scale-out"),
    # Launched mid-period from a template that only sets "team": partial tagging.
    InstanceSpec("plat-node-4", "m5.xlarge", {"team": "platform"}, 21, 37, 47, "scale-out", start_day=45),
    InstanceSpec("plat-stg-1", "m5.large", _t("platform", "staging", "eks-nodes"), 2, 3.5, 11, "24x7"),
    InstanceSpec("data-nb-1", "r5.xlarge", _t("data", "dev", "notebooks"), 9, 18, 30, "business"),
    InstanceSpec("data-etl-1", "c5.2xlarge", _t("data", "dev", "etl"), 1.2, 2.5, 6, "24x7"),
    InstanceSpec("orphan-1", "m5.large", {}, 0.8, 1.9, 9, "24x7"),
)

VOLUMES: tuple[VolumeSpec, ...] = (
    VolumeSpec("vol-pay-api-1", "gp3", 100, "pay-api-1", _t("payments", "prod", "api"), 200),
    VolumeSpec("vol-pay-api-2", "gp3", 100, "pay-api-2", _t("payments", "prod", "api"), 200),
    VolumeSpec("vol-srch-os-1", "gp2", 500, "srch-os-1", _t("search", "prod", "opensearch"), 300),
    VolumeSpec("vol-srch-os-2", "gp2", 500, "srch-os-2", _t("search", "prod", "opensearch"), 300),
    VolumeSpec("vol-data-nb-1", "gp3", 200, "data-nb-1", _t("data", "dev", "notebooks"), 150),
    VolumeSpec("vol-data-old", "gp2", 1000, "", _t("data", "dev", "etl"), 120),
    VolumeSpec("vol-plat-old", "gp3", 200, "", _t("platform", "staging", "eks-nodes"), 45),
    VolumeSpec("vol-unknown", "gp2", 50, "", {}, 10),
)

BUCKETS: tuple[tuple[str, int, float, dict[str, str]], ...] = (
    # name, starting GB, daily growth rate, tags
    ("payments-artifacts", 500, 0.003, _t("payments", "prod", "artifacts")),
    ("search-snapshots", 2000, 0.002, _t("search", "prod", "opensearch")),
    ("central-logs", 3000, 0.005, {}),  # untagged on purpose
)


def _hex_id(rng: random.Random, prefix: str, length: int = 16) -> str:
    return prefix + "".join(rng.choice("0123456789abcdef") for _ in range(length))


def _q(value: Decimal) -> Decimal:
    return value.quantize(Q6)


def _month_start(d: date) -> datetime:
    return datetime(d.year, d.month, 1)


def _instance_hours(spec: InstanceSpec, day_index: int, weekday: int, rng: random.Random) -> int:
    if day_index < spec.start_day:
        return 0
    if spec.schedule == "24x7":
        return 24
    if spec.schedule == "business":
        return rng.randint(10, 14) if weekday < 5 else 0
    if spec.schedule == "scale-out":
        return 24 if weekday < 5 else rng.randint(4, 10)
    raise ValueError(f"unknown schedule {spec.schedule}")


def _jitter(rng: random.Random, value: float, spread: float = 0.08) -> Decimal:
    return Decimal(str(round(max(0.0, value * (1 + rng.uniform(-spread, spread))), 1)))


def generate(
    out_dir: Path | str,
    seed: int = 42,
    start: date = date(2026, 7, 1),
    days: int = 90,
) -> dict[str, Path]:
    """Generate the three synthetic files into ``out_dir`` and return their paths."""
    if days < 1:
        raise ValueError("days must be >= 1")
    rng = random.Random(seed)
    out = Path(out_dir)

    instance_ids = {s.key: _hex_id(rng, "i-0") for s in INSTANCES}
    volume_ids = {v.key: _hex_id(rng, "vol-0") for v in VOLUMES}
    nat_ids = [_hex_id(rng, "nat-0") for _ in range(2)]

    records: list[CostRecord] = []
    running_hours = {s.key: 0 for s in INSTANCES}
    one_day = timedelta(days=1)

    def add(day_start: datetime, service: str, resource_id: str, resource_type: str,
            qty: Decimal, unit: str, list_cost: Decimal, tags: dict[str, str],
            *, instance_type: str = "", committed: bool = False,
            category: str = "Usage") -> CostRecord:
        list_cost = _q(list_cost)
        if committed:
            effective = _q(list_cost * (1 - EXISTING_SP_DISCOUNT))
            billed = Decimal("0.000000")
        else:
            effective = billed = list_cost
        rec = CostRecord(
            billing_period_start=_month_start(day_start.date()),
            charge_period_start=day_start,
            charge_period_end=day_start + one_day,
            service_name=service,
            resource_id=resource_id,
            resource_type=resource_type,
            region_id=REGION,
            instance_type=instance_type,
            usage_quantity=qty,
            pricing_unit=unit,
            list_cost=list_cost,
            billed_cost=billed,
            effective_cost=effective,
            charge_category=category,
            pricing_category="Committed" if committed else "On-Demand",
            tags=dict(tags),
        )
        records.append(rec)
        return rec

    gb_month_per_day = Decimal(24) / pricing.HOURS_PER_MONTH

    for i in range(days):
        day = start + timedelta(days=i)
        ds = datetime(day.year, day.month, day.day)
        weekday = day.weekday()
        growth = 1 + 0.004 * i  # gentle upward trend in usage-driven services

        # --- EC2 instances -------------------------------------------------
        sp_fee = Decimal("0")
        for spec in INSTANCES:
            hours = _instance_hours(spec, i, weekday, rng)
            if hours == 0:
                continue
            running_hours[spec.key] += hours
            price = pricing.EC2_HOURLY[spec.instance_type]
            rec = add(ds, "Amazon EC2", instance_ids[spec.key], "Instance", Decimal(hours), "Hours",
                      price * hours, spec.tags, instance_type=spec.instance_type,
                      committed=spec.committed)
            if spec.committed:
                sp_fee += rec.effective_cost

        # --- Savings Plan purchase (fully utilised, fee == covered effective cost)
        if sp_fee:
            records.append(
                CostRecord(
                    billing_period_start=_month_start(day),
                    charge_period_start=ds,
                    charge_period_end=ds + one_day,
                    service_name="Savings Plans",
                    resource_id="sp-compute-1yr-nu",
                    resource_type="SavingsPlan",
                    region_id="global",
                    usage_quantity=Decimal(24),
                    pricing_unit="Hours",
                    list_cost=None,
                    billed_cost=_q(sp_fee),
                    effective_cost=Decimal("0.000000"),
                    charge_category="Purchase",
                    pricing_category="Committed",
                    tags={},
                )
            )

        # --- EKS control planes --------------------------------------------
        for name, env in (("eks-prod", "prod"), ("eks-staging", "staging")):
            add(ds, "Amazon EKS", f"arn:aws:eks:{REGION}:cluster/{name}", "Cluster", Decimal(24), "Hours",
                pricing.EKS_CLUSTER_HOURLY * 24, _t("platform", env, "eks-control-plane"))

        # --- RDS -----------------------------------------------------------
        add(ds, "Amazon RDS", "db-payments-prod", "DBInstance", Decimal(24), "Hours",
            pricing.RDS_HOURLY["db.r5.large"] * 2 * 24, _t("payments", "prod", "postgres"),
            instance_type="db.r5.large")  # Multi-AZ ~= 2x single-AZ
        add(ds, "Amazon RDS", "db-platform-staging", "DBInstance", Decimal(24), "Hours",
            pricing.RDS_HOURLY["db.m5.large"] * 24, _t("platform", "staging", "postgres"),
            instance_type="db.m5.large")

        # --- S3 ------------------------------------------------------------
        for name, gb0, rate, tags in BUCKETS:
            gb = Decimal(str(round(gb0 * (1 + rate) ** i, 1)))
            qty = _q(gb * gb_month_per_day)
            add(ds, "Amazon S3", f"arn:aws:s3:::{name}", "Bucket", qty, "GB-Mo",
                qty * pricing.S3_STANDARD_PER_GB_MONTH, tags)

        # --- EBS -----------------------------------------------------------
        for vol in VOLUMES:
            qty = _q(Decimal(vol.size_gb) * gb_month_per_day)
            add(ds, "Amazon EBS", volume_ids[vol.key], "Volume", qty, "GB-Mo",
                qty * pricing.EBS_PER_GB_MONTH[vol.volume_type], vol.tags)

        # --- NAT Gateway ---------------------------------------------------
        for idx, nat in enumerate(nat_ids):
            nat_tags = _t("platform", "prod", "network")
            add(ds, "NAT Gateway", nat, "NatGateway", Decimal(24), "Hours",
                pricing.NAT_GATEWAY_HOURLY * 24, nat_tags)
            gb = Decimal(str(round(rng.uniform(150, 260) * growth * (1.3 if idx == 0 else 1.0), 1)))
            add(ds, "NAT Gateway", nat, "NatGateway", gb, "GB",
                gb * pricing.NAT_GATEWAY_PER_GB, nat_tags)

        # --- Data transfer (typically untagged: no resource to hang tags on)
        gb_out = Decimal(str(round(rng.uniform(220, 380) * growth, 1)))
        add(ds, "Data Transfer", "", "", gb_out, "GB", gb_out * pricing.DATA_TRANSFER_OUT_PER_GB, {})
        gb_az = Decimal(str(round(rng.uniform(600, 900) * growth, 1)))
        add(ds, "Data Transfer", "", "", gb_az, "GB", gb_az * pricing.DATA_TRANSFER_INTER_AZ_PER_GB, {})

    utilization = []
    for spec in INSTANCES:
        if spec.start_day >= days:
            continue  # never launched inside the generated window
        obs = Decimal((days - spec.start_day) * 24)
        utilization.append(
            UtilizationRecord(
                resource_id=instance_ids[spec.key],
                instance_type=spec.instance_type,
                region=REGION,
                avg_cpu_pct=_jitter(rng, spec.avg_cpu),
                p95_cpu_pct=_jitter(rng, spec.p95_cpu, spread=0.04),
                avg_mem_pct=_jitter(rng, spec.avg_mem, spread=0.04),
                observed_hours=obs,
                running_hours=Decimal(running_hours[spec.key]),
            )
        )

    volumes = [
        VolumeRecord(
            volume_id=volume_ids[v.key],
            volume_type=v.volume_type,
            size_gb=Decimal(v.size_gb),
            state="in-use" if v.attached_to else "available",
            attached_instance=instance_ids.get(v.attached_to, ""),
            region=REGION,
            days_in_state=v.days_in_state,
        )
        for v in VOLUMES
    ]

    paths = {
        "billing": out / "billing.csv",
        "utilization": out / "utilization.csv",
        "volumes": out / "ebs_volumes.csv",
    }
    write_billing(paths["billing"], records)
    write_utilization(paths["utilization"], utilization)
    write_volumes(paths["volumes"], volumes)
    return paths
