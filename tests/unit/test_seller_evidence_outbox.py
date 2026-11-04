from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from seller_agent.evidence_outbox import EvidenceOutbox
from seller_agent.settlement import SellerSettlementClient
from seller_agent.store import SellerStore
from sqlalchemy.ext.asyncio import create_async_engine

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
URL = "http://control/seller/transactions/vf_1/evidence"


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'seller.db'}"
    )
    value = SellerStore(engine)
    await value.create_schema()
    yield value
    await engine.dispose()


async def enqueue(outbox: EvidenceOutbox) -> bool:
    return await outbox.enqueue(
        transaction_id="vf_1",
        seller_id="northwind-audio",
        kind="shipment_manifest",
        content=b'{"tracking_number":"TRK-1"}',
        media_type="application/json",
        filename="manifest.json",
        note="auto",
        captured_at="2026-10-27T10:00:00Z",
        created_at=NOW,
    )


async def test_settlement_token_round_trips_and_replaces(store):
    await store.save_settlement_token("vf_1", "northwind-audio", "v1.a")
    await store.save_settlement_token("vf_1", "northwind-audio", "v1.b")
    assert await store.get_settlement_token("vf_1") == "v1.b"
    assert await store.get_settlement_token("vf_2") is None


async def test_enqueue_is_idempotent_per_transaction_and_kind(store):
    client = SellerSettlementClient("http://control")
    outbox = EvidenceOutbox(store, client, retry_seconds=2.0)
    assert await enqueue(outbox) is True
    assert await enqueue(outbox) is False
    row = await store.get_evidence_outbox("vf_1", "shipment_manifest")
    assert row["status"] == "pending"
    assert row["attempts"] == 0
    await client.close()


@respx.mock
async def test_run_once_uploads_due_evidence_and_marks_it_sent(store):
    route = respx.post(URL).mock(
        return_value=httpx.Response(201, json={"evidence_id": "ev_1"})
    )
    await store.save_settlement_token("vf_1", "northwind-audio", "v1.secret")
    client = SellerSettlementClient("http://control")
    outbox = EvidenceOutbox(store, client, retry_seconds=2.0)
    assert await enqueue(outbox) is True

    result = await outbox.run_once(now=NOW)

    assert result == {"sent": 1, "retried": 0, "failed": 0}
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer v1.secret"
    assert b'name="kind"' in request.content
    assert b"shipment_manifest" in request.content
    assert b"TRK-1" in request.content
    row = await store.get_evidence_outbox("vf_1", "shipment_manifest")
    assert row["status"] == "sent"
    assert row["sent_at"] == "2026-10-27T12:00:00Z"
    await client.close()


@respx.mock
async def test_run_once_backs_off_after_a_transient_failure(store):
    route = respx.post(URL).mock(return_value=httpx.Response(503))
    await store.save_settlement_token("vf_1", "northwind-audio", "v1.secret")
    client = SellerSettlementClient("http://control")
    outbox = EvidenceOutbox(store, client, retry_seconds=2.0)
    assert await enqueue(outbox) is True

    first = await outbox.run_once(now=NOW)

    assert first == {"sent": 0, "retried": 1, "failed": 0}
    row = await store.get_evidence_outbox("vf_1", "shipment_manifest")
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["next_attempt_at"] == "2026-10-27T12:00:02Z"
    assert row["last_error"]

    route.mock(return_value=httpx.Response(201, json={"evidence_id": "ev_1"}))
    second = await outbox.run_once(now=NOW + timedelta(seconds=3))
    assert second == {"sent": 1, "retried": 0, "failed": 0}
    await client.close()


@respx.mock
async def test_run_once_marks_permanent_failures(store):
    respx.post(URL).mock(return_value=httpx.Response(422))
    await store.save_settlement_token("vf_1", "northwind-audio", "v1.secret")
    client = SellerSettlementClient("http://control")
    outbox = EvidenceOutbox(store, client, retry_seconds=2.0)
    assert await enqueue(outbox) is True

    result = await outbox.run_once(now=NOW)

    assert result == {"sent": 0, "retried": 0, "failed": 1}
    row = await store.get_evidence_outbox("vf_1", "shipment_manifest")
    assert row["status"] == "failed"
    assert row["attempts"] == 1
    assert "evidence upload failed" in row["last_error"]
    await client.close()


async def test_run_once_waits_when_no_seller_token_is_stored(store):
    client = SellerSettlementClient("http://control")
    outbox = EvidenceOutbox(store, client, retry_seconds=2.0)
    assert await enqueue(outbox) is True

    result = await outbox.run_once(now=NOW)

    assert result == {"sent": 0, "retried": 1, "failed": 0}
    row = await store.get_evidence_outbox("vf_1", "shipment_manifest")
    assert row["status"] == "pending"
    assert row["last_error"] == "seller token unavailable"
    assert row["next_attempt_at"] == "2026-10-27T12:00:02Z"
    await client.close()
