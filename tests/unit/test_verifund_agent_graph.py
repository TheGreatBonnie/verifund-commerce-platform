from __future__ import annotations

from datetime import UTC, datetime

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from verifund_agent.graph import (
    VerifundProtocolError,
    build_graph,
    buyer_review_route,
    funding_approval_matches,
    seller_review_route,
)
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewResult,
    FundingApprovalDecision,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def award(**overrides):
    payload = {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "currency": "USD",
        "amount_cents": 123400,
        "shipping_cents": 3400,
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
    }
    payload.update(overrides)
    return payload


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
        "line_items": award()["line_items"],
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


AGREEMENT = agreement()
AGREEMENT_HASH = AGREEMENT.agreement_hash


def review(*args, **overrides) -> AgreementReviewResult:
    party = args[0] if args else overrides.pop("party", "buyer")
    payload = {
        "party": party,
        "status": "accepted",
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": AGREEMENT_HASH,
        "task_id": f"{party}-task-1",
        "context_id": "run-1",
        "reviewed_at": NOW,
    }
    payload.update(overrides)
    return AgreementReviewResult.model_validate(payload)


def funding_decision(**overrides) -> FundingApprovalDecision:
    payload = {
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": AGREEMENT_HASH,
        "approved": True,
        "approved_by": "demo-reviewer",
        "note": "approved in the console",
        "decided_at": NOW,
        "idempotency_key": "fund:vf_1:1",
    }
    payload.update(overrides)
    return FundingApprovalDecision.model_validate(payload)


class Buyer:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def create_agreement(self, run_id, request):
        self.calls.append(("create_agreement", run_id, request))
        return {
            "transaction_id": "vf_1",
            "state": "AWARDED",
            "agreement": AGREEMENT.model_dump(mode="json"),
            "agreement_version": 1,
            "agreement_hash": AGREEMENT_HASH,
            "seller_token_ref": "run:run-1:transaction:vf_1",
        }
    
    async def approve_funding(self, run_id, decision):
        self.calls.append(("approve_funding", run_id, decision))
        return {
            "projection": {
                "transaction_id": "vf_1",
                "state": "FUNDED",
            },
            "checkout_url": "http://paypal.test/checkout/1",
            "expires_at": "2026-10-27T12:30:00Z",
        }


def initial_state(**overrides):
    payload = {
        "task_id": "task-1",
        "context_id": "run-1",
        "run_id": "run-1",
        "award": award(),
        "buyer_task_id": "buyer-task-1",
        "buyer_context_id": "run-1",
        "stage": "initialized",
    }
    payload.update(overrides)
    return payload


def config(buyer: Buyer) -> dict:
    return {"configurable": {"thread_id": "task-1", "buyer": buyer}}


async def test_graph_stops_for_buyer_then_seller_then_funding() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)

    first = await graph.ainvoke(initial_state(), runtime)
    buyer_stop = first["__interrupt__"][0].value
    assert buyer_stop["reason"] == "buyer_review_required"
    assert buyer_stop["agreement_hash"] == AGREEMENT_HASH
    assert buyer_stop["agreement"]["transaction_id"] == "vf_1"
    assert buyer_stop["responseSchema"]["title"] == "AgreementReviewResult"

    second = await graph.ainvoke(
        Command(resume=review("buyer").model_dump(mode="json")), runtime
    )
    seller_stop = second["__interrupt__"][0].value
    assert seller_stop["reason"] == "seller_review_required"
    assert seller_stop["buyer_review"]["status"] == "accepted"
    assert seller_stop["agreement_hash"] == AGREEMENT_HASH

    third = await graph.ainvoke(
        Command(resume=review("seller").model_dump(mode="json")), runtime
    )
    funding_stop = third["__interrupt__"][0].value
    assert funding_stop["reason"] == "funding_approval_required"
    assert funding_stop["seller_decision"]["status"] == "accepted"
    assert funding_stop["responseSchema"]["title"] == "FundingApprovalDecision"

    done = await graph.ainvoke(
        Command(resume=funding_decision().model_dump(mode="json")), runtime
    )
    assert "__interrupt__" in done
    assert done["__interrupt__"][0].value["reason"] == "funding_pending"
    assert done["funding_approval"]["approved"] is True
    assert len(buyer.calls) == 2


async def test_the_buyer_is_called_once_across_every_resume() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await graph.ainvoke(initial_state(), runtime)
    await graph.ainvoke(
        Command(resume=review("buyer").model_dump(mode="json")), runtime
    )
    await graph.ainvoke(
        Command(resume=review("seller").model_dump(mode="json")), runtime
    )
    assert [call[0] for call in buyer.calls] == ["create_agreement"]


async def test_buyer_rejection_ends_before_the_seller_is_asked() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await graph.ainvoke(initial_state(), runtime)
    done = await graph.ainvoke(
        Command(
            resume=review("buyer", status="rejected").model_dump(mode="json")
        ),
        runtime,
    )
    assert "__interrupt__" not in done
    assert done["stage"] == "rejected"


@pytest.mark.parametrize(
    "overrides",
    [{"agreement_hash": "b" * 64}, {"party": "seller"}],
)
async def test_resume_must_echo_the_frozen_agreement(overrides) -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await graph.ainvoke(initial_state(), runtime)
    with pytest.raises(VerifundProtocolError):
        await graph.ainvoke(
            Command(
                resume=review("buyer", **overrides).model_dump(mode="json")
            ),
            runtime,
        )


def test_review_routes_never_treat_a_missing_decision_as_consent() -> None:
    assert buyer_review_route({}) == "rejected"
    assert seller_review_route({}) == "rejected"
    assert buyer_review_route(
        {"buyer_review": {"status": "accepted"}}
    ) == "accepted"
    assert seller_review_route(
        {"seller_decision": {"status": "accepted"}}
    ) == "accepted"


def test_funding_approval_must_match_the_agreement() -> None:
    approval = funding_decision()
    assert funding_approval_matches(approval, AGREEMENT) is True
    assert (
        funding_approval_matches(
            approval.model_copy(update={"run_id": "run-2"}), AGREEMENT
        )
        is False
    )
    assert (
        funding_approval_matches(
            approval.model_copy(update={"agreement_version": 2}), AGREEMENT
        )
        is False
    )
    assert (
        funding_approval_matches(
            approval.model_copy(update={"agreement_hash": "c" * 64}),
            AGREEMENT,
        )
        is False
    )
