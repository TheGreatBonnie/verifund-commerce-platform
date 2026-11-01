from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast

from a2a.server.events import EventQueue
from a2a.types.a2a_pb2 import Message, Part, Role
from buyer_agent.executor import BuyerExecutor
from buyer_agent.settings import Settings


class StatefulGraph:
    def __init__(self, values: dict | None = None) -> None:
        self.values = values or {}
        self.calls: list[tuple[object, dict]] = []

    async def aget_state(self, config):
        return SimpleNamespace(values=self.values, interrupts=())

    async def ainvoke(self, payload, config):
        self.calls.append((payload, config))
        return {"stage": "ordered", "messages": []}


class RecordingQueue:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def enqueue_event(self, event) -> None:
        self.events.append(event)


def _context(
    text: str = "Buy one MacBook Air M4.",
    task_id: str = "a2a-task",
    context_id: str = "thread-1",
) -> SimpleNamespace:
    message = Message(
        message_id="m1",
        task_id=task_id,
        context_id=context_id,
        role=Role.ROLE_USER,
        parts=[Part(text=text, media_type="text/plain")],
    )
    return SimpleNamespace(task_id=task_id, context_id=context_id, message=message)


def _executor(graph: StatefulGraph) -> BuyerExecutor:
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


async def test_fresh_brief_uses_context_id_as_the_graph_thread() -> None:
    graph = StatefulGraph()
    queue = RecordingQueue()

    await _executor(graph).execute(
        _context(context_id="thread-1"), cast(EventQueue, queue)
    )

    assert len(graph.calls) == 1
    _payload, config = graph.calls[0]
    assert config["configurable"]["thread_id"] == "thread-1"
    assert _status_responses(queue)[-1]["status"] == "ordered"


async def test_second_brief_on_a_completed_thread_fails() -> None:
    graph = StatefulGraph(values={"stage": "ordered", "run_id": "thread-1"})
    queue = RecordingQueue()

    await _executor(graph).execute(
        _context(context_id="thread-1"), cast(EventQueue, queue)
    )

    assert graph.calls == []
    response = _status_responses(queue)[-1]
    assert response["status"] == "failed"
    assert response["error"]["code"] == "thread_in_use"
    assert response["error"]["retryable"] is False


async def test_fresh_brief_on_a_new_checkpoint_starts_the_run() -> None:
    graph = StatefulGraph(values={"stage": "new"})
    queue = RecordingQueue()

    await _executor(graph).execute(
        _context(context_id="thread-2"), cast(EventQueue, queue)
    )

    assert len(graph.calls) == 1
    _payload, config = graph.calls[0]
    assert config["configurable"]["thread_id"] == "thread-2"
