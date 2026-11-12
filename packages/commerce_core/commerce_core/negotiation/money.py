from __future__ import annotations

from collections.abc import Sequence

from commerce_core.contracts import Offer, OfferLineItem


def recompute_subtotal(line_items: Sequence[OfferLineItem]) -> int:
    return sum(
        (item.unit_price_cents + item.warranty_addon_cents) * item.quantity
        for item in line_items
    )


def recompute_total(
    subtotal_cents: int,
    shipping_cents: int,
    tax_cents: int = 0,
    fees_cents: int = 0,
) -> int:
    return subtotal_cents + shipping_cents + tax_cents + fees_cents


def validate_offer_amounts(offer: Offer) -> tuple[bool, str | None]:
    subtotal = recompute_subtotal(offer.line_items)
    if subtotal != offer.subtotal_cents:
        return False, "subtotal_cents does not match line items"
    total = recompute_total(
        offer.subtotal_cents, offer.shipping_cents, offer.tax_cents, offer.fees_cents
    )
    if total != offer.total_cents:
        return False, "total_cents does not match subtotal, shipping, tax, fees"
    return True, None
