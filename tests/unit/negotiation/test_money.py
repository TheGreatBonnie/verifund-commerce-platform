from datetime import UTC, datetime, timedelta

from commerce_core.contracts import Offer, OfferLineItem, OfferStatus, OfferTerms
from commerce_core.negotiation.money import (
    recompute_subtotal,
    recompute_total,
    validate_offer_amounts,
)


def sample_offer(**updates):
    data = {
        "offer_id": "offer-1",
        "request_id": "rfq-1",
        "seller_id": "seller-a",
        "seller_name": "Seller A",
        "seller_rating": 4.5,
        "line_items": [
            OfferLineItem(
                sku="SKU",
                name="Item",
                quantity=2,
                unit_price_cents=1000,
                list_unit_price_cents=1200,
                warranty_addon_cents=50,
            )
        ],
        "subtotal_cents": 2100,
        "shipping_cents": 100,
        "tax_cents": 20,
        "fees_cents": 5,
        "total_cents": 2225,
        "delivery_days": 3,
        "warranty_months": 12,
        "returns_days": 30,
        "valid_until": datetime.now(UTC) + timedelta(days=1),
        "terms": OfferTerms(),
        "status": OfferStatus.PROPOSED,
        "round": 1,
    }
    data.update(updates)
    return Offer(**data)


def test_recompute_subtotal_and_total():
    offer = sample_offer()
    assert recompute_subtotal(offer.line_items) == 2100
    assert recompute_total(2100, 100, 20, 5) == 2225


def test_validate_offer_amounts_accepts_consistent_offer():
    ok, reason = validate_offer_amounts(sample_offer())
    assert ok is True
    assert reason is None


def test_validate_offer_amounts_rejects_inconsistent_total():
    offer = sample_offer().model_copy(update={"total_cents": 9999})
    ok, reason = validate_offer_amounts(offer)
    assert ok is False
    assert "total" in (reason or "").lower()
