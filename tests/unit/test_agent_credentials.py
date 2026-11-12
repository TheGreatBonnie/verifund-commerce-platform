import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.agents.credentials import issue_credential, verify_credential
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.repository import TenancyRepository


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cred.db'}")
    repo = Repository(engine)
    await repo.create_schema()
    s = TenancyRepository(engine)
    await s.create_schema()
    yield s
    await engine.dispose()


@pytest.fixture
async def agent(store):
    return await store.create_agent(
        organization_id="org_1",
        name="Acme Agent",
        created_by="user_1",
        policy_ref="acme/main",
        policy_version="1",
        policy_hash="a" * 64,
    )


async def test_raw_credential_is_returned_once_and_verifies(store, agent):
    await store.set_agent_status(agent["id"], "active")
    raw = await issue_credential(store, agent["organization_id"], agent["id"], ["a2a:call"])
    assert raw.startswith("vf_agent_")
    verified = await verify_credential(store, raw)
    assert verified["agent_id"] == agent["id"]
    rows = await store.list_credentials(agent["id"])
    assert all(raw != row["token_hash"] for row in rows)


async def test_non_active_agent_credential_is_rejected(store, agent):
    raw = await issue_credential(store, agent["organization_id"], agent["id"], ["a2a:call"])
    await store.set_agent_status(agent["id"], "suspended")
    with pytest.raises(VerifundError) as exc:
        await verify_credential(store, raw)
    assert exc.value.code == "agent_not_active"


async def test_test_credential_verifies_for_testing_agent(store, agent):
    await store.set_agent_status(agent["id"], "configuring")
    raw = await issue_credential(
        store, agent["organization_id"], agent["id"], ["a2a:test"])
    verified = await verify_credential(store, raw, purpose="a2a:test")
    assert verified["agent_id"] == agent["id"]
    # strict production verification still denies a non-active agent
    from verifund_control_plane.errors import VerifundError

    with pytest.raises(VerifundError) as exc:
        await verify_credential(store, raw)
    assert exc.value.code == "agent_not_active"


async def test_test_purpose_rejects_call_scope_credential(store, agent):
    await store.set_agent_status(agent["id"], "testing")
    raw = await issue_credential(
        store, agent["organization_id"], agent["id"], ["a2a:call"])
    from verifund_control_plane.errors import VerifundError

    with pytest.raises(VerifundError) as exc:
        await verify_credential(store, raw, purpose="a2a:test")
    assert exc.value.code == "scope_insufficient"


async def test_test_purpose_rejects_revoked_agent(store, agent):
    await store.set_agent_status(agent["id"], "testing")
    raw = await issue_credential(
        store, agent["organization_id"], agent["id"], ["a2a:test"])
    await store.set_agent_status(agent["id"], "revoked")
    from verifund_control_plane.errors import VerifundError

    with pytest.raises(VerifundError) as exc:
        await verify_credential(store, raw, purpose="a2a:test")
    assert exc.value.code == "agent_not_active"


async def test_test_purpose_allows_active_agent_retest(store, agent):
    await store.set_agent_status(agent["id"], "active")
    raw = await issue_credential(
        store, agent["organization_id"], agent["id"], ["a2a:test"])
    verified = await verify_credential(store, raw, purpose="a2a:test")
    assert verified["agent_id"] == agent["id"]
    verified_call = await verify_credential(store, raw, purpose="a2a:call")
    assert verified_call["agent_id"] == agent["id"]
