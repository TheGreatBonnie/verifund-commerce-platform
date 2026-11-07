import hashlib
from typing import ClassVar

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.tenancy.backfill import seed_demo_agents
from verifund_control_plane.tenancy.repository import TenancyRepository


class Settings:
    seller_tokens: ClassVar[dict] = {"northwind-audio": "dev-northwind"}
    buyer_agent_token = "dev-buyer-agent"


@pytest_asyncio.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/verifund.db")
    store = TenancyRepository(engine)
    await store.create_schema()
    yield store
    await engine.dispose()


async def test_seed_demo_agents(store):
    await seed_demo_agents(store, Settings())

    agent = await store.get_agent("agent_northwind-audio")
    assert agent is not None
    assert agent["status"] == "active"

    buyer = await store.get_agent("agent_marketmesh_buyer")
    assert buyer is not None and buyer["status"] == "active"

    buyer_credential = await store.get_credential_by_hash(
        hashlib.sha256(b"dev-buyer-agent").hexdigest())
    assert buyer_credential is not None
    assert buyer_credential["agent_id"] == "agent_marketmesh_buyer"
    assert buyer_credential["scopes"] == ["a2a:call"]

    seller_credential = await store.get_credential_by_hash(
        hashlib.sha256(b"dev-northwind").hexdigest())
    assert seller_credential is not None
    assert seller_credential["agent_id"] == "agent_northwind-audio"
    assert "a2a:test" in seller_credential["scopes"]


async def test_seed_demo_agents_is_idempotent(store):
    await seed_demo_agents(store, Settings())
    await seed_demo_agents(store, Settings())
    agents = await store.list_agents()
    assert len([a for a in agents
                if a["id"] in {"agent_northwind-audio",
                               "agent_marketmesh_buyer"}]) == 2
