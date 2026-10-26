from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from a2a.types.a2a_pb2 import Message, Part, Role
from buyer_agent.executor import BuyerExecutor
from buyer_agent.settings import Settings
from langgraph.types import Command

RUN_ID = "020448bc-39d0-41d7-8c14-828e3bda5c70"

# The exact shape the orchestrator sent during the failed MacBook Air resume.
FLAT_APPROVAL_MESSAGE = (
    "Human approval has been granted for the award. Resume the interrupted "
    "sourcing run with the following approval decision:\n\n"
    '{"approved": true, "approved_by": "Demo Buyer", "note": "", '
    f'"task_id": "{RUN_ID}"}}\n\n'
    "Proceed with the approved award to Northwind Audio at $979.00 and "
    "complete the sourcing run."
)


class SpyGraph:
    def __init__(self, result: dict | None = None) -> None:
        self.calls: list[tuple[object, dict]] = []
        self.result = result or {
            "stage": "ordered",
            "messages": [],
            "order": {"order_id": "MM-TEST-ORDER"},
        }

    async def ainvoke(self, payload, config):
        self.calls.append((payload, config))
        return self.result


class RecordingQueue:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def enqueue_event(self, event) -> None:
        self.events.append(event)


def _context(text: str, task_id: str = "a2a-task", context_id: str = "a2a-ctx"):
    message = Message(
        message_id="m1",
        task_id=task_id,
        context_id=context_id,
        role=Role.ROLE_USER,
        parts=[Part(text=text, media_type="text/plain")],
    )
    return SimpleNamespace(task_id=task_id, context_id=context_id, message=message)


def _executor(graph: SpyGraph) -> BuyerExecutor:
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


@pytest.mark.asyncio
async def test_flat_approval_resumes_the_approved_run():
    graph = SpyGraph()
    queue = RecordingQueue()

    await _executor(graph).execute(_context(FLAT_APPROVAL_MESSAGE), queue)

    assert len(graph.calls) == 1
    payload, config = graph.calls[0]
    assert isinstance(payload, Command)
    assert payload.resume == {
        "approved": True,
        "approved_by": "Demo Buyer",
        "note": "",
    }
    assert config["configurable"]["thread_id"] == RUN_ID
    assert _status_responses(queue)[-1]["status"] == "ordered"


@pytest.mark.asyncio
async def test_nested_approval_resumes_the_approved_run():
    graph = SpyGraph()
    queue = RecordingQueue()
    text = json.dumps(
        {
            "approval": {"approved": True, "approved_by": "Demo Buyer", "note": ""},
            "task_id": RUN_ID,
        }
    )

    await _executor(graph).execute(_context(text), queue)

    assert len(graph.calls) == 1
    payload, config = graph.calls[0]
    assert isinstance(payload, Command)
    assert payload.resume["approved"] is True
    assert config["configurable"]["thread_id"] == RUN_ID


@pytest.mark.asyncio
async def test_approval_without_task_id_does_not_start_a_sourcing_run():
    graph = SpyGraph()
    queue = RecordingQueue()
    text = json.dumps(
        {"approved": True, "approved_by": "Demo Buyer", "note": "looks good"}
    )

    await _executor(graph).execute(_context(text), queue)

    assert graph.calls == []
    response = _status_responses(queue)[-1]
    assert response["status"] == "failed"
    assert response["error"]["code"] == "invalid_request"
    assert response["error"]["retryable"] is False


@pytest.mark.asyncio
async def test_nested_approval_without_task_id_does_not_start_a_sourcing_run():
    graph = SpyGraph()
    queue = RecordingQueue()
    text = json.dumps(
        {"approval": {"approved": True, "approved_by": "Demo Buyer", "note": ""}}
    )

    await _executor(graph).execute(_context(text), queue)

    assert graph.calls == []
    response = _status_responses(queue)[-1]
    assert response["status"] == "failed"
    assert response["error"]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_plain_brief_still_starts_a_new_sourcing_run():
    graph = SpyGraph(result={"stage": "awaiting_approval", "messages": []})
    queue = RecordingQueue()

    await _executor(graph).execute(_context("Buy one MacBook Air M4."), queue)

    assert len(graph.calls) == 1
    payload, config = graph.calls[0]
    assert not isinstance(payload, Command)
    assert payload["messages"][0].content == "Buy one MacBook Air M4."
    assert config["configurable"]["thread_id"] == "a2a-ctx"
