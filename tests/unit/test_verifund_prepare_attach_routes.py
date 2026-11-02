from __future__ import annotations

import httpx
import pytest
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.verifund_control import NOW, OPS, agree, create_award


@pytest.fixture
async def ctx(tmp_path):
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
            yield client, app.state.service


async def test_prepare_route_requires_the_ops_token(ctx):
    client, _ = ctx
    award = await create_award(client)

    response = await client.post(
        f"/transactions/{award['transaction_id']}/funding/prepare"
    )

    assert response.status_code == 401


async def test_prepare_route_returns_the_funding_session(ctx):
    client, _ = ctx
    award = await agree(client)

    response = await client.post(
        f"/transactions/{award['transaction_id']}/funding/prepare", headers=OPS
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transaction_id"] == award["transaction_id"]
    assert body["amount_cents"] == 123400
    assert body["currency"] == "USD"
    assert body["order_attempt"] == 0
    assert body["provider_order_id"] is None


async def test_prepare_route_surfaces_an_invalid_state(ctx):
    client, _ = ctx
    award = await create_award(client)

    response = await client.post(
        f"/transactions/{award['transaction_id']}/funding/prepare", headers=OPS
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"


async def test_attach_route_requires_the_ops_token(ctx):
    client, _ = ctx
    award = await create_award(client)

    response = await client.post(
        f"/transactions/{award['transaction_id']}/funding/attach-order",
        json={"order_id": "EMBEDDED-ORDER-1"},
    )

    assert response.status_code == 401


async def test_attach_route_requires_an_order_id(ctx):
    client, _ = ctx
    award = await create_award(client)

    response = await client.post(
        f"/transactions/{award['transaction_id']}/funding/attach-order",
        json={"order_id": ""},
        headers=OPS,
    )

    assert response.status_code == 422


async def test_attach_route_starts_funding(ctx):
    client, _ = ctx
    award = await agree(client)
    txid = award["transaction_id"]
    await client.post(f"/transactions/{txid}/funding/prepare", headers=OPS)

    response = await client.post(
        f"/transactions/{txid}/funding/attach-order",
        json={"order_id": "EMBEDDED-ORDER-1"},
        headers=OPS,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "FUNDING_PENDING"
    assert body["funding"]["provider_order_id"] == "EMBEDDED-ORDER-1"


async def test_attach_route_surfaces_a_conflict(ctx):
    client, service = ctx
    award = await agree(client)
    txid = award["transaction_id"]
    await client.post(f"/transactions/{txid}/funding/prepare", headers=OPS)
    await client.post(
        f"/transactions/{txid}/funding/attach-order",
        json={"order_id": "EMBEDDED-ORDER-1"},
        headers=OPS,
    )
    async with service.repo.transaction() as conn:
        await service.repo.save_fake_order(
            conn,
            order_id="EMBEDDED-ORDER-1",
            transaction_id=txid,
            status="CREATED",
            amount_cents=123400,
            currency="USD",
            payer_action_url=None,
            raw={"id": "EMBEDDED-ORDER-1", "status": "CREATED"},
        )

    response = await client.post(
        f"/transactions/{txid}/funding/attach-order",
        json={"order_id": "EMBEDDED-ORDER-2"},
        headers=OPS,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
