from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from commerce_core.binding import binding_from_award, offer_hash
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops", "x-verifund-actor": "buyer-agent"}
FAKE = {"x-verifund-fake-webhook": "dev-verifund-fake-webhook"}


def award_payload() -> dict:
    payload = {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "request_id": "rfq-1",
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
    payload["offer_hash"] = offer_hash(binding_from_award(payload))
    return payload


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


async def awaiting_capture(client) -> tuple[dict, str]:
    award = (
        await client.post(
            "/awards",
            json=award_payload(),
            headers={**OPS, "idempotency-key": "award:run-1:offer-1"},
        )
    ).json()
    txid = award["transaction_id"]
    await client.post(
        f"/transactions/{txid}/accept",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": award["agreement_hash"],
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
            "agreement_version": award["agreement_version"],
        },
        headers=OPS,
    )
    agr_id = award["agreement"]["agreement_id"]
    token_resp = await client.post(
        f"/agreements/{agr_id}/approval-token",
        headers={**OPS, "idempotency-key": "tok:run-1"},
    )
    token = token_resp.json()["token"]
    await client.post(
        f"/agreements/{agr_id}/buyer-decision",
        json={
            "agreement_version": award["agreement_version"],
            "agreement_hash": award["agreement_hash"],
            "decision": "APPROVE",
            "note": "",
            "idempotency_key": "bd:run-1",
        },
        headers={**OPS, "idempotency-key": "bd:run-1", "X-Approval-Token": token},
    )
    await client.post(
        f"/transactions/{txid}/approve",
        json={
            "approval_id": "apr-1",
            "approved_by": "demo-reviewer",
            "approved_at": NOW.isoformat(),
            "agreement_hash": award["agreement_hash"],
            "agreement_version": award["agreement_version"],
        },
        headers=OPS,
    )
    financed = await client.post(
        f"/transactions/{txid}/fund",
        json={
            "agreement_hash": award["agreement_hash"],
            "agreement_version": award["agreement_version"],
            "return_url": "http://127.0.0.1:3000/runs/run-1",
            "cancel_url": "http://127.0.0.1:3000/runs/run-1",
        },
        headers={**OPS, "idempotency-key": f"fund:{txid}"},
    )
    assert financed.status_code == 200, financed.text
    state = (
        await client.get(f"/transactions/{txid}/state", headers=OPS)
    ).json()
    return award, state["funding"]["provider_order_id"]


def capture_event(event_id: str, order_id: str) -> dict:
    return {
        "id": event_id,
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAP-1",
            "status": "COMPLETED",
            "amount": {"value": "1234.00", "currency_code": "USD"},
            "supplementary_data": {"related_ids": {"order_id": order_id}},
        },
    }


async def test_capture_webhook_funds_transaction(api):
    award, order_id = await awaiting_capture(api)
    response = await api.post(
        "/webhooks/paypal",
        json=capture_event("WH-1", order_id),
        headers=FAKE,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "processed"

    state = (
        await api.get(f"/transactions/{award['transaction_id']}/state", headers=OPS)
    ).json()
    assert state["state"] == "FUNDED"
    assert state["funding"]["capture_id"] == "CAP-1"

    repo = api._transport.app.state.repo  # type: ignore[attr-defined]
    balances = await repo.ledger_balances(award["transaction_id"])
    assert balances["held_funds"] == 123400

    stored = await repo.get_webhook_event("WH-1")
    assert stored["verified"] == 0
    assert stored["status"] == "processed"


async def test_duplicate_webhook_is_idempotent(api):
    award, order_id = await awaiting_capture(api)
    event = capture_event("WH-1", order_id)
    assert (await api.post("/webhooks/paypal", json=event, headers=FAKE)).status_code == 200
    duplicate = await api.post("/webhooks/paypal", json=event, headers=FAKE)
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"

    repo = api._transport.app.state.repo  # type: ignore[attr-defined]
    balances = await repo.ledger_balances(award["transaction_id"])
    assert balances["held_funds"] == 123400
    state = (
        await api.get(f"/transactions/{award['transaction_id']}/state", headers=OPS)
    ).json()
    assert state["funding"]["capture_id"] == "CAP-1"


async def test_fake_webhook_requires_test_secret(api):
    _, order_id = await awaiting_capture(api)
    response = await api.post(
        "/webhooks/paypal",
        json=capture_event("WH-1", order_id),
        headers={"x-verifund-fake-webhook": "wrong"},
    )
    assert response.status_code == 401


async def test_unknown_order_is_unmatched(api):
    response = await api.post(
        "/webhooks/paypal",
        json=capture_event("WH-2", "ORDER-DOES-NOT-EXIST"),
        headers=FAKE,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unmatched"

    repo = api._transport.app.state.repo  # type: ignore[attr-defined]
    stored = await repo.get_webhook_event("WH-2")
    assert stored["status"] == "unmatched"


async def test_unknown_event_type_is_ignored(api):
    response = await api.post(
        "/webhooks/paypal",
        json={
            "id": "WH-3",
            "event_type": "CHECKOUT.ORDER.COMPLETED",
            "resource": {"id": "ORDER-1"},
        },
        headers=FAKE,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"