"""Cost allocation (showback) by tag, untagged spend, and top services."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence

from .models import CostRecord, money, pct

UNTAGGED = "(untagged)"
DEFAULT_KEYS: tuple[str, ...] = ("team", "env", "app")


@dataclass(frozen=True)
class Share:
    name: str
    cost: Decimal
    pct: Decimal


@dataclass(frozen=True)
class AllocationResult:
    cost_column: str
    total: Decimal
    by_key: dict[str, list[Share]]
    untagged_by_key: dict[str, Share]
    no_tags_at_all: Share
    top_services: list[Share]
    top_untagged_resources: list[Share]


def normalise_tag_value(value: str) -> str:
    """Trim and lower-case tag values so ``Search`` and ``search`` aggregate together."""
    return value.strip().lower()


def tag_value(record: CostRecord, key: str, normalise: bool = True) -> str | None:
    """Return the tag value, or None when the key is absent or blank (= untagged)."""
    raw = record.tags.get(key)
    if raw is None or not raw.strip():
        return None
    return normalise_tag_value(raw) if normalise else raw


def _ranked(totals: dict[str, Decimal], grand_total: Decimal, limit: int | None = None) -> list[Share]:
    items = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    if limit is not None:
        items = items[:limit]
    return [Share(name, money(cost), pct(cost, grand_total)) for name, cost in items]


def allocate(
    records: Iterable[CostRecord],
    keys: Sequence[str] = DEFAULT_KEYS,
    top_n: int = 5,
    cost_column: str = "effective",
    normalise: bool = True,
) -> AllocationResult:
    """Aggregate spend by each tag key.

    ``cost_column`` defaults to ``effective`` (amortised) because showback should
    reflect what a team's usage actually cost after commitments, not when the
    invoice was paid. Use ``billed`` to reconcile against the invoice.
    """
    total = Decimal("0")
    per_key: dict[str, dict[str, Decimal]] = {k: defaultdict(Decimal) for k in keys}
    untagged: dict[str, Decimal] = {k: Decimal("0") for k in keys}
    no_tags = Decimal("0")
    services: dict[str, Decimal] = defaultdict(Decimal)
    untagged_resources: dict[str, Decimal] = defaultdict(Decimal)

    for r in records:
        cost = r.cost(cost_column)
        if cost == 0:
            continue
        total += cost
        services[r.service_name] += cost
        has_any = False
        for k in keys:
            value = tag_value(r, k, normalise)
            if value is None:
                untagged[k] += cost
                per_key[k][UNTAGGED] += cost
            else:
                has_any = True
                per_key[k][value] += cost
        if not has_any:
            no_tags += cost
            label = r.resource_id or f"{r.service_name} (no resource id)"
            untagged_resources[label] += cost

    return AllocationResult(
        cost_column=cost_column,
        total=money(total),
        by_key={k: _ranked(per_key[k], total) for k in keys},
        untagged_by_key={k: Share(k, money(untagged[k]), pct(untagged[k], total)) for k in keys},
        no_tags_at_all=Share("no allocation tags", money(no_tags), pct(no_tags, total)),
        top_services=_ranked(services, total, top_n),
        top_untagged_resources=_ranked(untagged_resources, total, top_n),
    )
