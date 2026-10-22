from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from buyer_agent.server import create_app
from buyer_agent.settings import Settings
from langgraph.checkpoint.memory import MemorySaver

from tests.support.fake_buyer import FakeServices
from tests.support.servers import run_uvicorn


@pytest.fixture
async def buyer_server(tmp_path: Path):
    settings = Settings(
        host="127.0.0.1",
        port=9100,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'buyer.db'}",
        checkpoint_path=tmp_path / "checkpoints.db",
    )
    app = create_app(settings, MemorySaver(), FakeServices())
    async with run_uvicorn(app, 9100) as base_url:
        yield base_url


async def test_health_and_ready(buyer_server):
    async with httpx.AsyncClient() as client:
        assert (await client.get(f"{buyer_server}/health")).status_code == 200
        assert (await client.get(f"{buyer_server}/ready")).status_code == 200


async def test_agui_stream_starts_and_interrupts(buyer_server):
    payload = {
        "threadId": "agui-test",
        "runId": "run-1",
        "messages": [
            {
                "id": "m1",
                "role": "user",
                "content": "Buy 12 Nimbus NC-700 headsets for our team.",
            }
        ],
        "tools": [],
        "context": [],
        "state": {},
        "forwardedProps": {},
    }
    async with httpx.AsyncClient(timeout=60) as client, client.stream(
        "POST",
        f"{buyer_server}/agui",
        json=payload,
        headers={"Accept": "text/event-stream"},
    ) as response:
        body = "".join([chunk async for chunk in response.aiter_text()])
    assert response.status_code == 200
    assert "RUN_STARTED" in body
    assert "interrupt" in body.lower()
