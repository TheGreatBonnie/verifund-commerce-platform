"""The price term must separate offers that all fit the budget."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from commerce_core.contracts import (
    Currency,
    Mandate,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
    Preferences,
)
from commerce_core.scoring import rank_offers, score_offer


def _mandate() -> Mandate:
    return Mandate(
        run_id="run-1",
        buyer_id="buyer",
        category="MacBook",
        product_hint="MacBook Air M2",
        product_sku="EX-MACBOOK-AIR-M2",
        quantity=1,
        max_total_cents=150000,
        deadline_days=14,
        min_warranty_months=12,
        min_returns_days=14,
        preferences=Preferences(),
    )


def _offer(
    seller_id: str,
    seller_name: str,
    total_cents: int,
    *,
    delivery_days: int,
    warranty_months: int,
    returns_days: int,
    sustainability: bool,
) -> Offer:
    return Offer(
        offer_id=f"o-{seller_id}",
        request_id="r1",
        seller_id=seller_id,
        seller_name=seller_name,
        seller_rating=4.8,
        task_id=f"t-{seller_id}",
        context_id="c1",
        currency=Currency.USD,
        line_items=[
            OfferLineItem(
                sku="EX-MACBOOK-AIR-M2",
                name="MacBook Air M2",
                quantity=1,
                unit_price_cents=total_cents,
                list_unit_price_cents=total_cents + 3000,
                warranty_addon_cents=0,
            )
        ],
        subtotal_cents=total_cents,
        shipping_cents=0,
        tax_cents=0,
        fees_cents=0,
        total_cents=total_cents,
        delivery_days=delivery_days,
        warranty_months=warranty_months,
        returns_days=returns_days,
        valid_until=datetime.now(UTC) + timedelta(minutes=30),
        terms=OfferTerms(sustainability_certified=sustainability, stock_confidence=1.0),
        status=OfferStatus.PROPOSED,
        round=1,
        rationale="opening",
    )


def test_the_cheaper_offer_scores_higher_when_terms_are_equal() -> None:
    mandate = _mandate()
    cheaper = _offer(
        "cheap", "CheapCo", 114659,
        delivery_days=5, warranty_months=24, returns_days=45, sustainability=True,
    )
    dearer = _offer(
        "dear", "DearCo", 127399,
        delivery_days=5, warranty_months=24, returns_days=45, sustainability=True,
    )
    floor = min(cheaper.total_cents, dearer.total_cents)

    assert score_offer(mandate, cheaper, price_floor_total_cents=floor) > score_offer(
        mandate, dearer, price_floor_total_cents=floor
    )


def test_a_dearer_offer_can_still_win_on_materially_better_terms() -> None:
    """Price discriminates; it does not dominate a clearly superior offer."""
    mandate = _mandate()
    cheap = _offer(
        "cheap", "CheapCo", 114659,
        delivery_days=10, warranty_months=12, returns_days=14, sustainability=False,
    )
    premium = _offer(
        "premium", "PremiumCo", 118000,
        delivery_days=2, warranty_months=36, returns_days=45, sustainability=True,
    )

    ranked = rank_offers(mandate, [cheap, premium])

    assert ranked[0].offer.seller_id == "premium"


def test_ranking_prefers_the_cheaper_offer_when_premiums_do_not_justify_the_price() -> None:
    """The live run's shape: $127k (3d,24mo,45d,sust) vs $114.7k (5d,12mo,30d,no sust)."""
    mandate = _mandate()
    northwind = _offer(
        "northwind", "Northwind Audio", 127399,
        delivery_days=3, warranty_months=24, returns_days=45, sustainability=True,
    )
    aurora = _offer(
        "aurora", "Aurora Supply", 121029,
        delivery_days=7, warranty_months=36, returns_days=60, sustainability=True,
    )
    circuitforge = _offer(
        "circuitforge", "CircuitForge", 114659,
        delivery_days=5, warranty_months=12, returns_days=30, sustainability=False,
    )

    ranked = rank_offers(mandate, [northwind, aurora, circuitforge])

    # Northwind is the most expensive and its premiums do not outweigh a
    # $12.7k price gap, so it must not take the award.
    assert ranked[0].offer.seller_id != "northwind"
