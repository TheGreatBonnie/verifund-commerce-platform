from datetime import datetime, timedelta, timezone

from commerce_core.binding import (
    binding_from_award,
    canonical_offer_binding,
    offer_hash,
)
from commerce_core.contracts import Currency, Offer, OfferLineItem


def _offer():
    return Offer(
        offer_id="o1", request_id="r1", seller_id="s1",
        seller_name="S", seller_rating=4.5, currency=Currency.USD,
        line_items=[OfferLineItem(
            sku="SKU-1", name="Sensor", quantity=2,
            unit_price_cents=1000, list_unit_price_cents=1200,
            warranty_addon_cents=100,
        )],
        subtotal_cents=2200, shipping_cents=300, tax_cents=150,
        fees_cents=50, total_cents=2700, delivery_days=3,
        warranty_months=12, returns_days=30,
        valid_until=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def test_binding_and_hash_are_deterministic():
    offer = _offer()
    binding = canonical_offer_binding(offer)
    assert binding["total_cents"] == 2700
    assert binding["round"] == 1
    h1 = offer_hash(binding)
    h2 = offer_hash(canonical_offer_binding(offer))
    assert h1 == h2
    assert len(h1) == 64


def test_binding_from_award_matches_offer():
    offer = _offer()
    award_binding = binding_from_award({
        "offer_id": "o1", "request_id": "r1", "seller_id": "s1",
        "currency": "USD", "offer_round": 1, "offer_valid_until": offer.valid_until,
        "line_items": [{"sku": "SKU-1", "name": "Sensor", "quantity": 2,
                        "unit_price_cents": 1000, "warranty_addon_cents": 100}],
        "subtotal_cents": 2200, "shipping_cents": 300, "tax_cents": 150,
        "fees_cents": 50, "total_cents": 2700, "delivery_days": 3,
        "warranty_months": 12, "returns_days": 30,
    })
    assert offer_hash(award_binding) == offer_hash(canonical_offer_binding(offer))


def test_mutated_price_changes_hash():
    offer = _offer()
    binding = canonical_offer_binding(offer)
    binding["line_items"][0]["unit_price_cents"] = 1100
    assert offer_hash(binding) != offer_hash(canonical_offer_binding(offer))
