from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from commerce_core.contracts import (
    Mandate,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
)
from pydantic import ValidationError


def make_offer(**overrides):
    now = datetime.now(UTC)
    data: dict[str, Any] = dict(  # noqa: C408
        offer_id="offer-1",
        request_id="rfq-1",
        seller_id="northwind-audio",
        seller_name="Northwind Audio",
        seller_rating=4.8,
        currency="USD",
        line_items=[
            OfferLineItem(
                sku="NC-700-BLK",
                name="Nimbus NC-700 ANC Headset",
                quantity=12,
                unit_price_cents=28100,
                list_unit_price_cents=31900,
                warranty_addon_cents=0,
                attributes={"color": "black"},
            )
        ],
        subtotal_cents=337200,
        shipping_cents=0,
        total_cents=337200,
        delivery_days=3,
        warranty_months=36,
        returns_days=45,
        valid_until=now + timedelta(minutes=30),
        terms=OfferTerms(
            sustainability_certified=True,
            stock_confidence=1.0,
            split_shipment=False,
        ),
        status=OfferStatus.FINAL,
        round=3,
        rationale="Final offer.",
    )
    data.update(overrides)
    return Offer(**data)


def test_offer_totals_must_match_line_items():
    with pytest.raises(ValidationError):
        make_offer(total_cents=1)


def test_offer_total_includes_tax_and_fees():
    item = OfferLineItem(
        sku="S", name="N", quantity=2,
        unit_price_cents=1000, list_unit_price_cents=1200,
    )
    offer = Offer(
        offer_id="o1", request_id="r1", seller_id="s1",
        seller_name="S", seller_rating=4.5, currency="USD",
        line_items=[item], subtotal_cents=2000, shipping_cents=300,
        tax_cents=150, fees_cents=50, total_cents=2500,
        delivery_days=3, warranty_months=36, returns_days=45,
        valid_until=datetime.now(UTC) + timedelta(hours=1),
    )
    assert offer.total_cents == 2500


def test_offer_rejects_wrong_total():
    item = OfferLineItem(
        sku="S", name="N", quantity=1,
        unit_price_cents=1000, list_unit_price_cents=1200,
    )
    with pytest.raises(ValidationError):
        Offer(
            offer_id="o1", request_id="r1", seller_id="s1",
            seller_name="S", seller_rating=4.5, currency="USD",
            line_items=[item], subtotal_cents=1000, shipping_cents=300,
            tax_cents=150, fees_cents=50, total_cents=9999,
            delivery_days=3, warranty_months=36, returns_days=45,
            valid_until=datetime.now(UTC) + timedelta(hours=1),
        )


def test_mandate_rejects_non_positive_quantity():
    with pytest.raises(ValidationError):
        Mandate(
            run_id="run-1",
            category="consumer-electronics",
            product_hint="Nimbus NC-700",
            quantity=0,
            max_total_cents=340000,
            deadline_days=14,
            min_warranty_months=24,
            min_returns_days=30,
        )


def test_mandate_keeps_budget_internal():
    mandate = Mandate(
        run_id="run-1",
        category="consumer-electronics",
        product_hint="Nimbus NC-700",
        quantity=12,
        max_total_cents=340000,
        deadline_days=14,
        min_warranty_months=24,
        min_returns_days=30,
    )
    dumped = mandate.model_dump()
    assert "max_total_cents" in dumped
