from pathlib import Path

import pytest
from commerce_core.contracts import (
    Mandate,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
)
from commerce_core.pricing import Quote, SellerPolicy, load_policy

PROFILE_DIR = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "templates"
)


@pytest.fixture
def northwind_policy() -> SellerPolicy:
    return load_policy(PROFILE_DIR / "northwind.yaml")


@pytest.fixture
def circuitforge_policy() -> SellerPolicy:
    return load_policy(PROFILE_DIR / "circuitforge.yaml")


@pytest.fixture
def aurora_policy() -> SellerPolicy:
    return load_policy(PROFILE_DIR / "aurora.yaml")


@pytest.fixture
def mandate() -> Mandate:
    return Mandate(
        run_id="run-1",
        category="consumer-electronics",
        product_hint="Nimbus NC-700",
        quantity=12,
        max_total_cents=340000,
        deadline_days=14,
        min_warranty_months=24,
        min_returns_days=30,
    )


def offer_from_quote(
    policy: SellerPolicy,
    quote: Quote,
    *,
    status: OfferStatus,
    round_number: int,
) -> Offer:
    line_item = OfferLineItem(
        sku=policy.sku,
        name=policy.product_name,
        quantity=12,
        unit_price_cents=quote.base_unit_price_cents,
        list_unit_price_cents=policy.list_unit_price_cents,
        warranty_addon_cents=quote.warranty_addon_cents,
        attributes={"color": policy.color},
    )
    return Offer(
        offer_id=f"{policy.seller_id}-{status.value}-{round_number}",
        request_id="rfq-1",
        seller_id=policy.seller_id,
        seller_name=policy.name,
        seller_rating=policy.rating,
        currency="USD",
        line_items=[line_item],
        subtotal_cents=quote.subtotal_cents,
        shipping_cents=0,
        total_cents=quote.total_cents,
        delivery_days=quote.delivery_days,
        warranty_months=quote.warranty_months,
        returns_days=policy.returns_days,
        valid_until=quote.valid_until,
        terms=OfferTerms(
            sustainability_certified=policy.sustainability_certified,
            stock_confidence=quote.stock_confidence,
            split_shipment=quote.split_shipment,
        ),
        status=status,
        round=round_number,
        rationale="Test offer.",
    )


@pytest.fixture
def final_offers(
    northwind_policy: SellerPolicy,
    circuitforge_policy: SellerPolicy,
    aurora_policy: SellerPolicy,
) -> list[Offer]:
    return [
        offer_from_quote(
            northwind_policy,
            northwind_policy.quote(12, 28100, 36),
            status=OfferStatus.FINAL,
            round_number=3,
        ),
        offer_from_quote(
            circuitforge_policy,
            circuitforge_policy.quote(12, 26312, 24),
            status=OfferStatus.FINAL,
            round_number=3,
        ),
        offer_from_quote(
            aurora_policy,
            aurora_policy.quote(12, 28333, 24, allow_split=True),
            status=OfferStatus.FINAL,
            round_number=3,
        ),
    ]


@pytest.fixture
def initial_offers(
    northwind_policy: SellerPolicy,
    circuitforge_policy: SellerPolicy,
    aurora_policy: SellerPolicy,
) -> list[Offer]:
    return [
        offer_from_quote(
            northwind_policy,
            northwind_policy.initial_quote(12),
            status=OfferStatus.PROPOSED,
            round_number=1,
        ),
        offer_from_quote(
            circuitforge_policy,
            circuitforge_policy.initial_quote(12),
            status=OfferStatus.PROPOSED,
            round_number=1,
        ),
        offer_from_quote(
            aurora_policy,
            aurora_policy.initial_quote(12),
            status=OfferStatus.PROPOSED,
            round_number=1,
        ),
    ]
