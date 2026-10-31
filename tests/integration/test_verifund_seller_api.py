from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops", "x-verifund-actor": "buyer-agent"}


def payload(run_id="run-1", offer_id="offer-1") -> dict:
    return {
        "run_id": run_id,
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": offer_id,
        "amount_cents": 123400,
        "shipping_cents": 3400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
    }


@pytest.fixture
async def api(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def award(client, run_id="run-1", offer_id="offer-1") -> dict:
    response = await client.post(
        "/awards",
        json=payload(run_id, offer_id),
        headers={**OPS, "idempotency-key": f"award:{run_id}:{offer_id}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_seller_can_read_only_its_transaction(api):
    first = await award(api)
    second = await award(api, "run-2", "offer-2")
    headers = {"authorization": f"Bearer {first['seller_token']}"}
    read = await api.get(
        f"/seller/transactions/{first['transaction_id']}", headers=headers
    )
    assert read.status_code == 200
    body = read.json()
    assert body["amount_cents"] == 123400
    assert body["line_items"][0]["sku"] == "NC-700"
    assert body["allowed_actions"] == []

    wrong = await api.get(
        f"/seller/transactions/{second['transaction_id']}", headers=headers
    )
    assert wrong.status_code == 403


async def test_seller_cannot_upload_before_funding(api):
    award_body = await award(api)
    response = await api.post(
        f"/seller/transactions/{award_body['transaction_id']}/evidence",
        headers={"authorization": f"Bearer {award_body['seller_token']}"},
        data={"kind": "shipment_manifest"},
        files={"file": ("manifest.json", b'{"tracking_number":"TRK-1"}', "application/json")},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"