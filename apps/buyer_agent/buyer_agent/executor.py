import json
import uuid
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types.a2a_pb2 import (
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from commerce_core.a2a_parts import first_envelope
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from verifund_contracts import AgreementProjection

from buyer_agent.approval import normalize_approval
from buyer_agent.graph import build_buyer_graph
from buyer_agent.planner import select_buyer_planner
from buyer_agent.review import (
    parse_review_envelope,
    parse_review_result_envelope,
    seller_resume_value,
)
from buyer_agent.settings import Settings


class BuyerExecutor(AgentExecutor):
    def __init__(
        self,
        services: Any,
        settings: Settings,
        checkpointer: Any,
        graph: Any | None = None,
    ) -> None:
        self.services = services
        self.settings = settings
        self.planner = select_buyer_planner(
            settings.llm_mode,
            settings.nebius_api_key,
            settings.nebius_base_url,
            settings.nebius_model,
        )
        self.graph = graph or build_buyer_graph(
            services=services,
            checkpointer=checkpointer,
            planner=self.planner,
        )

    def _message_text(self, message: Any) -> str:
        if message is None:
            return ""
        for part in getattr(message, "parts", []):
            if part.HasField("text") and part.text.strip():
                return part.text.strip()
        return ""

    def _payload(self, text: str) -> dict[str, Any]:
        # Accept JSON even when the caller wraps it in prose, so approval
        # resumes work whether the orchestrator sends pure JSON or annotated text.
        candidate = text.strip()
        if not candidate.startswith("{"):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = candidate[start : end + 1]
        try:
            value = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            return {"brief": text}
        if not isinstance(value, dict):
            return {"brief": text}
        # Callers may send the approval decision at the top level instead of
        # nesting it under "approval". Normalise that shape rather than
        # treating an approval as a new shopping brief.
        if "approval" in value or "approved" in value:
            task_id = value.get("task_id")
            if not task_id:
                return {"resume_error": "approval response requires task_id"}
            if "approval" in value:
                return value
            return {
                "approval": {
                    field: value[field]
                    for field in ("approved", "approved_by", "note")
                    if field in value
                },
                "task_id": task_id,
            }
        return value

    def _agent_message(
        self, text: str, task_id: str, context_id: str, media_type: str = "text/plain"
    ) -> Message:
        return Message(
            message_id=str(uuid.uuid4()),
            task_id=task_id,
            context_id=context_id,
            role=Role.ROLE_AGENT,
            parts=[Part(text=text, media_type=media_type)],
        )

    async def _pending_interrupt(self, config: dict) -> dict | None:
        snapshot = await self.graph.aget_state(config)
        interrupts = getattr(snapshot, "interrupts", None) or ()
        if not interrupts:
            return None
        pending = interrupts[0]
        value = getattr(pending, "value", pending)
        return value if isinstance(value, dict) else None

    async def _fail(
        self,
        event_queue: EventQueue,
        task_id: str,
        context_id: str,
        *,
        reason: str,
        message: str,
    ) -> None:
        response = {
            "status": "failed",
            "task_id": task_id,
            "message": message,
            "reason": reason,
            "error": {
                "code": "invalid_request",
                "message": message,
                "retryable": False,
                "details": {},
            },
        }
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_FAILED,
                    message=self._agent_message(
                        json.dumps(response), task_id, context_id, "application/json"
                    ),
                ),
            )
        )

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or task_id
        thread_id = context_id
        text = self._message_text(context.message)
        payload = self._payload(text)

        message = context.message
        envelope = first_envelope(message) if message is not None else None
        review_request = None
        review_result = None
        review_kind: str | None = None
        if envelope is not None and str(envelope.get("schema", "")).endswith(
            "/agreement-review-request.json"
        ):
            assert message is not None
            try:
                review_request = parse_review_envelope(message)
            except ValueError as exc:
                await self._fail(
                    event_queue,
                    task_id,
                    context_id,
                    reason="invalid_review",
                    message=str(exc),
                )
                return
            if (
                review_request.buyer_task_id != (context.task_id or "")
                or review_request.buyer_context_id != (context.context_id or "")
            ):
                await self._fail(
                    event_queue,
                    task_id,
                    context_id,
                    reason="not_a_buyer_checkpoint",
                    message="agreement review does not match the interrupted Buyer task",
                )
                return
            review_kind = "agreement_create"
        elif envelope is not None and str(envelope.get("schema", "")).endswith(
            "/agreement-review-result.json"
        ):
            review_kind = "seller_review"

        if payload.get("resume_error"):
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_FAILED,
                        message=self._agent_message(
                            json.dumps(
                                {
                                    "status": "failed",
                                    "task_id": task_id,
                                    "message": payload["resume_error"],
                                    "error": {
                                        "code": "invalid_request",
                                        "message": payload["resume_error"],
                                        "retryable": False,
                                        "details": {},
                                    },
                                }
                            ),
                            task_id,
                            context_id,
                            "application/json",
                        ),
                    ),
                )
            )
            return

        await event_queue.enqueue_event(
            Task(
                id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
                history=[context.message] if context.message is not None else [],
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_WORKING,
                    message=self._agent_message(
                        "Buyer is evaluating the request.", task_id, context_id
                    ),
                ),
            )
        )

        config = {
            "configurable": {
                "thread_id": thread_id,
                "services": self.services,
                "planner": self.planner,
            }
        }

        try:
            resume = None
            if review_kind is not None:
                pending = await self._pending_interrupt(config)
                expected_reason = (
                    "agreement_create_required"
                    if review_kind == "agreement_create"
                    else "seller_review_required"
                )
                if pending is None:
                    await self._fail(
                        event_queue,
                        task_id,
                        context_id,
                        reason="no_pending_review",
                        message="No buyer agreement review is pending for this run.",
                    )
                    return
                reason = str(pending.get("reason") or "")
                if reason != expected_reason:
                    await self._fail(
                        event_queue,
                        task_id,
                        context_id,
                        reason="not_a_buyer_checkpoint",
                        message="The buyer task is not waiting for a Verifund agreement review.",
                    )
                    return
                if review_kind == "agreement_create":
                    assert review_request is not None
                    resume = {
                        "agreement": review_request.agreement.model_dump(mode="json")
                    }
                    if pending.get("seller_token_ref"):
                        resume["seller_token_ref"] = str(pending["seller_token_ref"])
                    thread_id = str(
                        review_request.buyer_context_id
                        or context.context_id
                        or thread_id
                    )
                    config["configurable"]["thread_id"] = thread_id
                else:
                    agreement = AgreementProjection.model_validate(
                        pending.get("agreement") or {}
                    )
                    assert message is not None
                    try:
                        review_result = parse_review_result_envelope(message, agreement)
                    except ValueError as exc:
                        await self._fail(
                            event_queue,
                            task_id,
                            context_id,
                            reason="agreement_mismatch",
                            message=str(exc),
                        )
                        return
                    resume = seller_resume_value(review_result)
            if resume is not None:
                result = await self.graph.ainvoke(Command(resume=resume), config=config)
            elif "approval" in payload and "task_id" in payload:
                thread_id = str(payload["task_id"])
                config["configurable"]["thread_id"] = thread_id
                decision = normalize_approval(payload["approval"])
                result = await self.graph.ainvoke(Command(resume=decision), config=config)
            elif "seller_result" in payload and "task_id" in payload:
                thread_id = str(payload["task_id"])
                config["configurable"]["thread_id"] = thread_id
                result = await self.graph.ainvoke(
                    Command(resume=payload["seller_result"]), config=config
                )
            else:
                brief = str(payload.get("brief") or text)
                result = await self.graph.ainvoke(
                    {
                        "messages": [HumanMessage(content=brief)],
                        "stage": "new",
                        "task_id": task_id,
                        "context_id": context_id,
                    },
                    config=config,
                )
        except Exception as exc:  # noqa: BLE001
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_FAILED,
                        message=self._agent_message(str(exc), task_id, context_id),
                    ),
                )
            )
            return

        if "__interrupt__" in result:
            interrupt_value = result["__interrupt__"][0].value
            reason = interrupt_value.get("reason", "order_approval")
            if reason == "seller_call":
                response = {
                    "status": "seller_call_required",
                    "reason": "seller_call",
                    "task_id": thread_id,
                    "seller_id": interrupt_value.get("seller_id"),
                    "card_url": interrupt_value.get("card_url"),
                    "kind": interrupt_value.get("kind"),
                    "request": interrupt_value.get("request"),
                    "seller_task_id": interrupt_value.get("seller_task_id"),
                    "seller_context_id": interrupt_value.get("seller_context_id"),
                    "message": interrupt_value.get("message", "Seller call required."),
                }
            elif reason == "agreement_create_required":
                response = {
                    "status": reason,
                    "task_id": thread_id,
                    "message": interrupt_value.get("message", "Create the canonical agreement."),
                    "run_id": interrupt_value.get("run_id"),
                    "buyer_task_id": interrupt_value.get("buyer_task_id"),
                    "buyer_context_id": interrupt_value.get("buyer_context_id"),
                    "award": interrupt_value.get("award"),
                    "seller_id": interrupt_value.get("seller_id"),
                    "seller_card_url": interrupt_value.get("seller_card_url"),
                }
            elif reason == "seller_review_required":
                response = {
                    "status": reason,
                    "task_id": thread_id,
                    "message": interrupt_value.get("message", "Seller review required."),
                    "run_id": interrupt_value.get("run_id"),
                    "transaction_id": interrupt_value.get("transaction_id"),
                    "agreement": interrupt_value.get("agreement"),
                    "seller_id": interrupt_value.get("seller_id"),
                    "buyer_task_id": interrupt_value.get("buyer_task_id"),
                    "buyer_context_id": interrupt_value.get("buyer_context_id"),
                    "buyer_agent_review": interrupt_value.get("buyer_agent_review"),
                    "seller_task_id": interrupt_value.get("seller_task_id"),
                    "seller_context_id": interrupt_value.get("seller_context_id"),
                }
            else:
                response = {
                    "status": "approval_required",
                    "reason": "order_approval",
                    "task_id": thread_id,
                    "message": interrupt_value.get(
                        "message", "Human approval required before placing the order."
                    ),
                    "award": result.get("award"),
                    "mandate": result.get("mandate"),
                }
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_INPUT_REQUIRED,
                        message=self._agent_message(
                            json.dumps(response), task_id, context_id, "application/json"
                        ),
                    ),
                )
            )
            return

        stage = result.get("stage", "completed")
        messages = result.get("messages", [])
        final_message = ""
        if messages:
            final_message = getattr(messages[-1], "content", "") or ""
        if not final_message:
            if stage == "ordered":
                final_message = "The sourcing run finished with an order."
            elif stage == "rejected":
                final_message = "The award was rejected and no order was placed."
            elif stage == "no_award":
                final_message = "No eligible award was found."
            else:
                final_message = "The sourcing run finished."

        response = {
            "status": stage,
            "task_id": thread_id,
            "message": final_message,
            "award": result.get("award"),
            "order": result.get("order"),
            "agreement": result.get("agreement"),
            "buyer_agent_review": result.get("buyer_review"),
            "seller_decision": result.get("seller_decision"),
            "settlement": result.get("settlement"),
            "error": result.get("error"),
        }
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_COMPLETED,
                    message=self._agent_message(
                        json.dumps(response), task_id, context_id, "application/json"
                    ),
                ),
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or task_id
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_CANCELED,
                    message=self._agent_message("Buyer task canceled.", task_id, context_id),
                ),
            )
        )
