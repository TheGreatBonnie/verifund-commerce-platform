"""Task 19a: narrowed ops release, non-overridable reasons, remediation return."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import update
from verifund_contracts import ReleaseRequest, ReviewReason, TransactionState
from verifund_control_plane.app import create_app
from verifund_control_plane.domain import NON_OVERRIDABLE_REASONS
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.settings import Settings

from tests.support.award_flow import NOW, award, award_payload


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
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client


async def _award(client) -> dict:
    return await award(client, award_payload())


async def _force(client, transaction_id: str, state: TransactionState, **values) -> None:
    repo = client._transport.app.state.repo
    async with repo.transaction() as conn:
        await conn.execute(
            update(repo.transactions)
            .where(repo.transactions.c.transaction_id == transaction_id)
            .values(state=state.value, **values)
        )


def test_non_verification_failure_not_overridable():
    assert ReviewReason.FUNDING_MISMATCH in NON_OVERRIDABLE_REASONS
    assert ReviewReason.INVALID_EVIDENCE_HASH in NON_OVERRIDABLE_REASONS
    assert ReviewReason.MANUAL_FLAG not in NON_OVERRIDABLE_REASONS
    assert NON_OVERRIDABLE_REASONS == frozenset(ReviewReason) - {
        ReviewReason.MANUAL_FLAG
    }


async def test_release_refused_during_open_dispute(client):
    body = await _award(client)
    txid = body["transaction_id"]
    await _force(
        client,
        txid,
        TransactionState.RELEASE_PERMITTED,
        dispute={"status": "open", "reason_code": "non_delivery", "claim": "x"},
    )
    service = client._transport.app.state.service
    with pytest.raises(VerifundError) as raised:
        await service.release(
            txid,
            ReleaseRequest(released_by="demo-reviewer", note="ship it"),
            actor="ops",
        )
    assert raised.value.code == "conflict"
    assert raised.value.status_code == 409


async def test_release_rejects_pre_capture_state(client):
    body = await _award(client)
    service = client._transport.app.state.service
    with pytest.raises(VerifundError) as raised:
        await service.release(
            body["transaction_id"],
            ReleaseRequest(released_by="demo-reviewer", note="ship it"),
            actor="ops",
        )
    assert raised.value.code == "invalid_state"


async def test_manual_flag_is_overridable_in_review(client):
    body = await _award(client)
    txid = body["transaction_id"]
    await _force(
        client,
        txid,
        TransactionState.REVIEW_REQUIRED,
        verification={
            "status": "review",
            "reasons": [ReviewReason.MANUAL_FLAG.value],
            "override_allowed": True,
        },
    )
    service = client._transport.app.state.service
    with pytest.raises(VerifundError) as raised:
        # The state gate is exercised; the missing capture/ledger is checked
        # only after the override reason gate passes.
        await service.release(
            txid,
            ReleaseRequest(
                released_by="demo-reviewer",
                note="checked evidence manually",
                override=True,
            ),
            actor="ops",
        )
    assert raised.value.code == "invalid_state"
    assert "captured funds" in raised.value.message


async def test_verification_failure_is_not_overridable(client):
    body = await _award(client)
    txid = body["transaction_id"]
    await _force(
        client,
        txid,
        TransactionState.REVIEW_REQUIRED,
        verification={
            "status": "review",
            "reasons": [ReviewReason.INVALID_EVIDENCE_HASH.value],
            "override_allowed": False,
        },
    )
    service = client._transport.app.state.service
    with pytest.raises(VerifundError) as raised:
        await service.release(
            txid,
            ReleaseRequest(
                released_by="demo-reviewer",
                note="trying anyway",
                override=True,
            ),
            actor="ops",
        )
    assert raised.value.code == "forbidden"
