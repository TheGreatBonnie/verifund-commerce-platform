from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from buyer_agent.graph import (
    AgreementProtocolError,
    BuyerState,
    _mediated_place_order,
    agreement_mismatch_reason,
    await_seller_review,
    build_buyer_graph,
    buyer_review_route,
    create_settlement_award,
    report_buyer_review,
    report_seller_review,
    seller_decision_matches,
)
from verifund_contracts import AgreementProjection, AgreementReviewResult

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64


def agreement(**overrides) -> AgreementProjection:
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
    if "amount_cents" in overrides:
        amount = overrides["amount_cents"]
        payload["amount_cents"] = amount
        payload["terms"] = {
            **payload["terms"],
            "totals": {**payload["terms"]["totals"], "total_cents": amount},
        }
    payload.update(
        {key: value for key, value in overrides.items() if key != "amount_cents"}
    )
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
    payload: dict[str, Any] = {
        "party": "seller",
        "status": "accepted",
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "offer_hash": "a" * 64,
        "actor_type": "SELLER_AGENT",
        "actor_id": "northwind-audio",
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


def test_buyer_graph_routes_approved_awards_by_settlement_mode() -> None:
    edges = {
        (edge.source, edge.target)
        for edge in build_buyer_graph().get_graph().edges
    }
    assert ("await_approval", "create_settlement_award") in edges
    assert ("await_approval", "place_order") in edges
    assert ("await_approval", "cancel_losers") in edges
    assert ("create_settlement_award", "await_seller_review") in edges
    assert ("await_seller_review", "report_seller_review") in edges
    assert ("report_seller_review", "precheck") in edges
    assert ("precheck", "finalize") in edges


def test_agreement_protocol_error_is_not_a_success_value() -> None:
    with pytest.raises(AgreementProtocolError):
        raise AgreementProtocolError("seller review hash mismatch")


class FakeBuyerSettlement:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def buyer_review(self, transaction_id, **kwargs):
        self.calls.append({"transaction_id": transaction_id, **kwargs})
        return {
            "transaction_id": transaction_id,
            "state": "AWARDED",
            "buyer_agent_review": {
                "status": kwargs["decision"],
                "reviewed_at": "2026-10-27T12:00:00Z",
            },
        }

    async def accept(self, transaction_id, **kwargs):
        self.calls.append({"transaction_id": transaction_id, **kwargs})
        return {"state": "AGREED"}

    async def reject(self, transaction_id, **kwargs):
        self.calls.append({"transaction_id": transaction_id, **kwargs})
        return {"state": "CANCELED"}


def _buyer_state(**overrides) -> BuyerState:
    base = state()
    base["task_id"] = "buyer-task-1"
    base["context_id"] = "run-1"
    base["sellers"] = [
        {
            "seller_id": "northwind-audio",
            "name": "Northwind Audio",
            "card_url": "http://seller/.well-known/agent-card.json",
            "rating": 4.8,
            "sustainability_certified": True,
        }
    ]
    base["settlement_mode"] = True
    base["settlement"] = None
    return cast(BuyerState, {**base, **overrides})


def _services() -> Any:
    return SimpleNamespace(
        registry=SimpleNamespace(
            endpoint=lambda seller_id: SimpleNamespace(
                card_url="http://seller/.well-known/agent-card.json"
            )
        ),
        trace=SimpleNamespace(upsert_run=None, record=None),
        settlement=FakeBuyerSettlement(),
    )


def _config(services: Any = None) -> dict:
    return {"configurable": {"services": services or _services()}}


def _awarded_settlement(**agreement_overrides) -> dict:
    return {
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "agreement": agreement(**agreement_overrides).model_dump(mode="json"),
        "state": "AWARDED",
        "funding_state": "AWARDED",
    }


async def test_create_settlement_award_waits_for_the_canonical_agreement(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_interrupt(value: Any) -> dict:
        captured.update(value if isinstance(value, dict) else {})
        return {
            "agreement": agreement().model_dump(mode="json"),
            "seller_token_ref": "run:run-1:transaction:vf_1",
        }

    monkeypatch.setattr("buyer_agent.graph.interrupt", fake_interrupt)
    result_value = await create_settlement_award(_buyer_state(), _config(SimpleNamespace()))

    assert result_value["stage"] == "awarded"
    assert captured["reason"] == "agreement_create_required"
    assert captured["buyer_task_id"] == "buyer-task-1"
    assert captured["buyer_context_id"] == "run-1"
    award = captured["award"]
    assert award["run_id"] == "run-1"
    assert award["seller_id"] == "northwind-audio"
    assert "winner" not in award
    assert award["line_items"][0]["sku"] == "NC-700"
    settlement = result_value["settlement"]
    assert settlement["state"] == "AWARDED"
    assert settlement["funding_state"] == "AWARDED"
    assert (
        AgreementProjection.model_validate(settlement["agreement"]).transaction_id
        == "vf_1"
    )


async def test_create_settlement_award_rejects_a_mismatched_agreement(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_interrupt(value: Any) -> dict:
        captured.update(value if isinstance(value, dict) else {})
        return {
            "agreement": agreement(amount_cents=123401).model_dump(mode="json"),
        }

    monkeypatch.setattr("buyer_agent.graph.interrupt", fake_interrupt)
    with pytest.raises(AgreementProtocolError):
        await create_settlement_award(_buyer_state(), _config(SimpleNamespace()))


async def test_report_buyer_review_accepts_the_canonical_agreement() -> None:
    services = _services()
    result_value = await report_buyer_review(
        _buyer_state(
            settlement=_awarded_settlement(),
            task_id="buyer-task-1",
            context_id="run-1",
        ),
        _config(services),
    )
    assert result_value["buyer_review"]["status"] == "accepted"
    assert result_value["buyer_review"]["reason_code"] is None
    assert result_value["stage"] == "buyer_reviewed"
    assert services.settlement.calls[0]["decision"] == "accepted"


async def test_report_buyer_review_rejects_an_agreement_that_mismatches_the_award() -> None:
    services = _services()
    result_value = await report_buyer_review(
        _buyer_state(
            settlement=_awarded_settlement(amount_cents=123401),
            task_id="buyer-task-1",
            context_id="run-1",
        ),
        _config(services),
    )
    assert result_value["buyer_review"]["status"] == "rejected"
    assert result_value["buyer_review"]["reason_code"] == "terms_mismatch"
    assert result_value["stage"] == "rejected"


async def test_await_seller_review_resumes_with_the_seller_decision(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_interrupt(value: Any) -> dict:
        captured.update(value if isinstance(value, dict) else {})
        return {
            "seller_decision": result(status="accepted").model_dump(mode="json"),
        }

    monkeypatch.setattr("buyer_agent.graph.interrupt", fake_interrupt)
    outcome = await await_seller_review(
        _buyer_state(
            settlement=_awarded_settlement(),
            task_id="buyer-task-1",
            context_id="run-1",
        ),
        _config(SimpleNamespace()),
    )
    assert outcome["stage"] == "seller_reviewed"
    assert captured["reason"] == "seller_review_required"
    assert AgreementProjection.model_validate(captured["agreement"]).transaction_id == "vf_1"


async def test_await_seller_review_fails_when_the_decision_mismatches_the_agreement(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_interrupt(value: Any) -> dict:
        captured.update(value if isinstance(value, dict) else {})
        return {
            "seller_decision": result(run_id="run-2").model_dump(mode="json"),
        }

    monkeypatch.setattr("buyer_agent.graph.interrupt", fake_interrupt)
    with pytest.raises(AgreementProtocolError):
        await await_seller_review(
            _buyer_state(
                settlement=_awarded_settlement(),
                task_id="buyer-task-1",
                context_id="run-1",
            ),
            _config(SimpleNamespace()),
        )


async def test_settlement_mode_never_uses_the_legacy_place_order_flow() -> None:
    outcome = await _mediated_place_order(
        _buyer_state(
            settlement_mode=True,
            approval={"approved": True, "approved_by": "Demo Buyer"},
        ),
        _config(SimpleNamespace()),
    )
    assert outcome["order"] is None
    assert outcome["stage"] == "failed"


async def test_report_seller_review_agrees_after_the_seller_accepts() -> None:
    services = _services()
    state_value = _buyer_state(
        settlement=_awarded_settlement(),
        task_id="buyer-task-1",
        context_id="run-1",
    )
    state_value["seller_decision"] = (
        result(status="accepted").model_dump(mode="json")
    )
    outcome = await report_seller_review(state_value, _config(services))
    assert outcome["stage"] == "agreed"
    assert outcome["seller_decision"]["status"] == "accepted"
    assert services.settlement.calls[0]["transaction_id"] == "vf_1"
