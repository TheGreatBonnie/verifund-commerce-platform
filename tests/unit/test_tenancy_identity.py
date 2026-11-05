import httpx
import pytest
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def seeded_identity(client):
    app = client._transport.app
    store = app.state.tenancy
    user = await store.upsert_user("user_1", "a@example.com", "A")
    org = await store.upsert_organization("org_1", "Acme", "acme")
    await store.upsert_membership(org["id"], user["id"], "org:admin", "mem_1")
    return {"tenant_id": org["id"]}


async def test_require_identity_rejects_missing_token(client):
    # No authenticator installed: Clerk verification with empty keys fails closed
    # so the route does not return identity without a token.
    response = await client.get("/v1/me")
    assert response.status_code in (401, 403, 500)


async def test_require_identity_expands_role_from_database(client, seeded_identity):
    app = client._transport.app
    app.state.clerk_authenticator = lambda request: {
        "sub": "user_1",
        "org_id": "org_1",
        "org_role": "org:admin",
    }
    response = await client.get("/v1/me", headers={"authorization": "Bearer x"})
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == seeded_identity["tenant_id"]
    assert "org:transactions:read" in body["permissions"]
