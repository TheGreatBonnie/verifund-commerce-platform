from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from a2a.types.a2a_pb2 import Message, Role
from commerce_core.a2a_parts import make_message

from buyer_agent.review import parse_review_envelope, resume_value
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewRequest,
    wrap_agreement_review_request,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64


def agreement() -> AgreementProjection:
    payload: dict[str, Any] = {
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
    probe = AgreementProjection.model_construct(**payload, agreement_hash="0" * 64)
    return AgreementProjection(**payload, agreement_hash=probe.recompute_hash())


def message(**overrides) -> Message:
    request = AgreementReviewRequest(
        party="buyer",
        run_id="run-1",
        transaction_id="vf_1",
        agreement=agreement(),
        buyer_task_id="buyer-task-1",
        buyer_context_id="run-1",
        requested_at=NOW,
        idempotency_key="review:vf_1:1",
    )
    payload = {**request.model_dump(mode="json"), **overrides}
    return make_message(
        role=Role.ROLE_USER,
        text="Buyer agreement review.",
        context_id="run-1",
        task_id="buyer-task-1",
        envelope=wrap_agreement_review_request(
            AgreementReviewRequest.model_validate(payload)
        ) if not overrides else {
            "schema": "https://marketmesh.example/extensions/verifund/v1/schemas/agreement-review-request.json",
            "schema_version": "1.0",
            "payload": payload,
        },
    )


def test_review_envelope_requires_the_original_buyer_task() -> None:
    request = parse_review_envelope(message())
    assert request.party == "buyer"
    assert request.buyer_task_id == "buyer-task-1"
    assert resume_value(request) == {
        "agreement": request.agreement.model_dump(mode="json")
    }


def test_review_envelope_rejects_a_seller_party() -> None:
    with pytest.raises(ValueError):
        parse_review_envelope(message(party="seller"))


def test_review_envelope_rejects_a_missing_envelope() -> None:
    with pytest.raises(ValueError):
        parse_review_envelope(
            Message(
                message_id="m1",
                role=Role.ROLE_USER,
                context_id="run-1",
                task_id="buyer-task-1",
                parts=[],
            )
        )
