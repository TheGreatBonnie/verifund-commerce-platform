"""TDD for enhancements 1 (strategy) and 11 (RAG substring grounding)."""
import pytest
from buyer_agent.planner import CounterChoice, mandate_from_text
from seller_agent.planner import SellerDecision


def test_counter_choice_accepts_strategy():
    choice = CounterChoice(target_unit_price_cents=18300, requested_changes={}, rationale="x", strategy="competitive")
    assert choice.strategy == "competitive"


def test_counter_choice_rejects_unknown_strategy():
    with pytest.raises(Exception):
        CounterChoice(target_unit_price_cents=18300, requested_changes={}, rationale="x", strategy="aggressive")


def test_seller_decision_accepts_strategy():
    dec = SellerDecision(action="counter", unit_price_cents=18500, warranty_months=12, rationale="x", strategy="value-based")
    assert dec.strategy == "value-based"


def test_seller_decision_rejects_unknown_strategy():
    with pytest.raises(Exception):
        SellerDecision(action="counter", unit_price_cents=18500, warranty_months=12, rationale="x", strategy="nope")


def test_scripted_planners_default_strategy_collaborative():
    import asyncio
    from commerce_core.contracts import Mandate, Preferences, Offer, OfferLineItem, OfferStatus, OfferTerms, RFQ, CounterOffer
    from seller_agent.planner import ScriptedSellerPlanner
    from buyer_agent.planner import ScriptedBuyerPlanner

    # Buyer scripted: needs minimal Offer + Mandate
    mandate = Mandate(run_id="r", category="consumer-electronics", product_hint="H", quantity=12, max_total_cents=340000, deadline_days=14, min_warranty_months=12, min_returns_days=30, preferences=Preferences())
    offer = Offer(offer_id="o1", request_id="r1", seller_id="s1", seller_name="S1", seller_rating=4.0, line_items=[OfferLineItem(sku="SKU", name="I", quantity=12, unit_price_cents=200, list_unit_price_cents=220)], subtotal_cents=2400, shipping_cents=0, total_cents=2400, delivery_days=7, warranty_months=12, returns_days=30, valid_until="2030-01-01T00:00:00Z", terms=OfferTerms(), status=OfferStatus.PROPOSED, round=1)
    choice = asyncio.run(ScriptedBuyerPlanner().choose_counter(offer, mandate, [18300], 2))
    assert choice.strategy == "collaborative"


def test_retrieve_candidates_grounding():
    from buyer_agent.planner import retrieve_candidates

    products = [
        {"sku": "SKU-LAPTOP", "name": "MacBook Air", "description": "M4 16GB memory 256GB SSD", "category": "consumer-electronics", "unit_price_cents": 97900, "seller": "Seller A", "offers": [{"available": True}]},
        {"sku": "SKU-WATCH", "name": "Smartwatch Series 10", "description": "GPS watch", "category": "consumer-electronics", "unit_price_cents": 39900, "seller": "Seller B", "offers": [{"available": True}]},
    ]
    hits = retrieve_candidates("laptop for programming", products)
    assert hits, "expected at least one candidate"
    assert all(h in products for h in hits) or all(isinstance(h, dict) for h in hits)
    assert hits[0]["sku"] == "SKU-LAPTOP", f"expected laptop first, got {hits[0]['sku']}"


def test_mandate_from_text_uses_catalog_hint():
    from buyer_agent.planner import mandate_from_text

    products = [
        {"sku": "SKU-LAPTOP", "name": "MacBook Air", "description": "M4 16GB memory", "category": "consumer-electronics", "unit_price_cents": 97900, "seller": "Seller A", "offers": [{"available": True}]},
    ]
    m = mandate_from_text("Find a laptop for programming", products)
    assert m.product_sku == "SKU-LAPTOP"
    assert "MacBook" in m.product_hint
