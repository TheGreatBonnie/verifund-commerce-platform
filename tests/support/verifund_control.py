from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from commerce_core.binding import binding_from_award, offer_hash

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops"}
ACTOR = {"x-verifund-actor": "buyer-agent"}


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
        "offer_valid_until": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    payload["offer_hash"] = offer_hash(binding_from_award(payload))
    return payload


async def create_award(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/awards",
        json=award_payload(),
        headers={**OPS, **ACTOR, "idempotency-key": "award:run-1:offer-1"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def agree(client: httpx.AsyncClient, award: dict | None = None) -> dict:
    award = award or await create_award(client)
    txid = award["transaction_id"]
    await client.post(
        f"/transactions/{txid}/accept",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": award["agreement_hash"],
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
        },
        headers={**OPS, **ACTOR},
    )
    agreement_id = award["agreement"]["agreement_id"]
    token = (
        await client.post(
            f"/agreements/{agreement_id}/approval-token",
            headers={**OPS, **ACTOR, "idempotency-key": "tok:1"},
        )
    ).json()["token"]
    await client.post(
        f"/agreements/{agreement_id}/buyer-decision",
        json={
            "agreement_version": award["agreement_version"],
            "agreement_hash": award["agreement_hash"],
            "decision": "APPROVE",
            "note": "",
            "idempotency_key": "bd:1",
        },
        headers={**OPS, **ACTOR, "idempotency-key": "bd:1", "X-Approval-Token": token},
    )
    approved = await client.post(
        f"/transactions/{txid}/approve",
        json={
            "approval_id": "apr-1",
            "approved_by": "demo-reviewer",
            "approved_at": NOW.isoformat(),
            "note": "approved",
            "agreement_hash": award["agreement_hash"],
            "agreement_version": award["agreement_version"],
        },
        headers={**OPS, **ACTOR},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()
