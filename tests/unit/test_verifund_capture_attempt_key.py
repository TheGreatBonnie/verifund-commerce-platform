from __future__ import annotations

import httpx
import pytest
from verifund_contracts import FundRequest
from verifund_control_plane.app import create_app
from verifund_control_plane.paypal.fake import FakePaymentPort
from verifund_control_plane.settings import Settings

from tests.support.verifund_control import NOW, OPS, agree


class RecordingPort(FakePaymentPort):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.capture_keys: list[str] = []

    async def capture_order(self, order_id: str, *, idempotency_key: str):
        self.capture_keys.append(idempotency_key)
        return await super().capture_order(order_id, idempotency_key=idempotency_key)


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
            service = app.state.service
            port = RecordingPort(service.repo, scenario="success", clock=lambda: NOW)
            service.payments = port
            yield client, service, port


async def funded_order(client, service, awarded: dict) -> str:
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
    order_id = projection["funding"]["provider_order_id"]
    async with service.repo.transaction() as conn:
        await service.repo.update_fake_order(conn, order_id, status="APPROVED")
    return order_id


async def test_capture_key_uses_the_attached_order_attempt(ctx):
    client, service, port = ctx
    awarded = await agree(client)
    txid = awarded["transaction_id"]
    await funded_order(client, service, awarded)
    async with service.repo.transaction() as conn:
        record = await service.repo.get_transaction(txid, conn)
        await service.repo.update_transaction(
            conn,
            txid,
            expected_version=record.version,
            changes={
                "funding": {**(record.funding or {}), "order_attempt": 2},
            },
        )

    await service.refresh_funding(txid, actor="console:buyer")

    assert port.capture_keys == [f"capture:{txid}:v2"]


async def test_capture_key_defaults_to_the_first_attempt(ctx):
    client, service, port = ctx
    awarded = await agree(client)
    txid = awarded["transaction_id"]
    await funded_order(client, service, awarded)

    await service.refresh_funding(txid, actor="console:buyer")

    assert port.capture_keys == [f"capture:{txid}:v1"]
