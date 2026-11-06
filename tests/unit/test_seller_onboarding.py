import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.onboarding.service import create_onboarding
from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.repository import TenancyRepository


@pytest.fixture
async def store(tmp_path):
    path = tmp_path / "onboarding.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    repo = Repository(engine)
    await repo.create_schema()
    s = TenancyRepository(engine)
    await s.create_schema()
    yield s
    await engine.dispose()


async def test_create_onboarding_is_idempotent(store):
    org = await store.upsert_organization("org_1", "Acme", "acme")
    user = await store.upsert_user("user_1", "a@example.com", "A")
    first = await create_onboarding(store, org["id"], user["id"])
    second = await create_onboarding(store, org["id"], user["id"])
    assert first["seller_id"] == second["seller_id"]
    assert (await store.get_onboarding(org["id"]))["status"] == "in_progress"


async def test_personal_org_is_rejected(store):
    user = await store.upsert_user("user_2", "b@example.com", "B")
    personal = await store.create_personal_organization(user["id"])
    with pytest.raises(VerifundError) as exc:
        await create_onboarding(store, personal["id"], user["id"])
    assert exc.value.status_code == 403
