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
