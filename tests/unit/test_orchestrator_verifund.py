from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal, cast

import pytest
from a2a.types.a2a_pb2 import TaskArtifactUpdateEvent
from commerce_core.a2a_parts import (
    first_envelope,
    make_artifact,
)
from commerce_core.contracts import Order, PurchaseOrderRequest
from commerce_core.extension import wrap_payload
from orchestrator_agent.agent import MARKETMESH_ORCHESTRATOR_INSTRUCTION
from orchestrator_agent.settings import Settings
from orchestrator_agent.verifund import (
    BuyerA2AAgents,
    SellerA2AClient,
    VerifundA2AClient,
    VerifundLifecycle,
    VerifundProtocolError,
    VerifundTaskHandle,
)
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewResult,
    FundingApprovalDecision,
    ReleaseApprovalDecision,
    TransactionState,
    VerifundCheckpoint,
    VerifundSkill,
    VerifundTaskResult,
    parse_verifund_resume_request,
    wrap_verifund_task_result,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


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
HASH = AGREEMENT.agreement_hash


def binding() -> dict:
    return {
        "run_id": AGREEMENT.run_id,
        "transaction_id": AGREEMENT.transaction_id,
        "agreement_version": AGREEMENT.agreement_version,
        "agreement_hash": AGREEMENT.agreement_hash,
        "agreement": AGREEMENT.model_dump(mode="json"),
    }


def review(
    party: Literal["buyer", "seller"],
    status: Literal["accepted", "rejected"] = "accepted",
) -> AgreementReviewResult:
    return AgreementReviewResult(
        party=party,
        status=status,
        run_id=AGREEMENT.run_id,
        transaction_id=AGREEMENT.transaction_id,
        agreement_version=AGREEMENT.agreement_version,
        agreement_hash=AGREEMENT.agreement_hash,
        offer_hash="a" * 64,
        actor_type="SELLER_AGENT" if party == "seller" else "BUYER_AGENT",
        actor_id=AGREEMENT.seller_id if party == "seller" else AGREEMENT.buyer_id,
        task_id=f"{party}-task-1",
        context_id=AGREEMENT.run_id,
        reviewed_at=NOW,
    )


def task_result(
    *,
    skill: VerifundSkill = VerifundSkill.AGREEMENT_CREATE,
    status: Literal["completed", "input_required", "approval_required", "failed"] = "input_required",
    checkpoint: VerifundCheckpoint | None = None,
    approval_type: Literal["funding", "release"] | None = None,
    state: TransactionState | None = None,
    data: dict[str, Any] | None = None,
    message: str = "",
) -> VerifundTaskResult:
    return VerifundTaskResult(
        skill=skill,
        status=status,
        task_id="vf-task-1",
        checkpoint=checkpoint,
        approval_type=approval_type,
        run_id=AGREEMENT.run_id,
        transaction_id=AGREEMENT.transaction_id,
        agreement_version=AGREEMENT.agreement_version,
        agreement_hash=AGREEMENT.agreement_hash,
        state=state,
        data=data or {},
        message=message,
    )


def funding_result() -> VerifundTaskResult:
    return task_result(
        skill=VerifundSkill.TRANSACTION_FUND,
        status="approval_required",
        checkpoint=VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED,
        approval_type="funding",
        data={
            **binding(),
            "buyer_review": review("buyer").model_dump(mode="json"),
            "seller_decision": review("seller").model_dump(mode="json"),
        },
        message="Approve funding for this agreement.",
    )


def release_result() -> VerifundTaskResult:
    return task_result(
        skill=VerifundSkill.TRANSACTION_RELEASE,
        status="approval_required",
        checkpoint=VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED,
        approval_type="release",
        state=TransactionState.RELEASE_PERMITTED,
        data={
            **binding(),
            "projection": {
                "transaction_id": AGREEMENT.transaction_id,
                "state": "RELEASE_PERMITTED",
                "verification": {
                    "status": "permitted",
                    "reasons": [],
                    "override_allowed": False,
                },
                "evidence": {
                    "required": ["shipment_manifest", "delivery_confirmation"],
                    "received": ["shipment_manifest", "delivery_confirmation"],
                    "complete": True,
                },
            },
        },
        message="Approve the release of held funds.",
    )


def order() -> dict:
    return {
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


def purchase_order() -> PurchaseOrderRequest:
    return PurchaseOrderRequest(
        request_id="po-run-1-offer-1",
        run_id=AGREEMENT.run_id,
        offer_id=AGREEMENT.offer_id,
        seller_id=AGREEMENT.seller_id,
        quantity=AGREEMENT.quantity,
        shipping_address={
            "name": "Demo Buyer",
            "line1": "1 Market Street",
            "city": "San Francisco",
            "region": "CA",
            "postal_code": "94105",
            "country": "US",
        },
        approval={
            "approval_id": "approval-1",
            "approved_by": "demo-reviewer",
            "approved_at": NOW.isoformat(),
            "note": "award approved",
        },
        idempotency_key="po:run-1:offer-1",
        expected_total_cents=AGREEMENT.amount_cents,
        settlement_transaction_id=AGREEMENT.transaction_id,
        agreement_hash=AGREEMENT.agreement_hash,
    )


class FakeVerifund:
    def __init__(
        self,
        *,
        start_result: VerifundTaskResult,
        resume_results: list[VerifundTaskResult],
        status_results: list[VerifundTaskResult] | None = None,
        receipt_result: VerifundTaskResult | None = None,
    ) -> None:
        self.start_result = start_result
        self.resume_results = list(resume_results)
        self.status_results = list(status_results or [])
        self.receipt_result = receipt_result
        self.calls: list[tuple] = []

    async def start(self, **kwargs):
        self.calls.append(("start", kwargs))
        return VerifundTaskHandle("vf-task-1", "vf-context-1", "run-1"), self.start_result

    async def status(self, handle):
        self.calls.append(("status", handle))
        return self.status_results.pop(0)

    async def resume(self, handle, *, checkpoint, value, idempotency_key):
        self.calls.append(("resume", handle, checkpoint, value, idempotency_key))
        return self.resume_results.pop(0)

    async def receipt(self, handle, *, transaction_id):
        self.calls.append(("receipt", handle, transaction_id))
        return self.receipt_result


class FakeBuyer:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.status = "seller_review_required"
        self.review_status = "accepted"

    async def resume_buyer(self, **kwargs):
        self.calls.append(("buyer", kwargs))
        return {
            "status": (
                "seller_review_required"
                if self.review_status == "accepted"
                else "rejected"
            ),
            "task_id": kwargs["task_id"],
            "buyer_agent_review": {
                "status": self.review_status,
                "agreement_version": AGREEMENT.agreement_version,
                "agreement_hash": AGREEMENT.agreement_hash,
                "reviewed_at": NOW.isoformat(),
                "reason_code": None,
            },
        }

    async def apply_seller_decision(self, **kwargs):
        self.calls.append(("buyer_seller", kwargs))
        decision = kwargs.get("decision")
        decision_status = getattr(decision, "status", None)
        if decision_status is None and isinstance(decision, dict):
            decision_status = decision.get("status")
        if decision_status == "rejected":
            status = "rejected"
        elif decision_status == "accepted":
            status = "agreed"
        else:
            status = "agreed" if self.review_status == "accepted" else "rejected"
        return {"status": status, "task_id": kwargs["task_id"]}


class FakeSeller:
    def __init__(
        self, status: Literal["accepted", "rejected"] = "accepted"
    ) -> None:
        self.status = status
        self.calls: list[tuple] = []

    async def review(self, card_url, request):
        self.calls.append(("review", card_url, request))
        return review("seller", self.status)

    async def purchase_order(self, **kwargs):
        self.calls.append(("purchase_order", kwargs))
        return order()


def lifecycle(
    verifund: FakeVerifund,
    buyer: FakeBuyer | None = None,
    seller: FakeSeller | None = None,
) -> VerifundLifecycle:
    return VerifundLifecycle(
        verifund=cast(VerifundA2AClient, verifund),
        buyer=cast(BuyerA2AAgents, buyer or FakeBuyer()),
        seller=cast(SellerA2AClient, seller or FakeSeller()),
        buyer_internal_url="http://buyer",
        buyer_internal_token="internal-token",
    )


async def test_lifecycle_reviews_buyer_then_seller_and_exposes_funding_hitl() -> None:
    verifund = FakeVerifund(
        start_result=task_result(
            checkpoint=VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
            data={**binding(), "seller_token_ref": "run:run-1:transaction:vf_1"},
        ),
        resume_results=[
            task_result(
                checkpoint=VerifundCheckpoint.BUYER_APPROVAL_REQUIRED,
                data=binding(),
            ),
            funding_result(),
        ],
    )
    buyer = FakeBuyer()
    seller = FakeSeller()
    value = lifecycle(verifund, buyer, seller)
    result = await value.start(
        run_id=AGREEMENT.run_id,
        award={"run_id": AGREEMENT.run_id, "offer_id": AGREEMENT.offer_id},
        buyer_task_id="buyer-task-1",
        buyer_context_id="run-1",
        seller_card_url="http://seller/.well-known/agent-card.json",
        seller_id=AGREEMENT.seller_id,
        idempotency_key="agreement:run-1:offer-1",
    )
    assert result["status"] == "input_required"
    assert result["checkpoint"] == "buyer_approval_required"
    assert result["seller_decision"]["status"] == "accepted"
    assert result["handle"] == {
        "task_id": "vf-task-1",
        "context_id": "vf-context-1",
        "run_id": "run-1",
    }
    assert [call[0] for call in buyer.calls] == ["buyer_seller"]
    resume_calls = [call for call in verifund.calls if call[0] == "resume"]
    assert resume_calls[0][2] is VerifundCheckpoint.SELLER_REVIEW_REQUIRED
    assert resume_calls[0][3]["party"] == "seller"


async def test_lifecycle_defers_the_buyer_decision_to_the_human_approval() -> None:
    verifund = FakeVerifund(
        start_result=task_result(
            checkpoint=VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
            data={**binding(), "seller_token_ref": "run:run-1:transaction:vf_1"},
        ),
        resume_results=[
            task_result(
                checkpoint=VerifundCheckpoint.BUYER_APPROVAL_REQUIRED,
                data=binding(),
            )
        ],
    )
    buyer = FakeBuyer()
    seller = FakeSeller()
    result = await lifecycle(verifund, buyer, seller).start(
        run_id=AGREEMENT.run_id,
        award={"run_id": AGREEMENT.run_id, "offer_id": AGREEMENT.offer_id},
        buyer_task_id="buyer-task-1",
        buyer_context_id="run-1",
        seller_card_url="http://seller/.well-known/agent-card.json",
        seller_id=AGREEMENT.seller_id,
        idempotency_key="agreement:run-1:offer-1",
    )
    assert result["status"] == "input_required"
    assert result["checkpoint"] == "buyer_approval_required"
    assert result["seller_decision"]["status"] == "accepted"
    assert result["buyer_review"] is None
    assert "hitl" not in result
    assert [call[0] for call in seller.calls] == ["review"]
    assert [call[0] for call in buyer.calls] == ["buyer_seller"]
    resume_calls = [call for call in verifund.calls if call[0] == "resume"]
    assert len(resume_calls) == 1
    assert resume_calls[0][2] is VerifundCheckpoint.SELLER_REVIEW_REQUIRED
    assert resume_calls[0][3]["party"] == "seller"


async def test_lifecycle_never_funds_after_seller_rejection() -> None:
    verifund = FakeVerifund(
        start_result=task_result(
            checkpoint=VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
            data={**binding(), "seller_token_ref": "run:run-1:transaction:vf_1"},
        ),
        resume_results=[
            task_result(
                status="completed",
                state=TransactionState.CANCELED,
                data={**binding(), "stage": "rejected"},
                message="The transaction was rejected; no funds moved.",
            ),
        ],
    )
    buyer = FakeBuyer()
    result = await lifecycle(verifund, buyer, FakeSeller("rejected")).start(
        run_id=AGREEMENT.run_id,
        award={"run_id": AGREEMENT.run_id, "offer_id": AGREEMENT.offer_id},
        buyer_task_id="buyer-task-1",
        buyer_context_id="run-1",
        seller_card_url="http://seller/.well-known/agent-card.json",
        seller_id=AGREEMENT.seller_id,
        idempotency_key="agreement:run-1:offer-1",
    )
    assert result["status"] == "completed"
    assert result["state"] == "CANCELED"
    assert result["seller_decision"]["status"] == "rejected"
    assert result["buyer_review"] is None
    assert "hitl" not in result
    resume_calls = [call for call in verifund.calls if call[0] == "resume"]
    assert len(resume_calls) == 1
    assert resume_calls[0][2] is VerifundCheckpoint.SELLER_REVIEW_REQUIRED
    assert not [
        call for call in resume_calls
        if call[2] is VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED
    ]


async def test_advance_places_the_purchase_order_and_reports_evidence() -> None:
    verifund = FakeVerifund(
        start_result=task_result(checkpoint=VerifundCheckpoint.SELLER_REVIEW_REQUIRED),
        resume_results=[
            task_result(
                status="completed",
                checkpoint=VerifundCheckpoint.EVIDENCE_PENDING,
                state=TransactionState.FULFILLMENT_PENDING,
                data={
                    **binding(),
                    "projection": {
                        "transaction_id": AGREEMENT.transaction_id,
                        "state": "FULFILLMENT_PENDING",
                        "evidence": {
                            "required": ["shipment_manifest"],
                            "received": [],
                            "complete": False,
                        },
                    },
                },
            )
        ],
        status_results=[
            task_result(
                checkpoint=VerifundCheckpoint.PURCHASE_ORDER_REQUIRED,
                state=TransactionState.FUNDED,
                data={
                    **binding(),
                    "seller_id": AGREEMENT.seller_id,
                    "seller_token_ref": "run:run-1:transaction:vf_1",
                    "purchase_order": purchase_order().model_dump(mode="json"),
                },
            )
        ],
    )
    seller = FakeSeller()
    result = await lifecycle(verifund, seller=seller).advance(
        VerifundTaskHandle("vf-task-1", "vf-context-1", "run-1"),
        seller_card_url="http://seller/.well-known/agent-card.json",
    )
    assert result["status"] == "working"
    assert result["checkpoint"] == "evidence_pending"
    assert result["evidence"]["complete"] is False
    purchase = seller.calls[0][1]["purchase_order"]
    assert purchase["run_id"] == "run-1"
    assert purchase["settlement_transaction_id"] == AGREEMENT.transaction_id
    assert purchase["agreement_hash"] == HASH
    resume = next(call for call in verifund.calls if call[0] == "resume")
    assert resume[2] is VerifundCheckpoint.PURCHASE_ORDER_REQUIRED
    assert resume[3]["order"]["order_id"] == "ord-1"


async def test_advance_exposes_the_release_hitl_with_the_exact_args() -> None:
    verifund = FakeVerifund(
        start_result=task_result(checkpoint=VerifundCheckpoint.SELLER_REVIEW_REQUIRED),
        resume_results=[],
        status_results=[release_result()],
    )
    result = await lifecycle(verifund).advance(
        VerifundTaskHandle("vf-task-1", "vf-context-1", "run-1"),
        seller_card_url="http://seller/.well-known/agent-card.json",
    )
    assert result["status"] == "approval_required"
    assert result["hitl"]["tool"] == "request_verifund_release_approval"
    args = result["hitl"]["args"]
    assert args["projection"]["state"] == "RELEASE_PERMITTED"
    assert args["projection"]["verification"]["override_allowed"] is False
    assert args["projection"]["evidence"]["complete"] is True
    assert args["transaction_id"] == AGREEMENT.transaction_id


async def test_release_decision_resumes_the_same_task_and_returns_the_receipt() -> None:
    receipt = {
        "payload": {
            "receipt_version": 1,
            "transaction_id": AGREEMENT.transaction_id,
            "agreement_hash": HASH,
            "amount_cents": AGREEMENT.amount_cents,
            "currency": "USD",
            "buyer_id": AGREEMENT.buyer_id,
            "seller_id": AGREEMENT.seller_id,
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
    verifund = FakeVerifund(
        start_result=task_result(checkpoint=VerifundCheckpoint.SELLER_REVIEW_REQUIRED),
        resume_results=[
            task_result(
                status="completed",
                state=TransactionState.RELEASED,
                data={**binding(), "stage": "completed", "receipt": receipt},
            )
        ],
    )
    decision = ReleaseApprovalDecision(
        run_id=AGREEMENT.run_id,
        transaction_id=AGREEMENT.transaction_id,
        agreement_version=AGREEMENT.agreement_version,
        agreement_hash=HASH,
        approved=True,
        released_by="demo-reviewer",
        note="evidence verified",
        decided_at=NOW,
        idempotency_key=f"release:{AGREEMENT.run_id}:{AGREEMENT.transaction_id}",
    )
    result = await lifecycle(verifund).resume_release(
        VerifundTaskHandle("vf-task-1", "vf-context-1", "run-1"),
        decision,
    )
    assert result["status"] == "completed"
    assert result["state"] == "RELEASED"
    assert result["receipt"]["verified"] is True
    resume = next(call for call in verifund.calls if call[0] == "resume")
    assert resume[1].task_id == "vf-task-1"
    assert resume[2] is VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED
    assert resume[3] == decision.model_dump(mode="json")


async def test_funding_decision_requires_a_structured_decision() -> None:
    verifund = FakeVerifund(
        start_result=task_result(checkpoint=VerifundCheckpoint.SELLER_REVIEW_REQUIRED),
        resume_results=[
            task_result(
                status="completed",
                checkpoint=VerifundCheckpoint.FUNDING_PENDING,
                state=TransactionState.FUNDING_PENDING,
                data={
                    **binding(),
                    "checkout_url": "http://paypal.test/checkout/1",
                    "projection": {"state": "FUNDING_PENDING"},
                },
            )
        ],
    )
    decision = FundingApprovalDecision(
        run_id=AGREEMENT.run_id,
        transaction_id=AGREEMENT.transaction_id,
        agreement_version=AGREEMENT.agreement_version,
        agreement_hash=HASH,
        approved=True,
        approved_by="demo-reviewer",
        note="approved",
        decided_at=NOW,
        idempotency_key=f"fund:{AGREEMENT.run_id}:{AGREEMENT.transaction_id}",
    )
    result = await lifecycle(verifund).resume_funding(
        VerifundTaskHandle("vf-task-1", "vf-context-1", "run-1"),
        decision,
    )
    assert result["status"] == "working"
    assert result["checkout_url"] == "http://paypal.test/checkout/1"
    resume = next(call for call in verifund.calls if call[0] == "resume")
    assert resume[2] is VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED
    assert resume[3]["approved"] is True


async def test_verifund_client_reuses_one_task_for_status_and_resume() -> None:
    sent = []

    async def send(base_url, message, token=None):
        sent.append(message)
        envelope = first_envelope(message)
        assert envelope is not None
        if envelope["schema"].endswith("/resume-request.json"):
            result = task_result(
                checkpoint=VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
                data=binding(),
            )
        else:
            result = task_result(
                checkpoint=VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
                data={**binding(), "seller_token_ref": "run:run-1:transaction:vf_1"},
            )
        return [
            TaskArtifactUpdateEvent(
                task_id=message.task_id or "vf-task-1",
                context_id=message.context_id or "vf-context-1",
                artifact=make_artifact(
                    "verifund-result", wrap_verifund_task_result(result)
                ),
            )
        ]

    client = VerifundA2AClient(
        base_url="http://verifund", token="agent-token", send=send
    )
    handle, _result = await client.start(
        run_id=AGREEMENT.run_id,
        award={"run_id": AGREEMENT.run_id},
        buyer_task_id="buyer-task-1",
        buyer_context_id="run-1",
        idempotency_key="agreement:run-1:offer-1",
    )
    assert handle.task_id == "vf-task-1"
    assert handle.context_id == "vf-context-1"
    await client.status(handle)
    await client.resume(
        handle,
        checkpoint=VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
        value=review("buyer").model_dump(mode="json"),
        idempotency_key="resume:buyer",
    )
    assert sent[1].task_id == "vf-task-1"
    assert sent[1].context_id == "vf-context-1"
    assert sent[2].task_id == "vf-task-1"
    assert sent[2].context_id == "vf-context-1"
    resume_envelope = first_envelope(sent[2])
    assert resume_envelope is not None
    resume = parse_verifund_resume_request(resume_envelope)
    assert resume.task_id == "vf-task-1"
    assert resume.checkpoint is VerifundCheckpoint.SELLER_REVIEW_REQUIRED


async def test_seller_purchase_order_injects_the_token_and_never_returns_it() -> None:
    sent = []

    async def resolve_token(url, token, ref, *, timeout_seconds=10.0):
        assert url == "http://buyer"
        assert token == "internal-token"
        assert ref == {
            "run_id": "run-1",
            "transaction_id": "vf_1",
            "seller_id": "northwind-audio",
            "purpose": "purchase_order",
        }
        return "v1.secret"

    async def send(base_url, message, token=None):
        sent.append((base_url, message, token))
        envelope = first_envelope(message)
        assert envelope is not None
        assert envelope["payload"]["settlement_token"] == "v1.secret"
        return [
            TaskArtifactUpdateEvent(
                task_id="seller-task-1",
                context_id="run-1",
                artifact=make_artifact(
                    "order", wrap_payload("order", Order.model_validate(order()))
                ),
            )
        ]

    client = SellerA2AClient(
        send=send, resolve_settlement_token=resolve_token
    )
    result = await client.purchase_order(
        card_url="http://seller/.well-known/agent-card.json",
        seller_id="northwind-audio",
        run_id="run-1",
        purchase_order=purchase_order(),
        buyer_internal_url="http://buyer",
        buyer_internal_token="internal-token",
    )
    assert result["order_id"] == "ord-1"
    assert "v1.secret" not in json.dumps(result)


async def test_verifund_protocol_errors_are_not_successes() -> None:
    with pytest.raises(VerifundProtocolError):
        raise VerifundProtocolError("Verifund returned no structured result")


def test_orchestrator_instruction_describes_the_verifund_settlement_flow() -> None:
    assert "verifund_create_agreement" in MARKETMESH_ORCHESTRATOR_INSTRUCTION
    assert "verifund_fund" in MARKETMESH_ORCHESTRATOR_INSTRUCTION
    assert "verifund_evidence_review" in MARKETMESH_ORCHESTRATOR_INSTRUCTION
    assert "verifund_release" in MARKETMESH_ORCHESTRATOR_INSTRUCTION
    assert "verifund_receipt" in MARKETMESH_ORCHESTRATOR_INSTRUCTION
    assert "never call the seller" in MARKETMESH_ORCHESTRATOR_INSTRUCTION.lower()
    assert "never invent a review" in MARKETMESH_ORCHESTRATOR_INSTRUCTION.lower()
    assert "request_award_approval" in MARKETMESH_ORCHESTRATOR_INSTRUCTION


def test_settings_default_to_sandbox_and_keep_verifund_credentials_separate(
    monkeypatch,
) -> None:
    for key in (
        "VERIFUND_MODE",
        "VERIFUND_AGENT_URL",
        "VERIFUND_AGENT_A2A_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None)
    assert settings.verifund_mode == "sandbox"
    assert settings.verifund_agent_url.endswith(":9301")
    assert settings.verifund_agent_a2a_token
    assert settings.verifund_agent_a2a_token != settings.buyer_internal_token
