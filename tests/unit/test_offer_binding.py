from datetime import UTC, datetime, timedelta

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
        valid_until=datetime.now(UTC) + timedelta(hours=1),
    )


def _v2_offer():
    offer = _offer()
    return offer.model_copy(
        update={
            "binding_version": 2,
            "line_items": [
                offer.line_items[0].model_copy(
                    update={"attributes": {"color": "#eaf0fb", "image_emoji": "💻"}}
                )
            ],
        }
    )


def _award_from(offer, binding_version: int) -> dict:
    return {
        "offer_id": offer.offer_id,
        "request_id": offer.request_id,
        "seller_id": offer.seller_id,
        "currency": "USD",
        "offer_round": offer.round,
        "offer_valid_until": offer.valid_until,
        "line_items": [i.model_dump(mode="json") for i in offer.line_items],
        "subtotal_cents": offer.subtotal_cents,
        "shipping_cents": offer.shipping_cents,
        "tax_cents": offer.tax_cents,
        "fees_cents": offer.fees_cents,
        "total_cents": offer.total_cents,
        "delivery_days": offer.delivery_days,
        "warranty_months": offer.warranty_months,
        "returns_days": offer.returns_days,
        "binding_version": binding_version,
    }


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


def test_v2_binding_binds_attributes_and_version():
    offer = _v2_offer()
    assert offer_hash(binding_from_award(_award_from(offer, 2))) == offer_hash(
        canonical_offer_binding(offer)
    )


def test_v1_verification_does_not_see_v2_attributes():
    offer = _v2_offer()
    assert offer_hash(binding_from_award(_award_from(offer, 1))) != offer_hash(
        canonical_offer_binding(offer)
    )


def test_mutated_price_changes_hash():
    offer = _offer()
    binding = canonical_offer_binding(offer)
    binding["line_items"][0]["unit_price_cents"] = 1100
    assert offer_hash(binding) != offer_hash(canonical_offer_binding(offer))
