from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from verifund_contracts import TransactionState
from verifund_control_plane.db import configure_sqlite, create_engine
from verifund_control_plane.domain import TransactionRecord
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import AuditInput, EventInput, Repository

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def record() -> TransactionRecord:
    return TransactionRecord(
        transaction_id="vf_1",
        run_id="run-1",
        buyer_id="demo-buyer",
        seller_id="northwind-audio",
        offer_id="offer-1",
        state=TransactionState.AWARDED,
        version=1,
        last_seq=0,
        amount_cents=123400,
        currency="USD",
        agreement_id="agr_1",
        agreement_hash="a" * 64,
        agreement_version=1,
        seller_decision=None,
        approval=None,
        funding=None,
        purchase_order=None,
        evidence_summary=None,
        verification=None,
        payout=None,
        receipt=None,
        deadlines={"funding": (NOW + timedelta(hours=24)).isoformat()},
        last_error=None,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
async def repo(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}")
    await configure_sqlite(engine)
    repository = Repository(engine)
    await repository.create_schema()
    try:
        yield repository
    finally:
        await engine.dispose()


async def test_insert_and_read_transaction(repo):
    txn = record()
    async with repo.transaction() as conn:
        await repo.insert_transaction(
            conn,
            txn,
            agreement={"agreement_version": 1, "amount_cents": 123400},
            events=[EventInput("award_created", {"run_id": "run-1"}, "buyer-agent")],
            audit=AuditInput("buyer-agent", "award_created"),
        )
    loaded = await repo.get_transaction("vf_1")
    assert loaded.state == TransactionState.AWARDED
    assert loaded.last_seq == 1
    events = await repo.events("vf_1")
    assert events[0]["type"] == "award_created"
    assert events[0]["seq"] == 1


async def test_transition_enforces_version_and_state(repo):
    async with repo.transaction() as conn:
        await repo.insert_transaction(conn, record(), agreement={}, events=[])
    async with repo.transaction() as conn:
        updated = await repo.transition(
            conn,
            "vf_1",
            expected_version=1,
            expected_state=TransactionState.AWARDED,
            new_state=TransactionState.AGREED,
            changes={"approval": {"approved_by": "demo"}},
            events=[EventInput("seller_accepted", {}, "buyer-agent")],
        )
    assert updated.state == TransactionState.AGREED
    assert updated.version == 2
    assert updated.last_seq == 1

    with pytest.raises(VerifundError) as raised:
        async with repo.transaction() as conn:
            await repo.transition(
                conn,
                "vf_1",
                expected_version=1,
                expected_state=TransactionState.AWARDED,
                new_state=TransactionState.CANCELED,
            )
    assert raised.value.code == "conflict"
    assert raised.value.status_code == 409


async def test_illegal_transition_is_invalid_state(repo):
    async with repo.transaction() as conn:
        await repo.insert_transaction(conn, record(), agreement={}, events=[])
    with pytest.raises(VerifundError) as raised:
        async with repo.transaction() as conn:
            await repo.transition(
                conn,
                "vf_1",
                expected_version=1,
                expected_state=TransactionState.AWARDED,
                new_state=TransactionState.RELEASED,
            )
    assert raised.value.code == "invalid_state"


async def test_idempotency_replays_and_rejects_body_change(repo):
    async with repo.transaction() as conn:
        await repo.put_idempotency(conn, "award", "key-1", "hash-1", {"ok": True})
    replayed = await repo.get_idempotency("award", "key-1", "hash-1")
    assert replayed == {"ok": True}
    with pytest.raises(VerifundError) as raised:
        await repo.get_idempotency("award", "key-1", "hash-2")
    assert raised.value.code == "conflict"
