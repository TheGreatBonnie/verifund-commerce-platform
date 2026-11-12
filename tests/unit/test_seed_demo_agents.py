import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.tenancy.backfill import seed_demo_agents
from verifund_control_plane.tenancy.repository import TenancyRepository


class Settings:
    pass


@pytest_asyncio.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/verifund.db")
    store = TenancyRepository(engine)
    await store.create_schema()
    yield store
    await engine.dispose()


async def test_seed_demo_agents(store, monkeypatch):
    monkeypatch.setenv("MARKETMESH_SEED_DEMO", "1")
    await seed_demo_agents(store, Settings())

    agent = await store.get_agent("agent_northwind-audio")
    assert agent is not None
    assert agent["status"] == "active"

    buyer = await store.get_agent("agent_marketmesh_buyer")
    assert buyer is not None and buyer["status"] == "active"

    creds = await store.list_credentials("agent_marketmesh_buyer")
    active = [c for c in creds if c["status"] == "active"]
    assert len(active) >= 1
    assert active[0]["agent_id"] == "agent_marketmesh_buyer"
    scopes = active[0]["scopes"]
    assert "a2a:call" in scopes

    creds = await store.list_credentials("agent_northwind-audio")
    active = [c for c in creds if c["status"] == "active"]
    assert len(active) >= 1
    assert active[0]["agent_id"] == "agent_northwind-audio"
    scopes = active[0]["scopes"]
    assert "a2a:test" in scopes


async def test_seed_demo_agents_is_idempotent(store, monkeypatch):
    monkeypatch.setenv("MARKETMESH_SEED_DEMO", "1")
    await seed_demo_agents(store, Settings())
    await seed_demo_agents(store, Settings())
    agents = await store.list_agents()
    assert len([a for a in agents
                if a["id"] in {"agent_northwind-audio",
                               "agent_marketmesh_buyer"}]) == 2
