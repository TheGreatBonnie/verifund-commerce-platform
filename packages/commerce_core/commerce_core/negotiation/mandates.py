from __future__ import annotations

from commerce_core.contracts import Mandate, Offer


def rfq_text_safe(text: str, max_total_cents: int) -> bool:
    if not text:
        return False
    budget_dollars = f"{max_total_cents // 100}"
    budget_cents = str(max_total_cents)
    return (
        "max_total_cents" not in text
        and budget_dollars not in text
        and budget_cents not in text
    )


def budget_allows(total_cents: int, max_total_cents: int) -> bool:
    return total_cents <= max_total_cents


def hard_constraint_failures(mandate: Mandate, offer: Offer) -> list[str]:
    failures: list[str] = []
    if not budget_allows(offer.total_cents, mandate.max_total_cents):
        failures.append("over_budget")
    if mandate.product_sku and any(item.sku != mandate.product_sku for item in offer.line_items):
        failures.append("sku_mismatch")
    if offer.warranty_months < mandate.min_warranty_months:
        failures.append("warranty_too_short")
    if offer.returns_days < mandate.min_returns_days:
        failures.append("returns_too_short")
    if offer.delivery_days > mandate.deadline_days:
        failures.append("delivery_too_slow")
    qty = sum(item.quantity for item in offer.line_items)
    if qty != mandate.quantity:
        failures.append("quantity_mismatch")
    return failures
