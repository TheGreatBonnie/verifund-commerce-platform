from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from buyer_agent.server import create_app as create_buyer_app
from buyer_agent.settings import Settings as BuyerSettings
from commerce_core.contracts import RFQ, RFQConstraints, RFQPreferences
from commerce_core.extension import wrap_payload
from langgraph.checkpoint.memory import MemorySaver
from seller_agent.server import create_app as create_seller_app
from seller_agent.settings import Settings as SellerSettings

from tests.support.fake_buyer import FakeServices


@pytest.fixture
async def seller_v03_app(tmp_path: Path):
    settings = SellerSettings(
        service_name="Northwind Audio",
        host="127.0.0.1",
        port=9201,
        public_base_url="http://127.0.0.1:9201",
        profile_path=Path("apps/seller_agent/seller_agent/profiles/northwind.yaml"),
        seller_token="test-seller-token",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'seller.db'}",
        llm_mode="scripted",
        nebius_api_key=None,
    )
    app = create_seller_app(settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def buyer_v03_app(tmp_path: Path):
    settings = BuyerSettings(
        host="127.0.0.1",
        port=9100,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'buyer.db'}",
        checkpoint_path=tmp_path / "checkpoints.db",
    )
    app = create_buyer_app(settings, MemorySaver(), FakeServices())
    async with app.router.lifespan_context(app):
        yield app


async def post_a2a(app, payload: dict, headers: dict[str, str]) -> dict:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
        response = await client.post("/a2a", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def v03_message_send(message: dict, request_id: str = "1") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": {"message": message},
    }


def sample_rfq(request_id: str, run_id: str) -> RFQ:
    return RFQ(
        request_id=request_id,
        run_id=run_id,
        category="consumer-electronics",
        product_hint="Nimbus NC-700",
        quantity=12,
        required_by=datetime.now(UTC) + timedelta(days=14),
        constraints=RFQConstraints(
            min_warranty_months=24,
            min_returns_days=30,
            color="black",
        ),
        preferences=RFQPreferences(sustainability=True),
    )


async def test_v03_message_send_reaches_seller(seller_v03_app):
    rfq = sample_rfq("rfq-v03", "run-v03")
    body = await post_a2a(
        seller_v03_app,
        v03_message_send(
            message={
                "kind": "message",
                "messageId": "m1",
                "role": "user",
                "contextId": "run-v03",
                "parts": [
                    {"kind": "text", "text": "Please quote 12 units."},
                    {"kind": "data", "data": wrap_payload("rfq", rfq)},
                ],
            }
        ),
        headers={
            "Authorization": "Bearer test-seller-token",
            "A2A-Version": "0.3",
        },
    )

    assert "error" not in body, body
    result = body["result"]
    assert result["kind"] == "task"
    assert result["status"]["state"] == "input-required"

    data_parts = [
        part
        for artifact in result.get("artifacts", [])
        for part in artifact["parts"]
        if part["kind"] == "data"
    ]
    assert any(part["data"]["schema"].endswith("/offer.json") for part in data_parts)


async def test_v10_send_message_still_works(seller_v03_app):
    rfq = sample_rfq("rfq-v10", "run-v10")
    body = await post_a2a(
        seller_v03_app,
        {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "m1",
                    "role": "ROLE_USER",
                    "contextId": "run-v10",
                    "parts": [
                        {
                            "text": "Please quote 12 units.",
                            "mediaType": "text/plain",
                        },
                        {
                            "data": wrap_payload("rfq", rfq),
                            "mediaType": "application/json",
                        },
                    ],
                }
            },
        },
        headers={
            "Authorization": "Bearer test-seller-token",
            "A2A-Version": "1.0",
        },
    )

    assert "error" not in body, body
    task = body["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    assert any(
        part["data"]["schema"].endswith("/offer.json")
        for artifact in task.get("artifacts", [])
        for part in artifact["parts"]
        if "data" in part
    )


async def test_v03_message_send_reaches_buyer(buyer_v03_app):
    body = await post_a2a(
        buyer_v03_app,
        v03_message_send(
            message={
                "kind": "message",
                "messageId": "m1",
                "role": "user",
                "contextId": "agui-v03",
                "parts": [
                    {
                        "kind": "text",
                        "text": "Buy 12 Nimbus NC-700 headsets for our team.",
                    }
                ],
            }
        ),
        headers={"A2A-Version": "0.3"},
    )

    assert "error" not in body, body
    result = body["result"]
    assert result["kind"] == "task"
    assert result["status"]["state"] == "input-required"

    status_text = result["status"]["message"]["parts"][0]["text"]
    status = json.loads(status_text)
    assert status["status"] == "approval_required"
