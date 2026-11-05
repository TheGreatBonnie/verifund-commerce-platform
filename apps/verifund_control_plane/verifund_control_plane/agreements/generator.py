from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from verifund_contracts.models import (
    AwardRequest,
    EvidenceKind,
)
from verifund_contracts.terms import validate_requirements


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def validate_award(award: AwardRequest, now: datetime) -> None:
    if now > award.offer_valid_until:
        raise ValueError("offer_expired")
    if award.currency != "USD":
        raise ValueError("invalid_terms")
    if award.delivery_days < 1:
        raise ValueError("invalid_terms")
    if EvidenceKind.DELIVERY_CONFIRMATION not in award.evidence_required:
        raise ValueError("invalid_terms")


def build_terms(award: AwardRequest, now: datetime) -> dict[str, Any]:
    items = []
    subtotal = 0
    for li in award.line_items:
        line_total = (li.unit_price_cents + li.warranty_addon_cents) * li.quantity
        subtotal += line_total
        items.append({
            "sku": li.sku,
            "name": li.name,
            "quantity": li.quantity,
            "unit_price_cents": li.unit_price_cents,
            "warranty_addon_cents": li.warranty_addon_cents,
            "line_total_cents": line_total,
            "attributes": dict(li.attributes or {}),
        })
    if subtotal != award.amount_cents - award.shipping_cents - award.tax_cents - award.fees_cents:
        raise ValueError("invalid_terms")
    if subtotal != sum(
        (li.unit_price_cents + li.warranty_addon_cents) * li.quantity
        for li in award.line_items
    ):
        raise ValueError("invalid_terms")
    # Creation floors for the requirement catalog (spec §3.1.1). Enforced only
    # when a catalog is authored; grandfathered awards carry none.
    if award.requirements:
        validate_requirements(list(award.requirements))
    return {
        "schema": "verifund.agreement.v1",
        "agreement_type": "goods",
        "terms_version": 1,
        "platform_terms_version": "v1",
        "parties": {
            "buyer": {"id": award.buyer_id, "display_name": award.buyer_display_name},
            "seller": {"id": award.seller_id, "display_name": award.seller_display_name},
        },
        "offer": {
            "offer_id": award.offer_id,
            "request_id": award.request_id,
            "offer_round": award.offer_round,
            "offer_hash": award.offer_hash,
            "offer_valid_until": _iso(award.offer_valid_until),
        },
        "items": items,
        "totals": {
            "currency": award.currency,
            "subtotal_cents": subtotal,
            "shipping_cents": award.shipping_cents,
            "tax_cents": award.tax_cents,
            "fees_cents": award.fees_cents,
            "total_cents": award.amount_cents,
        },
        "delivery": {"delivery_days": award.delivery_days, "starts_on": "FUNDING_CONFIRMED"},
        "warranty_months": award.warranty_months,
        "returns_days": award.returns_days,
        "inspection": {
            "period_hours": award.inspection_period_hours,
            "starts_on": award.inspection_starts_on,
        },
        "requirements": [
            r.model_dump(mode="json") for r in award.requirements
        ],
        # DEPRECATED mirror of `requirements`; retained for grandfathered callers.
        "evidence_required": [e.value for e in award.evidence_required],
        "remedies": award.remedies.model_dump(mode="json"),
        "dispute_window_hours": award.dispute_window_hours,
    }

from verifund_contracts.terms import apply_change_set, validate_terms

__all__ = ["apply_change_set", "build_terms", "validate_award", "validate_terms"]
