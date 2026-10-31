from __future__ import annotations

import uuid

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types.a2a_pb2 import (
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from commerce_core.a2a_parts import first_envelope, make_artifact
from verifund_contracts import (
    VERIFUND_RESUME_REQUEST_SCHEMA,
    VerifundTaskResult,
    parse_verifund_resume_request,
    parse_verifund_task_request,
    wrap_verifund_task_result,
)

from verifund_agent.service import VerifundAgentService

POLLING_CHECKPOINTS = {"funding_pending", "evidence_pending"}


def task_state(result: VerifundTaskResult) -> TaskState:
    if result.status == "failed":
        return TaskState.TASK_STATE_FAILED
    if result.status in {"input_required", "approval_required"}:
        return TaskState.TASK_STATE_INPUT_REQUIRED
    if result.checkpoint in POLLING_CHECKPOINTS:
        return TaskState.TASK_STATE_WORKING
    return TaskState.TASK_STATE_COMPLETED


class VerifundExecutor(AgentExecutor):
    def __init__(self, service: VerifundAgentService) -> None:
        self.service = service

    def _agent_message(
        self, text: str, task_id: str, context_id: str
    ) -> Message:
        return Message(
            message_id=str(uuid.uuid4()),
            task_id=task_id,
            context_id=context_id,
            role=Role.ROLE_AGENT,
            parts=[Part(text=text, media_type="text/plain")],
        )

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or task_id
        try:
            if context.message is None:
                raise ValueError("Verifund request is missing a message.")
            envelope = first_envelope(context.message)
            if envelope is None:
                raise ValueError(
                    "Verifund request requires a structured envelope."
                )
            if envelope.get("schema") == VERIFUND_RESUME_REQUEST_SCHEMA:
                resume = parse_verifund_resume_request(envelope)
                result = await self.service.resume(
                    resume, task_id=task_id, context_id=context_id
                )
            else:
                request = parse_verifund_task_request(envelope)
                result = await self.service.handle(
                    request, task_id=task_id, context_id=context_id
                )
        except Exception:  # noqa: BLE001
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_FAILED,
                        message=self._agent_message(
                            "The Verifund agent could not process this request.",
                            task_id,
                            context_id,
                        ),
                    ),
                )
            )
            return

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=make_artifact(
                    "verifund-result", wrap_verifund_task_result(result)
                ),
                last_chunk=True,
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=task_state(result),
                    message=self._agent_message(
                        result.message or result.status,
                        task_id,
                        context_id,
                    ),
                ),
            )
        )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or task_id
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_CANCELED,
                    message=self._agent_message(
                        "Verifund task canceled.", task_id, context_id
                    ),
                ),
            )
        )
