from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from verifund_control_plane.db import configure_database, create_engine
from verifund_control_plane.domain import TransactionRecord
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.paypal.fake import FakePaymentPort
from verifund_control_plane.repository import Repository

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


class Txn:
    transaction_id = "vf_1"
    amount_cents = 123400
    currency = "USD"
    seller_id = "northwind-audio"
    run_id = "run-1"


@pytest.fixture
async def repo(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}")
    await configure_database(engine)
    repository = Repository(engine)
    await repository.create_schema()
    try:
        yield repository
    finally:
        await engine.dispose()


async def test_fake_order_and_capture(repo):
    port = FakePaymentPort(repo, scenario="success", clock=lambda: NOW)
    order = await port.create_order(
        cast(TransactionRecord, Txn()),
        return_url="http://test/checkout/fake/token",
        cancel_url="http://test/cancel/token",
        idempotency_key="fund:vf_1:v1",
    )
    assert order.status == "CREATED"
    assert order.payer_action_url == "http://test/checkout/fake/token"

    capture = await port.capture_order(order.order_id, idempotency_key="capture:vf_1")
    assert capture.status == "COMPLETED"
    assert capture.amount_cents == 123400

    loaded = await port.get_order(order.order_id)
    assert loaded.captures[0].capture_id == capture.capture_id


async def test_fake_scenarios(repo):
    failed = FakePaymentPort(repo, scenario="order_create_failed", clock=lambda: NOW)
    with pytest.raises(VerifundError) as raised:
        await failed.create_order(
            cast(TransactionRecord, Txn()),
            return_url="http://test/checkout/fake/token",
            cancel_url="http://test/cancel/token",
            idempotency_key="fund:vf_1:v1",
        )
    assert raised.value.code == "provider_unavailable"

    mismatch = FakePaymentPort(repo, scenario="amount_mismatch", clock=lambda: NOW)
    order = await mismatch.create_order(
        cast(TransactionRecord, Txn()),
        return_url="http://test/checkout/fake/token",
        cancel_url="http://test/cancel/token",
        idempotency_key="fund:vf_1:v2",
    )
    capture = await mismatch.capture_order(order.order_id, idempotency_key="capture:vf_1")
    assert capture.amount_cents == 123500
