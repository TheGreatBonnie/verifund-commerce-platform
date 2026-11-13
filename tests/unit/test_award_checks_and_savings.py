"""The award a human approves must carry real checks and real savings."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from buyer_agent.graph import mandate_checks_for, winner_savings_cents
from commerce_core.contracts import (
    Currency,
    Mandate,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
    Preferences,
)


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


def _offer(total_cents: int, *, delivery_days: int = 3, warranty_months: int = 24, returns_days: int = 45) -> Offer:
    return Offer(
        offer_id="o1",
        request_id="r1",
        seller_id="c66f026638e24d4480e1be583a0b548c",
        seller_name="Northwind Audio",
        seller_rating=4.8,
        task_id="t1",
        context_id="c1",
        currency=Currency.USD,
        line_items=[
            OfferLineItem(
                sku="EX-MACBOOK-AIR-M2",
                name="MacBook Air M2",
                quantity=1,
                unit_price_cents=total_cents,
                list_unit_price_cents=total_cents + 2000,
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
        terms=OfferTerms(sustainability_certified=True, stock_confidence=1.0),
        status=OfferStatus.PROPOSED,
        round=1,
        rationale="opening",
    )


def test_mandate_checks_name_the_constraints_the_human_is_approving() -> None:
    checks = mandate_checks_for(_mandate(), _offer(127399))

    joined = " | ".join(checks).lower()
    assert "1,273.99" in " | ".join(checks) or "1273.99" in " | ".join(checks)
    assert "budget" in joined or "1,500.00" in " | ".join(checks)
    assert "delivery" in joined
    assert "warranty" in joined
    assert "returns" in joined or "return" in joined
    # Raw seller UUIDs are not a human-readable check.
    assert "c66f026638e24d4480e1be583a0b548c" not in joined


def test_savings_are_the_winner_own_opening_quote_minus_its_final_price() -> None:
    opening = _offer(129999)
    final = _offer(127399)

    # The winner's own negotiation moved the price down by $26.00.
    assert winner_savings_cents(
        "s1", [{"seller_id": "s1", "rounds": [opening.model_dump(mode="json"), final.model_dump(mode="json")]}], final
    ) == 2600


def test_savings_are_zero_when_the_winner_never_moved() -> None:
    opening = _offer(127399)

    assert winner_savings_cents(
        "s1", [{"seller_id": "s1", "rounds": [opening.model_dump(mode="json")]}], opening
    ) == 0
