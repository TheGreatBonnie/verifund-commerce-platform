import pytest
from datetime import datetime, timedelta, timezone

from verifund_control_plane.agreements.models import (
    ActorContext, Agreement, AgreementVersion, AgreementEvent,
)
from verifund_control_plane.agreements.repository import AgreementRepository
from verifund_control_plane.db import configure_sqlite, create_engine


@pytest.fixture
async def repo(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await configure_sqlite(engine)
    r = AgreementRepository(engine)
    async with engine.begin() as conn:
        await r.create_schema(conn)
    yield r
    await engine.dispose()


async def test_create_and_get(repo):
    now = datetime.now(timezone.utc)
    from verifund_contracts.models import AgreementState
    agr = Agreement(
        agreement_id="agr_1", transaction_id="txn_1", run_id="run_1",
        buyer_id="b", seller_id="s", current_version=1,
        status=AgreementState.PENDING_SELLER,
        offer_id="o1", offer_round=1, offer_hash="a" * 64,
        offer_valid_until=now, expires_at=now, agreed_at=None,
        rejected_at=None, expired_at=None, terminated_at=None,
        terminal_reason=None, seller_operator_required=False,
        row_version=1, created_at=now, updated_at=now,
    )
    ver = AgreementVersion(
        agreement_id="agr_1", version=1, terms={"x": 1}, agreement_hash="b" * 64,
        rendered_html="<html/>", renderer_version="v1", created_at=now,
    )
    async with repo.transaction() as conn:
        await repo.create(conn, agr, ver)
        await repo.append_event(conn, AgreementEvent(
            event_id=None, agreement_id="agr_1", version=1,
            event_type="agreement.created", payload={}, actor_type="system",
            actor_id="cp", created_at=now,
        ))
    got = await repo.get("agr_1")
    assert got is not None and got.agreement_id == "agr_1"
    vers = await repo.list_versions("agr_1")
    assert len(vers) == 1
    events = await repo.list_events("agr_1")
    assert len(events) == 1


async def test_cas_status(repo):
    now = datetime.now(timezone.utc)
    from verifund_contracts.models import AgreementState
    agr = Agreement(
        agreement_id="agr_2", transaction_id="txn_2", run_id="run_2",
        buyer_id="b", seller_id="s", current_version=1,
        status=AgreementState.PENDING_SELLER, offer_id="o1", offer_round=1,
        offer_hash="a" * 64, offer_valid_until=now, expires_at=now,
        agreed_at=None, rejected_at=None, expired_at=None, terminated_at=None,
        terminal_reason=None, seller_operator_required=False, row_version=1,
        created_at=now, updated_at=now,
    )
    ver = AgreementVersion(
        agreement_id="agr_2", version=1, terms={}, agreement_hash="b" * 64,
        rendered_html="<html/>", renderer_version="v1", created_at=now,
    )
    async with repo.transaction() as conn:
        await repo.create(conn, agr, ver)
    ok = await repo.update_status_cas(
        "agr_2", expected_status=AgreementState.PENDING_SELLER,
        expected_row_version=1, new_status=AgreementState.PENDING_BUYER,
        new_row_version=2, expires_at=None, now=now,
    )
    assert ok is True
    again = await repo.update_status_cas(
        "agr_2", expected_status=AgreementState.PENDING_SELLER,
        expected_row_version=1, new_status=AgreementState.PENDING_BUYER,
        new_row_version=2, expires_at=None, now=now,
    )
    assert again is False
