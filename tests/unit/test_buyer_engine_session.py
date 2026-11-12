from datetime import UTC, datetime, timedelta

from buyer_agent.engine_session import BuyerNegotiationSessionEngine
from commerce_core.contracts import (
    Mandate,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
    Preferences,
)


def mandate():
    return Mandate(
        run_id="run-1", category="consumer-electronics", product_hint="H", product_sku="SKU",
        quantity=12, max_total_cents=340000, deadline_days=14, min_warranty_months=12, min_returns_days=30,
        preferences=Preferences(),
    )


def offer():
    return Offer(
        offer_id="o1", request_id="req-1", seller_id="s1", seller_name="S1", seller_rating=1.0,
        line_items=[OfferLineItem(sku="SKU", name="I", quantity=12, unit_price_cents=200, list_unit_price_cents=220)],
        subtotal_cents=2400, shipping_cents=0, total_cents=2400, delivery_days=7, warranty_months=12, returns_days=30,
        valid_until=datetime.now(UTC) + timedelta(days=1), terms=OfferTerms(sustainability_certified=False),
        status=OfferStatus.PROPOSED, round=1,
    )


def test_buyer_session_budget_safety_and_trust():
    engine = BuyerNegotiationSessionEngine()
    m = mandate()
    assert engine.rfq_text_safe("Quote 12 units", m) is True
    assert engine.rfq_text_safe("total is 3400", m) is False
    trusted, err = engine.trusted_offer(
        offer(), mandate=m, expected_seller_id="s1", expected_request_id="req-1",
        validated_rating=4.9, validated_sustainability=True, now_utc=datetime.now(UTC),
    )
    assert err is None
    assert trusted is not None
    assert trusted.seller_rating == 4.9
