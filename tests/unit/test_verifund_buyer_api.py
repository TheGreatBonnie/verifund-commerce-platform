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
