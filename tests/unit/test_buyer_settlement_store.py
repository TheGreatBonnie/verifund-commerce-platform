from __future__ import annotations

from datetime import UTC, datetime

import pytest
from buyer_agent.settlement_store import SettlementStore
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'buyer.db'}"
    )
    value = SettlementStore(engine)
    await value.create_schema()
    yield value
    await engine.dispose()


async def test_secret_round_trip_and_delete(store):
    await store.save_secret(
        run_id="run-1",
        transaction_id="vf_1",
        seller_id="northwind-audio",
        purpose="seller_accept",
        token="v1.secret",
        expires_at=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
    )
    secret = await store.get_secret("run-1", "vf_1", "seller_accept")
    assert secret is not None
    assert secret["seller_token"] == "v1.secret"
    assert secret["seller_id"] == "northwind-audio"

    await store.delete_secret("vf_1")
    assert await store.get_secret("run-1", "vf_1", "seller_accept") is None


async def test_award_round_trip(store):
    assert await store.get_award("run-1") is None
    await store.save_award("run-1", {"run_id": "run-1", "offer_id": "offer-1"})
    award = await store.get_award("run-1")
    assert award is not None
    assert award["offer_id"] == "offer-1"
    await store.save_award("run-1", {"run_id": "run-1", "offer_id": "offer-2"})
    assert (await store.get_award("run-1"))["offer_id"] == "offer-2"


async def test_projection_round_trip(store):
    assert (
        await store.save_projection(
            "run-1",
            {"transaction_id": "vf_1", "state": "AWARDED", "last_seq": 3},
        )
        is True
    )
    assert (await store.get_projection("run-1"))["state"] == "AWARDED"
    assert (
        await store.save_projection(
            "run-1",
            {"transaction_id": "vf_1", "state": "AGREED", "last_seq": 4},
        )
        is True
    )
    assert (await store.get_projection("run-1"))["state"] == "AGREED"
    assert (
        await store.save_projection(
            "run-1",
            {"transaction_id": "vf_1", "state": "AGREED", "last_seq": 4},
        )
        is False
    )
