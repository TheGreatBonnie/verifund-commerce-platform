from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from verifund_control_plane.db import configure_sqlite, create_engine
from verifund_control_plane.repository import Repository

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'provenance.db'}")
    await configure_sqlite(engine)
    repository = Repository(engine)
    await repository.create_schema()
    try:
        yield repository
    finally:
        await engine.dispose()


async def test_issue_supersede_and_consume_challenge_once(repo):
    first = await repo.issue_provenance_challenge(
        organization_id="org",
        transaction_id="txn",
        challenge_id="ch_1",
        code="VF2048-AAAAAA",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=60),
    )
    assert first["status"] == "active"

    second = await repo.issue_provenance_challenge(
        organization_id="org",
        transaction_id="txn",
        challenge_id="ch_2",
        code="VF2048-BBBBBB",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=60),
    )
    assert second["status"] == "active"
    active = await repo.get_active_provenance_challenge("org", "txn", now=NOW)
    assert active is not None
    assert active["code"] == "VF2048-BBBBBB"

    consumed = await repo.consume_provenance_challenge(
        organization_id="org",
        transaction_id="txn",
        code="VF2048-BBBBBB",
        now=NOW + timedelta(minutes=1),
    )
    assert consumed is True
    consumed_again = await repo.consume_provenance_challenge(
        organization_id="org",
        transaction_id="txn",
        code="VF2048-BBBBBB",
        now=NOW + timedelta(minutes=2),
    )
    assert consumed_again is False
    assert await repo.get_active_provenance_challenge("org", "txn", now=NOW + timedelta(minutes=2)) is None


async def test_expired_challenge_cannot_be_consumed(repo):
    await repo.issue_provenance_challenge(
        organization_id="org",
        transaction_id="txn",
        challenge_id="ch_exp",
        code="VF2048-EXPIRE",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    consumed = await repo.consume_provenance_challenge(
        organization_id="org",
        transaction_id="txn",
        code="VF2048-EXPIRE",
        now=NOW + timedelta(minutes=2),
    )
    assert consumed is False
