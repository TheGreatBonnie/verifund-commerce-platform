from pathlib import Path

import pytest
from a2a.types.a2a_pb2 import Role
from buyer_agent.trace import TraceStore
from commerce_core.a2a_parts import make_message
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
async def trace_store(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'trace.db'}"
    )
    store = TraceStore(engine)
    await store.create_schema()
    try:
        yield store
    finally:
        await engine.dispose()


async def test_trace_redacts_authorization(trace_store):
    await trace_store.record(
        "run-1",
        direction="outbound",
        method="SendStreamingMessage",
        task_id="task-1",
        context_id="run-1",
        seller_id="northwind-audio",
        payload={"headers": {"authorization": "Bearer secret"}},
    )
    events = await trace_store.list("run-1")
    assert events[0].payload["headers"]["authorization"] == "[REDACTED]"


async def test_trace_redacts_nested_tokens_and_bytes(trace_store):
    await trace_store.record(
        "run-1",
        direction="outbound",
        method="SendStreamingMessage",
        payload={
            "headers": {"Authorization": "Bearer secret"},
            "body": {"token": "abc", "blob": b"hello"},
        },
    )
    events = await trace_store.list("run-1")
    assert events[0].payload["headers"]["Authorization"] == "[REDACTED]"
    assert events[0].payload["body"]["token"] == "[REDACTED]"
    assert events[0].payload["body"]["blob"] == "<5 bytes>"


async def test_trace_records_outbound_message(trace_store):
    message = make_message(
        role=Role.ROLE_USER,
        text="Requesting a quote.",
        context_id="run-1",
    )
    await trace_store.record_message(
        "run-1", "northwind-audio", message
    )
    events = await trace_store.list("run-1")
    assert events[0].direction == "outbound"
    assert events[0].seller_id == "northwind-audio"
    assert events[0].payload["kind"] == "message"
    assert events[0].payload["message"]["contextId"] == "run-1"
