from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import update
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import (
    NOW,
    OPS,
    accept,
    approve,
    award,
    fund_and_capture,
    purchase_order,
    upload_json,
)
from tests.support.seller_auth import clerk_seller_headers, seed_seller_profile


async def seller_headers(api):
    app = api._transport.app
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


async def settle_scans_and_verify(api, transaction_id: str) -> None:
    """Stand-in for the scan-settlement sweep (Milestone D, Task 20a): flip
    pending scans to clean and re-run verification."""
    app = api._transport.app
    repo = app.state.repo
    async with repo.transaction() as conn:
        await conn.execute(
            update(repo.evidence)
            .where(repo.evidence.c.transaction_id == transaction_id)
            .values(scan_status="clean")
        )
    await app.state.service.verify(transaction_id, actor="system")


async def seed_system_delivery(api, award_body: dict, delivered_at: datetime) -> None:
    """Stand-in for CONFIRM_DELIVERY (Milestone B, Task 13): the control plane
    normally creates this record from the buyer/carrier attestation. Until it
    lands, seed the same system-generated, buyer-attributed artifact directly."""
    app = api._transport.app
    service = app.state.service
    repo = app.state.repo
    payload = json.dumps(
        {"delivered_at": delivered_at.isoformat(), "recipient": "Demo Buyer"}
    ).encode()
    item = await service.evidence_store.put(
        transaction_id=award_body["transaction_id"],
        seller_id="northwind-audio",
        kind="delivery_confirmation",
        media_type="application/json",
        original_filename="delivery.json",
        data=payload,
        note=None,
        captured_at=None,
    )
    item = item.model_copy(
        update={
            "requirement_id": "delivery_confirmation",
            "origin": "system",
            "attributed_to": "demo-buyer",
            "scan_status": "clean",
            "agreement_version": award_body["agreement_version"],
        }
    )
    async with repo.transaction() as conn:
        await repo.add_evidence(
            conn, award_body["transaction_id"], "northwind-audio", item
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
    headers = await seller_headers(api)
    uploaded = await upload_json(
        api, award_body, "shipment_manifest", manifest, headers=headers
    )
    assert uploaded.status_code == 201, uploaded.text
    state = (await api.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "VERIFICATION_PENDING"

    # The delivery confirmation is system-owned: the seller cannot
    # create it (Task 9a); the control plane does (stand-in for Task 13).
    rejected = await upload_json(
        api,
        award_body,
        "delivery_confirmation",
        {"delivered_at": (NOW - timedelta(hours=30)).isoformat()},
        headers=headers,
    )
    assert rejected.status_code == 422, rejected.text
    await seed_system_delivery(api, award_body, NOW - timedelta(hours=30))

    invoice = {
        "invoice_id": "INV-1",
        "seller_id": "northwind-audio",
        "total_cents": 123400,
        "currency": "USD",
        "line_items": [{"sku": "NC-700", "quantity": 12, "unit_price_cents": 10000}],
    }
    uploaded = await upload_json(api, award_body, "invoice", invoice, headers=headers)
    assert uploaded.status_code == 201, uploaded.text
    # Scans settle asynchronously in production (Task 20a); settle here.
    await settle_scans_and_verify(api, txid)
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
    # OPS token issuance still exists for agreement/buyer flows, but
    # migrated /seller/* data routes no longer accept bearer seller tokens.
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

    headers = await seller_headers(api)
    current = await api.get(
        f"/seller/transactions/{txid}",
        headers=headers,
    )
    assert current.status_code == 200, current.text

    stale = await api.get(
        f"/seller/transactions/{txid}",
        headers={"authorization": f"Bearer {old_token}"},
    )
    assert stale.status_code == 401

    revoked = await api.post(
        f"/transactions/{txid}/seller-token/revoke", headers=OPS
    )
    assert revoked.status_code == 200
    legacy = await api.get(
        f"/seller/transactions/{txid}",
        headers={"authorization": f"Bearer {new_token}"},
    )
    assert legacy.status_code == 401
