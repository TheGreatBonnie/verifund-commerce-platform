from __future__ import annotations

from copy import deepcopy

import httpx
import pytest
import respx
from orchestrator_agent.marketplace import (
    fetch_marketplace_products,
    filter_and_rank_products,
    shape_search_result,
)

MACBOOK = {
    "id": "MM-MACBOOK-AIR-M4-13",
    "sku": "MM-MACBOOK-AIR-M4-13",
    "name": "MacBook Air M4 13-inch",
    "category": "Electronics",
    "description": "Apple M4 · 16GB memory · 256GB SSD · Space Gray",
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
            "incoming": 0,
        }
    ],
}

MONITOR = {
    "id": "MM-4K-MONITOR-27",
    "sku": "MM-4K-MONITOR-27",
    "name": "27-inch 4K USB-C Monitor",
    "category": "Electronics",
    "description": "4K UHD · USB-C hub · Height adjustable",
    "unit_price_cents": 49900,
    "original_unit_price_cents": None,
    "rating": 4.7,
    "offers": [
        {
            "seller_id": "northwind-audio",
            "seller_name": "Northwind Audio",
            "unit_price_cents": 49900,
            "currency": "USD",
            "available": False,
            "on_hand": 0,
            "incoming": 0,
        }
    ],
}

CHAIR = {
    "id": "MM-ERGONOMIC-MESH-CHAIR",
    "sku": "MM-ERGONOMIC-MESH-CHAIR",
    "name": "Ergonomic Mesh Office Chair",
    "category": "Home & Living",
    "description": "Adjustable lumbar support · Breathable mesh",
    "unit_price_cents": 27900,
    "original_unit_price_cents": 34900,
    "rating": 4.6,
    "offers": [
        {
            "seller_id": "aurora-supply",
            "seller_name": "Aurora Supply",
            "unit_price_cents": 27900,
            "currency": "USD",
            "available": True,
            "on_hand": 4,
            "incoming": 0,
        }
    ],
}

CATALOG = [MACBOOK, MONITOR, CHAIR]


def skus(products: list[dict]) -> list[str]:
    return [product["sku"] for product in products]


def test_headline_prompt_selects_the_macbook_only():
    products = filter_and_rank_products(
        CATALOG,
        query="laptop",
        use_case="programming",
        max_unit_price_cents=150000,
    )
    assert skus(products) == ["MM-MACBOOK-AIR-M4-13"]
    shaped = shape_search_result(
        {"query": "laptop", "use_case": "programming"}, products
    )
    assert shaped["total_candidates"] == 1


def test_literal_prompt_tolerates_filler_words():
    products = filter_and_rank_products(
        CATALOG,
        query="Find me a good laptop for programming under $1500",
        max_unit_price_cents=150000,
    )
    assert skus(products) == ["MM-MACBOOK-AIR-M4-13"]


def test_notebook_synonym_matches_the_macbook():
    products = filter_and_rank_products(CATALOG, query="notebook")
    assert skus(products) == ["MM-MACBOOK-AIR-M4-13"]


def test_use_case_ranks_without_filtering_other_categories():
    products = filter_and_rank_products(CATALOG, use_case="programming")
    assert products[0]["sku"] == "MM-MACBOOK-AIR-M4-13"
    assert set(skus(products)) == {
        "MM-MACBOOK-AIR-M4-13",
        "MM-4K-MONITOR-27",
        "MM-ERGONOMIC-MESH-CHAIR",
    }


def test_price_ceiling_excludes_the_macbook():
    products = filter_and_rank_products(CATALOG, max_unit_price_cents=90000)
    assert "MM-MACBOOK-AIR-M4-13" not in skus(products)


def test_in_stock_filter_excludes_unavailable_products():
    products = filter_and_rank_products(CATALOG, in_stock_only=True)
    assert "MM-4K-MONITOR-27" not in skus(products)
    assert "MM-MACBOOK-AIR-M4-13" in skus(products)


def test_results_are_grounded_and_inputs_are_not_mutated():
    before = deepcopy(CATALOG)
    products = filter_and_rank_products(CATALOG, query="laptop")
    assert set(skus(products)) <= {product["sku"] for product in CATALOG}
    assert CATALOG == before


def test_ordering_is_deterministic_for_equal_scores():
    products = [
        {
            "sku": "B-2",
            "name": "Widget B",
            "category": "Tools",
            "description": "",
            "unit_price_cents": 200,
            "original_unit_price_cents": None,
            "rating": 4.0,
            "offers": [{"available": True, "seller_name": "Seller"}],
        },
        {
            "sku": "A-1",
            "name": "Widget A",
            "category": "Tools",
            "description": "",
            "unit_price_cents": 200,
            "original_unit_price_cents": None,
            "rating": 4.0,
            "offers": [{"available": True, "seller_name": "Seller"}],
        },
        {
            "sku": "C-0",
            "name": "Widget C",
            "category": "Tools",
            "description": "",
            "unit_price_cents": 100,
            "original_unit_price_cents": None,
            "rating": 4.0,
            "offers": [{"available": True, "seller_name": "Seller"}],
        },
    ]
    first = skus(filter_and_rank_products(products))
    second = skus(filter_and_rank_products(products))
    assert first == second == ["C-0", "A-1", "B-2"]


def test_empty_input_and_empty_match_return_nothing():
    assert filter_and_rank_products([]) == []
    assert filter_and_rank_products(CATALOG, query="zzzzzz") == []


def test_match_rationale_is_deterministic_and_grounded():
    product = filter_and_rank_products(
        [MACBOOK], query="laptop", use_case="programming"
    )[0]
    assert product["match_rationale"] == [
        "query:laptop:name",
        "use_case:programming:name",
        "offers:available",
        "rating:4.6",
        "price:discounted",
    ]


def test_currency_is_derived_from_the_first_offer_and_defaults_to_usd():
    eur = {
        **MONITOR,
        "sku": "EUR-1",
        "offers": [{**MONITOR["offers"][0], "currency": "EUR"}],
    }
    no_offers = {**MONITOR, "sku": "USD-1", "offers": []}
    shaped = shape_search_result({}, filter_and_rank_products([eur, no_offers]))
    by_sku = {product["sku"]: product for product in shaped["products"]}
    assert by_sku["EUR-1"]["currency"] == "EUR"
    assert by_sku["USD-1"]["currency"] == "USD"


@respx.mock
async def test_fetch_uses_the_internal_token_and_forwards_category_only():
    route = respx.get("http://buyer/api/marketplace/products").mock(
        return_value=httpx.Response(200, json={"products": [MACBOOK]})
    )

    products = await fetch_marketplace_products(
        base_url="http://buyer/",
        internal_token="internal-token",
        timeout=2.0,
        category="Electronics",
    )

    assert products == [MACBOOK]
    request = route.calls[0].request
    assert request.headers["x-verifund-internal-token"] == "internal-token"
    assert request.url.params["category"] == "Electronics"
    assert "q" not in request.url.params


@respx.mock
async def test_fetch_rejects_a_malformed_payload():
    respx.get("http://buyer/api/marketplace/products").mock(
        return_value=httpx.Response(200, json={"products": "nope"})
    )
    with pytest.raises(ValueError):
        await fetch_marketplace_products(
            base_url="http://buyer",
            internal_token="internal-token",
            timeout=2.0,
        )


@respx.mock
async def test_fetch_raises_on_an_upstream_error():
    respx.get("http://buyer/api/marketplace/products").mock(
        return_value=httpx.Response(502)
    )
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_marketplace_products(
            base_url="http://buyer",
            internal_token="internal-token",
            timeout=2.0,
        )


def test_shape_reports_pre_limit_total_and_truncates():
    ranked = filter_and_rank_products(CATALOG)
    shaped = shape_search_result({"category": "Electronics"}, ranked, limit=2)
    assert shaped["total_candidates"] == len(ranked)
    assert len(shaped["products"]) == 2
    assert shaped["applied_filters"] == {"category": "Electronics"}
