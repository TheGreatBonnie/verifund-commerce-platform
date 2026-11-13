from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import ValidationError
from verifund_agent.client import BuyerAPIError, BuyerInternalClient
from verifund_agent.graph import (
    VerifundProtocolError,
    build_graph,
    funding_decision_route,
    release_approval_matches,
    release_decision_route,
)
from verifund_agent.service import VerifundAgentService
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewResult,
    BuyerAgreementApprovalDecision,
    FundingApprovalDecision,
    ReleaseApprovalDecision,
    TransactionState,
    VerifundCheckpoint,
    VerifundResumeRequest,
    VerifundSkill,
    VerifundTaskRequest,
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
    probe = AgreementProjection.model_construct(
        **payload, agreement_hash="0" * 64
    )
    return AgreementProjection(
        **payload, agreement_hash=probe.recompute_hash()
    )


AGREEMENT = agreement()
HASH = AGREEMENT.agreement_hash


def projection(state: str, **overrides) -> dict:
    payload = {
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "state": state,
        "amount_cents": 123400,
        "currency": "USD",
        "allowed_actions": [],
        "approval": {
            "approval_id": "approval-1",
            "approved_by": "demo-reviewer",
            "approved_at": "2026-10-27T12:00:00Z",
            "note": "approved",
        },
        "evidence": {
            "required": ["shipment_manifest", "delivery_confirmation"],
            "received": ["shipment_manifest"],
            "complete": False,
            "items": [
                {"evidence_id": "ev_1", "kind": "shipment_manifest"}
            ],
        },
        "verification": {
            "status": "pending",
            "reasons": [],
            "override_allowed": False,
        },
    }
    payload.update(overrides)
    return payload


def review(party: str, **overrides) -> AgreementReviewResult:
    payload = {
        "party": party,
        "status": "accepted",
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "offer_hash": "a" * 64,
        "actor_type": "SELLER_AGENT" if party == "seller" else "BUYER_AGENT",
        "actor_id": "northwind-audio" if party == "seller" else "demo-buyer",
        "authority_ref": f"{party}-mandate:1",
        "authority_snapshot": {},
        "verified_change_request_id": None,
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
        "agreement_hash": HASH,
        "approved": True,
        "approved_by": "demo-reviewer",
        "note": "approved in the console",
        "decided_at": NOW,
        "idempotency_key": "fund:vf_1:1",
    }
    payload.update(overrides)
    return FundingApprovalDecision.model_validate(payload)


def buyer_approval_decision(**overrides) -> BuyerAgreementApprovalDecision:
    payload = {
        "agreement_version": 1,
        "agreement_hash": HASH,
        "decision": "APPROVE",
        "idempotency_key": "buyer-decision:vf_1:1",
    }
    payload.update(overrides)
    return BuyerAgreementApprovalDecision.model_validate(payload)


def release_decision(**overrides) -> ReleaseApprovalDecision:
    payload = {
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "approved": True,
        "released_by": "demo-reviewer",
        "note": "evidence verified",
        "override": False,
        "decided_at": NOW,
        "idempotency_key": "release:vf_1:1",
    }
    payload.update(overrides)
    return ReleaseApprovalDecision.model_validate(payload)


def order(**overrides) -> dict:
    payload = {
        "schema_version": "1.0",
        "order_id": "ord-1",
        "offer_id": "offer-1",
        "seller_id": "northwind-audio",
        "status": "confirmed",
        "currency": "USD",
        "quantity": 12,
        "total_cents": 123400,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "list_unit_price_cents": 11000,
                "warranty_addon_cents": 0,
                "attributes": {},
            }
        ],
        "reserved_at": NOW.isoformat(),
        "eta": "2026-11-03T12:00:00Z",
        "tracking_number": "TRK-1",
        "fulfillment": {"carrier": "UPS", "status": "confirmed"},
    }
    payload.update(overrides)
    return payload


class Buyer:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.view_projection = projection("FUNDING_PENDING")
        self.release_state = "PAYOUT_PENDING"
        self.receipt_ready = True

    async def create_agreement(self, run_id, request):
        self.calls.append(("create_agreement", run_id, request))
        return {
            "transaction_id": "vf_1",
            "state": "AWARDED",
            "agreement": AGREEMENT.model_dump(mode="json"),
            "agreement_version": 1,
            "agreement_hash": HASH,
            "seller_token_ref": "run:run-1:transaction:vf_1",
        }

    async def get_award(self, run_id):
        self.calls.append(("get_award", run_id))
        return award()

    async def approve_funding(self, run_id, decision):
        self.calls.append(("approve_funding", run_id, decision))
        self.view_projection = projection("FUNDING_PENDING")
        return {
            "projection": self.view_projection,
            "checkout_url": "http://paypal.test/checkout/1",
            "expires_at": "2026-10-27T12:30:00Z",
        }

    async def get_settlement(self, run_id):
        self.calls.append(("get_settlement", run_id))
        self._sync_count = getattr(self, "_sync_count", 0) + 1
        if self._sync_count == 1:
            status = "PENDING_SELLER"
        elif self._sync_count == 2:
            status = "PENDING_BUYER"
        else:
            status = "AGREED"
        agreement = AGREEMENT.model_copy(update={"status": status})
        return {
            "run_id": run_id,
            "transaction_id": "vf_1",
            "agreement_version": 1,
            "agreement_hash": HASH,
            "agreement": agreement.model_dump(mode="json"),
            "projection": self.view_projection,
        }

    async def get_agreement(self, run_id):
        self.calls.append(("get_agreement", run_id))
        agreement = AGREEMENT.model_copy(update={"status": "AGREED"})
        return agreement.model_dump(mode="json")

    async def purchase_order(self, run_id, request):
        self.calls.append(("purchase_order", run_id, request))
        return {
            "run_id": run_id,
            "transaction_id": "vf_1",
            "agreement_version": 1,
            "agreement_hash": HASH,
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
                "agreement_hash": HASH,
            },
        }

    async def report_order(self, run_id, request):
        self.calls.append(("report_order", run_id, request))
        self.view_projection = projection("FULFILLMENT_PENDING")
        return {
            "run_id": run_id,
            "transaction_id": "vf_1",
            "agreement_version": 1,
            "agreement_hash": HASH,
            "state": "FULFILLMENT_PENDING",
            "projection": self.view_projection,
        }

    async def release(self, run_id, decision):
        self.calls.append(("release", run_id, decision))
        self.view_projection = projection(self.release_state)
        return self.view_projection

    async def receipt(self, run_id):
        self.calls.append(("receipt", run_id))
        if not self.receipt_ready:
            raise BuyerAPIError(
                "buyer returned HTTP 404", status_code=404, retryable=False
            )
        return {
            "payload": {
                "receipt_version": 1,
                "transaction_id": "vf_1",
                "agreement_hash": HASH,
                "amount_cents": 123400,
                "currency": "USD",
                "buyer_id": "demo-buyer",
                "seller_id": "northwind-audio",
                "capture_id": "cap-1",
                "payout_item_id": "payout-1",
                "evidence_hashes": ["b" * 64],
                "released_at": "2026-10-27T12:05:00Z",
            },
            "payload_hash": "c" * 64,
            "signature": "sig",
            "kid": "kid-1",
            "verified": True,
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


async def reach_funding_approval(graph, runtime, buyer: Buyer) -> None:
    await graph.ainvoke(initial_state(), runtime)
    await graph.ainvoke(
        Command(resume=review("seller").model_dump(mode="json")), runtime
    )
    await graph.ainvoke(
        Command(resume=buyer_approval_decision().model_dump(mode="json")), runtime
    )


async def test_graph_waits_for_funding_order_evidence_and_release() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await reach_funding_approval(graph, runtime, buyer)

    funded = await graph.ainvoke(
        Command(resume=funding_decision().model_dump(mode="json")), runtime
    )
    funding_stop = funded["__interrupt__"][0].value
    assert funding_stop["reason"] == "funding_pending"
    assert funding_stop["checkout_url"] == "http://paypal.test/checkout/1"
    assert funding_stop["projection"]["state"] == "FUNDING_PENDING"

    buyer.view_projection = projection("FUNDED")
    ordered = await graph.ainvoke(
        Command(resume={"projection": buyer.view_projection}), runtime
    )
    order_stop = ordered["__interrupt__"][0].value
    assert order_stop["reason"] == "purchase_order_required"
    assert order_stop["seller_id"] == "northwind-audio"
    assert order_stop["purchase_order"]["request_id"] == "po-run-1-offer-1"
    assert order_stop["seller_token_ref"] == "run:run-1:transaction:vf_1"

    evidence = await graph.ainvoke(
        Command(resume={"order": order()}), runtime
    )
    evidence_stop = evidence["__interrupt__"][0].value
    assert evidence_stop["reason"] == "evidence_pending"
    assert evidence_stop["projection"]["state"] == "FULFILLMENT_PENDING"

    buyer.view_projection = projection(
        "RELEASE_PERMITTED",
        evidence={
            "required": ["shipment_manifest", "delivery_confirmation"],
            "received": ["shipment_manifest", "delivery_confirmation"],
            "complete": True,
            "items": [
                {"evidence_id": "ev_1", "kind": "shipment_manifest"},
                {"evidence_id": "ev_2", "kind": "delivery_confirmation"},
            ],
        },
        verification={"status": "permitted", "reasons": []},
    )
    release = await graph.ainvoke(
        Command(resume={"projection": buyer.view_projection}), runtime
    )
    release_stop = release["__interrupt__"][0].value
    assert release_stop["reason"] == "release_approval_required"
    assert release_stop["responseSchema"]["title"] == "ReleaseApprovalDecision"
    assert release_stop["override_allowed"] is False

    done = await graph.ainvoke(
        Command(resume=release_decision().model_dump(mode="json")), runtime
    )
    assert "__interrupt__" not in done
    assert done["stage"] == "completed"
    assert done["receipt"]["verified"] is True


async def test_graph_funding_rejection_never_orders() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await reach_funding_approval(graph, runtime, buyer)

    done = await graph.ainvoke(
        Command(
            resume=funding_decision(approved=False).model_dump(mode="json")
        ),
        runtime,
    )
    assert done["stage"] == "funding_rejected"
    assert [call[0] for call in buyer.calls] == [
        "get_award",
        "create_agreement",
        "get_settlement",
        "get_settlement",
        "get_agreement",
        "get_settlement",
        "approve_funding",
    ]


async def test_graph_order_must_match_the_purchase_order() -> None:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await reach_funding_approval(graph, runtime, buyer)
    await graph.ainvoke(
        Command(resume=funding_decision().model_dump(mode="json")), runtime
    )
    buyer.view_projection = projection("FUNDED")
    await graph.ainvoke(
        Command(resume={"projection": buyer.view_projection}), runtime
    )
    with pytest.raises(VerifundProtocolError):
        await graph.ainvoke(
            Command(resume={"order": order(offer_id="offer-2")}), runtime
        )
    assert "report_order" not in [call[0] for call in buyer.calls]


async def test_graph_release_rejection_goes_to_manual_review() -> None:
    buyer = Buyer()
    buyer.release_state = "REVIEW_REQUIRED"
    graph = build_graph(MemorySaver())
    runtime = config(buyer)
    await reach_funding_approval(graph, runtime, buyer)
    await graph.ainvoke(
        Command(resume=funding_decision().model_dump(mode="json")), runtime
    )
    buyer.view_projection = projection("FUNDED")
    await graph.ainvoke(
        Command(resume={"projection": buyer.view_projection}), runtime
    )
    await graph.ainvoke(Command(resume={"order": order()}), runtime)
    buyer.view_projection = projection("RELEASE_PERMITTED")
    await graph.ainvoke(
        Command(resume={"projection": buyer.view_projection}), runtime
    )
    done = await graph.ainvoke(
        Command(
            resume=release_decision(approved=False).model_dump(mode="json")
        ),
        runtime,
    )
    assert done["stage"] == "review_required"
    assert "receipt" not in [call[0] for call in buyer.calls]


def test_funding_and_release_routes_default_to_rejected() -> None:
    assert funding_decision_route({}) == "rejected"
    assert release_decision_route({}) == "rejected"
    assert funding_decision_route(
        {"funding_approval": {"approved": True}}
    ) == "approved"
    assert release_decision_route(
        {"release_approval": {"approved": True}}
    ) == "approved"


def test_release_approval_must_match_the_agreement() -> None:
    approval = release_decision()
    assert release_approval_matches(approval, AGREEMENT) is True
    assert (
        release_approval_matches(
            approval.model_copy(update={"run_id": "run-2"}), AGREEMENT
        )
        is False
    )
    assert (
        release_approval_matches(
            approval.model_copy(update={"agreement_hash": "d" * 64}),
            AGREEMENT,
        )
        is False
    )


def task_request(**overrides) -> VerifundTaskRequest:
    payload = {
        "skill": VerifundSkill.AGREEMENT_CREATE,
        "run_id": "run-1",
        "payload": {
            "award": award(),
            "buyer_task_id": "buyer-task-1",
            "buyer_context_id": "run-1",
        },
        "idempotency_key": "agreement:run-1:offer-1",
    }
    payload.update(overrides)
    return VerifundTaskRequest.model_validate(payload)


def status_request(**overrides) -> VerifundTaskRequest:
    payload = {
        "skill": VerifundSkill.TRANSACTION_STATUS,
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "idempotency_key": "status:run-1:vf_1",
    }
    payload.update(overrides)
    return VerifundTaskRequest.model_validate(payload)


def receipt_request(**overrides) -> VerifundTaskRequest:
    payload = {
        "skill": VerifundSkill.RECEIPT_GET,
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "idempotency_key": "receipt:run-1:vf_1",
    }
    payload.update(overrides)
    return VerifundTaskRequest.model_validate(payload)


def resume_request(checkpoint, value, **overrides) -> VerifundResumeRequest:
    payload = {
        "run_id": "run-1",
        "task_id": "task-1",
        "checkpoint": checkpoint,
        "value": value,
        "idempotency_key": f"resume:task-1:{checkpoint}",
    }
    payload.update(overrides)
    return VerifundResumeRequest.model_validate(payload)


def service() -> tuple[VerifundAgentService, Buyer]:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    return VerifundAgentService(graph=graph, buyer=cast(BuyerInternalClient, buyer)), buyer


async def reach_funding_checkpoint(value, buyer) -> None:
    await value.handle(task_request(), task_id="task-1", context_id="run-1")
    await value.resume(
        resume_request(
            VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
            review("seller").model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    await value.resume(
        resume_request(
            VerifundCheckpoint.BUYER_APPROVAL_REQUIRED,
            buyer_approval_decision().model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )


async def test_status_drives_the_lifecycle_to_release_and_receipt() -> None:
    value, buyer = service()
    await reach_funding_checkpoint(value, buyer)

    pending = await value.resume(
        resume_request(
            VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED,
            funding_decision().model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    assert pending.status == "completed"
    assert pending.checkpoint == VerifundCheckpoint.FUNDING_PENDING
    assert pending.state == TransactionState.FUNDING_PENDING
    assert pending.next_action == "funding_settlement"
    assert pending.data["checkout_url"] == "http://paypal.test/checkout/1"

    buyer.view_projection = projection("FUNDED")
    purchase_order = await value.handle(
        status_request(), task_id="task-1", context_id="run-1"
    )
    assert purchase_order.status == "input_required"
    assert purchase_order.checkpoint == VerifundCheckpoint.PURCHASE_ORDER_REQUIRED
    assert purchase_order.next_action == "purchase_order"
    assert purchase_order.state == TransactionState.FUNDED
    assert purchase_order.data["purchase_order"]["request_id"] == (
        "po-run-1-offer-1"
    )
    assert purchase_order.data["seller_token_ref"] == (
        "run:run-1:transaction:vf_1"
    )

    evidence = await value.resume(
        resume_request(
            VerifundCheckpoint.PURCHASE_ORDER_REQUIRED,
            {"order": order()},
        ),
        task_id="task-1",
        context_id="run-1",
    )
    assert evidence.status == "completed"
    assert evidence.checkpoint == VerifundCheckpoint.EVIDENCE_PENDING
    assert evidence.state == TransactionState.FULFILLMENT_PENDING
    report = buyer.calls[[call[0] for call in buyer.calls].index("report_order")]
    assert report[2].order["seller_order_id"] == "ord-1"
    assert report[2].order["total_cents"] == 123400

    buyer.view_projection = projection(
        "RELEASE_PERMITTED",
        evidence={
            "required": ["shipment_manifest", "delivery_confirmation"],
            "received": ["shipment_manifest", "delivery_confirmation"],
            "complete": True,
            "items": [
                {"evidence_id": "ev_1", "kind": "shipment_manifest"},
                {"evidence_id": "ev_2", "kind": "delivery_confirmation"},
            ],
        },
        verification={"status": "permitted", "reasons": []},
    )
    release = await value.handle(
        status_request(), task_id="task-1", context_id="run-1"
    )
    assert release.status == "approval_required"
    assert release.checkpoint == VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED
    assert release.approval_type == "release"
    assert release.next_action == "approve_release"
    assert release.data["evidence"]["complete"] is True
    assert release.data["override_allowed"] is False

    done = await value.resume(
        resume_request(
            VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED,
            release_decision().model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    assert done.status == "completed"
    assert done.state == TransactionState.RELEASED
    assert done.data["receipt"]["verified"] is True
    assert done.data["receipt"]["payload"]["transaction_id"] == "vf_1"


async def test_funding_pending_status_is_idempotent() -> None:
    value, buyer = service()
    await reach_funding_checkpoint(value, buyer)
    first = await value.resume(
        resume_request(
            VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED,
            funding_decision().model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    second = await value.handle(
        status_request(), task_id="task-1", context_id="run-1"
    )
    assert first.checkpoint == second.checkpoint == VerifundCheckpoint.FUNDING_PENDING
    assert [call[0] for call in buyer.calls].count("approve_funding") == 1
    assert "purchase_order" not in [call[0] for call in buyer.calls]


async def test_evidence_pending_returns_the_latest_evidence() -> None:
    value, buyer = service()
    await reach_funding_checkpoint(value, buyer)
    await value.resume(
        resume_request(
            VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED,
            funding_decision().model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    buyer.view_projection = projection("FUNDED")
    await value.handle(status_request(), task_id="task-1", context_id="run-1")
    await value.resume(
        resume_request(
            VerifundCheckpoint.PURCHASE_ORDER_REQUIRED,
            {"order": order()},
        ),
        task_id="task-1",
        context_id="run-1",
    )
    buyer.view_projection = projection(
        "FULFILLMENT_PENDING",
        evidence={
            "required": ["shipment_manifest", "delivery_confirmation"],
            "received": ["delivery_confirmation"],
            "complete": False,
            "items": [
                {"evidence_id": "ev_2", "kind": "delivery_confirmation"}
            ],
        },
    )
    status = await value.handle(
        status_request(), task_id="task-1", context_id="run-1"
    )
    assert status.checkpoint == VerifundCheckpoint.EVIDENCE_PENDING
    assert status.data["evidence"]["received"] == ["delivery_confirmation"]
    assert "release" not in [call[0] for call in buyer.calls]


async def test_funding_rejection_cancels_the_task() -> None:
    value, buyer = service()
    await reach_funding_checkpoint(value, buyer)
    done = await value.resume(
        resume_request(
            VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED,
            funding_decision(approved=False).model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    assert done.status == "completed"
    assert done.state == TransactionState.CANCELED
    assert "purchase_order" not in [call[0] for call in buyer.calls]


async def test_release_rejection_flags_manual_review() -> None:
    value, buyer = service()
    buyer.release_state = "REVIEW_REQUIRED"
    await reach_funding_checkpoint(value, buyer)
    await value.resume(
        resume_request(
            VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED,
            funding_decision().model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    buyer.view_projection = projection("FUNDED")
    await value.handle(status_request(), task_id="task-1", context_id="run-1")
    await value.resume(
        resume_request(
            VerifundCheckpoint.PURCHASE_ORDER_REQUIRED,
            {"order": order()},
        ),
        task_id="task-1",
        context_id="run-1",
    )
    buyer.view_projection = projection("RELEASE_PERMITTED")
    await value.handle(status_request(), task_id="task-1", context_id="run-1")
    done = await value.resume(
        resume_request(
            VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED,
            release_decision(approved=False).model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    assert done.status == "completed"
    assert done.state == TransactionState.REVIEW_REQUIRED
    assert "receipt" not in [call[0] for call in buyer.calls]


async def test_purchase_order_resume_must_match_the_purchase_order() -> None:
    value, buyer = service()
    await reach_funding_checkpoint(value, buyer)
    await value.resume(
        resume_request(
            VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED,
            funding_decision().model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    buyer.view_projection = projection("FUNDED")
    await value.handle(status_request(), task_id="task-1", context_id="run-1")
    refused = await value.resume(
        resume_request(
            VerifundCheckpoint.PURCHASE_ORDER_REQUIRED,
            {"order": order(quantity=1)},
        ),
        task_id="task-1",
        context_id="run-1",
    )
    assert refused.status == "failed"
    assert "quantity" in refused.message
    assert "report_order" not in [call[0] for call in buyer.calls]


async def test_receipt_is_available_after_the_payout_completes() -> None:
    value, buyer = service()
    buyer.receipt_ready = False
    await reach_funding_checkpoint(value, buyer)
    await value.resume(
        resume_request(
            VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED,
            funding_decision().model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    buyer.view_projection = projection("FUNDED")
    await value.handle(status_request(), task_id="task-1", context_id="run-1")
    await value.resume(
        resume_request(
            VerifundCheckpoint.PURCHASE_ORDER_REQUIRED,
            {"order": order()},
        ),
        task_id="task-1",
        context_id="run-1",
    )
    buyer.view_projection = projection("RELEASE_PERMITTED")
    await value.handle(status_request(), task_id="task-1", context_id="run-1")
    released = await value.resume(
        resume_request(
            VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED,
            release_decision().model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    assert released.checkpoint is None
    assert released.state == TransactionState.PAYOUT_PENDING
    assert released.data["receipt"] is None

    buyer.receipt_ready = True
    receipt = await value.handle(
        receipt_request(), task_id="task-1", context_id="run-1"
    )
    assert receipt.status == "completed"
    assert receipt.state == TransactionState.RELEASED
    assert receipt.data["receipt"]["verified"] is True


def test_pending_checkpoints_cannot_be_resumed_externally() -> None:
    with pytest.raises(ValidationError):
        resume_request(
            VerifundCheckpoint.FUNDING_PENDING,
            {"projection": projection("FUNDED")},
        )
    with pytest.raises(ValidationError):
        resume_request(
            VerifundCheckpoint.EVIDENCE_PENDING,
            {"projection": projection("RELEASE_PERMITTED")},
        )
