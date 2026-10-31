from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from verifund_contracts import ReviewReason, TransactionState
from verifund_control_plane.domain import TransactionRecord
from verifund_control_plane.evidence import EvidenceStore
from verifund_control_plane.policy import evaluate

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64
DELIVERED = NOW - timedelta(hours=30)


def record() -> TransactionRecord:
    return TransactionRecord(
        transaction_id="vf_1",
        run_id="run-1",
        buyer_id="demo-buyer",
        seller_id="northwind-audio",
        offer_id="offer-1",
        state=TransactionState.VERIFICATION_PENDING,
        version=5,
        last_seq=10,
        amount_cents=123400,
        currency="USD",
        agreement_id="agr_1",
        agreement_hash=HASH,
        agreement_version=1,
        buyer_agent_review=None,
        seller_decision={"status": "accepted", "reported_at": NOW.isoformat()},
        approval={"approved_by": "demo", "approved_at": NOW.isoformat()},
        cancellation=None,
        funding={
            "status": "captured",
            "capture_id": "CAP-1",
            "capture_amount_cents": 123400,
            "capture_currency": "USD",
        },
        purchase_order={
            "seller_order_id": "MM-1",
            "tracking_number": "TRK-1",
            "carrier": "Northwind Logistics",
            "eta": (NOW + timedelta(days=2)).isoformat(),
        },
        evidence_summary=None,
        verification=None,
        payout=None,
        receipt=None,
        deadlines={
            "evidence": (NOW + timedelta(hours=24)).isoformat(),
            "inspection": None,
        },
        last_error=None,
        created_at=NOW,
        updated_at=NOW,
    )


async def seed(store: EvidenceStore, delivered_at: datetime, tracking="TRK-1"):
    manifest = {
        "tracking_number": tracking,
        "carrier": "Northwind Logistics",
        "shipped_at": (delivered_at - timedelta(days=1)).isoformat(),
        "seller_id": "northwind-audio",
        "agreement_hash": HASH,
        "line_items": [],
    }
    delivery = {
        "delivered_at": delivered_at.isoformat(),
        "recipient": "Demo Buyer",
    }
    items = []
    for kind, payload in (
        ("shipment_manifest", manifest),
        ("delivery_confirmation", delivery),
    ):
        items.append(
            await store.put(
                transaction_id="vf_1",
                seller_id="northwind-audio",
                kind=kind,
                media_type="application/json",
                original_filename=f"{kind}.json",
                data=json.dumps(payload).encode(),
                note=None,
                captured_at=None,
            )
        )
    return items


async def test_policy_passes_after_inspection_window(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    items = await seed(store, DELIVERED)
    result = evaluate(
        record(),
        items,
        store,
        NOW,
        inspection_window_hours=24,
        ledger_balances={"held_funds": 123400, "platform_cash": 123400, "seller_paid": 0},
    )
    assert result.passed
    assert result.reasons == ()


async def test_future_inspection_window_waits(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    items = await seed(store, NOW - timedelta(hours=1))
    result = evaluate(
        record(),
        items,
        store,
        NOW,
        inspection_window_hours=24,
        ledger_balances={"held_funds": 123400, "platform_cash": 123400, "seller_paid": 0},
    )
    assert not result.passed
    assert result.waiting
    assert result.reasons == (ReviewReason.INSPECTION_NOT_ELAPSED,)


async def test_policy_reports_missing_evidence_tracking_and_ledger(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    items = await seed(store, NOW - timedelta(hours=30), tracking="OTHER")
    item_record = record()
    item_record.purchase_order = {
        "seller_order_id": "MM-1",
        "tracking_number": "TRK-1",
    }
    result = evaluate(
        item_record,
        items[:1],
        store,
        NOW,
        inspection_window_hours=24,
        ledger_balances={"held_funds": 1, "platform_cash": 1, "seller_paid": 0},
    )
    assert ReviewReason.MISSING_EVIDENCE in result.reasons
    assert ReviewReason.TRACKING_MISMATCH in result.reasons
    assert ReviewReason.LEDGER_INCOMPLETE in result.reasons
    assert not result.override_allowed


async def test_funding_mismatch_is_not_overridable(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    items = await seed(store, DELIVERED)
    item_record = record()
    item_record.funding = {
        "status": "captured",
        "capture_id": "CAP-1",
        "capture_amount_cents": 120000,
        "capture_currency": "USD",
    }
    result = evaluate(
        item_record,
        items,
        store,
        NOW,
        inspection_window_hours=24,
        ledger_balances={"held_funds": 123400, "platform_cash": 123400, "seller_paid": 0},
    )
    assert ReviewReason.FUNDING_MISMATCH in result.reasons
    assert not result.override_allowed