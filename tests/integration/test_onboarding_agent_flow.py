from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest_asyncio
from seller_agent.server import create_app as create_seller_app
from seller_agent.settings import Settings as SellerSettings
from verifund_control_plane.agents.credentials import verify_credential
from verifund_control_plane.app import create_app
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.settings import Settings

EXAMPLE = Path("scripts/fixtures/example-catalog.json").read_text(encoding="utf-8")
CLOCK = lambda: datetime.now(UTC)


@pytest_asyncio.fixture
async def stack(tmp_path):
    seller_settings = SellerSettings(
        config_source="shared",
        shared_db_url=f"sqlite+aiosqlite:///{tmp_path}/sellers.db",
        internal_api_token="secret",
        verifund_mode="off",
    )
    seller_app = create_seller_app(seller_settings)

    cp_settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/verifund.db",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
        seller_internal_token="secret",
        seller_agent_url="http://seller-shared",
        registry_url="http://registry",
        agents_public_base_url="https://agents.verifund.com",
    )
    cp_app = create_app(cp_settings, clock=CLOCK)

    published: list[dict] = []

    def registry_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/agents" and request.method == "POST":
            import json as _json
            published.append(_json.loads(request.content))
            return httpx.Response(201, json={"published": True})
        return httpx.Response(404, json={"code": "not_found"})

    async with (
        seller_app.router.lifespan_context(seller_app),
        cp_app.router.lifespan_context(cp_app),
    ):
        async def _verify(token: str, *, purpose: str = "a2a:call"):
            tenancy = cp_app.state.tenancy
            try:
                return await verify_credential(tenancy, token, purpose=purpose)
            except VerifundError:
                return None

        seller_app.state.credential_verifier = _verify
        cp_app.state.runtime_client_factory = lambda: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=seller_app),
            base_url="http://seller-shared",
        )
        cp_app.state.registry_client_factory = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(registry_handler),
            base_url="http://registry",
        )
        cp = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=cp_app), base_url="http://cp")

        async def _seed(org_id: str, seller_id: str, display: str,
                        role: str = "org:admin", verified: bool = True):
            store = cp_app.state.tenancy
            user = await store.upsert_user(f"user_{seller_id}",
                                           f"{seller_id}@example.com",
                                           display)
            org = await store.upsert_organization(org_id, display, seller_id)
            await store.upsert_membership(org["id"], user["id"], role,
                                         f"mem_{seller_id}")
            await store.upsert_seller_profile(org["id"], seller_id, display)
            if verified:
                await store.set_verification_status(seller_id, "verified")
            return org, user

        def _headers(seller_id: str):
            app = cp_app
            app.state.clerk_authenticator = (
                lambda request: {
                    "sub": f"user_{seller_id}",
                    "org_id": f"org_{seller_id}",
                    "org_role": "org:admin",
                })
            return {"authorization": f"Bearer {seller_id}"}

        await _seed("org_acme", "acme", "Acme", verified=True)
        yield {
            "cp": cp,
            "published": published,
            "headers": _headers("acme"),
            "seller_app": seller_app,
            "cp_app": cp_app,
        }
        await cp.aclose()


async def test_full_onboarding_saga_reaches_active(stack):
    cp = stack["cp"]
    h = stack["headers"]

    r = await cp.post("/v1/agents", json={"display_name": "Acme Industrial"},
                      headers=h)
    assert r.status_code == 201, r.text
    agent_id = r.json()["agent_id"]
    assert agent_id == "agent_acme"

    r = await cp.patch(f"/v1/agents/{agent_id}/config",
                       json={"instructions": "Be crisp.",
                             "tool_allowlist": [
                                 "commerce.catalog.search",
                                 "commerce.quote",
                                 "commerce.negotiate",
                             ]},
                       headers=h)
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["max_discount_bps"] == 1000
    assert cfg["policy_hash"]

    r = await cp.patch(f"/v1/agents/{agent_id}/policies",
                       json={"max_discount_bps": 1500},
                       headers=h)
    assert r.status_code == 200
    assert r.json()["max_discount_bps"] == 1500

    r = await cp.post("/v1/seller/catalog/import",
                      json={"document": EXAMPLE},
                      headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["inserted"] >= 1

    r = await cp.post(f"/v1/agents/{agent_id}/test", json={}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["passed"] is True, r.json()
    assert [c["name"] for c in r.json()["checks"]] == [
        "auth", "catalog", "pricing", "a2a", "authority", "revocation"]

    r = await cp.post(f"/v1/agents/{agent_id}/activate", json={}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"
    published = stack["published"]
    assert published and published[0]["agent_id"] == agent_id
    assert published[0]["card_url"] == "https://agents.verifund.com/acme/a2a"

    r = await cp.get(f"/v1/agents/{agent_id}/status", headers=h)
    assert r.json()["status"] == "active"
    assert r.json()["latest_test_run"]["passed"] == "1"


async def test_cross_tenant_status_is_404(stack):
    cp = stack["cp"]
    h = stack["headers"]
    r = await cp.post("/v1/agents", json={"display_name": "Acme"}, headers=h)
    agent_id = r.json()["agent_id"]

    store = stack["cp_app"].state.tenancy
    other_user = await store.upsert_user("user_other", "o@example.com", "O")
    other = await store.upsert_organization("org_other", "Other", "other")
    await store.upsert_membership(other["id"], other_user["id"], "org:admin",
                                  "mem_other")
    app = stack["cp_app"]
    app.state.clerk_authenticator = (
        lambda request: {"sub": "user_other",
                         "org_id": "org_other",
                         "org_role": "org:admin"})
    other_headers = {"authorization": "Bearer other"}

    r = await cp.get(f"/v1/agents/{agent_id}/status", headers=other_headers)
    assert r.status_code == 404


async def test_create_agent_uses_opaque_uuid_for_org_without_profile(stack):
    cp = stack["cp"]
    store = stack["cp_app"].state.tenancy
    user = await store.upsert_user("user_noprof", "noprof@example.com", "NoProf")
    org = await store.upsert_organization("org_noprof", "NoProf", "noprof")
    await store.upsert_membership(org["id"], user["id"], "org:admin", "mem_noprof")
    app = stack["cp_app"]
    app.state.clerk_authenticator = (
        lambda request: {"sub": "user_noprof", "org_id": "org_noprof", "org_role": "org:admin"})
    headers = {"authorization": "Bearer noprof"}
    r = await cp.post("/v1/seller/onboarding", headers=headers)
    assert r.status_code == 201, r.text
    r = await cp.post("/v1/agents", json={}, headers=headers)
    assert r.status_code == 201, r.text
    agent_id = r.json()["agent_id"]
    assert agent_id.startswith("agent_")
    assert len(agent_id.removeprefix("agent_")) == 32
