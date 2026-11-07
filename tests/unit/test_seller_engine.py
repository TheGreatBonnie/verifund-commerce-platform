from commerce_core.contracts import OfferStatus
from seller_agent.engine import SellerNegotiationEngine
from seller_agent.planner import SellerDecision


def test_seller_engine_validate_and_status():
    engine = SellerNegotiationEngine()
    ok = engine.validate_decision(
        SellerDecision(action="counter", unit_price_cents=18500, warranty_months=12, rationale="x"),
        allowed_prices=[18500],
        allowed_warranty_months=[12, 24],
        floor_unit_price_cents=18000,
    )
    assert ok is True
    bad = engine.validate_decision(
        SellerDecision(action="counter", unit_price_cents=18400, warranty_months=12, rationale="x"),
        allowed_prices=[18500],
        allowed_warranty_months=[12, 24],
        floor_unit_price_cents=18000,
    )
    assert bad is False
    assert engine.status_for_offer(
        round=3, max_rounds=3, unit_price_cents=18500, floor_unit_price_cents=18000, next_prices=[18400]
    ) == OfferStatus.FINAL
