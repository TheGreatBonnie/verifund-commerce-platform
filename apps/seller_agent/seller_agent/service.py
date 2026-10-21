from __future__ import annotations

from dataclasses import dataclass

from a2a.types.a2a_pb2 import Artifact, Message, TaskState

from commerce_core.a2a_parts import first_envelope, make_artifact
from commerce_core.contracts import CommerceErrorCode, Offer, Order
from commerce_core.extension import wrap_payload
from commerce_core.pricing import SellerPolicy

from seller_agent.graph import (
    CommerceProtocolError,
    build_graph,
    error_artifact,
    kind_from_envelope,
)
from seller_agent.order_service import OrderService
from seller_agent.planner import SellerPlanner
from seller_agent.store import SellerStore

TASK_STATES = {
    "working": TaskState.TASK_STATE_WORKING,
    "input_required": TaskState.TASK_STATE_INPUT_REQUIRED,
    "completed": TaskState.TASK_STATE_COMPLETED,
    "failed": TaskState.TASK_STATE_FAILED,
    "canceled": TaskState.TASK_STATE_CANCELED,
}


@dataclass
class SellerTurn:
    task_state: TaskState
    artifacts: list[Artifact]
    message: str


class SellerService:
    def __init__(
        self,
        *,
        store: SellerStore,
        policy: SellerPolicy,
        planner: SellerPlanner,
    ) -> None:
        self.store = store
        self.policy = policy
        self.planner = planner
        self.order_service = OrderService(store)
        self.graph = build_graph()

    async def handle_turn(
        self, task_id: str, context_id: str, message: Message
    ) -> SellerTurn:
        envelope = first_envelope(message)
        try:
            if envelope is None:
                raise CommerceProtocolError("missing DataPart")
            kind_from_envelope(envelope)
        except CommerceProtocolError as exc:
            error = {
                "code": CommerceErrorCode.INVALID_REQUEST.value,
                "message": str(exc),
                "retryable": False,
                "details": {},
            }
            return SellerTurn(
                task_state=TaskState.TASK_STATE_FAILED,
                artifacts=[error_artifact(error)],
                message=str(exc),
            )

        state = {
            "task_id": task_id,
            "context_id": context_id,
            "incoming": envelope,
        }
        try:
            result = await self.graph.ainvoke(
                state,
                config={
                    "configurable": {
                        "thread_id": task_id,
                        "planner": self.planner,
                        "service": self,
                    }
                },
            )
        except Exception as exc:
            error = {
                "code": CommerceErrorCode.INVALID_REQUEST.value,
                "message": str(exc),
                "retryable": False,
                "details": {},
            }
            return SellerTurn(
                task_state=TaskState.TASK_STATE_FAILED,
                artifacts=[error_artifact(error)],
                message=str(exc),
            )

        if result.get("error"):
            return SellerTurn(
                task_state=TASK_STATES.get(
                    result.get("task_state", "failed"),
                    TaskState.TASK_STATE_FAILED,
                ),
                artifacts=[error_artifact(result["error"])],
                message=result.get("message", "Commerce error."),
            )
        if result.get("offer"):
            offer = Offer.model_validate(result["offer"])
            return SellerTurn(
                task_state=TASK_STATES.get(
                    result.get("task_state", "input_required"),
                    TaskState.TASK_STATE_INPUT_REQUIRED,
                ),
                artifacts=[
                    make_artifact("offer", wrap_payload("offer", offer))
                ],
                message=result.get("message", "Structured offer available."),
            )
        if result.get("order"):
            order = Order.model_validate(result["order"])
            return SellerTurn(
                task_state=TASK_STATES.get(
                    result.get("task_state", "completed"),
                    TaskState.TASK_STATE_COMPLETED,
                ),
                artifacts=[
                    make_artifact("order", wrap_payload("order", order))
                ],
                message=result.get("message", "Order confirmed."),
            )
        error = {
            "code": CommerceErrorCode.INVALID_REQUEST.value,
            "message": "Seller produced no response.",
            "retryable": False,
            "details": {},
        }
        return SellerTurn(
            task_state=TaskState.TASK_STATE_FAILED,
            artifacts=[error_artifact(error)],
            message="Seller produced no response.",
        )
