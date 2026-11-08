from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest_asyncio
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

CLOCK = lambda: datetime.now(UTC)


async def _build_app(tmp_path, *, sandbox: bool):
    # Use fake mode to avoid strict sandbox env validation in tests; gate the
    # route's auto-approve path by app.state.settings.is_sandbox.
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=CLOCK)
    if sandbox:
        app.state.settings = SimpleNamespace(is_sandbox=True, mode="sandbox")
    return app


async def _seed_seller(app):
    store = app.state.tenancy
    user = await store.upsert_user("user_s1", "s1@example.com", "Seller")
    org = await store.upsert_organization("org_s1", "Seller Org", "seller-org")
    await store.upsert_membership(org["id"], user["id"], "org:admin", "mem_s1")
    app.state.clerk_authenticator = lambda request: {
        "sub": "user_s1",
        "org_id": "org_s1",
        "org_role": "org:admin",
    }
    return {"authorization": "Bearer s1"}


@pytest_asyncio.fixture
async def sandbox_client(tmp_path):
    app = await _build_app(tmp_path / "sbx", sandbox=True)
    async with app.router.lifespan_context(app):
        headers = await _seed_seller(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, headers


@pytest_asyncio.fixture
async def pending_client(tmp_path):
    app = await _build_app(tmp_path / "pend", sandbox=False)
    async with app.router.lifespan_context(app):
        headers = await _seed_seller(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, headers


async def test_profile_route_saves_and_advances(sandbox_client):
    client, headers = sandbox_client
    r = await client.post("/v1/seller/onboarding", headers=headers)
    assert r.status_code == 201, r.text
    r = await client.post(
        "/v1/seller/onboarding/profile",
        json={"display_name": "Seller One Inc"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile"]["display_name"] == "Seller One Inc"
    assert body["onboarding"]["current_step"] == "agent"


async def test_submit_route_auto_approves_in_sandbox(sandbox_client):
    client, headers = sandbox_client
    await client.post("/v1/seller/onboarding", headers=headers)
    await client.post(
        "/v1/seller/onboarding/profile",
        json={"display_name": "Seller One Inc"},
        headers=headers,
    )
    r = await client.post(
        "/v1/seller/verification/submit",
        json={"documents": {"note": "sandbox"}, "payout_email": "seller@paypal.example"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] == "verified"


async def test_submit_route_pending_when_not_sandbox(pending_client):
    client, headers = pending_client
    await client.post("/v1/seller/onboarding", headers=headers)
    await client.post(
        "/v1/seller/onboarding/profile",
        json={"display_name": "Seller One Inc"},
        headers=headers,
    )
    r = await client.post(
        "/v1/seller/verification/submit",
        json={"documents": {"note": "review"}, "payout_email": "seller@paypal.example"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] == "pending"


async def test_verification_submit_requires_payout_email(sandbox_client):
    client, headers = sandbox_client
    await client.post("/v1/seller/onboarding", headers=headers)
    await client.post(
        "/v1/seller/onboarding/profile",
        json={"display_name": "Seller One Inc"},
        headers=headers,
    )
    r = await client.post(
        "/v1/seller/verification/submit",
        json={"documents": {"note": "x"}},
        headers=headers,
    )
    assert r.status_code == 422, r.text


async def test_agent_create_blocked_before_profile(sandbox_client):
    client, headers = sandbox_client
    # Business org exists (seeded) but no onboarding yet — agent creation
    # must be blocked until POST /v1/seller/onboarding creates the profile.
    r = await client.post("/v1/agents", json={}, headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "onboarding_incomplete"
