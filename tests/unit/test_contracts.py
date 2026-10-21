from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from commerce_core.contracts import (
    Mandate,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
)


def make_offer(**overrides):
    now = datetime.now(UTC)
    data = dict(
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
