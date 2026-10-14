"""Request validation without third-party schema libraries.

The order contract is small and stable, so explicit checks are easier to
read, test and keep dependency-free than a JSON Schema engine. Every check
returns *all* problems at once so a client can fix a request in one round
trip. Unknown fields are rejected: silently accepting them hides client bugs
and makes later contract changes ambiguous.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MAX_BODY_BYTES = 16 * 1024
MAX_ITEMS = 50
MAX_QUANTITY = 100
MAX_UNIT_PRICE_CENTS = 1_000_000
CURRENCIES = frozenset({"USD", "EUR", "GBP"})

IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
CUSTOMER_ID_RE = re.compile(r"^cus_[A-Za-z0-9]{4,60}$")
SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")
CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

ORDER_FIELDS = frozenset({"customerId", "currency", "items"})
ITEM_FIELDS = frozenset({"sku", "quantity", "unitPriceCents"})


@dataclass(frozen=True)
class FieldError:
    """One validation problem, addressed by a JSON-path-like field name."""

    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


def _is_int(value: Any) -> bool:
    # bool is a subclass of int in Python; a JSON `true` is not a quantity.
    return isinstance(value, int) and not isinstance(value, bool)


def is_valid_correlation_id(value: str | None) -> bool:
    """Client-supplied correlation IDs are echoed into logs, so constrain them."""
    return bool(value) and bool(CORRELATION_ID_RE.match(value))


def validate_idempotency_key(value: str | None) -> list[FieldError]:
    """The key is mandatory: it is what makes client retries safe."""
    if value is None or value == "":
        return [FieldError("Idempotency-Key", "header is required")]
    if not IDEMPOTENCY_KEY_RE.match(value):
        return [
            FieldError(
                "Idempotency-Key",
                "must be 8-128 characters of letters, digits, '.', '_', ':' or '-'",
            )
        ]
    return []


def _validate_item(index: int, item: Any) -> list[FieldError]:
    prefix = f"items[{index}]"
    if not isinstance(item, dict):
        return [FieldError(prefix, "must be an object")]
    errors: list[FieldError] = []
    for extra in sorted(set(item) - ITEM_FIELDS):
        errors.append(FieldError(f"{prefix}.{extra}", "unknown field"))

    sku = item.get("sku")
    if not isinstance(sku, str) or not SKU_RE.match(sku):
        errors.append(FieldError(f"{prefix}.sku", "must match ^[A-Z0-9][A-Z0-9-]{1,31}$"))

    quantity = item.get("quantity")
    if not _is_int(quantity) or not 1 <= quantity <= MAX_QUANTITY:
        errors.append(FieldError(f"{prefix}.quantity", f"must be an integer from 1 to {MAX_QUANTITY}"))

    price = item.get("unitPriceCents")
    if not _is_int(price) or not 0 <= price <= MAX_UNIT_PRICE_CENTS:
        errors.append(
            FieldError(
                f"{prefix}.unitPriceCents",
                f"must be an integer from 0 to {MAX_UNIT_PRICE_CENTS}",
            )
        )
    return errors


def validate_order(order: Any) -> list[FieldError]:
    """Validate an order payload; an empty list means it is valid."""
    if not isinstance(order, dict):
        return [FieldError("$", "body must be a JSON object")]

    errors: list[FieldError] = []
    for extra in sorted(set(order) - ORDER_FIELDS):
        errors.append(FieldError(extra, "unknown field"))

    customer_id = order.get("customerId")
    if not isinstance(customer_id, str) or not CUSTOMER_ID_RE.match(customer_id):
        errors.append(FieldError("customerId", "must match ^cus_[A-Za-z0-9]{4,60}$"))

    currency = order.get("currency")
    if currency not in CURRENCIES:
        errors.append(FieldError("currency", f"must be one of {', '.join(sorted(CURRENCIES))}"))

    items = order.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        errors.append(FieldError("items", f"must be a list of 1 to {MAX_ITEMS} items"))
    else:
        for index, item in enumerate(items):
            errors.extend(_validate_item(index, item))
        skus = [item.get("sku") for item in items if isinstance(item, dict)]
        duplicates = sorted({sku for sku in skus if isinstance(sku, str) and skus.count(sku) > 1})
        for sku in duplicates:
            errors.append(FieldError("items", f"duplicate sku {sku}; combine the quantities"))
    return errors


def order_total_cents(order: dict[str, Any]) -> int:
    """Total of a *validated* order."""
    return sum(item["quantity"] * item["unitPriceCents"] for item in order["items"])
