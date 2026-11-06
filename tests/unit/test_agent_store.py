import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.repository import TenancyRepository


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent.db'}")
    repo = Repository(engine)
    await repo.create_schema()
    s = TenancyRepository(engine)
    await s.create_schema()
    yield s
    await engine.dispose()


async def test_agent_round_trip_and_active_test_run(store):
    agent = await store.create_agent(
        organization_id="org_1",
        name="Acme Agent",
        created_by="user_1",
        policy_ref="acme/main",
        policy_version="1",
        policy_hash="a" * 64,
    )
    assert agent["status"] == "draft"
    await store.set_agent_status(agent["id"], "testing")
    await store.create_test_run(
        agent["id"],
        "org_1",
        policy_hash="a" * 64,
        card_hash="b" * 64,
        checks=[{"name": "catalog", "passed": True}],
        passed=True,
    )
    assert (
        await store.latest_passing_test(agent["id"], "a" * 64, "b" * 64)
        is not None
    )
