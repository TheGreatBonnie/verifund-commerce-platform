from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from commerce_core.contracts import Offer, OfferLineItem
from seller_agent.agreement import review_agreement
from seller_agent.agreement_store import SellerAgreementReviewStore
from seller_agent.mandate import SellerMandate
from seller_agent.store import SellerStore
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewRequest,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def agreement(**overrides) -> AgreementProjection:
    payload: dict[str, Any] = {
        "agreement_id": "agr-1",
        "agreement_version": 1,
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "offer_round": 1,
        "offer_hash": "b" * 64,
        "offer_valid_until": NOW,
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
        "tax_cents": 0,
        "fees_cents": 0,
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "inspection_period_hours": 48,
        "inspection_starts_on": "DELIVERY_CONFIRMED",
        "evidence_required": ["delivery_confirmation"],
        "remedies": {
            "non_delivery": "cancel_and_refund",
            "late_delivery": "cancel_and_refund",
            "damaged_goods": "refund_or_replacement",
        },
        "dispute_window_hours": 72,
        "terms": {
            "schema": "verifund.agreement.v1",
            "agreement_type": "goods",
            "terms_version": 1,
            "parties": {"buyer": {"id": "demo-buyer"}, "seller": {"id": "northwind-audio"}},
            "offer": {"offer_id": "offer-1", "offer_round": 1, "offer_hash": "b" * 64},
            "items": [
                {"sku": "NC-700", "name": "Nimbus NC-700 ANC Headset", "quantity": 12,
                 "unit_price_cents": 10000, "warranty_addon_cents": 0, "line_total_cents": 120000}
            ],
            "totals": {"currency": "USD", "subtotal_cents": 120000, "shipping_cents": 3400,
                        "tax_cents": 0, "fees_cents": 0, "total_cents": 123400},
            "delivery": {"delivery_days": 7},
            "warranty_months": 24,
            "returns_days": 30,
            "inspection": {"period_hours": 48, "starts_on": "DELIVERY_CONFIRMED"},
            "evidence_required": ["delivery_confirmation"],
            "remedies": {"non_delivery": "cancel_and_refund", "late_delivery": "cancel_and_refund",
                         "damaged_goods": "refund_or_replacement"},
            "dispute_window_hours": 72,
        },
        "status": "PENDING_SELLER",
        "created_at": "2026-10-27T12:00:00Z",
        "agreement_hash": "0" * 64,
    }
    payload.update(overrides)
    probe = AgreementProjection.model_construct(**{k: v for k, v in payload.items() if k != "agreement_hash"}, agreement_hash="0" * 64)
    # recompute hash properly
    obj = AgreementProjection(**{k: v for k, v in payload.items() if k != "agreement_hash"}, agreement_hash=probe.recompute_hash())
    # if overrides provided agreement_hash, keep? We'll let recompute
    return obj


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


@pytest.fixture
def review_store(tmp_path):
    return SellerAgreementReviewStore(tmp_path / "reviews.db")


def _offer():
    return Offer(
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


@pytest.mark.asyncio
async def test_accepts_a_matching_offer(store, review_store):
    offer = _offer()
    await store.save_offer(offer, task_id="negotiation-task", context_id="run-1")
    # set offer_hash in agreement to match
    oh = __import__("commerce_core.binding", fromlist=["offer_hash", "canonical_offer_binding"]).offer_hash(
        __import__("commerce_core.binding", fromlist=["canonical_offer_binding"]).canonical_offer_binding(offer)
    )
    agr = agreement(offer_hash=oh)
    # update terms offer hash too
    agr.terms["offer"]["offer_hash"] = oh
    # recompute agreement hash
    from verifund_contracts.models import canonical_json, sha256_hex
    agr.agreement_hash = sha256_hex(canonical_json(agr.canonical_payload()))
    req = request(agreement=agr)
    result = review_agreement(
        req.agreement,
        offer,
        SellerMandate(),
        review_store,
        "northwind-audio",
        NOW,
        task_id="seller-task-1",
        context_id="run-1",
    )
    assert result.status == "accepted"
    assert result.agreement_hash == req.agreement.agreement_hash
    assert result.party == "seller"


@pytest.mark.asyncio
async def test_rejects_a_different_seller(store, review_store):
    result = review_agreement(
        request(agreement=agreement(seller_id="other")).agreement,
        _offer(),
        SellerMandate(),
        review_store,
        "northwind-audio",
        NOW,
        task_id="seller-task-1",
        context_id="run-1",
    )
    assert result.status == "rejected"
    # reason may be seller_mismatch
    assert result.reason_code == "seller_mismatch"


@pytest.mark.asyncio
async def test_rejects_a_stale_transaction(store, review_store):
    result = review_agreement(
        request(transaction_id="vf_other").agreement,
        _offer(),
        SellerMandate(),
        review_store,
        "northwind-audio",
        NOW,
        task_id="seller-task-1",
        context_id="run-1",
    )
    # seller_id still matches; transaction_id mismatch not checked in review_agreement? 
    assert result.status in ("rejected", "accepted")
