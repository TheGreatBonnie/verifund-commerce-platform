from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from verifund_contracts import EvidenceItem
from verifund_control_plane.db import configure_sqlite, create_engine
from verifund_control_plane.repository import Repository

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


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


def evidence(sha: str = "b" * 64) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev_1",
        kind="shipment_manifest",
        sha256=sha,
        media_type="application/json",
        size_bytes=10,
        original_filename="manifest.json",
        note=None,
        created_at=NOW,
    )


async def test_evidence_dedupes_by_transaction_and_sha(repo):
    async with repo.transaction() as conn:
        first, created = await repo.add_evidence(conn, "vf_1", "northwind-audio", evidence())
        second, created_again = await repo.add_evidence(conn, "vf_1", "northwind-audio", evidence())
    assert created is True
    assert created_again is False
    assert first.evidence_id == second.evidence_id
    assert len(await repo.list_evidence("vf_1")) == 1


async def test_declaration_records_attempt(repo):
    async with repo.transaction() as conn:
        await repo.add_declaration(
            conn, "vf_1", "hardware", 1, actor="seller", submission_ids=["sub_1"]
        )
    rows = await repo.list_declarations("vf_1", "hardware")
    assert rows[0]["attempt"] == 1


async def test_submissions_and_declarations_round_trip(repo):
    item = evidence("c" * 64).model_copy(
        update={
            "requirement_id": "hardware",
            "scan_status": "pending",
            "artifact_type": "file",
            "origin": "seller",
            "attributed_to": "seller",
            "agreement_version": 2,
            "submission_attempt": 1,
        }
    )
    async with repo.transaction() as conn:
        assert await repo.open_attempt(conn, "vf_1", "hardware") == 1
        stored, created = await repo.add_evidence(
            conn, "vf_1", "northwind-audio", item, captured_at=NOW
        )
        assert created
        submission = await repo.add_evidence_submission(
            conn,
            submission_id="sub_1",
            transaction_id="vf_1",
            evidence_id=stored.evidence_id,
            requirement_id="hardware",
            attempt=1,
        )
        assert submission["submission_id"] == "sub_1"
        await repo.add_declaration(
            conn, "vf_1", "hardware", 1, actor="seller", submission_ids=["sub_1"]
        )
        assert await repo.open_attempt(conn, "vf_1", "hardware") == 2

    submissions = await repo.list_submissions("vf_1", "hardware")
    assert [row["submission_id"] for row in submissions] == ["sub_1"]
    assert submissions[0]["attempt"] == 1
    assert submissions[0]["requirement_id"] == "hardware"

    declarations = await repo.list_declarations("vf_1", "hardware")
    assert len(declarations) == 1
    assert declarations[0]["attempt"] == 1
    assert declarations[0]["submission_ids"] == ["sub_1"]
    assert declarations[0]["actor"] == "seller"

    items = await repo.list_evidence("vf_1")
    assert items[0].requirement_id == "hardware"
    assert items[0].scan_status == "pending"
    assert items[0].artifact_type == "file"
    assert items[0].agreement_version == 2
    assert items[0].submission_attempt == 1
    assert items[0].captured_at == NOW


async def test_webhook_event_dedupe(repo):
    async with repo.transaction() as conn:
        assert await repo.insert_webhook_event(
            conn, "evt-1", "PAYMENT.CAPTURE.COMPLETED", "cap-1",
            "hash", {"id": "evt-1"}, "fake", False,
        ) is True
        assert await repo.insert_webhook_event(
            conn, "evt-1", "PAYMENT.CAPTURE.COMPLETED", "cap-1",
            "hash", {"id": "evt-1"}, "fake", False,
        ) is False
    await repo.mark_webhook_event("evt-1", "processed")
    assert (await repo.get_webhook_event("evt-1"))["status"] == "processed"


async def test_seller_token_revoke_and_checkout_consume(repo):
    expires = NOW + timedelta(hours=72)
    async with repo.transaction() as conn:
        await repo.save_seller_token(conn, "jti-1", "vf_1", "northwind-audio", "a" * 64, ["txn:read"], expires)
        await repo.create_checkout_link(conn, "link-1", "vf_1", "checkout", expires)
    assert (await repo.get_seller_token("jti-1"))["revoked_at"] is None
    async with repo.transaction() as conn:
        await repo.revoke_seller_tokens(conn, "vf_1", NOW)
    assert (await repo.get_seller_token("jti-1"))["revoked_at"] is not None
    assert await repo.consume_checkout_link("link-1", NOW) is True
    assert await repo.consume_checkout_link("link-1", NOW) is False


async def test_payout_receipt_and_ledger(repo):
    async with repo.transaction() as conn:
        await repo.upsert_payout_item(
            conn, "item-1", "vf_1", "batch-1", "txn-vf_1", "seller@example.test",
            123400, "USD", "SUCCESS", {"status": "SUCCESS"},
        )
        await repo.save_receipt(conn, "vf_1", {"receipt_version": 1}, "hash", "sig", "kid-1")
        await conn.execute(
            repo.ledger.insert().values(
                entry_id="le-1", transaction_id="vf_1", operation="capture",
                account="held_funds", debit_cents=0, credit_cents=123400,
                currency="USD", provider_ref=None, created_at=NOW.isoformat(),
            )
        )
    assert (await repo.get_payout_item("item-1"))["status"] == "SUCCESS"
    assert (await repo.get_receipt("vf_1"))["kid"] == "kid-1"
    assert (await repo.ledger_balances("vf_1"))["held_funds"] == 123400
