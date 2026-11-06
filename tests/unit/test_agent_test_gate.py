import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane.agents.credentials import issue_credential
from verifund_control_plane.agents.lifecycle import activate_agent
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.repository import TenancyRepository


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'gate.db'}")
    repo = Repository(engine)
    await repo.create_schema()
    s = TenancyRepository(engine)
    await s.create_schema()
    org = await s.upsert_organization("org_1", "Acme", "acme")
    await s.upsert_seller_profile(org["id"], "acme", "Acme")
    await s.set_verification_status("acme", "verified")
    s._org_id = org["id"]
    yield s
    await engine.dispose()


@pytest.fixture
async def tested_agent(store):
    agent = await store.create_agent(
        organization_id=store._org_id,
        name="Acme",
        created_by="user_1",
        policy_ref="acme/main",
        policy_version="1",
        policy_hash="a" * 64,
    )
    await store.set_agent_status(agent["id"], "testing")
    await store.create_test_run(
        agent["id"],
        store._org_id,
        policy_hash="a" * 64,
        card_hash="",
        checks=[{"name": "x", "passed": True}],
        passed=True,
    )
    await issue_credential(store, store._org_id, agent["id"], ["a2a:call"])
    return agent


async def test_policy_change_after_pass_blocks_activation(store, tested_agent):
    await store.set_policy_hash(tested_agent["id"], "e" * 64)
    with pytest.raises(VerifundError) as exc:
        await activate_agent(store, tested_agent["id"])
    assert exc.value.code == "onboarding_incomplete"


async def test_passing_run_allows_activation(store, tested_agent):
    agent = await activate_agent(store, tested_agent["id"])
    assert agent["status"] == "active"
