from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
import pytest
from commerce_core.binding import binding_from_award, offer_hash
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops", "x-verifund-actor": "buyer-agent"}


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
                "warranty_addon_cents": 0,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "offer_round": 1,
        "inspection_period_hours": 24,
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


async def award(client) -> dict:
    response = await client.post(
        "/awards",
        json=award_payload(),
        headers={**OPS, "idempotency-key": "award:run-1:offer-1"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def accept(client, award_body: dict) -> None:
    response = await client.post(
        f"/transactions/{award_body['transaction_id']}/accept",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": award_body["agreement_hash"],
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
            "agreement_version": award_body["agreement_version"],
        },
        headers=OPS,
    )
    assert response.status_code == 200, response.text
    # buyer approval via agreement token
    agr_id = award_body["agreement"]["agreement_id"]
    token_resp = await client.post(
        f"/agreements/{agr_id}/approval-token",
        headers={**OPS, "idempotency-key": "tok:run-1"},
    )
    token = token_resp.json()["token"]
    await client.post(
        f"/agreements/{agr_id}/buyer-decision",
        json={
            "agreement_version": award_body["agreement_version"],
            "agreement_hash": award_body["agreement_hash"],
            "decision": "APPROVE",
            "note": "",
            "idempotency_key": "bd:run-1",
        },
        headers={**OPS, "idempotency-key": "bd:run-1", "X-Approval-Token": token},
    )


async def approve(client, award_body: dict) -> None:
    response = await client.post(
        f"/transactions/{award_body['transaction_id']}/approve",
        json={
            "approval_id": "apr-1",
            "approved_by": "demo-reviewer",
            "approved_at": NOW.isoformat(),
            "note": "approved",
            "agreement_hash": award_body["agreement_hash"],
            "agreement_version": award_body["agreement_version"],
        },
        headers=OPS,
    )
    assert response.status_code == 200, response.text


async def fund_and_capture(client, award_body: dict) -> None:
    txid = award_body["transaction_id"]
    funded = await client.post(
        f"/transactions/{txid}/fund",
        json={
            "agreement_hash": award_body["agreement_hash"],
            "agreement_version": award_body["agreement_version"],
            "return_url": "http://127.0.0.1:3000/runs/run-1",
            "cancel_url": "http://127.0.0.1:3000/runs/run-1",
        },
        headers={**OPS, "idempotency-key": f"fund:{txid}"},
    )
    assert funded.status_code == 200, funded.text
    checkout_url = funded.json()["checkout_url"]
    path = urlsplit(checkout_url).path
    page = await client.get(path)
    assert page.status_code == 200
    approved = await client.post(
        path, data={"action": "approve"}, follow_redirects=False
    )
    assert approved.status_code == 303


def purchase_order(award_body: dict) -> dict:
    return {
        "agreement_hash": award_body["agreement_hash"],
        "seller_order_id": "MM-1",
        "offer_id": "offer-1",
        "quantity": 12,
        "total_cents": 123400,
        "currency": "USD",
        "tracking_number": "TRK-1",
        "carrier": "Northwind Logistics",
        "reserved_at": NOW.isoformat(),
        "eta": (NOW + timedelta(days=7)).isoformat(),
        "line_items": [
            {
                "sku": "NC-700",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
    }


async def upload(
    client, award_body: dict, kind: str, payload: dict
) -> httpx.Response:
    return await client.post(
        f"/seller/transactions/{award_body['transaction_id']}/evidence",
        headers={
            "authorization": f"Bearer {award_body['seller_token']}"
        },
        data={"kind": kind},
        files={
            "file": (
                f"{kind}.json",
                json.dumps(payload).encode(),
                "application/json",
            )
        },
    )


async def test_fake_lifecycle_reaches_released_with_receipt(api):
    award_body = await award(api)
    txid = award_body["transaction_id"]
    await accept(api, award_body)
    await approve(api, award_body)
    await fund_and_capture(api, award_body)

    state = (await api.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "FUNDED"

    reported = await api.post(
        f"/transactions/{txid}/purchase-order",
        json=purchase_order(award_body),
        headers={**OPS, "idempotency-key": f"po:{txid}"},
    )
    assert reported.status_code == 200, reported.text
    assert reported.json()["state"] == "FULFILLMENT_PENDING"

    manifest = {
        "tracking_number": "TRK-1",
        "carrier": "Northwind Logistics",
        "shipped_at": (NOW - timedelta(days=2)).isoformat(),
        "seller_id": "northwind-audio",
        "agreement_hash": award_body["agreement_hash"],
        "line_items": [{"sku": "NC-700", "quantity": 12}],
    }
    uploaded = await upload(api, award_body, "shipment_manifest", manifest)
    assert uploaded.status_code == 201, uploaded.text
    state = (await api.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "VERIFICATION_PENDING"

    delivery = {
        "delivered_at": (NOW - timedelta(hours=30)).isoformat(),
        "recipient": "Demo Buyer",
    }
    uploaded = await upload(api, award_body, "delivery_confirmation", delivery)
    assert uploaded.status_code == 201, uploaded.text

    invoice = {
        "invoice_id": "INV-1",
        "seller_id": "northwind-audio",
        "total_cents": 123400,
        "currency": "USD",
        "line_items": [{"sku": "NC-700", "quantity": 12, "unit_price_cents": 10000}],
    }
    uploaded = await upload(api, award_body, "invoice", invoice)
    assert uploaded.status_code == 201, uploaded.text
    state = (await api.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "RELEASE_PERMITTED"
    assert state["verification"]["status"] == "passed"
    requirement_ids = [r["requirement_id"] for r in state["verification"]["requirements"]]
    assert requirement_ids == ["shipment_manifest", "delivery_confirmation", "invoice"]
    assert [r["requirement_id"] for r in state["evidence"]["requirements"]] == requirement_ids
    assert all(r["status"] == "pass" for r in state["verification"]["requirements"])

    released = await api.post(
        f"/transactions/{txid}/release",
        json={
            "released_by": "demo-reviewer",
            "note": "Evidence verified",
            "override": False,
        },
        headers=OPS,
    )
    assert released.status_code == 200, released.text
    assert released.json()["state"] == "RELEASED"
    assert released.json()["payout"]["status"] == "SUCCESS"

    receipt = await api.get(f"/transactions/{txid}/receipt", headers=OPS)
    assert receipt.status_code == 200, receipt.text
    body = receipt.json()
    assert body["verified"] is True
    assert body["payload"]["transaction_id"] == txid
    assert body["payload"]["payout_item_id"] == f"item_{txid}"
    assert len(body["payload"]["evidence_hashes"]) == 3

    state = (await api.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["receipt_available"] is True

    repo = api._transport.app.state.repo  # type: ignore[attr-defined]
    balances = await repo.ledger_balances(txid)
    assert balances == {
        "held_funds": 0,
        "platform_cash": 123400,
        "seller_paid": 123400,
    }


async def test_purchase_order_mismatch_is_rejected(api):
    award_body = await award(api)
    txid = award_body["transaction_id"]
    await accept(api, award_body)
    await approve(api, award_body)
    await fund_and_capture(api, award_body)

    body = purchase_order(award_body)
    body["total_cents"] = 120000
    response = await api.post(
        f"/transactions/{txid}/purchase-order",
        json=body,
        headers={**OPS, "idempotency-key": f"po:{txid}"},
    )
    assert response.status_code == 409
    state = (await api.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "FUNDED"


async def test_release_override_requires_note_and_allows_manual_flag(api):
    award_body = await award(api)
    txid = award_body["transaction_id"]
    await accept(api, award_body)
    await approve(api, award_body)
    await fund_and_capture(api, award_body)

    flagged = await api.post(
        f"/transactions/{txid}/flag-review",
        json={"reason": "manual_check", "note": "look closer"},
        headers={**OPS, "x-verifund-actor": "console:reviewer"},
    )
    assert flagged.status_code == 200, flagged.text
    assert flagged.json()["state"] == "REVIEW_REQUIRED"
    assert flagged.json()["verification"]["override_allowed"] is True

    refused = await api.post(
        f"/transactions/{txid}/release",
        json={
            "released_by": "demo-reviewer",
            "note": "",
            "override": False,
        },
        headers={**OPS, "x-verifund-actor": "console:reviewer"},
    )
    assert refused.status_code == 403

    released = await api.post(
        f"/transactions/{txid}/release",
        json={
            "released_by": "demo-reviewer",
            "note": "checked evidence manually",
            "override": True,
        },
        headers={**OPS, "x-verifund-actor": "console:reviewer"},
    )
    assert released.status_code == 200, released.text
    assert released.json()["state"] == "RELEASED"


async def test_seller_token_reissue_revokes_old_token(api):
    award_body = await award(api)
    txid = award_body["transaction_id"]
    old_token = award_body["seller_token"]

    reissued = await api.post(
        f"/transactions/{txid}/seller-token",
        json={
            "run_id": "run-1",
            "transaction_id": txid,
            "seller_id": "northwind-audio",
            "purpose": "purchase_order",
        },
        headers=OPS,
    )
    assert reissued.status_code == 200, reissued.text
    new_token = reissued.json()["seller_token"]
    assert new_token != old_token

    stale = await api.get(
        f"/seller/transactions/{txid}",
        headers={"authorization": f"Bearer {old_token}"},
    )
    assert stale.status_code == 401

    current = await api.get(
        f"/seller/transactions/{txid}",
        headers={"authorization": f"Bearer {new_token}"},
    )
    assert current.status_code == 200

    revoked = await api.post(
        f"/transactions/{txid}/seller-token/revoke", headers=OPS
    )
    assert revoked.status_code == 200
    gone = await api.get(
        f"/seller/transactions/{txid}",
        headers={"authorization": f"Bearer {new_token}"},
    )
    assert gone.status_code == 401
