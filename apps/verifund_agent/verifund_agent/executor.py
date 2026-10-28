import uuid

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types.a2a_pb2 import (
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from commerce_core.a2a_parts import make_artifact
from verifund_contracts import (
    parse_verifund_task_request,
    wrap_verifund_task_result,
)
from verifund_contracts.a2a import VERIFUND_TASK_RESULT_SCHEMA

from verifund_agent.service import VerifundAgentService


class VerifundExecutor(AgentExecutor):
    def __init__(self, service: VerifundAgentService) -> None:
        self.service = service

    def _agent_message(self, text: str, task_id: str, context_id: str) -> Message:
        return Message(
            message_id=str(uuid.uuid4()),
            task_id=task_id,
            context_id=context_id,
            role=Role.ROLE_AGENT,
            parts=[Part(text=text, media_type="text/plain")],
        )

    async def _start_task(
        self, context: RequestContext, event_queue: EventQueue
    ) -> tuple[str, str]:
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or task_id
        history = [context.message] if context.message is not None else []
        await event_queue.enqueue_event(
            Task(
                id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
                history=history,
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_WORKING,
                    message=self._agent_message(
                        "Verifund is processing the request.",
                        task_id,
                        context_id,
                    ),
                ),
            )
        )
        return task_id, context_id

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        task_id, context_id = await self._start_task(context, event_queue)
        try:
            if context.message is None:
                raise ValueError("Verifund request is missing a message.")
            from commerce_core.a2a_parts import first_envelope

            envelope = first_envelope(context.message)
            request = parse_verifund_task_request(envelope)
            result = await self.service.handle(
                request, task_id=task_id, context_id=context_id
            )
        except Exception as exc:  # noqa: BLE001
            result = None
            error_message = str(exc)
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_FAILED,
                        message=self._agent_message(
                            error_message, task_id, context_id
                        ),
                    ),
                )
            )
            return
        status = TaskState.TASK_STATE_COMPLETED
        if result.status in {"input_required", "approval_required"}:
            status = TaskState.TASK_STATE_INPUT_REQUIRED
        elif result.status == "failed":
            status = TaskState.TASK_STATE_FAILED
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=make_artifact(
                    "verifund-result",
                    wrap_verifund_task_result(result),
                ),
                last_chunk=True,
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=status,
                    message=self._agent_message(
                        result.message or "Verifund response.", task_id, context_id
                    ),
                ),
            )
        )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        task_id, context_id = await self._start_task(context, event_queue)
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_CANCELED,
                    message=self._agent_message(
                        "Task canceled.", task_id, context_id
                    ),
                ),
            )
        )
