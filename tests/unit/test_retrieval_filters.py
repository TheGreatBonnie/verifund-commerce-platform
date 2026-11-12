from __future__ import annotations

from commerce_core.retrieval.filters import (
    currency,
    matches_filters,
    offer_available,
    price_cents,
    seller_name,
)

PRODUCT = {
    "id": "MM-MACBOOK-AIR-M4-13",
    "sku": "MM-MACBOOK-AIR-M4-13",
    "name": "MacBook Air M4 13-inch",
    "category": "Electronics",
    "description": "Apple M4 - 16GB memory",
    "unit_price_cents": 99900,
    "original_unit_price_cents": 119900,
    "rating": 4.6,
    "offers": [
        {
            "seller_id": "northwind-audio",
            "seller_name": "Northwind Audio",
            "unit_price_cents": 99900,
            "currency": "USD",
            "available": True,
            "on_hand": 8,
        }
    ],
}

UNAVAILABLE = {
    **PRODUCT,
    "sku": "MM-4K-MONITOR-27",
    "unit_price_cents": 32900,
    "offers": [{**PRODUCT["offers"][0], "available": False, "on_hand": 0}],
}


def test_field_helpers_read_the_marketplace_row_shape():
    assert price_cents(PRODUCT) == 99900
    assert offer_available(PRODUCT) is True
    assert offer_available(UNAVAILABLE) is False
    assert currency(PRODUCT) == "USD"
    assert seller_name(PRODUCT) == "Northwind Audio"


def test_field_helpers_fall_back_safely_for_partial_rows():
    assert price_cents({}) == 0
    assert offer_available({}) is False
    assert currency({}) == "USD"
    assert seller_name({}) == ""


def test_category_filter_is_case_insensitive():
    assert matches_filters(PRODUCT, category="electronics") is True
    assert matches_filters(PRODUCT, category="Furniture") is False


def test_price_ceiling_excludes_expensive_products():
    assert matches_filters(PRODUCT, max_unit_price_cents=99900) is True
    assert matches_filters(PRODUCT, max_unit_price_cents=99899) is False


def test_in_stock_filter_requires_an_available_offer():
    assert matches_filters(UNAVAILABLE, in_stock_only=True) is False
    assert matches_filters(UNAVAILABLE, in_stock_only=False) is True


def test_filters_combine_conjunctively():
    assert (
        matches_filters(
            PRODUCT,
            category="Electronics",
            max_unit_price_cents=120000,
            in_stock_only=True,
        )
        is True
    )
    assert (
        matches_filters(
            PRODUCT,
            category="Electronics",
            max_unit_price_cents=50000,
            in_stock_only=True,
        )
        is False
    )


def test_seller_column_wins_over_the_offer_row():
    assert seller_name({**PRODUCT, "seller": "CircuitForge"}) == "CircuitForge"
