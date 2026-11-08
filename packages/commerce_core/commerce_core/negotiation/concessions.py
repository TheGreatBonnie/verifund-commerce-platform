from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ALLOWED_REQUESTED_CHANGE_KEYS = {
    "warranty_months",
    "split_shipment",
    "shipping_cents",
    "delivery_days",
}


@dataclass(frozen=True)
class RejectResult:
    code: str
    reason: str
    retryable: bool = False


@dataclass(frozen=True)
class AllowedBuyerCounter:
    target_unit_price_cents: int
    requested_changes: dict[str, int | bool]
    rationale: str = ""


def validate_requested_changes(
    changes: dict[str, Any],
    allowed_warranty_months: list[int],
    allow_split: bool,
) -> tuple[dict[str, int | bool] | None, str | None]:
    unknown = set(changes) - ALLOWED_REQUESTED_CHANGE_KEYS
    if unknown:
        return None, f"unsupported requested changes: {sorted(unknown)}"
    normalized: dict[str, int | bool] = {}
    if "warranty_months" in changes:
        value = changes["warranty_months"]
        if isinstance(value, bool) or not isinstance(value, int):
            return None, "warranty_months must be an integer"
        if value not in allowed_warranty_months:
            return None, "requested warranty is not supported"
        normalized["warranty_months"] = value
    if "split_shipment" in changes:
        value = changes["split_shipment"]
        if not isinstance(value, bool):
            return None, "split_shipment must be a boolean"
        if value and not allow_split:
            return None, "split shipment is not supported"
        normalized["split_shipment"] = value
    if "shipping_cents" in changes:
        value = changes["shipping_cents"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None, "shipping_cents must be a non-negative integer"
        normalized["shipping_cents"] = value
    if "delivery_days" in changes:
        value = changes["delivery_days"]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None, "delivery_days must be a positive integer"
        normalized["delivery_days"] = value
    return normalized, None


def constrain_buyer_counter(
    *,
    target_unit_price_cents: int,
    allowed_targets: list[int],
    requested_changes: dict[str, Any],
    allowed_warranty_months: list[int],
    allow_split: bool,
    rationale: str = "",
) -> tuple[AllowedBuyerCounter | None, RejectResult | None]:
    if target_unit_price_cents not in allowed_targets:
        return None, RejectResult(
            "unsupported_constraint", "counter target is outside allowed list"
        )
    normalized, err = validate_requested_changes(
        requested_changes, allowed_warranty_months, allow_split
    )
    if err is not None or normalized is None:
        return None, RejectResult("unsupported_constraint", err or "invalid requested changes")
    return AllowedBuyerCounter(target_unit_price_cents, normalized, rationale), None
