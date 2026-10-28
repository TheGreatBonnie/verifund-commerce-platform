from __future__ import annotations

from datetime import UTC, datetime

import pytest
from commerce_core.contracts import Offer, OfferLineItem
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.agreement import review_agreement
from seller_agent.store import SellerStore
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewRequest,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64


def agreement(**overrides) -> AgreementProjection:
    payload = {
        "agreement_version": 1,
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "currency": "USD",
        "amount_cents": 123400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        "shipping_cents": 3400,
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "created_at": "2026-10-27T12:00:00Z",
    }
    payload.update(overrides)
    probe = AgreementProjection.model_construct(**payload, agreement_hash="0" * 64)
    return AgreementProjection(**payload, agreement_hash=probe.recompute_hash())


def request(**overrides) -> AgreementReviewRequest:
    payload = {
        "party": "seller",
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement": agreement(),
        "seller_task_id": "seller-task-1",
        "seller_context_id": "run-1",
        "requested_at": NOW,
        "idempotency_key": "review:vf_1:1",
    }
    payload.update(overrides)
    return AgreementReviewRequest.model_validate(payload)


class Policy:
    seller_id = "northwind-audio"


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'seller.db'}")
    value = SellerStore(engine)
    await value.create_schema()
    yield value
    await engine.dispose()


async def test_accepts_a_matching_offer(store):
    offer = Offer(
        offer_id="offer-1",
        request_id="rfq-1",
        seller_id="northwind-audio",
        seller_name="Northwind Audio",
        seller_rating=4.8,
        line_items=[
            OfferLineItem(
                sku="NC-700",
                name="Nimbus NC-700 ANC Headset",
                quantity=12,
                unit_price_cents=10000,
                list_unit_price_cents=12000,
                warranty_addon_cents=0,
                attributes={"color": "graphite"},
            )
        ],
        subtotal_cents=120000,
        shipping_cents=3400,
        total_cents=123400,
        delivery_days=7,
        warranty_months=24,
        returns_days=30,
        valid_until=NOW,
    )
    await store.save_offer(offer, task_id="negotiation-task", context_id="run-1")
    result = await review_agreement(Policy(), store, request())
    assert result.status == "accepted"
    assert result.agreement_hash == request().agreement.agreement_hash
    assert result.party == "seller"


async def test_rejects_a_different_seller(store):
    result = await review_agreement(
        Policy(), store, request(agreement=agreement(seller_id="other"))
    )
    assert result.status == "rejected"
    assert result.reason_code == "terms_mismatch"


async def test_rejects_a_stale_transaction(store):
    result = await review_agreement(
        Policy(), store, request(transaction_id="vf_other")
    )
    assert result.status == "rejected"
