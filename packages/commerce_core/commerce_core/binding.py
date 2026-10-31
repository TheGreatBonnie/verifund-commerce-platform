from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from commerce_core.contracts import Offer


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _iso(value: datetime | str) -> str:
    """Normalize to second-precision UTC so buyer, seller, and control plane agree.

    Award payloads may arrive as second-precision `Z` strings while in-process
    values carry microseconds. Truncating to seconds makes the two forms hash
    identically; sub-second precision is not part of the commercial terms.
    """
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_offer_binding(offer: Offer) -> dict[str, Any]:
    return {
        "offer_id": offer.offer_id,
        "request_id": offer.request_id,
        "seller_id": offer.seller_id,
        "currency": offer.currency.value if hasattr(offer.currency, "value") else str(offer.currency),
        "round": offer.round,
        "line_items": [
            {
                "sku": item.sku,
                "name": item.name,
                "quantity": item.quantity,
                "unit_price_cents": item.unit_price_cents,
                "warranty_addon_cents": item.warranty_addon_cents,
            }
            for item in offer.line_items
        ],
        "subtotal_cents": offer.subtotal_cents,
        "shipping_cents": offer.shipping_cents,
        "tax_cents": offer.tax_cents,
        "fees_cents": offer.fees_cents,
        "total_cents": offer.total_cents,
        "delivery_days": offer.delivery_days,
        "warranty_months": offer.warranty_months,
        "returns_days": offer.returns_days,
        "offer_valid_until": _iso(offer.valid_until),
    }


def binding_from_award(award: dict[str, Any]) -> dict[str, Any]:
    line_items = [
        {
            "sku": item["sku"],
            "name": item["name"],
            "quantity": item["quantity"],
            "unit_price_cents": item["unit_price_cents"],
            "warranty_addon_cents": item.get("warranty_addon_cents", 0),
        }
        for item in award["line_items"]
    ]
    subtotal = award.get("subtotal_cents")
    if subtotal is None:
        subtotal = sum(
            (item["unit_price_cents"] + item["warranty_addon_cents"]) * item["quantity"]
            for item in line_items
        )
    return {
        "offer_id": award["offer_id"],
        "request_id": award["request_id"],
        "seller_id": award["seller_id"],
        "currency": award["currency"],
        "round": award["offer_round"],
        "line_items": line_items,
        "subtotal_cents": subtotal,
        "shipping_cents": award["shipping_cents"],
        "tax_cents": award["tax_cents"],
        "fees_cents": award["fees_cents"],
        "total_cents": award.get("total_cents", award.get("amount_cents")),
        "delivery_days": award["delivery_days"],
        "warranty_months": award["warranty_months"],
        "returns_days": award["returns_days"],
        "offer_valid_until": _iso(award["offer_valid_until"]),
    }


def offer_hash(binding: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(binding)).hexdigest()
