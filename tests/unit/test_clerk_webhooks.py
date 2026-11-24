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


async def test_clerk_webhook_is_idempotent(client):
    app = client._transport.app
    app.state.clerk_verifier = lambda body, headers: {
        "type": "user.created",
        "data": {"id": "user_1", "email_addresses": [{"email_address": "a@example.com"}]},
    }
    payload = b'{"type":"user.created"}'
    first = await client.post(
        "/v1/webhooks/clerk",
        content=payload,
        headers={"svix-id": "msg_1", "content-type": "application/json"},
    )
    second = await client.post(
        "/v1/webhooks/clerk",
        content=payload,
        headers={"svix-id": "msg_1", "content-type": "application/json"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    rows = await app.state.repo.list_webhook_events(source="clerk")
    assert len([r for r in rows if r["event_id"] == "msg_1"]) == 1


async def test_clerk_webhook_grants_and_revokes_platform_admin(client):
    app = client._transport.app
    store = app.state.tenancy

    def verifier_for(role):
        return lambda body, headers: {
            "type": "user.updated",
            "data": {
                "id": "user_1",
                "email_addresses": [{"email_address": "a@example.com"}],
                "public_metadata": {"role": role},
            },
        }

    app.state.clerk_verifier = verifier_for("admin")
    grant = await client.post(
        "/v1/webhooks/clerk",
        content=b"{}",
        headers={"svix-id": "role_grant", "content-type": "application/json"},
    )
    assert grant.status_code == 200
    user = await store.get_user_by_clerk_id("user_1")
    assert await store.is_platform_admin(user["id"]) is True

    app.state.clerk_verifier = verifier_for("buyer")
    revoke = await client.post(
        "/v1/webhooks/clerk",
        content=b"{}",
        headers={"svix-id": "role_revoke", "content-type": "application/json"},
    )
    assert revoke.status_code == 200
    assert await store.is_platform_admin(user["id"]) is False


async def test_clerk_user_deletion_revokes_platform_admin(client):
    app = client._transport.app
    store = app.state.tenancy
    app.state.clerk_verifier = lambda body, headers: {
        "type": "user.updated",
        "data": {
            "id": "user_del",
            "email_addresses": [{"email_address": "del@example.com"}],
            "public_metadata": {"role": "admin"},
        },
    }
    await client.post(
        "/v1/webhooks/clerk",
        content=b"{}",
        headers={"svix-id": "del_grant", "content-type": "application/json"},
    )
    user = await store.get_user_by_clerk_id("user_del")
    assert await store.is_platform_admin(user["id"]) is True

    app.state.clerk_verifier = lambda body, headers: {
        "type": "user.deleted",
        "data": {"id": "user_del"},
    }
    await client.post(
        "/v1/webhooks/clerk",
        content=b"{}",
        headers={"svix-id": "del_delete", "content-type": "application/json"},
    )
    assert await store.is_platform_admin(user["id"]) is False
