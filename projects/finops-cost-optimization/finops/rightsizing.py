"""Rule-based rightsizing recommendations.

Rules, evaluated per instance in this order:

1. **Idle** - p95 CPU below ``idle_p95_cpu`` *and* average memory below
   ``idle_avg_mem``: stop/terminate candidate. No further rules apply.
2. **Downsize** - p95 CPU below ``downsize_p95_cpu``: step down one size at a
   time within the same family while the *projected* p95 CPU and memory (which
   double per step, since each size halves vCPU and RAM) stay under the
   ceilings. At most ``max_steps`` steps; never below the smallest size.
3. **Graviton** - for x86 m5/c5/r5, propose the same-size m7g/c7g/r7g of the
   (possibly downsized) type. The delta is *incremental* to rule 2, so deltas
   can be summed. Always flagged as needing arm64 compatibility testing.

Unattached EBS volumes (state ``available``) become delete candidates.

Monthly deltas use illustrative prices from :mod:`finops.pricing` and the
instance's observed run ratio (running_hours / observed_hours) x 730 hours.
Negative delta = saving.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from . import pricing
from .models import CostRecord, UtilizationRecord, VolumeRecord, money

GRAVITON_CAVEAT = (
    "arm64: rebuild/verify container images and native dependencies (multi-arch "
    "builds), check agents/AMIs, and load-test before migrating"
)


@dataclass(frozen=True)
class RightsizeConfig:
    idle_p95_cpu: Decimal = Decimal("5")
    idle_avg_mem: Decimal = Decimal("20")
    downsize_p95_cpu: Decimal = Decimal("40")
    max_projected_p95_cpu: Decimal = Decimal("70")
    max_projected_mem: Decimal = Decimal("75")
    max_steps: int = 2
    min_observed_hours: Decimal = Decimal("336")  # 14 days for "high" confidence
    graviton: bool = True


@dataclass(frozen=True)
class Recommendation:
    resource_id: str
    kind: str  # terminate | downsize | graviton | delete-volume
    current: str
    proposed: str
    monthly_delta: Decimal
    confidence: str  # high | medium | low
    rationale: str
    requires_compat_testing: bool = False
    caveat: str = ""
    owner: str = ""


@dataclass(frozen=True)
class RightsizeResult:
    recommendations: list[Recommendation]
    skipped: list[str] = field(default_factory=list)

    @property
    def total_monthly_delta(self) -> Decimal:
        return money(sum((r.monthly_delta for r in self.recommendations), Decimal("0")))

    def by_kind(self, kind: str) -> list[Recommendation]:
        return [r for r in self.recommendations if r.kind == kind]


def graviton_equivalent(instance_type: str) -> str | None:
    """Map an x86 m5/c5/r5 type to its same-size Graviton type, else None."""
    family, size = pricing.split_instance_type(instance_type)
    target_family = pricing.GRAVITON_EQUIVALENT.get(family)
    if target_family is None:
        return None
    candidate = f"{target_family}.{size}"
    return candidate if candidate in pricing.EC2_HOURLY else None


def _observation_confidence(u: UtilizationRecord, cfg: RightsizeConfig) -> str:
    if u.observed_hours >= cfg.min_observed_hours:
        return "high"
    if u.observed_hours >= cfg.min_observed_hours / 2:
        return "medium"
    return "low"


def _lower(conf: str) -> str:
    return {"high": "medium", "medium": "low", "low": "low"}[conf]


def _owner_index(records: Iterable[CostRecord] | None) -> dict[str, str]:
    index: dict[str, str] = {}
    for r in records or ():
        if r.resource_id and r.resource_id not in index:
            team = r.tags.get("team", "").strip().lower()
            app = r.tags.get("app", "").strip().lower()
            index[r.resource_id] = "/".join(p for p in (team, app) if p) or "(untagged)"
    return index


def downsize_target(u: UtilizationRecord, cfg: RightsizeConfig) -> tuple[str, int]:
    """Return (proposed_type, steps). ``steps == 0`` means keep the current size."""
    family, size = pricing.split_instance_type(u.instance_type)
    if size not in pricing.SIZE_ORDER:
        return u.instance_type, 0
    idx = pricing.SIZE_ORDER.index(size)
    steps = 0
    while steps < cfg.max_steps and idx - steps > 0:
        factor = Decimal(2) ** (steps + 1)
        candidate = f"{family}.{pricing.SIZE_ORDER[idx - steps - 1]}"
        if candidate not in pricing.EC2_HOURLY:
            break
        if u.p95_cpu_pct * factor > cfg.max_projected_p95_cpu:
            break
        if u.avg_mem_pct * factor > cfg.max_projected_mem:
            break
        steps += 1
    if steps == 0:
        return u.instance_type, 0
    return f"{family}.{pricing.SIZE_ORDER[idx - steps]}", steps


def recommend(
    utilization: Iterable[UtilizationRecord],
    volumes: Iterable[VolumeRecord] = (),
    config: RightsizeConfig | None = None,
    billing: Iterable[CostRecord] | None = None,
) -> RightsizeResult:
    cfg = config or RightsizeConfig()
    owners = _owner_index(billing)
    recs: list[Recommendation] = []
    skipped: list[str] = []

    for u in utilization:
        try:
            current_price = pricing.ec2_hourly(u.instance_type)
            pricing.split_instance_type(u.instance_type)
        except ValueError:
            current_price = None
        if current_price is None:
            skipped.append(f"{u.resource_id}: {u.instance_type} not in illustrative price table")
            continue
        if u.observed_hours <= 0 or u.running_hours <= 0:
            skipped.append(f"{u.resource_id}: no running hours observed")
            continue

        run_ratio = min(Decimal(1), u.running_hours / u.observed_hours)
        monthly_hours = pricing.HOURS_PER_MONTH * run_ratio
        base_conf = _observation_confidence(u, cfg)
        owner = owners.get(u.resource_id, "")
        metrics = f"p95 CPU {u.p95_cpu_pct}%, avg CPU {u.avg_cpu_pct}%, avg mem {u.avg_mem_pct}%"

        if u.p95_cpu_pct < cfg.idle_p95_cpu and u.avg_mem_pct < cfg.idle_avg_mem:
            recs.append(
                Recommendation(
                    resource_id=u.resource_id,
                    kind="terminate",
                    current=u.instance_type,
                    proposed="stop or terminate",
                    monthly_delta=money(-current_price * monthly_hours),
                    confidence=base_conf,
                    rationale=f"Idle: {metrics} over {u.observed_hours}h observed. "
                    "Confirm with owner; snapshot/AMI before terminating.",
                    owner=owner,
                )
            )
            continue

        effective_type = u.instance_type
        effective_price = current_price
        if u.p95_cpu_pct < cfg.downsize_p95_cpu:
            proposed, steps = downsize_target(u, cfg)
            if steps:
                new_price = pricing.EC2_HOURLY[proposed]
                factor = Decimal(2) ** steps
                projected_cpu = u.p95_cpu_pct * factor
                conf = base_conf if projected_cpu <= cfg.max_projected_p95_cpu - 10 else _lower(base_conf)
                recs.append(
                    Recommendation(
                        resource_id=u.resource_id,
                        kind="downsize",
                        current=u.instance_type,
                        proposed=proposed,
                        monthly_delta=money((new_price - current_price) * monthly_hours),
                        confidence=conf,
                        rationale=f"{metrics}; {steps} size step(s) down projects p95 CPU "
                        f"~{projected_cpu}% and mem ~{u.avg_mem_pct * factor}% "
                        f"(ceilings {cfg.max_projected_p95_cpu}%/{cfg.max_projected_mem}%).",
                        owner=owner,
                    )
                )
                effective_type, effective_price = proposed, new_price

        if cfg.graviton:
            target = graviton_equivalent(effective_type)
            if target is not None:
                g_price = pricing.EC2_HOURLY[target]
                incremental = " (incremental to the downsize above)" if effective_type != u.instance_type else ""
                recs.append(
                    Recommendation(
                        resource_id=u.resource_id,
                        kind="graviton",
                        current=effective_type,
                        proposed=target,
                        monthly_delta=money((g_price - effective_price) * monthly_hours),
                        confidence=_lower(base_conf),
                        rationale=f"Same vCPU/memory on Graviton at a lower illustrative "
                        f"hourly price{incremental}.",
                        requires_compat_testing=True,
                        caveat=GRAVITON_CAVEAT,
                        owner=owner,
                    )
                )

    for v in volumes:
        if v.state != "available":
            continue
        price = pricing.ebs_gb_month(v.volume_type)
        if price is None:
            skipped.append(f"{v.volume_id}: volume type {v.volume_type} not in price table")
            continue
        if v.days_in_state >= 30:
            conf = "high"
        elif v.days_in_state >= 7:
            conf = "medium"
        else:
            conf = "low"
        recs.append(
            Recommendation(
                resource_id=v.volume_id,
                kind="delete-volume",
                current=f"{v.volume_type} {v.size_gb} GB (unattached)",
                proposed="snapshot then delete",
                monthly_delta=money(-price * v.size_gb),
                confidence=conf,
                rationale=f"Unattached for {v.days_in_state} days. A snapshot costs less per GB "
                "and only stores used blocks; delete the volume once the owner confirms.",
                owner=owners.get(v.volume_id, ""),
            )
        )

    order = {"terminate": 0, "delete-volume": 1, "downsize": 2, "graviton": 3}
    recs.sort(key=lambda r: (order[r.kind], r.monthly_delta, r.resource_id))
    return RightsizeResult(recommendations=recs, skipped=skipped)
