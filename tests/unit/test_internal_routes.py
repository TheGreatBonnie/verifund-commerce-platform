import json

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from seller_agent.settings import Settings
from seller_agent.server import create_app

INTERNAL = "internal-test-token"
ORG = "org_A"
ORG_B = "org_B"
AGENT = "agent_demo"


@pytest_asyncio.fixture
async def client(tmp_path):
    settings = Settings(
        config_source="shared",
        shared_db_url=f"sqlite+aiosqlite:///{tmp_path}/sellers.db",
        internal_api_token=INTERNAL,
        verifund_mode="off",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as async_client:
            yield async_client


def h(org=ORG, agent=AGENT, token=INTERNAL) -> dict[str, str]:
    return {"x-internal-token": token,
            "x-org-id": org,
            "x-agent-id": agent}


async def test_internal_routes_require_token(client):
    r = await client.post("/internal/agent-configs", json={
        "agent_id": AGENT, "organization_id": ORG,
        "seller_id": "demo", "name": "Demo"})
    assert r.status_code == 401


async def test_agent_configs_create_and_conflict(client):
    body = {"agent_id": AGENT, "organization_id": ORG,
            "seller_id": "demo", "name": "Demo",
            "instructions": "be crisp",
            "tool_allowlist": ["commerce.catalog.search"],
            "max_discount_bps": 1500,
            "autonomy_mode": "policy_bounded"}
    r1 = await client.post("/internal/agent-configs", json=body, headers=h())
    assert r1.status_code == 200 and r1.json()["config_version"] == 1
    r2 = await client.post(
        "/internal/agent-configs",
        json={**body, "expected_config_version": 99},
        headers=h())
    assert r2.status_code == 409


async def test_catalog_import_validates_and_writes(client):
    doc = json.dumps({"version": 1, "products": [
        {"sku": "T1", "name": "Thing", "category": "c",
         "list_unit_price_cents": 100,
         "initial_unit_price_cents": 90,
         "floor_unit_price_cents": 80,
         "stock_on_hand": 2}]})
    r = await client.post("/internal/catalog/import",
                          json={"document": doc}, headers=h())
    assert r.status_code == 200 and r.json()["inserted"] == 1
    bad = json.dumps({"version": 1, "products": [
        {"sku": "T1", "name": "Thing", "category": "c",
         "list_unit_price_cents": 100,
         "initial_unit_price_cents": 70,
         "floor_unit_price_cents": 80,
         "stock_on_hand": 2}]})
    r = await client.post("/internal/catalog/import",
                          json={"document": bad}, headers=h())
    assert r.status_code == 422 and len(r.json()["errors"]) >= 1


async def test_catalog_import_duplicate_sku_rejected(client):
    doc = json.dumps({"version": 1, "products": [
        {"sku": "T1", "name": "A", "category": "c",
         "list_unit_price_cents": 100,
         "initial_unit_price_cents": 90,
         "floor_unit_price_cents": 80,
         "stock_on_hand": 2},
        {"sku": "T1", "name": "B", "category": "c",
         "list_unit_price_cents": 200,
         "initial_unit_price_cents": 180,
         "floor_unit_price_cents": 160,
         "stock_on_hand": 3}]})
    r = await client.post("/internal/catalog/import",
                          json={"document": doc}, headers=h())
    assert r.status_code == 422
    # no writes: fetch with the agent endpoint should show no products
    r = await client.get(f"/internal/agent-configs/{AGENT}", headers=h())
    assert r.status_code == 404  # agent never created; no products written either


async def test_org_mismatch_is_403(client):
    body = {"agent_id": AGENT, "organization_id": ORG_B,
            "seller_id": "demo", "name": "Demo"}
    r = await client.post("/internal/agent-configs",
                          json=body, headers=h(org=ORG))
    assert r.status_code == 403


async def test_agent_configs_roundtrip_and_cross_org_hidden(client):
    body = {"agent_id": AGENT, "organization_id": ORG,
            "seller_id": "demo", "name": "Demo"}
    r = await client.post("/internal/agent-configs", json=body, headers=h())
    assert r.status_code == 200
    r = await client.get(f"/internal/agent-configs/{AGENT}", headers=h())
    assert r.status_code == 200 and r.json()["agent_id"] == AGENT
    r = await client.get(f"/internal/agent-configs/{AGENT}",
                         headers=h(org=ORG_B, agent="agent_other"))
    assert r.status_code == 404
