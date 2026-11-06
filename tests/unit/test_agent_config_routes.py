from datetime import UTC, datetime

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
        seller_internal_token="secret-token",
        seller_agent_url="http://runtime",
        registry_url="http://registry",
        agents_public_base_url="https://agents.verifund.com",
    )
    clock = lambda: datetime.now(UTC)
    app = create_app(settings, clock=clock)

    runtime_state = {"configs": {}, "force_test_fail": False}
    published: list[dict] = []

    def runtime_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        org = request.headers.get("x-org-id")
        if request.headers.get("x-internal-token") != "secret-token":
            return httpx.Response(401, json={"code": "internal_auth"})
        if path == "/internal/agent-configs" and request.method == "POST":
            import json as _json
            body = _json.loads(request.content) if request.content else {}
            agent_id = body["agent_id"]
            current = runtime_state["configs"].get((org, agent_id))
            expected = (body or {}).get("expected_config_version")
            if current and expected is not None and expected != current["config_version"]:
                return httpx.Response(409, json={
                    "code": "config_conflict",
                    "config_version": current["config_version"],
                })
            version = (current or {"config_version": 0})["config_version"] + 1
            config = {
                "agent_id": agent_id,
                "organization_id": org,
                "seller_id": body.get("seller_id", agent_id),
                "name": body.get("name") or "Seller agent",
                "tagline": body.get("tagline") or "",
                "instructions": body.get("instructions") or "",
                "max_discount_bps": body.get("max_discount_bps") or 1000,
                "autonomy_mode": body.get("autonomy_mode") or "policy_bounded",
                "tool_allowlist": body.get("tool_allowlist") or [],
                "policy_version": 1,
                "policy_hash": "a" * 64,
                "config_version": version,
                "status": "draft",
            }
            runtime_state["configs"][(org, agent_id)] = config
            return httpx.Response(200, json=config)
        if path.startswith("/internal/agent-configs/") and request.method == "GET":
            agent_id = path.rsplit("/", 1)[-1]
            config = runtime_state["configs"].get((org, agent_id))
            if not config:
                return httpx.Response(404, json={"code": "unknown_agent"})
            return httpx.Response(200, json=config)
        if path == "/internal/catalog/import":
            return httpx.Response(200, json={"inserted": 2, "updated": 0,
                                             "replaced": 0, "errors": []})
        if path == "/internal/test-suite":
            import json as _json
            body = _json.loads(request.read())
            fail = body.get("force_fail") or runtime_state.get("force_test_fail")
            checks = [
                {"name": name, "passed": not fail,
                 "detail": ("ok" if not fail else "forced failure")}
                for name in ["auth", "catalog", "pricing",
                             "a2a", "authority", "revocation"]
            ]
            return httpx.Response(200, json={"passed": not fail,
                                             "checks": checks})
        return httpx.Response(404, json={"code": "not_found"})

    def registry_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/agents" and request.method == "POST":
            import json as _json
            published.append(_json.loads(request.content))
            return httpx.Response(201, json={"ok": True})
        return httpx.Response(404, json={"code": "not_found"})

    async with app.router.lifespan_context(app):
        app.state.runtime_client_factory = (
            lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(runtime_handler),
                base_url="http://runtime"))
        app.state.registry_client_factory = (
            lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(registry_handler),
                base_url="http://registry"))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://test") as c:
            c._published = published
            c._runtime_state = runtime_state
            yield c


@pytest.fixture
async def identities(client):
    app = client._transport.app
    store = app.state.tenancy
    admin = await store.upsert_user("admin_1", "a@example.com", "A")
    member = await store.upsert_user("member_1", "m@example.com", "M")
    org = await store.upsert_organization("org_acme", "Acme", "acme")
    await store.upsert_membership(org["id"], admin["id"], "org:admin", "mem_2")
    await store.upsert_membership(org["id"], member["id"], "org:member", "mem_1")
    await store.upsert_seller_profile(org["id"], "acme", "Acme")
    await store.set_verification_status("acme", "verified")

    def _payload(request):
        provided = request.headers.get("authorization", "")
        if provided == "Bearer admin":
            return {"sub": "admin_1", "org_id": "org_acme", "org_role": "org:admin"}
        if provided == "Bearer member":
            return {"sub": "member_1", "org_id": "org_acme", "org_role": "org:member"}
        return None

    app.state.clerk_authenticator = lambda request: _payload(request)
    return {
        "admin_headers": {"authorization": "Bearer admin"},
        "member_headers": {"authorization": "Bearer member"},
        "org_id": org["id"],
    }


def _headers(base, extra=()):
    return {**base, **(extra or {})}


async def test_create_agent_is_idempotent_and_projects_config(client, identities):
    r1 = await client.post("/v1/agents", json={"display_name": "Acme Sales"},
                           headers=_headers(identities["admin_headers"],
                                            {"idempotency-key": "k1"}))
    assert r1.status_code == 201
    body = r1.json()
    assert body["agent_id"] == "agent_acme"
    r2 = await client.post("/v1/agents", json={"display_name": "Acme Sales"},
                           headers=_headers(identities["admin_headers"],
                                            {"idempotency-key": "k1"}))
    assert r2.status_code == 200
    assert r2.json()["agent_id"] == "agent_acme"
    store = client._transport.app.state.tenancy
    agents = await store.list_agents(identities["org_id"])
    assert [a["id"] for a in agents] == ["agent_acme"]


async def test_member_cannot_create_agent(client, identities):
    r = await client.post("/v1/agents", json={"display_name": "X"},
                          headers=_headers(identities["member_headers"]))
    assert r.status_code == 403


async def test_config_save_and_conflict(client, identities):
    await client.post("/v1/agents", json={"display_name": "Acme"},
                      headers=identities["admin_headers"])
    r = await client.patch("/v1/agents/agent_acme/config",
                           json={"max_discount_bps": 1500,
                                 "expected_config_version": 1},
                           headers=identities["admin_headers"])
    assert r.status_code == 200
    assert r.json()["config_version"] == 2
    r = await client.patch("/v1/agents/agent_acme/config",
                           json={"max_discount_bps": 900,
                                 "expected_config_version": 1},
                           headers=identities["admin_headers"])
    assert r.status_code == 409


async def test_catalog_import_proxies_to_runtime(client, identities):
    r = await client.post("/v1/seller/catalog/import",
                          json={"document": '{"version":1,"products":[]}',
                                "replace_catalog": True},
                          headers=identities["admin_headers"])
    assert r.status_code == 200
    assert r.json()["inserted"] == 2


async def test_import_validation_error_propagates_as_422(client, identities):
    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"errors": [{"row": 1, "field": "sku",
                                                     "message": "duplicate"}]})

    app = client._transport.app
    app.state.runtime_client_factory = (
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(failing_handler),
                                  base_url="http://runtime"))
    r = await client.post("/v1/seller/catalog/import",
                          json={"document": '{"version":1,"products":[]}'},
                          headers=identities["admin_headers"])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "catalog_invalid"
    entries = r.json()["error"]["details"]["errors"]
    assert entries and entries[0]["message"] == "duplicate"


async def test_full_flow_reaches_active_and_publishes_card(client, identities):
    await client.post("/v1/agents", json={"display_name": "Acme"},
                      headers=identities["admin_headers"])
    r = await client.post("/v1/agents/agent_acme/test", json={},
                          headers=identities["admin_headers"])
    assert r.status_code == 200
    assert [c["name"] for c in r.json()["checks"]] == [
        "auth", "catalog", "pricing", "a2a", "authority", "revocation"]
    r = await client.post("/v1/agents/agent_acme/activate", json={},
                          headers=identities["admin_headers"])
    assert r.status_code == 200
    assert r.json()["status"] == "active"
    published = client._published
    assert published and published[0]["agent_id"] == "agent_acme"
    assert published[0]["card_url"] == "https://agents.verifund.com/acme/a2a"
    assert published[0]["published"] is True


async def test_activation_blocked_before_passing_test(client, identities):
    await client.post("/v1/agents", json={"display_name": "Acme"},
                      headers=identities["admin_headers"])
    r = await client.post("/v1/agents/agent_acme/activate", json={},
                          headers=identities["admin_headers"])
    assert r.status_code == 409


async def test_foreign_org_agent_is_not_found(client, identities):
    store = client._transport.app.state.tenancy
    other = await store.upsert_organization("org_other", "Other", "other")
    await store.upsert_seller_profile(other["id"], "other", "Other")
    await store.create_agent(organization_id=other["id"], name="OtherAgent",
                             created_by="user_1", policy_ref="other/v1",
                             policy_version="1", policy_hash="b" * 64)
    other_agent = (await store.list_agents(other["id"]))[0]
    r = await client.patch(f"/v1/agents/{other_agent['id']}/config",
                           json={"max_discount_bps": 900},
                           headers=identities["admin_headers"])
    assert r.status_code == 404


async def test_status_endpoint_reports_latest_run(client, identities):
    await client.post("/v1/agents", json={"display_name": "Acme"},
                      headers=identities["admin_headers"])
    await client.post("/v1/agents/agent_acme/test", json={},
                      headers=identities["admin_headers"])
    r = await client.get("/v1/agents/agent_acme/status",
                         headers=identities["admin_headers"])
    assert r.status_code == 200
    assert r.json()["latest_test_run"]["passed"] == "1"
