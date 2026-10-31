from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx
from pydantic import ValidationError
from verifund_contracts import (
    AwardRequest,
    RejectRequest,
    TransactionProjection,
    VerifundClient,
    VerifundError,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def award_payload(**overrides):
    payload = {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "request_id": "rfq-1",
        "buyer_display_name": "Demo Buyer",
        "seller_display_name": "Northwind Audio",
        "currency": "USD",
        "amount_cents": 123400,
        "shipping_cents": 3400,
        "tax_cents": 0,
        "fees_cents": 0,
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
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "offer_round": 1,
        "offer_hash": "a" * 64,
        "offer_valid_until": NOW,
        "inspection_period_hours": 48,
        "inspection_starts_on": "DELIVERY_CONFIRMED",
        "evidence_required": [
            "shipment_manifest",
            "delivery_confirmation",
            "invoice",
        ],
        "remedies": {
            "non_delivery": "cancel_and_refund",
            "late_delivery": "cancel_and_refund",
            "damaged_goods": "refund_or_replacement",
        },
        "dispute_window_hours": 72,
    }
    payload.update(overrides)
    return payload


def test_award_rejects_non_matching_total():
    with pytest.raises(ValidationError):
        AwardRequest(**award_payload(amount_cents=123401))


def test_award_accepts_matching_total():
    request = AwardRequest(**award_payload())
    assert request.amount_cents == 123400


def test_reject_reason_must_be_known():
    with pytest.raises(ValidationError):
        RejectRequest(
            seller_id="northwind-audio",
            agreement_hash="a" * 64,
            reason_code="made_up",
            seller_task_id="task-1",
            rejected_at=NOW,
        )


def test_projection_round_trip_has_no_extra_fields():
    projection = TransactionProjection(
        transaction_id="vf_1",
        run_id="run-1",
        state="AWARDED",
        last_seq=1,
        amount_cents=123400,
        currency="USD",
        buyer_id="demo-buyer",
        seller_id="northwind-audio",
        agreement_hash="a" * 64,
        agreement_version=1,
        seller_decision=None,
        buyer_agent_review=None,
        approval=None,
        cancellation=None,
        funding=None,
        purchase_order=None,
        evidence=None,
        verification=None,
        payout=None,
        receipt_available=False,
        deadlines={"evidence": None, "inspection": None},
        allowed_actions=["cancel"],
        updated_at=NOW,
    )
    assert projection.model_dump()["state"] == "AWARDED"


@respx.mock
async def test_client_sends_ops_headers_and_raises_structured_error():
    route = respx.post("http://control/awards").mock(
        return_value=httpx.Response(
            409,
            json={
                "error": {
                    "code": "hash_mismatch",
                    "message": "hash mismatch",
                    "retryable": False,
                    "details": {},
                    "request_id": "req-1",
                }
            },
        )
    )
    client = VerifundClient("http://control", ops_token="ops-token")
    with pytest.raises(VerifundError) as raised:
        await client.award(
            AwardRequest(**award_payload()),
            actor="buyer-agent",
            idempotency_key="award:run-1:offer-1",
        )
    assert raised.value.code == "hash_mismatch"
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer ops-token"
    assert request.headers["x-verifund-actor"] == "buyer-agent"
    assert request.headers["idempotency-key"] == "award:run-1:offer-1"
