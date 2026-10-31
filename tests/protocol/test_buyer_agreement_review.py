from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from a2a.types.a2a_pb2 import Message, Role
from buyer_agent.review import (
    parse_review_envelope,
    parse_review_result_envelope,
    resume_value,
)
from commerce_core.a2a_parts import make_message
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewRequest,
    AgreementReviewResult,
    wrap_agreement_review_request,
    wrap_agreement_review_result,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64


def agreement() -> AgreementProjection:
    # reuse the buyer checkpoint helper payload shape
    payload: dict[str, Any] = {
        "agreement_id": "agr_1",
        "agreement_version": 1,
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "offer_round": 1,
        "offer_hash": "a" * 64,
        "offer_valid_until": "2026-10-28T12:00:00Z",
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
            "platform_terms_version": "v1",
            "parties": {
                "buyer": {"id": "demo-buyer", "display_name": "Buyer"},
                "seller": {"id": "northwind-audio", "display_name": "Seller"},
            },
            "offer": {
                "offer_id": "offer-1",
                "request_id": "r1",
                "offer_round": 1,
                "offer_hash": "a" * 64,
                "offer_valid_until": "2026-10-28T12:00:00Z",
            },
            "items": [
                {
                    "sku": "NC-700",
                    "name": "Nimbus NC-700 ANC Headset",
                    "quantity": 12,
                    "unit_price_cents": 10000,
                    "warranty_addon_cents": 0,
                    "line_total_cents": 120000,
                }
            ],
            "totals": {
                "currency": "USD",
                "subtotal_cents": 120000,
                "shipping_cents": 3400,
                "tax_cents": 0,
                "fees_cents": 0,
                "total_cents": 123400,
            },
            "delivery": {"delivery_days": 7, "starts_on": "FUNDING_CONFIRMED"},
            "warranty_months": 24,
            "returns_days": 30,
            "inspection": {"period_hours": 48, "starts_on": "DELIVERY_CONFIRMED"},
            "evidence_required": ["delivery_confirmation"],
            "remedies": {
                "non_delivery": "cancel_and_refund",
                "late_delivery": "cancel_and_refund",
                "damaged_goods": "refund_or_replacement",
            },
            "dispute_window_hours": 72,
        },
        "status": "PENDING_SELLER",
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


def seller_message(**overrides) -> Message:
    fields = {
        "party": "seller",
        "status": "accepted",
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": agreement().agreement_hash,
        "offer_hash": "a" * 64,
        "actor_type": "SELLER_AGENT",
        "actor_id": "northwind-audio",
        "task_id": "seller-task-1",
        "context_id": "run-1",
        "reviewed_at": NOW,
        **overrides,
    }
    resolved = AgreementReviewResult.model_validate(fields)
    return make_message(
        role=Role.ROLE_USER,
        text="Seller agreement review.",
        context_id="run-1",
        task_id="buyer-task-1",
        envelope=wrap_agreement_review_result(resolved),
    )


def test_seller_review_result_is_parsed_and_bound_to_the_agreement() -> None:
    parsed = parse_review_result_envelope(seller_message(), agreement())
    assert parsed.party == "seller"
    assert parsed.status == "accepted"
    assert parsed.agreement_hash == agreement().agreement_hash


def test_seller_review_result_rejects_a_hash_mismatch() -> None:
    with pytest.raises(ValueError):
        parse_review_result_envelope(
            seller_message(agreement_hash="b" * 64),
            agreement(),
        )
