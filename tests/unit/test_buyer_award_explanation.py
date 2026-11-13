"""The award explanation the human reads must be prose, never a machine blob."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from buyer_agent.planner import NebiusBuyerPlanner
from commerce_core.contracts import (
    AwardPackage,
    Currency,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
)


def _award() -> AwardPackage:
    winner = Offer(
        offer_id="o1",
        request_id="r1",
        seller_id="s1",
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
                unit_price_cents=127399,
                list_unit_price_cents=129999,
                warranty_addon_cents=0,
            )
        ],
        subtotal_cents=127399,
        shipping_cents=0,
        tax_cents=0,
        fees_cents=0,
        total_cents=127399,
        delivery_days=3,
        warranty_months=24,
        returns_days=45,
        valid_until=datetime.now(UTC) + timedelta(minutes=30),
        terms=OfferTerms(sustainability_certified=True, stock_confidence=1.0),
        status=OfferStatus.PROPOSED,
        round=1,
        rationale="opening",
    )
    return AwardPackage(
        winner=winner,
        score=95.79,
        alternatives=[],
        scores={"s1": 95.79},
        savings_cents=0,
        mandate_checks=[],
    )


@pytest.mark.anyio
async def test_explain_award_rejects_a_json_blob() -> None:
    """A JSON counter-object is not a human justification."""

    class FakeResponse:
        content = (
            '```json\n{"action":"counter","target_unit_price_cents":115000,'
            '"rationale":"press the price"}\n```'
        )

    class FakeLLM:
        async def ainvoke(self, messages):
            return FakeResponse()

    planner = NebiusBuyerPlanner.__new__(NebiusBuyerPlanner)
    planner.explain_llm = FakeLLM()

    with pytest.raises(ValueError):
        await planner.explain_award(_award())


@pytest.mark.anyio
async def test_explain_award_keeps_prose() -> None:
    class FakeResponse:
        content = (
            "Northwind Audio wins at $1,273.99 because it delivers fastest "
            "while meeting every mandate check."
        )

    class FakeLLM:
        async def ainvoke(self, messages):
            return FakeResponse()

    planner = NebiusBuyerPlanner.__new__(NebiusBuyerPlanner)
    planner.explain_llm = FakeLLM()

    text = await planner.explain_award(_award())

    assert "Northwind Audio" in text
    assert "target_unit_price_cents" not in text
