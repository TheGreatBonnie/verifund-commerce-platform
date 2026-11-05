"""Outbound PayPal tracker sync and visibility (plan Tasks 28/29)."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select
from verifund_contracts import TransactionState
from verifund_control_plane.app import create_app
from verifund_control_plane.paypal_tracking import (
    FakePayPalTracking,
    PayPalTrackingHttpClient,
    normalize_carrier,
)
from verifund_control_plane.settings import Settings

from tests.support.award_flow import (
    NOW,
    OPS,
    accept,
    approve,
    award,
    award_payload,
    fund_and_capture,
    upload_reference,
)


def requirement_catalog() -> list[dict]:
    return [
        {
            "requirement_id": "shipping",
            "title": "Shipping information",
            "description": "Carrier and tracking number for the shipment.",
            "owner": "seller",
            "kind": "shipment_manifest",
            "source": "reference",
            "accepted_formats": [],
            "checks": [
                {
                    "check_id": "tracking_present",
                    "description": "A tracking number is present.",
                    "operator": "exists",
                    "verification_method": "deterministic",
                    "ai_derived": False,
                }
            ],
            "required": True,
        },
        {
            "requirement_id": "delivery_confirmation",
            "title": "Delivery confirmation",
            "description": "System-generated from the carrier record and buyer confirmation.",
            "owner": "system",
            "kind": "delivery_confirmation",
            "source": "reference",
            "accepted_formats": [],
            "checks": [
                {
                    "check_id": "carrier_and_buyer_agree",
                    "description": "Carrier record and buyer confirmation agree.",
                    "operator": "exists",
                    "verification_method": "deterministic",
                    "ai_derived": False,
                }
            ],
            "required": True,
        },
    ]


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
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client


async def _funded(client) -> dict:
    body = await award(
        client, award_payload(requirements=requirement_catalog())
    )
    await accept(client, body)
    await approve(client, body)
    await fund_and_capture(client, body)
    return body


async def test_tracker_sync_is_idempotent():
    client = FakePayPalTracking()
    kwargs = dict(
        transaction_id="vf_1",
        capture_id="8MC585209K746392H",
        tracking_number="TEST-TRACK-001",
        carrier="OTHER",
        carrier_name_other="Verifund Sandbox Carrier",
        items=[{"sku": "sku01", "quantity": "1"}],
    )
    first = await client.sync(**kwargs)
    second = await client.sync(**kwargs)
    assert first == second == "8MC585209K746392H-TEST-TRACK-001"


def test_carrier_enum_and_other_fallback():
    assert normalize_carrier("UPS") == ("UPS", None)
    assert normalize_carrier("fedex") == ("FEDEX", None)
    assert normalize_carrier("Northwind Logistics") == (
        "OTHER",
        "Northwind Logistics",
    )
    assert normalize_carrier("") == ("OTHER", None)


async def test_http_client_tracks_and_reads_back():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 300})
        if request.url.path.endswith("/track"):
            return httpx.Response(200, json={"tracker_id": "cap-1-TRK-1"})
        if request.url.path.startswith("/v1/shipping/trackers/"):
            return httpx.Response(
                200,
                json={"tracker_id": "cap-1-TRK-1", "status": "DELIVERED"},
            )
        return httpx.Response(404, json={})

    tracking = PayPalTrackingHttpClient(
        base_url="https://api-m.sandbox.paypal.com",
        client_id="client",
        client_secret="secret",
        transport=httpx.MockTransport(handler),
        clock=lambda: NOW,
    )
    tracker_id = await tracking.sync(
        transaction_id="vf_1",
        capture_id="cap-1",
        tracking_number="TRK-1",
        carrier="Northwind Logistics",
        items=[{"sku": "NC-700", "quantity": "12"}],
    )
    assert tracker_id == "cap-1-TRK-1"
    track_call = calls[-1]
    payload = json.loads(track_call.content)
    assert track_call.url.path == "/v2/checkout/orders/cap-1/track"
    assert payload["carrier"] == "OTHER"
    assert payload["carrier_name_other"] == "Northwind Logistics"
    assert payload["notify_payer"] is True
    assert payload["items"] == [{"sku": "NC-700", "quantity": "12"}]

    fetched = await tracking.fetch("cap-1-TRK-1")
    assert fetched == {
        "tracker_id": "cap-1-TRK-1",
        "last_status": "DELIVERED",
        "status_source": "merchant_push",
    }


async def test_shipping_reference_registers_tracker(client):
    body = await _funded(client)
    txid = body["transaction_id"]
    response = await upload_reference(client, body, "shipping", "TRK-1")
    assert response.status_code == 201, response.text

    app = client._transport.app
    record = await app.state.repo.get_transaction(txid)
    capture_id = (record.funding or {})["capture_id"]
    assert record.tracker["tracker_id"] == f"{capture_id}-TRK-1"
    assert record.tracker["status_source"] == "merchant_push"
    assert record.tracker["last_status"] == "SHIPPED"

    async with app.state.repo.engine.connect() as conn:
        rows = (
            await conn.execute(
                select(app.state.repo.audit_log).where(
                    app.state.repo.audit_log.c.transaction_id == txid,
                    app.state.repo.audit_log.c.action
                    == "paypal.tracker_registered",
                )
            )
        ).all()
    assert len(rows) == 1


async def test_tracker_is_visible_in_dispute_context(client):
    body = await _funded(client)
    txid = body["transaction_id"]
    assert (await upload_reference(client, body, "shipping", "TRK-1")).status_code == 201

    app = client._transport.app
    record = await app.state.repo.get_transaction(txid)
    tracker_id = record.tracker["tracker_id"]

    # A tracker read does not affect verification or release; it is display data.
    context = await app.state.service.dispute_decision_context(txid)
    assert context["tracker"]["tracker_id"] == tracker_id
    assert context["tracker"]["status_source"] == "merchant_push"

    app.state.tracking.set_status(tracker_id, "DELIVERED")
    refreshed = await app.state.service.refresh_tracker(txid)
    assert refreshed["last_status"] == "DELIVERED"
    context = await client.get(
        f"/ops/transactions/{txid}/dispute-context", headers=OPS
    )
    assert context.status_code == 200, context.text
    assert context.json()["tracker"]["last_status"] == "DELIVERED"


async def test_tracker_refresh_failure_is_non_fatal(client):
    body = await _funded(client)
    txid = body["transaction_id"]
    assert (await upload_reference(client, body, "shipping", "TRK-1")).status_code == 201

    app = client._transport.app

    class Broken(FakePayPalTracking):
        async def fetch(self, tracker_id: str):
            raise RuntimeError("paypal down")

    app.state.service.tracking = Broken()
    tracker = await app.state.service.refresh_tracker(txid)
    assert tracker["tracker_id"].endswith("-TRK-1")
