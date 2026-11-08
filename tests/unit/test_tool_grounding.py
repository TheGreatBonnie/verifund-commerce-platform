"""TDD for #9 tool-use grounding (read-only, bind_tools, empty+continue)."""
from buyer_agent.planner import (
    build_buyer_tools,
    get_market_price,
    get_seller_summary,
)
from buyer_agent.planner import (
    search_products as buyer_search_products,
)
from seller_agent.planner import build_seller_tools, get_policy_bounds, get_stock


def _products():
    return [
        {"sku": "SKU-LAPTOP", "name": "MacBook Air", "description": "M4 16GB memory 256GB SSD", "category": "consumer-electronics", "unit_price_cents": 97900, "seller": "Seller A", "seller_id": "s1", "rating": 4.8, "sustainability_certified": True, "delivery_days": 5, "offers": [{"available": True, "unit_price_cents": 97900}]},
        {"sku": "SKU-WATCH", "name": "Smartwatch Series 10", "description": "GPS watch", "category": "consumer-electronics", "unit_price_cents": 39900, "seller": "Seller B", "seller_id": "s2", "rating": 4.2, "offers": [{"available": True, "unit_price_cents": 39900}]},
    ]


def test_search_products_returns_ranked_copies():
    hits = buyer_search_products("laptop programming", _products())
    assert hits, "expected hits"
    assert hits[0]["sku"] == "SKU-LAPTOP"
    assert hits[0] is not _products()[0]  # copy, not original ref
    assert all(h in _products() or h["sku"] in {"SKU-LAPTOP", "SKU-WATCH"} for h in hits)  # no invented rows


def test_search_products_empty_on_no_match():
    assert buyer_search_products("nonexistentxyz", _products()) == []


def test_get_market_price_aggregates():
    result = get_market_price("SKU-LAPTOP", _products())
    assert result["status"] == "ok"
    assert result["min_unit_price_cents"] == 97900
    assert result["count"] == 1
    missing = get_market_price("NOPE", _products())
    assert missing["status"] == "unavailable"


def test_get_seller_summary():
    s = get_seller_summary("s1", _products())
    assert s["status"] == "ok"
    assert s["rating"] == 4.8
    assert s["sustainability_certified"] is True
    missing = get_seller_summary("nope", _products())
    assert missing["status"] == "unavailable"


def test_buyer_tools_list_has_three():
    tools = build_buyer_tools(_products())
    names = {t.name for t in tools}
    assert names == {"search_products", "get_market_price", "get_seller_summary"}


def test_seller_get_stock_and_bounds():
    stock = {"SKU-LAPTOP": {"on_hand": 5, "incoming": 2, "incoming_days": 7}}
    s1 = get_stock("SKU-LAPTOP", stock)
    assert s1["status"] == "ok" and s1["on_hand"] == 5
    assert get_stock("NOPE", stock)["status"] == "unavailable"

    from commerce_core.pricing import SellerPolicy
    policy = SellerPolicy(
        seller_id="s1", name="Seller A", tagline="t", categories=["consumer-electronics"],
        list_unit_price_cents=19900, floor_unit_price_cents=18000, initial_unit_price_cents=18900,
        concession_ladder_cents=[18500], base_warranty_months=12, warranty_addons_cents={12: 0, 24: 1500},
        returns_days=30, delivery_days=5, stock_on_hand=5, sustainability_certified=True, rating=4.5,
        sku="SKU-LAPTOP", product_name="MacBook Air",
    )
    bounds = get_policy_bounds("SKU-LAPTOP", policy)
    assert bounds["status"] == "ok"
    assert bounds["floor_unit_price_cents"] == 18000
    assert 24 in bounds["allowed_warranty_months"]
    assert bounds["max_rounds"] == policy.max_rounds
    assert get_policy_bounds("NOPE", policy)["status"] == "unavailable"


def test_seller_tools_list_has_two():
    tools = build_seller_tools({}, None)
    names = {t.name for t in tools}
    assert names == {"get_stock", "get_policy_bounds"}
