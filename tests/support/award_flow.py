"""Shared HTTP-level helpers for the Verifund control-plane lifecycle.

These exercise the fake-provider control plane end to end (award -> accept ->
approve -> fund -> capture) and the requirement-addressed evidence upload.
Used by the lifecycle integration tests and the upload unit tests.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from commerce_core.binding import binding_from_award, offer_hash

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops", "x-verifund-actor": "buyer-agent"}


def award_payload(**overrides: Any) -> dict:
    payload: dict[str, Any] = {
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
        "offer_valid_until": (NOW + timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z"
        ),
        "inspection_period_hours": 24,
    }
    payload.update(overrides)
    payload["offer_hash"] = offer_hash(binding_from_award(payload))
    return payload


async def award(client: httpx.AsyncClient, payload: dict | None = None) -> dict:
    body = payload or award_payload()
    response = await client.post(
        "/awards",
        json=body,
        headers={
            **OPS,
            "idempotency-key": f"award:{body['run_id']}:{body['offer_id']}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def accept(client: httpx.AsyncClient, award_body: dict, *, seller_id: str = "northwind-audio") -> None:
    response = await client.post(
        f"/transactions/{award_body['transaction_id']}/accept",
        json={
            "seller_id": seller_id,
            "agreement_hash": award_body["agreement_hash"],
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
            "agreement_version": award_body["agreement_version"],
        },
        headers=OPS,
    )
    assert response.status_code == 200, response.text
    agr_id = award_body["agreement"]["agreement_id"]
    key = award_body["agreement_hash"][:16]
    from tests.support.buyer_auth import internal_buyer_headers, seed_buyer_profile

    app = getattr(client._transport, "app")
    if not getattr(app.state.settings, "buyer_settlement_internal_token", None):
        app.state.settings.buyer_settlement_internal_token = "buyer-secret"
    await seed_buyer_profile(app, buyer_id=award_body.get("buyer_id", "demo-buyer"))
    buyer_headers = internal_buyer_headers(
        token="buyer-secret", clerk_user_id="user_buyer", buyer_id=award_body.get("buyer_id", "demo-buyer")
    )
    resp = await client.post(
        f"/agreements/{agr_id}/buyer-decision",
        json={
            "agreement_version": award_body["agreement_version"],
            "agreement_hash": award_body["agreement_hash"],
            "decision": "APPROVE",
            "note": "",
            "idempotency_key": f"bd:{key}",
        },
        headers={**buyer_headers, "idempotency-key": f"bd:{key}"},
    )
    assert resp.status_code == 200, resp.text


async def approve(client: httpx.AsyncClient, award_body: dict) -> None:
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


async def fund_and_capture(client: httpx.AsyncClient, award_body: dict) -> None:
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


def seller_headers(award_body: dict, *, headers: dict[str, str] | None = None) -> dict[str, str]:
    """Legacy bearer seller-token headers.

    Deprecated for migrated ``/seller/*`` routes, which now require Clerk
    (console) or internal service auth (settlement); see
    ``tests.support.seller_auth``. Retained only for agreement-era helpers.
    """
    if headers is not None:
        return headers
    return {"authorization": f"Bearer {award_body['seller_token']}"}


async def upload_file(
    client: httpx.AsyncClient,
    award_body: dict,
    requirement_id: str,
    *,
    data: bytes,
    filename: str,
    media_type: str,
    captured_at: datetime | None = None,
    agreement_version: int | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    form: dict[str, str] = {"requirement_id": requirement_id}
    if captured_at is not None:
        form["captured_at"] = captured_at.isoformat().replace("+00:00", "Z")
    if agreement_version is not None:
        form["agreement_version"] = str(agreement_version)
    return await client.post(
        f"/seller/transactions/{award_body['transaction_id']}/evidence",
        headers=seller_headers(award_body, headers=headers),
        data=form,
        files={"file": (filename, data, media_type)},
    )


async def upload_json(
    client: httpx.AsyncClient,
    award_body: dict,
    requirement_id: str,
    payload: dict,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return await upload_file(
        client,
        award_body,
        requirement_id,
        data=json.dumps(payload).encode(),
        filename=f"{requirement_id}.json",
        media_type="application/json",
        headers=headers,
    )


async def upload_reference(
    client: httpx.AsyncClient,
    award_body: dict,
    requirement_id: str,
    reference: str,
    reference_type: str = "tracking",
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.post(
        f"/seller/transactions/{award_body['transaction_id']}/evidence",
        headers=seller_headers(award_body, headers=headers),
        data={
            "requirement_id": requirement_id,
            "reference": reference,
            "reference_type": reference_type,
        },
    )
