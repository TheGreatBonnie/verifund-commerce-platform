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
from commerce_core.contracts import CommerceErrorCode

from seller_agent.graph import error_artifact
from seller_agent.service import SellerService


class SellerExecutor(AgentExecutor):
    def __init__(self, service: SellerService) -> None:
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

    async def _start_task(
        self, context: RequestContext, event_queue: EventQueue
    ) -> tuple[str, str]:
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or task_id
        message = context.message
        history = (
            [self.service.redact_message(message)]
            if message is not None
            else []
        )
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
                        "Seller is evaluating the request.",
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
                raise ValueError("Seller request is missing a message.")
            turn = await self.service.handle_turn(
                task_id, context_id, context.message
            )
        except Exception:  # noqa: BLE001
            error = {
                "code": CommerceErrorCode.INVALID_REQUEST.value,
                "message": "The seller could not process this request.",
                "retryable": False,
                "details": {},
            }
            await event_queue.enqueue_event(
                TaskArtifactUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    artifact=error_artifact(error),
                    last_chunk=True,
                )
            )
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_FAILED,
                        message=self._agent_message(
                            "The seller could not process this request.",
                            task_id,
                            context_id,
                        ),
                    ),
                )
            )
            return

        for artifact in turn.artifacts:
            await event_queue.enqueue_event(
                TaskArtifactUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    artifact=artifact,
                    last_chunk=True,
                )
            )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=turn.task_state,
                    message=self._agent_message(
                        turn.message, task_id, context_id
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
