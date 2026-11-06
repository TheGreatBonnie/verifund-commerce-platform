from types import SimpleNamespace

import httpx
import pytest
from buyer_agent import console_api
from buyer_agent.settings import Settings
from buyer_agent.trace import TraceStore
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
async def buyer_client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    trace = TraceStore(engine)
    await trace.create_schema()
    app = FastAPI()
    app.include_router(console_api.router)
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}",
        internal_api_token="test-internal-token",
    )
    app.state.settings = settings
    app.state.services = SimpleNamespace(trace=trace)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client
    await engine.dispose()


@pytest.fixture
async def run_org_a(buyer_client):
    trace = buyer_client._transport.app.state.services.trace
    await trace.upsert_run("run_a", organization_id="org_a", user_id="u_a")
    await trace.record(
        "run_a",
        direction="in",
        method="chat",
        payload={"text": "hello"},
    )
    return "run_a"


async def test_stream_rejects_a_foreign_organization(buyer_client, run_org_a):
    response = await buyer_client.get(
        f"/api/runs/{run_org_a}/stream",
        params={"organization_id": "org_b"},
        headers={"x-verifund-internal-token": "test-internal-token"},
    )
    assert response.status_code == 404


async def test_stream_allows_the_owning_organization(buyer_client, run_org_a):
    response = await buyer_client.get(
        f"/api/runs/{run_org_a}/stream",
        params={"organization_id": "org_a"},
        headers={"x-verifund-internal-token": "test-internal-token"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert "hello" in response.text


async def test_stream_requires_internal_token(buyer_client, run_org_a):
    response = await buyer_client.get(
        f"/api/runs/{run_org_a}/stream",
        params={"organization_id": "org_a"},
    )
    assert response.status_code == 401
