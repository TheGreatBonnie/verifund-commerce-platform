from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from langgraph.checkpoint.memory import MemorySaver
from verifund_agent.client import BuyerInternalClient
from verifund_agent.graph import build_graph
from verifund_agent.service import VerifundAgentService
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewResult,
    BuyerAgreementApprovalDecision,
    FundingApprovalDecision,
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


def agreement() -> AgreementProjection:
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


def buyer_approval_decision(**overrides) -> BuyerAgreementApprovalDecision:
    payload = {
        "agreement_version": 1,
        "agreement_hash": AGREEMENT_HASH,
        "decision": "APPROVE",
        "idempotency_key": "buyer-decision:vf_1:1",
    }
    payload.update(overrides)
    return BuyerAgreementApprovalDecision.model_validate(payload)

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


class Buyer:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self._sync_count = 0

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

    async def get_settlement(self, run_id):
        self.calls.append(("get_settlement", run_id))
        self._sync_count += 1
        if self._sync_count == 1:
            status = "PENDING_SELLER"
        elif self._sync_count == 2:
            status = "PENDING_BUYER"
        else:
            status = "AGREED"
        agreement = AGREEMENT.model_copy(update={"status": status}).model_dump(mode="json")
        return {
            "agreement": agreement,
            "projection": {"transaction_id": "vf_1", "state": "AWARDED"},
        }

    async def get_agreement(self, run_id):
        self.calls.append(("get_agreement", run_id))
        agreement = AGREEMENT.model_copy(update={"status": "AGREED"}).model_dump(mode="json")
        return agreement


def service() -> tuple[VerifundAgentService, Buyer]:
    buyer = Buyer()
    graph = build_graph(MemorySaver())
    return VerifundAgentService(graph=graph, buyer=cast(BuyerInternalClient, buyer)), buyer


async def test_agreement_create_stops_at_the_seller_review() -> None:
    value, _buyer = service()
    result = await value.handle(
        task_request(), task_id="task-1", context_id="run-1"
    )
    assert result.status == "input_required"
    assert result.checkpoint == "seller_review_required"
    assert result.next_action == "seller_review"
    assert result.task_id == "task-1"
    assert result.state == "AWARDED"
    assert result.data["agreement"]["agreement_hash"] == AGREEMENT_HASH
    assert result.data["seller_token_ref"] == "run:run-1:transaction:vf_1"
    assert result.data["responseSchema"]["title"] == "AgreementReviewResult"


async def test_status_returns_the_pending_checkpoint_without_a_second_buyer_call() -> None:
    value, _buyer = service()
    await value.handle(task_request(), task_id="task-1", context_id="run-1")
    status = await value.handle(
        status_request(), task_id="task-1", context_id="run-1"
    )
    assert status.status == "input_required"
    assert status.checkpoint == "seller_review_required"


async def test_resume_advances_the_same_task_to_the_buyer_approval() -> None:
    value, _buyer = service()
    await value.handle(task_request(), task_id="task-1", context_id="run-1")
    resumed = await value.resume(
        resume_request(
            VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
            review("seller").model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    assert resumed.status == "input_required"
    assert resumed.checkpoint == "buyer_approval_required"
    assert resumed.next_action == "buyer_approval"
    assert resumed.data["seller_decision"]["status"] == "accepted"


async def test_seller_acceptance_opens_the_funding_approval() -> None:
    value, _ = service()
    await value.handle(task_request(), task_id="task-1", context_id="run-1")
    await value.resume(
        resume_request(
            VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
            review("seller").model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    funding = await value.resume(
        resume_request(
            VerifundCheckpoint.BUYER_APPROVAL_REQUIRED,
            buyer_approval_decision().model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    assert funding.status == "approval_required"
    assert funding.checkpoint == "funding_approval_required"
    assert funding.approval_type == "funding"
    assert funding.state == "AGREED"
    assert funding.data["seller_decision"]["status"] == "accepted"


async def test_a_stale_resume_returns_the_current_checkpoint() -> None:
    value, _ = service()
    await value.handle(task_request(), task_id="task-1", context_id="run-1")
    await value.resume(
        resume_request(
            VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
            review("seller").model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    repeated = await value.resume(
        resume_request(
            VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
            review("seller").model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    assert repeated.status == "input_required"
    assert repeated.checkpoint == "buyer_approval_required"


async def test_a_skipped_checkpoint_is_rejected() -> None:
    value, _ = service()
    await value.handle(task_request(), task_id="task-1", context_id="run-1")
    skipped = await value.resume(
        resume_request(
            VerifundCheckpoint.BUYER_APPROVAL_REQUIRED,
            buyer_approval_decision().model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    assert skipped.status == "failed"
    assert "does not match" in skipped.message


async def test_resume_requires_the_original_task() -> None:
    value, _ = service()
    await value.handle(task_request(), task_id="task-1", context_id="run-1")
    refused = await value.resume(
        resume_request(
            VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
            review("seller").model_dump(mode="json"),
            task_id="task-2",
        ),
        task_id="task-1",
        context_id="run-1",
    )
    assert refused.status == "failed"
    assert "task" in refused.message.lower()


async def test_agreement_create_rejects_a_run_mismatch() -> None:
    value, buyer = service()
    result = await value.handle(
        task_request(run_id="run-2"),
        task_id="task-1",
        context_id="run-1",
    )
    assert result.status == "failed"
    assert "run" in result.message.lower()
    assert buyer.calls == []


async def test_agreement_create_rejects_a_second_run_on_the_same_thread() -> None:
    value, _buyer = service()
    await value.handle(task_request(), task_id="task-1", context_id="thread-1")

    second = await value.handle(
        task_request(
            run_id="run-2",
            idempotency_key="agreement:run-2:offer-1",
            payload={
                "award": award(run_id="run-2"),
                "buyer_task_id": "buyer-task-2",
                "buyer_context_id": "thread-1",
            },
        ),
        task_id="task-2",
        context_id="thread-1",
    )

    assert second.status == "failed"
    assert "conversation" in second.message.lower()


async def test_agreement_create_is_idempotent_for_the_same_task() -> None:
    value, _buyer = service()
    first = await value.handle(
        task_request(), task_id="task-1", context_id="run-1"
    )
    second = await value.handle(
        task_request(), task_id="task-1", context_id="run-1"
    )
    assert first.checkpoint == second.checkpoint == "seller_review_required"


async def test_seller_rejection_finishes_the_task() -> None:
    value, _ = service()
    await value.handle(task_request(), task_id="task-1", context_id="run-1")
    rejected = await value.resume(
        resume_request(
            VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
            review("seller", status="rejected").model_dump(mode="json"),
        ),
        task_id="task-1",
        context_id="run-1",
    )
    assert rejected.status == "completed"
    assert rejected.state == "CANCELED"
    assert rejected.checkpoint is None


async def test_status_reports_the_funding_approval() -> None:
    value, _ = service()
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
    status = await value.handle(
        status_request(), task_id="task-1", context_id="run-1"
    )
    assert status.checkpoint == "funding_approval_required"
    assert status.status == "approval_required"
    assert status.approval_type == "funding"
