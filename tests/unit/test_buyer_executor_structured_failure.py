from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from a2a.server.events import EventQueue
from a2a.types.a2a_pb2 import Message, Role
from commerce_core.a2a_parts import make_message
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewResult,
    wrap_agreement_review_result,
)

from .test_buyer_executor_settlement_resume import (
    RecordingQueue,
    _context,
    _executor,
    _new_agreement,
)


class _RaisingGraph:
    """A graph whose resume raises, as the real graph can during a review."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[tuple[object, dict]] = []

    async def aget_state(self, config):
        return SimpleNamespace(
            interrupts=(
                SimpleNamespace(
                    value={
                        "reason": "seller_review_required",
                        "agreement": _new_agreement().model_dump(mode="json"),
                    }
                ),
            )
        )

    async def ainvoke(self, payload, config):
        self.calls.append((payload, config))
        raise self.error


def _seller_message(agreement: AgreementProjection) -> Message:
    result = AgreementReviewResult(
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
    )
    return make_message(
        role=Role.ROLE_USER,
        text="Seller agreement review.",
        context_id="run-1",
        task_id="buyer-task-1",
        envelope=wrap_agreement_review_result(result),
    )


def _structured_responses(queue: RecordingQueue) -> list[dict]:
    responses: list[dict] = []
    for event in queue.events:
        message = getattr(getattr(event, "status", None), "message", None)
        for part in getattr(message, "parts", []):
            if not part.HasField("text"):
                continue
            try:
                value = json.loads(part.text)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(value, dict):
                responses.append(value)
    return responses


async def test_a_raising_graph_returns_a_structured_failure_not_plain_text() -> None:
    """A graph exception must reach the caller as a JSON envelope.

    The Verifund lifecycle only understands JSON status responses. A plain
    text failure makes it report "Buyer returned no structured response",
    hiding the real error from the user and from the logs.
    """
    agreement = _new_agreement()
    graph = _RaisingGraph(RuntimeError("seller review result is invalid"))
    queue = RecordingQueue()

    await _executor(graph).execute(
        _context(_seller_message(agreement), task_id="buyer-task-1", context_id="run-1"),
        cast(EventQueue, queue),
    )

    responses = _structured_responses(queue)
    assert responses, "expected a structured failure response"
    failure = responses[-1]
    assert failure["status"] == "failed"
    assert failure["reason"] == "buyer_graph_error"
    assert "seller review result is invalid" in failure["message"]


async def test_a_raising_graph_still_reports_the_completed_run_shape() -> None:
    """The failure response keeps the fields the orchestrator reads."""
    agreement = _new_agreement()
    graph = _RaisingGraph(ValueError("agreement hash mismatch"))
    queue = RecordingQueue()

    await _executor(graph).execute(
        _context(_seller_message(agreement), task_id="buyer-task-1", context_id="run-1"),
        cast(EventQueue, queue),
    )

    failure = _structured_responses(queue)[-1]
    assert failure["task_id"] == "buyer-task-1"
    assert failure["error"]["code"] == "buyer_graph_error"
    assert "ValueError" in failure["message"]
