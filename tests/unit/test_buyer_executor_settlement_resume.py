from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from a2a.server.events import EventQueue
from a2a.types.a2a_pb2 import Message, Role
from buyer_agent.executor import BuyerExecutor
from buyer_agent.settings import Settings
from commerce_core.a2a_parts import make_message
from langgraph.types import Command
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewResult,
    wrap_agreement_review_result,
)
from verifund_contracts import (
    AgreementProjection as _AgreementProjection,
)


def _new_agreement() -> AgreementProjection:
    payload: dict = {
        "agreement_id": "agr_1",
        "agreement_version": 1,
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "offer_round": 1,
        "offer_hash": "a" * 64,
        "offer_valid_until": datetime.now(UTC),
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
    probe = _AgreementProjection.model_construct(
        **payload, agreement_hash="0" * 64
    )
    return _AgreementProjection(**payload, agreement_hash=probe.recompute_hash())


class InterruptedGraph:
    def __init__(
        self, pending: dict | None = None, result=None
    ) -> None:
        self.pending = pending
        self.calls: list[tuple[object, dict]] = []
        self.result = result or {
            "stage": "awarded",
            "messages": [],
            "agreement": {},
        }

    async def aget_state(self, config):
        if self.pending is None:
            return SimpleNamespace(interrupts=())
        return SimpleNamespace(interrupts=(SimpleNamespace(value=self.pending),))

    async def ainvoke(self, payload, config):
        self.calls.append((payload, config))
        return self.result


class RecordingQueue:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def enqueue_event(self, event) -> None:
        self.events.append(event)


def _context(message: Message, task_id: str = "a2a-task", context_id: str = "a2a-ctx"):
    return SimpleNamespace(
        task_id=task_id, context_id=context_id, message=message
    )


def _executor(graph: InterruptedGraph) -> BuyerExecutor:
    return BuyerExecutor(
        services=SimpleNamespace(),
        settings=Settings(llm_mode="scripted"),
        checkpointer=None,
        graph=graph,
    )


def _status_responses(queue: RecordingQueue) -> list[dict]:
    responses = []
    for event in queue.events:
        status = getattr(event, "status", None)
        message = getattr(status, "message", None)
        for part in getattr(message, "parts", []):
            if part.HasField("text"):
                try:
                    responses.append(json.loads(part.text))
                except (json.JSONDecodeError, ValueError):
                    continue
    return responses


def _agreement_message(
    agreement: AgreementProjection, *, party: str = "buyer"
) -> Message:
    envelope = (
        {
            "schema": "https://marketmesh.example/extensions/verifund/v2/schemas/agreement-review-request.json",
            "schema_version": "1.0",
            "payload": {
                "party": "buyer",
                "run_id": agreement.run_id,
                "transaction_id": agreement.transaction_id,
                "agreement": agreement.model_dump(mode="json"),
                "buyer_task_id": "buyer-task-1",
                "buyer_context_id": "run-1",
                "requested_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "idempotency_key": "review:vf_1:1",
            },
        }
        if party == "buyer"
        else {
            "schema": "https://marketmesh.example/extensions/verifund/v2/schemas/agreement-review-result.json",
            "schema_version": "1.0",
            "payload": AgreementReviewResult(
                party="seller",
                status="accepted",
                run_id=agreement.run_id,
                transaction_id=agreement.transaction_id,
                agreement_version=agreement.agreement_version,
                agreement_hash=agreement.agreement_hash,
                offer_hash="a" * 64,
                actor_type="SELLER_AGENT",
                actor_id="northwind-audio",
                task_id="seller-task-1",
                context_id="run-1",
                reviewed_at=datetime.now(UTC),
            ).model_dump(mode="json"),
        }
    )
    return make_message(
        role=Role.ROLE_USER,
        text="Seller agreement review." if party == "seller" else "Buyer agreement review.",
        context_id="run-1",
        task_id="buyer-task-1",
        envelope=envelope,
    )


async def test_agreement_create_review_resumes_the_interrupted_run() -> None:
    agreement = _new_agreement()
    graph = InterruptedGraph(
        pending={
            "reason": "agreement_create_required",
            "run_id": "run-1",
            "buyer_task_id": "buyer-task-1",
            "buyer_context_id": "run-1",
            "agreement": agreement.model_dump(mode="json"),
            "seller_token_ref": "run:run-1:transaction:vf_1",
        },
        result={
            "stage": "awarded",
            "messages": [],
            "agreement": agreement.model_dump(mode="json"),
        },
    )
    queue = RecordingQueue()

    await _executor(graph).execute(
        _context(
            _agreement_message(agreement, party="buyer"),
            task_id="buyer-task-1",
            context_id="run-1",
        ),
        cast(EventQueue, queue),
    )

    assert len(graph.calls) == 1
    payload, config = graph.calls[0]
    assert isinstance(payload, Command)
    assert payload.resume["agreement"]["run_id"] == "run-1"
    assert payload.resume["seller_token_ref"] == "run:run-1:transaction:vf_1"
    assert config["configurable"]["thread_id"] == "run-1"
    assert _status_responses(queue)[-1]["status"] == "awarded"


async def test_seller_review_result_resumes_the_seller_decision() -> None:
    agreement = _new_agreement()
    graph = InterruptedGraph(
        pending={
            "reason": "seller_review_required",
            "agreement": agreement.model_dump(mode="json"),
        },
        result={"stage": "seller_reviewed", "messages": []},
    )
    queue = RecordingQueue()

    await _executor(graph).execute(
        _context(_agreement_message(agreement, party="seller"), task_id="buyer-task-1", context_id="run-1"),
        cast(EventQueue, queue),
    )

    assert len(graph.calls) == 1
    payload, config = graph.calls[0]
    assert isinstance(payload, Command)
    assert payload.resume["seller_decision"]["party"] == "seller"
    assert config["configurable"]["thread_id"] == "run-1"
    assert _status_responses(queue)[-1]["status"] == "seller_reviewed"


async def test_seller_review_result_with_a_wrong_hash_fails_cleanly() -> None:
    agreement = _new_agreement()
    graph = InterruptedGraph(
        pending={
            "reason": "seller_review_required",
            "agreement": agreement.model_dump(mode="json"),
        },
        result={"stage": "seller_reviewed", "messages": []},
    )
    queue = RecordingQueue()

    bad = AgreementReviewResult(
        party="seller",
        status="accepted",
        run_id=agreement.run_id,
        transaction_id=agreement.transaction_id,
        agreement_version=agreement.agreement_version,
        agreement_hash="b" * 64,
        offer_hash="a" * 64,
        actor_type="SELLER_AGENT",
        actor_id="northwind-audio",
        task_id="seller-task-1",
        context_id="run-1",
        reviewed_at=datetime.now(UTC),
    )
    message = make_message(
        role=Role.ROLE_USER,
        text="Seller agreement review.",
        context_id="run-1",
        task_id="buyer-task-1",
        envelope=wrap_agreement_review_result(bad),
    )
    await _executor(graph).execute(_context(message, task_id="buyer-task-1", context_id="run-1"), cast(EventQueue, queue))

    assert graph.calls == []
    response = _status_responses(queue)[-1]
    assert response["status"] == "failed"


async def test_seller_review_without_a_pending_interrupt_fails_cleanly() -> None:
    graph = InterruptedGraph(pending=None)
    queue = RecordingQueue()

    await _executor(graph).execute(
        _context(
            _agreement_message(_new_agreement(), party="seller"),
            task_id="buyer-task-1",
            context_id="run-1",
        ),
        cast(EventQueue, queue),
    )

    assert graph.calls == []
    response = _status_responses(queue)[-1]
    assert response["status"] == "failed"
    assert response["reason"] == "no_pending_review"
