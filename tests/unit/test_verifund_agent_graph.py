from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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
    CheckoutDecision,
    FundingApprovalDecision,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def award(**overrides):
    payload: dict[str, Any] = {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "request_id": "rfq-1",
        "buyer_display_name": "Buyer",
        "seller_display_name": "Seller",
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
        "offer_valid_until": NOW,
        "currency": "USD",
        "amount_cents": 123400,
        "quantity": 12,
        "line_items": award()["line_items"],
        "shipping_cents": 3400,
        "tax_cents": 0,
        "fees_cents": 0,
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
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
        "terms": {
            "schema": "verifund.agreement.v1",
            "agreement_type": "goods",
            "terms_version": 1,
            "totals": {
                "subtotal_cents": 120000,
                "shipping_cents": 3400,
                "tax_cents": 0,
                "fees_cents": 0,
                "total_cents": 123400,
            },
            "delivery": {"delivery_days": 7},
            "warranty": {"warranty_months": 24},
            "returns": {"returns_days": 30},
            "inspection": {"period_hours": 48, "starts_on": "DELIVERY_CONFIRMED"},
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
        },
        "status": "PENDING_SELLER",
        "expires_at": None,
        "created_at": "2026-10-27T12:00:00Z",
    }
    payload.update(overrides)
    payload.pop("agreement_hash", None)
    probe = AgreementProjection.model_construct(**payload, agreement_hash="0" * 64)
    return AgreementProjection(**payload, agreement_hash=probe.recompute_hash())


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
        "offer_hash": "a" * 64,
        "actor_type": "SELLER_AGENT",
        "actor_id": "northwind-audio",
        "authority_ref": "seller-mandate:northwind-audio:1",
        "authority_snapshot": {},
        "verified_change_request_id": None,
        "task_id": f"{party}-task-1",
        "context_id": "run-1",
        "reviewed_at": NOW,
    }
    payload.update(overrides)
    return AgreementReviewResult.model_validate(payload)


def buyer_approval_decision(**overrides):
    from verifund_contracts import BuyerAgreementApprovalDecision
    payload = {
        "agreement_version": 1,
        "agreement_hash": AGREEMENT_HASH,
        "decision": "APPROVE",
        "idempotency_key": "buyer-decision:vf_1:1",
    }
    payload.update(overrides)
    return BuyerAgreementApprovalDecision.model_validate(payload)


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
        self._settlement_calls = 0
        self.settlement_state = "AWARDED"
        self.settlement_transaction_id = "vf_1"

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

    async def get_settlement(self, run_id, *, refresh=False):
        self.calls.append(("get_settlement", run_id, refresh))
        self._settlement_calls += 1
        agreement = AGREEMENT.model_dump(mode="json")
        if self._settlement_calls == 2:
            agreement["status"] = "PENDING_BUYER"
        elif self._settlement_calls >= 3:
            agreement["status"] = "AGREED"
        return {
            "agreement": agreement,
            "projection": {
                "transaction_id": self.settlement_transaction_id,
                "state": self.settlement_state,
            },
        }

    async def approve_funding(self, run_id, decision, *, defer_checkout=False):
        self.calls.append(("approve_funding", run_id, decision, defer_checkout))
        return {
            "projection": {
                "transaction_id": "vf_1",
                "state": "AGREED" if defer_checkout else "FUNDED",
            },
            "checkout_url": None if defer_checkout else "http://paypal.test/checkout/1",
            "expires_at": None if defer_checkout else "2026-10-27T12:30:00Z",
        }

    async def prepare_funding(self, run_id):
        self.calls.append(("prepare_funding", run_id))
        return {
            "checkout_session": {
                "transaction_id": "vf_1",
                "amount_cents": 123400,
                "currency": "USD",
                "expires_at": "2026-10-27T12:30:00Z",
                "agreement_version": 1,
                "agreement_hash": AGREEMENT_HASH,
                "order_attempt": 0,
                "provider_order_id": None,
            }
        }

    async def cancel(self, run_id, *, reason_code, note=""):
        self.calls.append(("cancel", run_id, reason_code, note))
        return {"transaction_id": "vf_1", "state": "CANCELED"}

    async def purchase_order(self, run_id, request):
        self.calls.append(("purchase_order", run_id, request))
        return {
            "run_id": run_id,
            "transaction_id": "vf_1",
            "agreement_version": 1,
            "agreement_hash": AGREEMENT_HASH,
            "seller_id": "northwind-audio",
            "offer_id": "offer-1",
            "amount_cents": 123400,
            "seller_token_ref": "run:run-1:transaction:vf_1",
            "purchase_order": {
                "request_id": "po-run-1-offer-1",
                "run_id": run_id,
                "offer_id": "offer-1",
                "seller_id": "northwind-audio",
                "quantity": 12,
                "expected_total_cents": 123400,
                "settlement_transaction_id": "vf_1",
                "agreement_hash": AGREEMENT_HASH,
            },
        }

    async def get_agreement(self, run_id):
        self.calls.append(("get_agreement", run_id))
        agreement = AGREEMENT.model_dump(mode="json")
        agreement["status"] = "AGREED"
        return agreement


class StaleBuyer(Buyer):
    """The buyer store never learns that the console recorded the decision."""

    async def get_settlement(self, run_id, *, refresh=False):
        self.calls.append(("get_settlement", run_id, refresh))
        return {
            "agreement": {
                **AGREEMENT.model_dump(mode="json"),
                "status": "PENDING_SELLER",
            },
            "projection": {"transaction_id": "vf_1", "state": "AWARDED"},
        }

    async def get_agreement(self, run_id):
        self.calls.append(("get_agreement", run_id))
        return {
            **AGREEMENT.model_dump(mode="json"),
            "status": "PENDING_BUYER",
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


async def test_graph_stops_for_seller_then_buyer_then_funding() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)

    first = await graph.ainvoke(initial_state(), runtime)
    seller_stop = first["__interrupt__"][0].value
    assert seller_stop["reason"] == "seller_review_required"
    assert seller_stop["agreement_hash"] == AGREEMENT_HASH
    assert seller_stop["agreement"]["transaction_id"] == "vf_1"

    second = await graph.ainvoke(
        Command(resume=review("seller").model_dump(mode="json")), runtime
    )
    buyer_stop = second["__interrupt__"][0].value
    assert buyer_stop["reason"] == "buyer_approval_required"
    assert buyer_stop["agreement_hash"] == AGREEMENT_HASH

    third = await graph.ainvoke(
        Command(resume=buyer_approval_decision().model_dump(mode="json")), runtime
    )
    funding_stop = third["__interrupt__"][0].value
    assert funding_stop["reason"] == "funding_approval_required"
    assert funding_stop["responseSchema"]["title"] == "FundingApprovalDecision"

    done = await graph.ainvoke(
        Command(resume=funding_decision().model_dump(mode="json")), runtime
    )
    assert "__interrupt__" in done
    assert done["__interrupt__"][0].value["reason"] == "funding_pending"
    assert done["funding_approval"]["approved"] is True


async def test_buyer_approval_reaches_funding_when_the_buyer_cache_lags() -> None:
    buyer = StaleBuyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)

    await graph.ainvoke(initial_state(), runtime)
    await graph.ainvoke(
        Command(resume=review("seller").model_dump(mode="json")), runtime
    )
    third = await graph.ainvoke(
        Command(resume=buyer_approval_decision().model_dump(mode="json")),
        runtime,
    )

    funding_stop = third["__interrupt__"][0].value
    assert funding_stop["reason"] == "funding_approval_required"
    assert funding_stop["buyer_review"]["status"] == "accepted"
    assert funding_stop["seller_decision"]["status"] == "accepted"


async def test_buyer_rejection_ends_even_when_the_buyer_cache_lags() -> None:
    buyer = StaleBuyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)

    await graph.ainvoke(initial_state(), runtime)
    await graph.ainvoke(
        Command(resume=review("seller").model_dump(mode="json")), runtime
    )
    done = await graph.ainvoke(
        Command(
            resume=buyer_approval_decision(decision="REJECT").model_dump(
                mode="json"
            )
        ),
        runtime,
    )

    assert "__interrupt__" not in done
    assert done["agreement"]["status"] == "REJECTED"


async def test_the_buyer_is_called_once_across_every_resume() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await graph.ainvoke(initial_state(), runtime)
    await graph.ainvoke(
        Command(resume=review("seller").model_dump(mode="json")), runtime
    )
    await graph.ainvoke(
        Command(resume=buyer_approval_decision().model_dump(mode="json")), runtime
    )
    assert [call[0] for call in buyer.calls].count("create_agreement") == 1


async def test_buyer_rejection_ends_before_the_seller_is_asked() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await graph.ainvoke(initial_state(), runtime)
    done = await graph.ainvoke(
        Command(
            resume=review("seller", status="rejected").model_dump(mode="json")
        ),
        runtime,
    )
    assert "__interrupt__" not in done
    assert done["stage"] == "rejected"


@pytest.mark.parametrize(
    "overrides",
    [{"agreement_hash": "b" * 64}, {"party": "buyer"}],
)
async def test_resume_must_echo_the_frozen_agreement(overrides) -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await graph.ainvoke(initial_state(), runtime)
    with pytest.raises(VerifundProtocolError):
        await graph.ainvoke(
            Command(
                resume=review("seller", **overrides).model_dump(mode="json")
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


async def reach_funding_approval(graph, runtime, **overrides) -> None:
    await graph.ainvoke(initial_state(**overrides), runtime)
    await graph.ainvoke(
        Command(resume=review("seller").model_dump(mode="json")), runtime
    )
    await graph.ainvoke(
        Command(resume=buyer_approval_decision().model_dump(mode="json")), runtime
    )


def checkout_decision(**overrides) -> CheckoutDecision:
    payload = {
        "status": "completed",
        "transaction_id": "vf_1",
        "order_id": "ORDER-1",
        "capture_id": "CAP-1",
        "projection": {"transaction_id": "vf_1", "state": "FUNDED"},
        "idempotency_key": "checkout:vf_1",
    }
    payload.update(overrides)
    return CheckoutDecision.model_validate(payload)


async def test_embedded_checkout_stops_before_creating_a_paypal_order() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await reach_funding_approval(graph, runtime, checkout_mode="embedded")

    approved = await graph.ainvoke(
        Command(resume=funding_decision().model_dump(mode="json")), runtime
    )

    stop = approved["__interrupt__"][0].value
    assert stop["reason"] == "funding_checkout_required"
    assert stop["amount_cents"] == 123400
    assert stop["currency"] == "USD"
    assert stop["expires_at"] == "2026-10-27T12:30:00Z"
    assert stop["responseSchema"]["title"] == "CheckoutDecision"
    names = [call[0] for call in buyer.calls]
    assert "prepare_funding" in names
    assert names.count("approve_funding") == 1
    assert buyer.calls[names.index("approve_funding")][3] is True


async def test_completed_checkout_goes_straight_to_the_purchase_order() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await reach_funding_approval(graph, runtime, checkout_mode="embedded")
    await graph.ainvoke(
        Command(resume=funding_decision().model_dump(mode="json")), runtime
    )
    buyer.settlement_state = "FUNDED"

    result = await graph.ainvoke(
        Command(resume=checkout_decision().model_dump(mode="json")), runtime
    )

    stop = result["__interrupt__"][0].value
    assert stop["reason"] == "purchase_order_required"


async def test_completed_checkout_without_a_relayed_projection_uses_the_server_settlement() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await reach_funding_approval(graph, runtime, checkout_mode="embedded")
    await graph.ainvoke(
        Command(resume=funding_decision().model_dump(mode="json")), runtime
    )
    buyer.settlement_state = "FUNDED"

    result = await graph.ainvoke(
        Command(
            resume={
                "status": "completed",
                "transaction_id": "vf_1",
                "order_id": "ORDER-1",
                "capture_id": "CAP-1",
                "idempotency_key": "checkout:vf_1",
            }
        ),
        runtime,
    )

    stop = result["__interrupt__"][0].value
    assert stop["reason"] == "purchase_order_required"
    assert ("get_settlement", "run-1", True) in buyer.calls


async def test_completed_checkout_rejects_an_unfunded_server_settlement() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await reach_funding_approval(graph, runtime, checkout_mode="embedded")
    await graph.ainvoke(
        Command(resume=funding_decision().model_dump(mode="json")), runtime
    )
    # The relayed projection claims FUNDED; the authoritative settlement does
    # not. The graph must trust the server, not the card.
    buyer.settlement_state = "FUNDING_PENDING"

    with pytest.raises(VerifundProtocolError, match="checkout is not settled"):
        await graph.ainvoke(
            Command(resume=checkout_decision().model_dump(mode="json")),
            runtime,
        )


async def test_canceled_checkout_cancels_the_run() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await reach_funding_approval(graph, runtime, checkout_mode="embedded")
    await graph.ainvoke(
        Command(resume=funding_decision().model_dump(mode="json")), runtime
    )

    done = await graph.ainvoke(
        Command(
            resume=checkout_decision(
                status="canceled", projection={}, capture_id=None
            ).model_dump(mode="json")
        ),
        runtime,
    )

    assert "__interrupt__" not in done
    assert done["stage"] == "funding_rejected"
    names = [call[0] for call in buyer.calls]
    assert "cancel" in names
    assert "purchase_order" not in names


async def test_checkout_fallback_funds_through_the_redirect_flow() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await reach_funding_approval(graph, runtime, checkout_mode="embedded")
    await graph.ainvoke(
        Command(resume=funding_decision().model_dump(mode="json")), runtime
    )

    fallback = await graph.ainvoke(
        Command(
            resume=checkout_decision(
                status="fallback", projection={}, capture_id=None
            ).model_dump(mode="json")
        ),
        runtime,
    )

    stop = fallback["__interrupt__"][0].value
    assert stop["reason"] == "funding_pending"
    assert stop["checkout_url"] == "http://paypal.test/checkout/1"
    names = [call[0] for call in buyer.calls]
    assert names.count("approve_funding") == 2
    assert buyer.calls[names.index("approve_funding", names.index("prepare_funding"))][3] is False


async def test_checkout_must_settle_the_agreed_transaction() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await reach_funding_approval(graph, runtime, checkout_mode="embedded")
    await graph.ainvoke(
        Command(resume=funding_decision().model_dump(mode="json")), runtime
    )

    with pytest.raises(VerifundProtocolError):
        await graph.ainvoke(
            Command(
                resume=checkout_decision(transaction_id="vf_2").model_dump(
                    mode="json"
                )
            ),
            runtime,
        )
    buyer.settlement_transaction_id = "vf_2"
    with pytest.raises(VerifundProtocolError):
        await graph.ainvoke(
            Command(resume=checkout_decision().model_dump(mode="json")),
            runtime,
        )


async def test_redirect_mode_never_prepares_a_checkout() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await reach_funding_approval(graph, runtime)

    funded = await graph.ainvoke(
        Command(resume=funding_decision().model_dump(mode="json")), runtime
    )

    assert funded["__interrupt__"][0].value["reason"] == "funding_pending"
    names = [call[0] for call in buyer.calls]
    assert "prepare_funding" not in names
    assert buyer.calls[names.index("approve_funding")][3] is False
