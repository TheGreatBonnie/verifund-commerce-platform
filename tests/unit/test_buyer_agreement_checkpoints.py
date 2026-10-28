from __future__ import annotations

from datetime import UTC, datetime

import pytest
from verifund_contracts import AgreementProjection, AgreementReviewResult

from buyer_agent.graph import (
    AgreementProtocolError,
    agreement_mismatch_reason,
    build_buyer_graph,
    buyer_review_route,
    seller_decision_matches,
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
    probe = AgreementProjection.model_construct(
        **payload, agreement_hash="0" * 64
    )
    return AgreementProjection(
        **payload, agreement_hash=probe.recompute_hash()
    )


def state(**overrides) -> dict:
    return {
        "run_id": "run-1",
        "award": {
            "winner": {
                "seller_id": "northwind-audio",
                "offer_id": "offer-1",
                "total_cents": 123400,
                "shipping_cents": 3400,
                "currency": "USD",
                "quantity": 12,
                "delivery_days": 7,
                "warranty_months": 24,
                "returns_days": 30,
                "line_items": [
                    {
                        "sku": "NC-700",
                        "name": "Nimbus NC-700 ANC Headset",
                        "quantity": 12,
                        "unit_price_cents": 10000,
                        "warranty_addon_cents": 0,
                    }
                ],
            }
        },
        "mandate": {"buyer_id": "demo-buyer"},
        **overrides,
    }


def test_agreement_mismatch_reason_binds_terms_to_the_award() -> None:
    assert agreement_mismatch_reason(agreement(), state()) is None
    assert (
        agreement_mismatch_reason(agreement(amount_cents=123401), state())
        == "terms_mismatch"
    )
    assert (
        agreement_mismatch_reason(agreement(seller_id="other"), state())
        == "terms_mismatch"
    )
    assert (
        agreement_mismatch_reason(agreement(buyer_id="other"), state())
        == "terms_mismatch"
    )


def result(**overrides) -> AgreementReviewResult:
    payload = {
        "party": "seller",
        "status": "accepted",
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "task_id": "seller-task-1",
        "context_id": "run-1",
        "reviewed_at": NOW,
    }
    payload.update(overrides)
    return AgreementReviewResult(**payload)


def test_buyer_review_route_requires_a_structured_acceptance() -> None:
    assert buyer_review_route({"buyer_review": {"status": "accepted"}}) == "accepted"
    assert buyer_review_route({"buyer_review": {"status": "rejected"}}) == "rejected"
    assert buyer_review_route({}) == "rejected"


def test_seller_decision_must_echo_the_frozen_agreement() -> None:
    agreed = agreement()
    assert seller_decision_matches(result(), agreed) is True
    assert seller_decision_matches(result(party="buyer"), agreed) is False
    assert seller_decision_matches(result(run_id="run-2"), agreed) is False
    assert seller_decision_matches(result(agreement_version=2), agreed) is False
    assert seller_decision_matches(result(agreement_hash="b" * 64), agreed) is False


def test_buyer_graph_ends_at_the_bilateral_agreement() -> None:
    nodes = set(build_buyer_graph().get_graph().nodes)
    assert {
        "create_settlement_award",
        "report_buyer_review",
        "await_seller_review",
        "report_seller_review",
    } <= nodes
    assert not {
        "await_funding_approval",
        "report_settlement_approval",
        "fund_settlement",
        "settlement_place_order",
        "await_release",
    } & nodes


def test_agreement_protocol_error_is_not_a_success_value() -> None:
    with pytest.raises(AgreementProtocolError):
        raise AgreementProtocolError("seller review hash mismatch")
