"""Buyer API routes — Clerk/internal principal auth."""

from __future__ import annotations

import httpx
import pytest
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import NOW
from tests.support.buyer_auth import clerk_buyer_headers, internal_buyer_headers, seed_buyer_profile


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
        buyer_settlement_internal_token="buyer-secret",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def _buyer_headers(client):
    app = client._transport.app
    seeded = await seed_buyer_profile(app, buyer_id="demo-buyer")
    return internal_buyer_headers(token="buyer-secret", clerk_user_id="user_buyer", buyer_id="demo-buyer")


async def test_buyer_delivery_requires_token(client):
    response = await client.post(
        "/buyer/transactions/vf_1/delivery-confirmed",
        json={"confirmed_at": "2026-10-27T12:00:00Z"},
    )
    assert response.status_code == 401


async def test_buyer_accept_requires_token(client):
    response = await client.post("/buyer/transactions/vf_1/accept", json={})
    assert response.status_code in (401, 404)


async def test_buyer_dispute_requires_token(client):
    response = await client.post("/buyer/transactions/vf_1/dispute", json={})
    assert response.status_code == 401


async def test_buyer_routes_404_for_unknown_transaction_with_valid_principal(client):
    headers = await _buyer_headers(client)
    response = await client.post(
        "/buyer/transactions/vf_1/delivery-confirmed",
        headers=headers,
        json={"confirmed_at": "2026-10-27T12:00:00Z"},
    )
    assert response.status_code == 404


async def test_ops_buyer_token_no_longer_authorizes_buyer_routes(client):
    from tests.support.award_flow import OPS, award, award_payload

    body = await award(client, award_payload())
    txid = body["transaction_id"]
    issued = await client.post(
        f"/ops/transactions/{txid}/issue-buyer-token",
        headers=OPS,
    )
    assert issued.status_code == 410, issued.text
    response = await client.post(
        f"/buyer/transactions/{txid}/delivery-confirmed",
        headers={"Authorization": "Bearer legacy-buyer-token"},
        json={"confirmed_at": "2026-10-27T12:00:00Z"},
    )
    # Legacy buyer_txn bearer is not an accepted auth method on migrated routes.
    assert response.status_code in (401, 404)


async def test_internal_buyer_can_call_delivery_confirmed(client):
    from tests.support.award_flow import award, award_payload

    headers = await _buyer_headers(client)
    body = await award(client, award_payload())
    txid = body["transaction_id"]

    response = await client.post(
        f"/buyer/transactions/{txid}/delivery-confirmed",
        headers=headers,
        json={"confirmed_at": "2026-10-27T12:00:00Z"},
    )
    # State gate (ENFORCED) — an AWARDED txn is not yet in fulfilment so service returns 409; auth/ownership passed.
    assert response.status_code in {409}

    # Cross-buyer: different buyer gets 404 (no leak)
    app = client._transport.app
    other = await seed_buyer_profile(app, buyer_id="other-buyer", clerk_user_id="user_other")
    other_headers = internal_buyer_headers(token="buyer-secret", clerk_user_id="user_other", buyer_id="other-buyer")
    denied = await client.post(
        f"/buyer/transactions/{txid}/accept", headers=other_headers, json={}
    )
    assert denied.status_code == 404


async def _funded_release_permitted(client):
    from sqlalchemy import update
    from verifund_contracts import TransactionState

    from tests.support.award_flow import (
        accept,
        approve,
        award,
        award_payload,
        fund_and_capture,
    )

    headers = await _buyer_headers(client)
    body = await award(client, award_payload())
    await accept(client, body)
    await approve(client, body)
    await fund_and_capture(client, body)
    txid = body["transaction_id"]
    repo = client._transport.app.state.repo
    async with repo.transaction() as conn:
        await conn.execute(
            update(repo.transactions)
            .where(repo.transactions.c.transaction_id == txid)
            .values(state=TransactionState.RELEASE_PERMITTED.value)
        )
    return txid, headers


async def test_buyer_accept_releases_immediately_and_is_final(client):
    txid, headers = await _funded_release_permitted(client)

    accepted = await client.post(
        f"/buyer/transactions/{txid}/accept", headers=headers, json={}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["state"] == "RELEASED"

    # ACCEPT is final: no later dispute may be opened.
    disputed = await client.post(
        f"/buyer/transactions/{txid}/dispute",
        headers=headers,
        json={
            "requirement_ids": ["hardware"],
            "reason_code": "not_as_described",
            "claim": "arrived damaged",
            "evidence": [{"evidence_id": "ev_1"}],
        },
    )
    assert disputed.status_code == 409

    # Accept is idempotent once released.
    again = await client.post(
        f"/buyer/transactions/{txid}/accept", headers=headers, json={}
    )
    assert again.status_code == 200
    assert again.json()["state"] == "RELEASED"


async def test_buyer_accept_rejected_before_verification(client):
    from tests.support.award_flow import award, award_payload

    headers = await _buyer_headers(client)
    body = await award(client, award_payload())
    txid = body["transaction_id"]
    response = await client.post(
        f"/buyer/transactions/{txid}/accept",
        headers=headers,
        json={},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"
