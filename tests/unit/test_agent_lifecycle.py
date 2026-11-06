import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane.agents.credentials import issue_credential
from verifund_control_plane.agents.lifecycle import activate_agent, confirm_policy
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.repository import TenancyRepository


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'life.db'}")
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
async def draft_agent(store):
    return await store.create_agent(
        organization_id=store._org_id,
        name="Acme",
        created_by="user_1",
        policy_ref="acme/main",
        policy_version="1",
        policy_hash="a" * 64,
    )


@pytest.fixture
async def active_agent(store, draft_agent):
    await store.set_agent_status(draft_agent["id"], "testing")
    await store.create_test_run(
        draft_agent["id"],
        store._org_id,
        policy_hash="a" * 64,
        card_hash=draft_agent.get("card_hash") or "",
        checks=[{"name": "x", "passed": True}],
        passed=True,
    )
    await issue_credential(store, store._org_id, draft_agent["id"], ["a2a:call"])
    await store.set_agent_status(draft_agent["id"], "active")
    return await store.get_agent(draft_agent["id"])


async def test_policy_confirmation_records_hash(store, draft_agent):
    updated = await confirm_policy(store, draft_agent["id"], "2", "c" * 64)
    assert updated["policy_version"] == "2"
    assert updated["policy_hash"] == "c" * 64


async def test_activation_blocked_on_drift(store, active_agent):
    await store.set_agent_status(active_agent["id"], "testing")
    await store.set_policy_drift(active_agent["id"], True)
    with pytest.raises(VerifundError) as exc:
        await activate_agent(store, active_agent["id"])
    assert exc.value.code == "policy_drift"
