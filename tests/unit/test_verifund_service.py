from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from commerce_core.binding import binding_from_award, offer_hash
from verifund_contracts import AgreementProjection
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops"}
ACTOR = {"x-verifund-actor": "buyer-agent"}
HASH = "a" * 64


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


async def create_award(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/awards",
        json=award_payload(),
        headers={
            **OPS,
            **ACTOR,
            "idempotency-key": "award:run-1:offer-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_ops_auth_is_required(api):
    response = await api.get("/transactions")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_award_creates_transaction_token_and_agreement(api):
    body = await create_award(api)
    assert body["transaction_id"].startswith("vf_")
    assert body["state"] == "AWARDED"
    assert len(body["agreement_hash"]) == 64
    assert body["seller_token"].startswith("v1.")
    assert body["expires_at"].startswith("2026-10-30T12:00:00")
    assert body["agreement_version"] == 1
    assert body["agreement"]["agreement_version"] == 1
    assert body["agreement"]["transaction_id"] == body["transaction_id"]
    assert body["agreement"]["amount_cents"] == 123400
    assert body["agreement"]["agreement_hash"] == body["agreement_hash"]


async def test_award_projection_hash_matches_the_canonical_terms(api):
    body = await create_award(api)
    projection = AgreementProjection.model_validate(body["agreement"])
    assert projection.recompute_hash() == body["agreement_hash"]


async def test_award_is_idempotent(api):
    first = await create_award(api)
    second = await create_award(api)
    assert first["transaction_id"] == second["transaction_id"]
    txns = (await api.get("/transactions", headers=OPS)).json()
    assert len(txns) == 1


async def test_accept_requires_hash_and_seller(api):
    award = await create_award(api)
    bad = await api.post(
        f"/transactions/{award['transaction_id']}/accept",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": HASH,
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
        },
        headers={**OPS, **ACTOR},
    )
    assert bad.status_code == 409
    assert bad.json()["error"]["code"] == "hash_mismatch"

    buyer_review = await api.post(
        f"/transactions/{award['transaction_id']}/buyer-review",
        json={
            "buyer_id": "demo-buyer",
            "agreement_version": 1,
            "agreement_hash": award["agreement_hash"],
            "decision": "accepted",
            "buyer_task_id": "buyer-review-task-1",
            "reviewed_at": NOW.isoformat(),
        },
        headers={**OPS, **ACTOR, "idempotency-key": "buyer-review:run-1:v1"},
    )
    assert buyer_review.status_code == 200
    assert buyer_review.json()["state"] == "AWARDED"

    accepted = await api.post(
        f"/transactions/{award['transaction_id']}/accept",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": award["agreement_hash"],
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
        },
        headers={**OPS, **ACTOR},
    )
    assert accepted.status_code == 200
    assert accepted.json()["state"] == "AWARDED"
    assert accepted.json()["buyer_agent_review"]["status"] == "accepted"
    assert accepted.json()["seller_decision"]["status"] == "accepted"

    replay = await api.post(
        f"/transactions/{award['transaction_id']}/accept",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": award["agreement_hash"],
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
        },
        headers={**OPS, **ACTOR},
    )
    assert replay.status_code == 200
    assert replay.json()["state"] == "AWARDED"


async def test_rejection_cancels_without_ledger(api):
    award = await create_award(api)
    response = await api.post(
        f"/transactions/{award['transaction_id']}/reject",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": award["agreement_hash"],
            "reason_code": "out_of_stock",
            "note": "SKU unavailable",
            "seller_task_id": "task-1",
            "rejected_at": NOW.isoformat(),
        },
        headers={**OPS, **ACTOR, "idempotency-key": "reject:vf_1:task-1"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "CANCELED"
    assert body["cancellation"]["reason_code"] == "seller_rejected"
    events = (
        await api.get(f"/transactions/{award['transaction_id']}/events", headers=OPS)
    ).json()
    assert [event["type"] for event in events][-2:] == [
        "seller_rejected",
        "canceled",
    ]


async def test_approval_binds_hash_and_cancel_before_capture(api):
    award = await create_award(api)
    txid = award["transaction_id"]
    accepted = {
        "seller_id": "northwind-audio",
        "agreement_hash": award["agreement_hash"],
        "accepted_total_cents": 123400,
        "seller_task_id": "task-1",
        "accepted_at": NOW.isoformat(),
    }
    await api.post(f"/transactions/{txid}/accept", json=accepted, headers={**OPS, **ACTOR})
    # buyer approval via BuyerPrincipal (internal service auth)
    agr_id = award["agreement"]["agreement_id"]
    from tests.support.buyer_auth import internal_buyer_headers, seed_buyer_profile

    api._transport.app = api._transport.app
    if not getattr(api._transport.app.state.settings, "buyer_settlement_internal_token", None):
        api._transport.app.state.settings.buyer_settlement_internal_token = "buyer-secret"
    await seed_buyer_profile(api._transport.app, buyer_id=award.get("buyer_id", "demo-buyer"))
    _buyer_headers = internal_buyer_headers(
        token="buyer-secret", clerk_user_id="user_buyer", buyer_id=award.get("buyer_id", "demo-buyer")
    )
    await api.post(
        f"/agreements/{agr_id}/buyer-decision",
        json={
            "agreement_version": award["agreement_version"],
            "agreement_hash": award["agreement_hash"],
            "decision": "APPROVE",
            "note": "",
            "idempotency_key": "bd:1",
        },
        headers={**_buyer_headers, "idempotency-key": "bd:1"},
    )
    approved = await api.post(
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
    assert approved.status_code == 200
    assert approved.json()["state"] == "AGREED"
    assert approved.json()["approval"]["approved_by"] == "demo-reviewer"

    canceled = await api.post(
        f"/transactions/{txid}/cancel",
        json={"reason_code": "buyer_rejected", "note": "not acceptable"},
        headers={**OPS, "x-verifund-actor": "console:reviewer"},
    )
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["state"] == "CANCELED"
    assert canceled.json()["cancellation"]["reason_code"] == "buyer_rejected"
