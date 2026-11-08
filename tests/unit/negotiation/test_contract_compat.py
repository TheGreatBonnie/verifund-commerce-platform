from datetime import UTC, datetime, timedelta

from commerce_core.contracts import (
    AcceptOffer,
    CounterOffer,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
)


def test_additive_contract_fields_are_optional():
    counter = CounterOffer(negotiation_round=2, target_unit_price_cents=100, requested_changes={})
    assert counter.in_response_to_offer_id is None
    accept = AcceptOffer(offer_id="o1", round=1, accepted_total_cents=100)
    assert accept.idempotency_key is None
    offer = Offer(
        offer_id="o1", request_id="r1", seller_id="s1", seller_name="S1", seller_rating=4.0,
        line_items=[OfferLineItem(sku="SKU", name="I", quantity=1, unit_price_cents=100, list_unit_price_cents=120)],
        subtotal_cents=100, shipping_cents=0, total_cents=100, delivery_days=1, warranty_months=0, returns_days=0,
        valid_until=datetime.now(UTC) + timedelta(days=1), terms=OfferTerms(), status=OfferStatus.PROPOSED, round=1,
    )
    assert getattr(offer, "parent_offer_id", None) is None
