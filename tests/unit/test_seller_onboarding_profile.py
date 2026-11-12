from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

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


async def test_update_seller_display_name(repo):
    await repo.upsert_seller_profile("org_1", "acme", "Acme")
    updated = await repo.update_seller_display_name("acme", "Acme Industrial")
    assert updated is not None
    assert updated["seller_id"] == "acme"
    assert updated["display_name"] == "Acme Industrial"


async def test_update_seller_display_name_missing(repo):
    assert await repo.update_seller_display_name("missing", "X") is None

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.onboarding.service import (
    create_onboarding,
    save_profile_and_continue,
)


async def _seed_business(repo, clerk_org_id="org_acme"):
    org = await repo.upsert_organization(clerk_org_id, "Acme", "acme")
    user = await repo.upsert_user("user_1", "u@example.com", "User")
    await repo.upsert_membership(org["id"], user["id"], "org:admin", "mem_1")
    return org, user


async def test_save_profile_and_continue_advances_to_agent(repo):
    org, user = await _seed_business(repo)
    await create_onboarding(repo, org["id"], user["id"])
    result = await save_profile_and_continue(
        repo, org["id"], user["id"], "Acme Industrial"
    )
    assert result["profile"]["display_name"] == "Acme Industrial"
    assert result["onboarding"]["current_step"] == "agent"
    assert result["onboarding"]["status"] == "in_progress"


async def test_save_profile_and_continue_not_found(repo):
    with pytest.raises(VerifundError) as exc:
        await save_profile_and_continue(repo, "org_missing", "u1", "X")
    assert exc.value.code == "not_found"
