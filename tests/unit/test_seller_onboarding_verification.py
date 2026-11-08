import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.onboarding.service import (
    create_onboarding,
    submit_verification,
)
from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.repository import TenancyRepository


@pytest.fixture
async def repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    repository = TenancyRepository(engine)
    core = Repository(engine)
    async with engine.begin() as conn:
        await conn.run_sync(core.metadata.create_all)
        await conn.run_sync(repository.metadata.create_all)
    yield repository
    await engine.dispose()


async def _seed(repo):
    org = await repo.upsert_organization("org_acme", "Acme", "acme")
    user = await repo.upsert_user("user_1", "u@example.com", "User")
    await repo.upsert_membership(org["id"], user["id"], "org:admin", "mem_1")
    await create_onboarding(repo, org["id"], user["id"])
    return org, user


async def test_submit_verification_pending_without_auto_approve(repo):
    org, user = await _seed(repo)
    profile = await submit_verification(
        repo, org["id"], user["id"], {"note": "docs"}, payout_email="seller@paypal.example", auto_approve_sandbox=False
    )
    assert profile["verification_status"] == "pending"
    onboarding = await repo.get_onboarding(org["id"])
    assert onboarding["status"] == "submitted"
    assert onboarding["current_step"] == "verification"


async def test_submit_verification_auto_approves_in_sandbox(repo):
    org, user = await _seed(repo)
    profile = await submit_verification(
        repo, org["id"], user["id"], {"note": "docs"}, payout_email="seller@paypal.example", auto_approve_sandbox=True
    )
    assert profile["verification_status"] == "verified"
    onboarding = await repo.get_onboarding(org["id"])
    assert onboarding["current_step"] in {"activation", "agent_setup", "verified", "complete"} or onboarding["status"] == "in_progress"
    assert (await repo.get_seller_profile_by_organization(org["id"]))["verification_status"] == "verified"


async def test_submit_verification_invalid_state(repo):
    org, user = await _seed(repo)
    await submit_verification(repo, org["id"], user["id"], {}, payout_email="seller@paypal.example", auto_approve_sandbox=False)
    with pytest.raises(VerifundError) as exc:
        await submit_verification(repo, org["id"], user["id"], {}, payout_email="seller@paypal.example", auto_approve_sandbox=False)
    assert exc.value.code == "invalid_state"
