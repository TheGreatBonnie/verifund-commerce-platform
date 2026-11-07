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


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


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
    clock = Clock(NOW)
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=clock)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, app.state.service, clock


async def agree(client: httpx.AsyncClient) -> dict:
    award = (
        await client.post(
            "/awards",
            json=award_payload(),
            headers={**OPS, **ACTOR, "idempotency-key": "award:run-1:offer-1"},
        )
    ).json()
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
    from tests.support.buyer_auth import internal_buyer_headers, seed_buyer_profile

    app = getattr(client._transport, "app")
    if not getattr(app.state.settings, "buyer_settlement_internal_token", None):
        app.state.settings.buyer_settlement_internal_token = "buyer-secret"
    await seed_buyer_profile(app, buyer_id=award.get("buyer_id", "demo-buyer"))
    _buyer_headers = internal_buyer_headers(
        token="buyer-secret", clerk_user_id="user_buyer", buyer_id=award.get("buyer_id", "demo-buyer")
    )
    await client.post(
        f"/agreements/{agreement_id}/buyer-decision",
        json={
            "agreement_version": award["agreement_version"],
            "agreement_hash": award["agreement_hash"],
            "decision": "APPROVE",
            "note": "",
            "idempotency_key": "bd:1",
        },
        headers={**_buyer_headers, "idempotency-key": "bd:1"},
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


async def redirected_order(client, service, awarded: dict) -> str:
    """Create a redirect-style fake order and return its provider order id."""
    await service.fund(
        awarded["transaction_id"],
        FundRequest(
            agreement_hash=awarded["agreement_hash"],
            agreement_version=awarded["agreement_version"],
            return_url="http://127.0.0.1:3000/return",
            cancel_url="http://127.0.0.1:3000/cancel",
        ),
        actor="console:buyer",
        idempotency_key=None,
    )
    projection = (
        await client.get(f"/transactions/{awarded['transaction_id']}", headers=OPS)
    ).json()
    return projection["funding"]["provider_order_id"]


async def test_first_attach_starts_funding_and_keeps_the_prepared_deadline(ctx):
    client, service, _ = ctx
    awarded = await agree(client)
    txid = awarded["transaction_id"]
    await service.prepare_funding(txid, actor="console:buyer")

    projection = await service.attach_funding_order(
        txid, "EMBEDDED-ORDER-1", actor="console:buyer"
    )

    assert projection["state"] == "FUNDING_PENDING"
    assert projection["funding"]["status"] == "pending"
    assert projection["funding"]["provider_order_id"] == "EMBEDDED-ORDER-1"
    assert projection["deadlines"]["funding"].startswith("2026-10-28T12:00:00")
    record = await service.repo.get_transaction(txid)
    assert record.funding["order_attempt"] == 1


async def test_attaching_the_same_order_is_idempotent(ctx):
    client, service, _ = ctx
    awarded = await agree(client)
    txid = awarded["transaction_id"]
    await service.attach_funding_order(txid, "EMBEDDED-ORDER-1", actor="console:buyer")
    version = (await service.repo.get_transaction(txid)).version

    projection = await service.attach_funding_order(
        txid, "EMBEDDED-ORDER-1", actor="console:buyer"
    )

    assert projection["funding"]["provider_order_id"] == "EMBEDDED-ORDER-1"
    record = await service.repo.get_transaction(txid)
    assert record.funding["order_attempt"] == 1
    assert record.version == version


async def test_a_different_live_order_is_rejected(ctx):
    client, service, _ = ctx
    awarded = await agree(client)
    txid = awarded["transaction_id"]
    live_order = await redirected_order(client, service, awarded)

    with pytest.raises(VerifundError) as raised:
        await service.attach_funding_order(txid, "EMBEDDED-ORDER-2", actor="console:buyer")
    assert raised.value.code == "conflict"
    record = await service.repo.get_transaction(txid)
    assert record.funding["provider_order_id"] == live_order


async def test_a_different_order_replaces_an_expired_one(ctx):
    client, service, _ = ctx
    awarded = await agree(client)
    txid = awarded["transaction_id"]
    live_order = await redirected_order(client, service, awarded)
    async with service.repo.transaction() as conn:
        await service.repo.update_fake_order(conn, live_order, status="EXPIRED")

    projection = await service.attach_funding_order(
        txid, "EMBEDDED-ORDER-2", actor="console:buyer"
    )

    assert projection["funding"]["provider_order_id"] == "EMBEDDED-ORDER-2"
    record = await service.repo.get_transaction(txid)
    assert record.funding["order_attempt"] == 2


async def test_a_different_order_replaces_one_past_the_deadline(ctx):
    client, service, clock = ctx
    awarded = await agree(client)
    txid = awarded["transaction_id"]
    await redirected_order(client, service, awarded)
    clock.value = NOW + timedelta(hours=25)

    projection = await service.attach_funding_order(
        txid, "EMBEDDED-ORDER-2", actor="console:buyer"
    )

    assert projection["funding"]["provider_order_id"] == "EMBEDDED-ORDER-2"
    record = await service.repo.get_transaction(txid)
    assert record.funding["order_attempt"] == 2
    assert record.deadlines["funding"].startswith("2026-10-29T13:00:00")


async def test_attach_rejects_a_transaction_that_is_not_funding(ctx):
    client, service, _ = ctx
    award = (
        await client.post(
            "/awards",
            json=award_payload(),
            headers={**OPS, **ACTOR, "idempotency-key": "award:run-1:offer-1"},
        )
    ).json()

    with pytest.raises(VerifundError) as raised:
        await service.attach_funding_order(
            award["transaction_id"], "EMBEDDED-ORDER-1", actor="console:buyer"
        )
    assert raised.value.code == "invalid_state"
