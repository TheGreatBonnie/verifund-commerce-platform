from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from buyer_agent.trace import TraceStore


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
