from datetime import UTC, datetime, timedelta

from commerce_core.contracts import Offer, OfferLineItem, OfferStatus, OfferTerms
from commerce_core.negotiation.trust import verify_offer_binding


def raw_offer(**updates):
    data = dict(
        offer_id="o1",
        request_id="req-1",
        seller_id="seller-a",
        seller_name="Seller A",
        seller_rating=1.0,
        line_items=[OfferLineItem(sku="SKU", name="I", quantity=12, unit_price_cents=200, list_unit_price_cents=220)],
        subtotal_cents=2400,
        shipping_cents=0,
        total_cents=2400,
        delivery_days=7,
        warranty_months=12,
        returns_days=30,
        valid_until=datetime.now(UTC) + timedelta(days=1),
        terms=OfferTerms(sustainability_certified=False, stock_confidence=0.5),
        status=OfferStatus.PROPOSED,
        round=1,
    )
    data.update(updates)
    return Offer(**data)


def test_verify_offer_binding_sanitizes_untrusted_claims():
    trusted, reject = verify_offer_binding(
        raw_offer(),
        expected_seller_id="seller-a",
        expected_request_id="req-1",
        expected_sku="SKU",
        validated_rating=4.8,
        validated_sustainability=True,
        now_utc=datetime.now(UTC),
    )
    assert reject is None
    assert trusted is not None
    assert trusted.seller_rating == 4.8
    assert trusted.terms.sustainability_certified is True


def test_verify_offer_binding_rejects_mismatch_and_expiry():
    _, reject = verify_offer_binding(
        raw_offer(seller_id="evil"),
        expected_seller_id="seller-a",
        expected_request_id="req-1",
        expected_sku="SKU",
        validated_rating=4.8,
        validated_sustainability=True,
        now_utc=datetime.now(UTC),
    )
    assert reject is not None
    assert reject.code == "binding_mismatch"

    _, reject = verify_offer_binding(
        raw_offer(valid_until=datetime.now(UTC) - timedelta(seconds=1)),
        expected_seller_id="seller-a",
        expected_request_id="req-1",
        expected_sku="SKU",
        validated_rating=4.8,
        validated_sustainability=True,
        now_utc=datetime.now(UTC),
    )
    assert reject is not None
    assert reject.code == "offer_expired"
