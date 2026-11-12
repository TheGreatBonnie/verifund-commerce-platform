"""Deterministic filters for marketplace product rows.

Rows come from the buyer agent's `/api/marketplace/products` aggregation and
carry `sku`, `category`, `unit_price_cents` (the cheapest available offer) and
an `offers` list. These checks stay deterministic so retrieval only ever ranks
products that already satisfy the shopper's hard constraints.
"""

from __future__ import annotations

from collections.abc import Collection


def price_cents(product: dict) -> int:
    value = product.get("unit_price_cents")
    return int(value) if isinstance(value, (int, float)) else 0


def offer_available(product: dict) -> bool:
    offers = product.get("offers") or []
    return any(
        isinstance(offer, dict) and offer.get("available") is True for offer in offers
    )


def currency(product: dict) -> str:
    offers = product.get("offers") or []
    if offers and isinstance(offers[0], dict):
        return str(offers[0].get("currency") or "USD")
    return "USD"


def seller_name(product: dict) -> str:
    seller = product.get("seller")
    if seller:
        return str(seller)
    offers = product.get("offers") or []
    if offers and isinstance(offers[0], dict):
        return str(offers[0].get("seller_name") or "")
    return ""


def matches_filters(
    product: dict,
    *,
    category: str | None = None,
    categories: Collection[str] | None = None,
    max_unit_price_cents: int | None = None,
    in_stock_only: bool = False,
) -> bool:
    """Return True when the row satisfies every hard constraint.

    ``categories`` is an exact, case-insensitive allow-list and takes
    precedence over the single ``category`` value. Substring matching is
    deliberately not used: "Laptop" must not match "Laptop Accessory".
    """
    product_category = str(product.get("category") or "").casefold()
    if categories is not None:
        if product_category not in {value.casefold() for value in categories}:
            return False
    elif category and product_category != category.casefold():
        return False
    if max_unit_price_cents is not None and price_cents(product) > max_unit_price_cents:
        return False
    if in_stock_only:
        return offer_available(product)
    return True
