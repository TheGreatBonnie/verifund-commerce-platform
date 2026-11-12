from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from commerce_core.binding import binding_from_award, offer_hash
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.seller_auth import clerk_seller_headers, seed_seller_profile

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops", "x-verifund-actor": "buyer-agent"}


def payload(run_id="run-1", offer_id="offer-1", seller_id: str = "northwind-audio") -> dict:
    award = {
        "run_id": run_id,
        "buyer_id": "demo-buyer",
        "seller_id": seller_id,
        "offer_id": offer_id,
        "request_id": f"rfq-{run_id}",
        "buyer_display_name": "Demo Buyer",
        "seller_display_name": "Northwind Audio",
        "currency": "USD",
        "amount_cents": 123400,
        "shipping_cents": 3400,
        "tax_cents": 0,
        "fees_cents": 0,
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
        "offer_round": 1,
        "offer_valid_until": (NOW + timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z"
        ),
    }
    award["offer_hash"] = offer_hash(binding_from_award(award))
    return award


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
            yield client, app


async def award(client, run_id="run-1", offer_id="offer-1", seller_id: str = "northwind-audio") -> dict:
    response = await client.post(
        "/awards",
        json=payload(run_id, offer_id, seller_id=seller_id),
        headers={**OPS, "idempotency-key": f"award:{run_id}:{offer_id}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_seller_can_read_only_its_transaction(api):
    http, app = api
    first = await award(http)
    second = await award(http, "run-2", "offer-2", seller_id="other-seller")
    headers = await _seller_headers(app)

    read = await http.get(
        f"/seller/transactions/{first['transaction_id']}", headers=headers
    )
    assert read.status_code == 200
    body = read.json()
    assert body["amount_cents"] == 123400
    assert body["line_items"][0]["sku"] == "NC-700"
    assert body["allowed_actions"] == []

    wrong = await http.get(
        f"/seller/transactions/{second['transaction_id']}", headers=headers
    )
    assert wrong.status_code in {403, 404}


async def test_seller_cannot_upload_before_funding(api):
    http, app = api
    award_body = await award(http)
    response = await http.post(
        f"/seller/transactions/{award_body['transaction_id']}/evidence",
        headers=await _seller_headers(app),
        data={"requirement_id": "shipment_manifest"},
        files={"file": ("manifest.json", b'{"tracking_number":"TRK-1"}', "application/json")},
    )
    assert response.status_code == 409


async def _seller_headers(app):
    await seed_seller_profile(
        app,
        clerk_org_id="org_northwind",
        seller_id="northwind-audio",
        display_name="northwind-audio",
        clerk_user_id="user_northwind",
    )
    return clerk_seller_headers(
        app, sub="user_northwind", org_id="org_northwind", token="tok_northwind"
    )
