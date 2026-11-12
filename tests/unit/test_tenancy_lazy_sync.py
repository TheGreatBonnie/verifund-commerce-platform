import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.settings import Settings
from verifund_control_plane.tenancy.identity import resolve_identity
from verifund_control_plane.tenancy.repository import TenancyRepository


class FakeDirectory:
    def __init__(self):
        self.users = {}
        self.orgs = {}
        self.memberships = {}

    async def user(self, clerk_user_id):
        return self.users.get(clerk_user_id)

    async def organization(self, clerk_org_id):
        return self.orgs.get(clerk_org_id)

    async def membership(self, clerk_org_id, clerk_user_id):
        return self.memberships.get((clerk_org_id, clerk_user_id))


@pytest.fixture
async def store_and_settings(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'lazy.db'}")
    store = TenancyRepository(engine)
    await store.create_schema()
    settings = Settings(_env_file=None, mode="fake")
    yield store, settings
    await engine.dispose()


@pytest.fixture
def fake_directory():
    d = FakeDirectory()
    d.users["user_1"] = {"id": "user_1", "email": "a@example.com", "name": "A"}
    d.orgs["org_new"] = {"id": "org_new", "name": "New", "slug": "new"}
    d.memberships[("org_new", "user_1")] = {
        "organization": {"id": "org_new"},
        "public_user_data": {"user_id": "user_1"},
        "role": "org:admin",
    }
    return d


async def test_missing_organization_is_fetched_lazily(store_and_settings, fake_directory):
    store, settings = store_and_settings
    identity = await resolve_identity(
        store,
        {"sub": "user_1", "org_id": "org_new", "org_role": "org:admin"},
        settings,
        directory=fake_directory,
    )
    assert identity.tenant_id
    assert await store.get_organization_by_clerk_id("org_new") is not None


async def test_no_org_claim_resolves_personal_tenant(store_and_settings, fake_directory):
    store, settings = store_and_settings
    identity = await resolve_identity(
        store, {"sub": "user_1"}, settings, directory=fake_directory
    )
    org = await store.get_organization(identity.tenant_id)
    assert org["kind"] == "personal"
    assert org["owner_user_id"] == identity.user_id
