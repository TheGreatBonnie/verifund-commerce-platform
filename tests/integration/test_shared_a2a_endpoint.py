import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from a2a.types.a2a_pb2 import Role, SendMessageRequest
from commerce_core.a2a_parts import make_message
from commerce_core.contracts import RFQ, RFQConstraints, RFQPreferences
from commerce_core.extension import wrap_payload
from fastapi.testclient import TestClient
from google.protobuf.json_format import MessageToDict
from seller_agent.settings import Settings
from seller_agent.shared_app import create_shared_app
from seller_agent.shared_schema import configure_shared_engine, create_shared_schema
from seller_agent.shared_store import ConfigUpsert, OrgScopedStore
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


class Verifier:
    async def verify(self, token, purpose="a2a:call"):
        if token == "buyer":
            return {"organization_id": "org-buyer", "agent_id": "agent_buyer",
                    "status": "active", "scopes": ["a2a:call"]}
        return None


async def _seed(url: str) -> None:
    engine = create_async_engine(url)
    await configure_shared_engine(engine)
    await create_shared_schema(engine)
    store = OrgScopedStore(
        engine, organization_id="org-seller-a", agent_id="agent_seller-a")
    await store.upsert_config(
        "agent_seller-a",
        ConfigUpsert(instructions="sell", max_discount_bps=1000,
                     autonomy_mode="policy_bounded"),
        seller_id="seller-a", name="Seller A", tagline="Fast",
    )
    await store.import_products([{
        "sku": "SKU-1", "name": "Widget", "category": "general",
        "description": "A widget", "list_unit_price_cents": 1000,
        "initial_unit_price_cents": 950, "floor_unit_price_cents": 800,
        "stock_on_hand": 10, "concession_ladder_cents": [950, 900, 850],
        "base_warranty_months": 12, "warranty_addons_cents": {12: 0},
    }], replace=False)
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE seller_configs SET status='active' "
            "WHERE agent_id='agent_seller-a'"))
    await engine.dispose()


@pytest.fixture
def client(tmp_path):
    db = f"sqlite+aiosqlite:///{tmp_path}/sellers.db"
    asyncio.run(_seed(db))
    settings = Settings(
        config_source="shared",
        shared_db_url=db,
        public_base_url="http://testserver",
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
        internal_api_token="internal",
        verifund_mode="off",
    )
    app = create_shared_app(settings, credential_verifier=Verifier())
    with TestClient(app) as test_client:
        yield test_client


def _send_body(tenant: str) -> dict:
    rfq = RFQ(
        request_id="req-1",
        run_id="run-1",
        category="general",
        product_hint="Widget",
        product_sku="SKU-1",
        quantity=1,
        required_by=datetime.now(UTC) + timedelta(days=7),
        constraints=RFQConstraints(min_warranty_months=0, min_returns_days=0),
        preferences=RFQPreferences(),
    )
    message = make_message(
        role=Role.ROLE_USER,
        text="Need one unit.",
        context_id="ctx-1",
        envelope=wrap_payload("rfq", rfq),
    )
    request = SendMessageRequest(tenant=tenant, message=message)
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "SendMessage",
        "params": MessageToDict(request),
    }


def _post(client: TestClient, seller_id: str, body: dict, token: str = "buyer"):
    headers = {"A2A-Version": "1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(f"/{seller_id}/a2a", headers=headers, json=body)


def test_card_and_a2a_share_one_host(client):
    card = client.get("/seller-a/.well-known/agent-card.json")
    assert card.status_code == 200
    card_json = card.json()
    assert card_json["supportedInterfaces"][0]["tenant"] == "agent_seller-a"
    assert card_json["supportedInterfaces"][0]["url"] == (
        "http://testserver/seller-a/a2a")

    response = _post(client, "seller-a", _send_body("agent_seller-a"))
    assert response.status_code == 200
    payload = response.json()
    assert "error" not in payload
    task = payload["result"]["task"]
    assert task["id"]
    assert task["status"]["state"] in (
        "TASK_STATE_INPUT_REQUIRED", "TASK_STATE_COMPLETED")


def test_catalog_is_public(client):
    response = client.get("/seller-a/api/catalog")
    assert response.status_code == 200
    assert response.json()["products"][0]["sku"] == "SKU-1"


def test_dashboard_requires_internal_token(client):
    assert client.get("/seller-a/api/console/dashboard").status_code == 401
    response = client.get(
        "/seller-a/api/console/dashboard",
        headers={"X-Internal-Token": "internal"},
    )
    assert response.status_code == 200
    assert response.json()["seller_id"] == "seller-a"


def test_unknown_seller_card_is_404(client):
    assert client.get(
        "/missing/.well-known/agent-card.json").status_code == 404


def test_missing_credential_is_401(client):
    response = _post(
        client, "seller-a", _send_body("agent_seller-a"), token="")
    assert response.status_code == 401


def test_unknown_tenant_is_jsonrpc_error(client):
    response = _post(client, "seller-a", _send_body("agent_missing"))
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32001


def test_path_tenant_mismatch_is_invalid_params(client):
    response = _post(client, "seller-b", _send_body("agent_seller-a"))
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32602
