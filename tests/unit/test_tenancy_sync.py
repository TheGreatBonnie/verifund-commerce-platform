import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.tenancy.repository import TenancyRepository
from verifund_control_plane.tenancy.sync import apply_clerk_event


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sync.db'}")
    s = TenancyRepository(engine)
    await s.create_schema()
    yield s
    await engine.dispose()


async def test_org_created_does_not_create_a_seller_profile(store):
    await apply_clerk_event(
        store,
        {
            "type": "organization.created",
            "data": {"id": "org_1", "name": "Acme", "slug": "acme"},
        },
    )
    org = await store.get_organization_by_clerk_id("org_1")
    assert org["kind"] == "business"
    assert await store.get_seller_profile_by_organization(org["id"]) is None


async def test_membership_deleted_marks_removed(store):
    user = await store.upsert_user("user_1", "a@example.com", "A")
    org = await store.upsert_organization("org_1", "Acme", "acme")
    await store.upsert_membership(org["id"], user["id"], "org:member", "mem_1")
    await apply_clerk_event(
        store,
        {
            "type": "organizationMembership.deleted",
            "data": {
                "organization": {"id": "org_1"},
                "public_user_data": {"user_id": "user_1"},
            },
        },
    )
    row = await store.get_membership(org["id"], user["id"])
    assert row["status"] == "removed"
