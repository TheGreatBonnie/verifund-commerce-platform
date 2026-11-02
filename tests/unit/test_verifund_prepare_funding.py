from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from commerce_core.binding import binding_from_award, offer_hash
from verifund_contracts import FundRequest
from verifund_control_plane.app import create_app
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
DEADLINE = "2026-10-28T12:00:00Z"
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


async def create_award(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/awards",
        json=award_payload(),
        headers={**OPS, **ACTOR, "idempotency-key": "award:run-1:offer-1"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def agree(client: httpx.AsyncClient) -> dict:
    award = await create_award(client)
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
    assert approved.json()["state"] == "AGREED"
    return approved.json()


async def patch_transaction(service, transaction_id: str, changes: dict) -> None:
    async with service.repo.transaction() as conn:
        current = await service.repo.get_transaction(transaction_id, conn)
        await service.repo.update_transaction(
            conn,
            transaction_id,
            expected_version=current.version,
            changes=changes,
        )


async def test_prepare_pins_the_deadline_without_transitioning(ctx):
    client, service = ctx
    body = await agree(client)
    txid = body["transaction_id"]

    session = await service.prepare_funding(txid, actor="console:buyer")

    assert session["transaction_id"] == txid
    assert session["amount_cents"] == 123400
    assert session["currency"] == "USD"
    assert session["expires_at"] == DEADLINE
    assert session["order_attempt"] == 0
    assert session["provider_order_id"] is None
    projection = (await client.get(f"/transactions/{txid}", headers=OPS)).json()
    assert projection["state"] == "AGREED"
    assert projection["deadlines"]["funding"].startswith("2026-10-28T12:00:00")
    assert projection["funding"] is None


async def test_prepare_replay_is_stable_and_bumps_the_version_once(ctx):
    client, service = ctx
    txid = (await agree(client))["transaction_id"]

    first = await service.prepare_funding(txid, actor="console:buyer")
    version = (await service.repo.get_transaction(txid)).version
    second = await service.prepare_funding(txid, actor="console:buyer")

    assert first["expires_at"] == second["expires_at"] == DEADLINE
    assert (await service.repo.get_transaction(txid)).version == version


async def test_prepare_returns_the_attached_order_while_pending(ctx):
    client, service = ctx
    award = await agree(client)
    txid = award["transaction_id"]
    await service.fund(
        txid,
        FundRequest(
            agreement_hash=award["agreement_hash"],
            agreement_version=award["agreement_version"],
            return_url="http://127.0.0.1:3000/return",
            cancel_url="http://127.0.0.1:3000/cancel",
        ),
        actor="console:buyer",
        idempotency_key=None,
    )

    session = await service.prepare_funding(txid, actor="console:buyer")

    assert session["provider_order_id"]
    assert session["expires_at"].startswith("2026-10-28T12:00:00")


async def test_prepare_requires_a_buyer_approval(ctx):
    client, service = ctx
    txid = (await agree(client))["transaction_id"]
    await patch_transaction(service, txid, {"approval": None})

    with pytest.raises(VerifundError) as raised:
        await service.prepare_funding(txid, actor="console:buyer")
    assert raised.value.code == "invalid_state"


async def test_prepare_rejects_an_approval_bound_to_another_version(ctx):
    client, service = ctx
    txid = (await agree(client))["transaction_id"]
    record = await service.repo.get_transaction(txid)
    await patch_transaction(
        service, txid, {"approval": {**(record.approval or {}), "agreement_version": 2}}
    )

    with pytest.raises(VerifundError) as raised:
        await service.prepare_funding(txid, actor="console:buyer")
    assert raised.value.code == "hash_mismatch"


async def test_prepare_rejects_a_transaction_that_is_not_agreed(ctx):
    client, service = ctx
    award = await create_award(client)

    with pytest.raises(VerifundError) as raised:
        await service.prepare_funding(award["transaction_id"], actor="console:buyer")
    assert raised.value.code == "invalid_state"
