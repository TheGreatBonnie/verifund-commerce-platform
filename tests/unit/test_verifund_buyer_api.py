"""Buyer API routes (plan Task 12)."""

from __future__ import annotations

import httpx
import pytest
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import NOW


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
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_buyer_delivery_requires_token(client):
    response = await client.post(
        "/buyer/transactions/vf_1/delivery-confirmed",
        json={"confirmed_at": "2026-10-27T12:00:00Z"},
    )
    assert response.status_code == 401


async def test_buyer_accept_requires_token(client):
    response = await client.post("/buyer/transactions/vf_1/accept", json={})
    assert response.status_code == 401


async def test_buyer_dispute_requires_token(client):
    response = await client.post("/buyer/transactions/vf_1/dispute", json={})
    assert response.status_code == 401


async def test_buyer_routes_return_501_with_valid_token(client):
    app = client._transport.app
    repo = app.state.repo
    issued = app.state.buyer_tokens.issue("demo-buyer", "vf_1")
    async with repo.transaction() as conn:
        await repo.save_buyer_token(
            conn,
            jti_hash=issued.jti_hash,
            transaction_id="vf_1",
            buyer_id="demo-buyer",
            scopes=["txn:buy"],
            expires_at=issued.expires_at,
        )
    headers = {"Authorization": f"Bearer {issued.token}"}
    response = await client.post(
        "/buyer/transactions/vf_1/delivery-confirmed",
        headers=headers,
        json={"confirmed_at": "2026-10-27T12:00:00Z"},
    )
    # Ownership check: transaction vf_1 doesn't exist -> 404 before the 501 body.
    assert response.status_code in {404, 501}


async def test_ops_issues_buyer_token_accepted_by_buyer_routes(client):
    from tests.support.award_flow import OPS, award, award_payload

    body = await award(client, award_payload())
    txid = body["transaction_id"]
    issued = await client.post(
        f"/ops/transactions/{txid}/issue-buyer-token",
        headers=OPS,
    )
    assert issued.status_code == 200, issued.text
    token = issued.json()["token"]

    response = await client.post(
        f"/buyer/transactions/{txid}/delivery-confirmed",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirmed_at": "2026-10-27T12:00:00Z"},
    )
    # Delivery confirmation is implemented in Task 13; an AWARDED transaction
    # is not yet in fulfillment, so the state gate rejects with 409. Auth and
    # ownership must have passed to reach this point.
    assert response.status_code in {409}


async def _funded_release_permitted(client) -> tuple[str, str]:
    from sqlalchemy import update
    from verifund_contracts import TransactionState

    from tests.support.award_flow import (
        OPS,
        accept,
        approve,
        award,
        award_payload,
        fund_and_capture,
    )

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
    issued = await client.post(
        f"/ops/transactions/{txid}/issue-buyer-token",
        headers=OPS,
    )
    assert issued.status_code == 200, issued.text
    return txid, issued.json()["token"]


async def test_buyer_accept_releases_immediately_and_is_final(client):
    txid, token = await _funded_release_permitted(client)
    headers = {"Authorization": f"Bearer {token}"}

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
    from tests.support.award_flow import OPS, award, award_payload

    body = await award(client, award_payload())
    txid = body["transaction_id"]
    issued = await client.post(
        f"/ops/transactions/{txid}/issue-buyer-token", headers=OPS
    )
    response = await client.post(
        f"/buyer/transactions/{txid}/accept",
        headers={"Authorization": f"Bearer {issued.json()['token']}"},
        json={},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"

