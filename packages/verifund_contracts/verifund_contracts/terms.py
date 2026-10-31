from __future__ import annotations

import copy
from typing import Any

from verifund_contracts.models import AwardRequest


def validate_terms(terms: dict[str, Any], award: AwardRequest | None = None) -> None:
    if terms.get("schema") != "verifund.agreement.v1":
        raise ValueError("invalid_terms")
    if terms.get("agreement_type") != "goods":
        raise ValueError("invalid_terms")
    if terms.get("terms_version") != 1:
        raise ValueError("invalid_terms")
    parties = terms.get("parties", {})
    offer = terms.get("offer", {})
    if award is not None:
        if parties.get("buyer", {}).get("id") != award.buyer_id:
            raise ValueError("invalid_terms")
        if parties.get("seller", {}).get("id") != award.seller_id:
            raise ValueError("invalid_terms")
        if offer.get("offer_id") != award.offer_id:
            raise ValueError("invalid_terms")
        if offer.get("offer_round") != award.offer_round:
            raise ValueError("offer_mismatch")
        if offer.get("offer_hash") != award.offer_hash:
            raise ValueError("offer_mismatch")
    totals = terms.get("totals", {})
    if totals.get("currency") != "USD":
        raise ValueError("invalid_terms")
    items = terms.get("items", [])
    if not items:
        raise ValueError("invalid_terms")
    skus = [i.get("sku") for i in items]
    if len(set(skus)) != len(skus):
        raise ValueError("invalid_terms")
    subtotal = sum(
        (i.get("unit_price_cents", 0) + i.get("warranty_addon_cents", 0)) * i.get("quantity", 0)
        for i in items
    )
    if subtotal != totals.get("subtotal_cents"):
        raise ValueError("invalid_terms")
    if totals.get("total_cents") != (
        totals.get("subtotal_cents", 0) + totals.get("shipping_cents", 0)
        + totals.get("tax_cents", 0) + totals.get("fees_cents", 0)
    ):
        raise ValueError("invalid_terms")
    if any(i.get("quantity", 0) <= 0 for i in items):
        raise ValueError("invalid_terms")
    if any(i.get("unit_price_cents", 0) < 0 for i in items):
        raise ValueError("invalid_terms")
    delivery = terms.get("delivery", {})
    if delivery.get("delivery_days", 0) < 1:
        raise ValueError("invalid_terms")
    inspection = terms.get("inspection", {})
    if inspection.get("period_hours", 0) < 1:
        raise ValueError("invalid_terms")
    evidence = terms.get("evidence_required", [])
    if not evidence or "delivery_confirmation" not in evidence:
        raise ValueError("invalid_terms")
    if terms.get("dispute_window_hours", 0) < 1:
        raise ValueError("invalid_terms")
    remedies = terms.get("remedies", {})
    if not all(k in remedies for k in ("non_delivery", "late_delivery", "damaged_goods")):
        raise ValueError("invalid_terms")
    if terms.get("totals", {}).get("total_cents", 0) != totals.get("subtotal_cents", 0) + totals.get("shipping_cents", 0) + totals.get("tax_cents", 0) + totals.get("fees_cents", 0):
        raise ValueError("invalid_terms")
    if award is not None and terms.get("totals", {}).get("total_cents", 0) != award.amount_cents:
        raise ValueError("invalid_terms")


def apply_change_set(base_terms: dict[str, Any], change_set: Any) -> dict[str, Any]:
    terms = copy.deepcopy(base_terms)
    items_by_sku = {i["sku"]: i for i in terms["items"]}
    if isinstance(change_set, (list, tuple)):
        operations = change_set
    elif hasattr(change_set, "operations"):
        operations = change_set.operations
    else:
        operations = [change_set]
    for op in operations:
        kind = op.op.value if hasattr(op.op, "value") else str(op.op)

        def _required(name: str, _op=op):
            value = getattr(_op, name)
            if value is None:
                raise ValueError("invalid_change_set")
            return value

        if kind == "set_unit_price":
            if op.sku not in items_by_sku:
                raise ValueError("invalid_change_set")
            items_by_sku[op.sku]["unit_price_cents"] = _required("unit_price_cents")
            items_by_sku[op.sku]["line_total_cents"] = (
                items_by_sku[op.sku]["unit_price_cents"]
                + items_by_sku[op.sku]["warranty_addon_cents"]
            ) * items_by_sku[op.sku]["quantity"]
        elif kind == "set_quantity":
            if op.sku not in items_by_sku:
                raise ValueError("invalid_change_set")
            quantity = _required("quantity")
            if quantity <= 0:
                raise ValueError("invalid_change_set")
            items_by_sku[op.sku]["quantity"] = quantity
            items_by_sku[op.sku]["line_total_cents"] = (
                items_by_sku[op.sku]["unit_price_cents"]
                + items_by_sku[op.sku]["warranty_addon_cents"]
            ) * quantity
        elif kind == "set_shipping":
            terms["totals"]["shipping_cents"] = _required("shipping_cents")
        elif kind == "set_tax":
            terms["totals"]["tax_cents"] = _required("tax_cents")
        elif kind == "set_fees":
            terms["totals"]["fees_cents"] = _required("fees_cents")
        elif kind == "set_delivery_days":
            terms["delivery"]["delivery_days"] = _required("delivery_days")
        elif kind == "set_warranty_months":
            terms["warranty_months"] = _required("warranty_months")
        elif kind == "set_returns_days":
            terms["returns_days"] = _required("returns_days")
        elif kind == "set_inspection_period":
            terms["inspection"]["period_hours"] = _required("inspection_period_hours")
        elif kind == "set_evidence_required":
            evidence = _required("evidence_required")
            evidence_values = [e.value if hasattr(e, "value") else str(e) for e in evidence]
            if "delivery_confirmation" not in evidence_values:
                raise ValueError("invalid_change_set")
            terms["evidence_required"] = evidence_values
        elif kind == "set_remedies":
            remedies = _required("remedies")
            terms["remedies"] = remedies.model_dump(mode="json")
            if getattr(op, "dispute_window_hours", None) is not None:
                terms["dispute_window_hours"] = op.dispute_window_hours
        else:
            raise ValueError("invalid_change_set")
        # recompute subtotal/total
        terms["totals"]["subtotal_cents"] = sum(i["line_total_cents"] for i in terms["items"])
        terms["totals"]["total_cents"] = (
            terms["totals"]["subtotal_cents"] + terms["totals"]["shipping_cents"]
            + terms["totals"]["tax_cents"] + terms["totals"]["fees_cents"]
        )
    return terms
