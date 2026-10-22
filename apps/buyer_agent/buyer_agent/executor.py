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
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from buyer_agent.approval import normalize_approval
from buyer_agent.graph import build_buyer_graph
from buyer_agent.planner import select_buyer_planner
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
        if not text.startswith("{"):
            return {"brief": text}
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return {"brief": text}
        if not isinstance(value, dict):
            return {"brief": text}
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

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or task_id
        thread_id = context_id
        text = self._message_text(context.message)
        payload = self._payload(text)

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
            if "approval" in payload and "task_id" in payload:
                thread_id = str(payload["task_id"])
                config["configurable"]["thread_id"] = thread_id
                decision = normalize_approval(payload["approval"])
                result = await self.graph.ainvoke(Command(resume=decision), config=config)
            else:
                brief = str(payload.get("brief") or text)
                result = await self.graph.ainvoke(
                    {"messages": [HumanMessage(content=brief)], "stage": "new"},
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
            response = {
                "status": "approval_required",
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
