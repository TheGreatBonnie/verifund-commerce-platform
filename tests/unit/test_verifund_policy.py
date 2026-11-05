from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from verifund_contracts import EvidenceItem, ReviewReason, TransactionState
from verifund_control_plane.domain import TransactionRecord
from verifund_control_plane.evidence import EvidenceStore
from verifund_control_plane.policy import evaluate

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64
DELIVERED = NOW - timedelta(hours=30)

# Grandfathered (policy_version 1) terms projected from the legacy
# `evidence_required` list; no `inspection` block so the evaluation window
# falls back to the `inspection_window_hours` argument.
TERMS = {
    "policy_version": 1,
    "evidence_required": ["shipment_manifest", "delivery_confirmation"],
}


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
        dispute=None,
        payout=None,
        tracker=None,
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
        terms=TERMS,
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
        terms=TERMS,
        inspection_window_hours=24,
        ledger_balances={"held_funds": 123400, "platform_cash": 123400, "seller_paid": 0},
    )
    assert not result.passed
    assert result.pending
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
        terms=TERMS,
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
        terms=TERMS,
        inspection_window_hours=24,
        ledger_balances={"held_funds": 123400, "platform_cash": 123400, "seller_paid": 0},
    )
    assert ReviewReason.FUNDING_MISMATCH in result.reasons
    assert not result.override_allowed

BALANCES = {"held_funds": 123400, "platform_cash": 123400, "seller_paid": 0}

DELIVERY_REQUIREMENT: dict[str, Any] = {
    "requirement_id": "delivery_confirmation",
    "title": "Delivery confirmation",
    "description": "System-generated from the carrier record and the buyer confirmation.",
    "owner": "system",
    "kind": "delivery_confirmation",
    "source": "reference",
    "accepted_formats": [],
    "checks": [
        {
            "check_id": "carrier_and_buyer_agree",
            "description": "Carrier record and buyer confirmation agree on delivery.",
            "operator": "exists",
            "verification_method": "deterministic",
            "ai_derived": False,
        }
    ],
    "required": True,
}

HARDWARE_REQUIREMENT: dict[str, Any] = {
    "requirement_id": "hardware",
    "title": "Hardware diagnostic report",
    "description": "Diagnostic report showing at least 32 GB of RAM.",
    "owner": "seller",
    "kind": "other",
    "source": "file",
    "accepted_formats": ["text/csv"],
    "checks": [
        {
            "check_id": "ram_gte_32gb",
            "description": "At least 32 GB of RAM.",
            "expected_value": 32,
            "operator": "gte",
            "unit": "GB",
            "verification_method": "deterministic",
            "ai_derived": False,
        }
    ],
    "required": True,
}

SERIAL_REQUIREMENT: dict[str, Any] = {
    "requirement_id": "serial",
    "title": "Serial number photograph",
    "description": "Photograph of the device serial number label.",
    "owner": "seller",
    "kind": "other",
    "source": "file",
    "accepted_formats": ["image/jpeg"],
    "checks": [
        {
            "check_id": "serial_matches_device",
            "description": "Extracted serial number matches the device being shipped.",
            "expected_value": "S-1",
            "operator": "eq",
            "verification_method": "extraction",
            "ai_derived": True,
        }
    ],
    "required": True,
}


def custom_terms(requirements: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    terms: dict[str, Any] = {
        "policy_version": 2,
        "evidence_required": ["delivery_confirmation"],
        "inspection": {"period_hours": 24, "starts_on": "DELIVERY_CONFIRMED"},
        "requirements": requirements,
    }
    terms.update(overrides)
    return terms


async def seed_bytes(
    store: EvidenceStore,
    *,
    data: bytes,
    requirement_id: str | None,
    kind: str,
    media_type: str,
    filename: str,
) -> EvidenceItem:
    digest = hashlib.sha256(data).hexdigest()
    (store.root / digest).write_bytes(data)
    return EvidenceItem(
        evidence_id=f"ev_{digest[:12]}",
        requirement_id=requirement_id,
        kind=kind,
        sha256=digest,
        media_type=media_type,
        size_bytes=len(data),
        original_filename=filename,
        created_at=NOW,
    )


def delivery_payload(delivered_at: datetime) -> bytes:
    return json.dumps(
        {"delivered_at": delivered_at.isoformat(), "recipient": "Demo Buyer"}
    ).encode()


async def test_evaluate_uses_agreement_requirements(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    terms = custom_terms([HARDWARE_REQUIREMENT, DELIVERY_REQUIREMENT])
    ram = await seed_bytes(
        store,
        data=b"ram_gb,64\nstorage_tb,1\n",
        requirement_id="hardware",
        kind="other",
        media_type="text/csv",
        filename="diag.csv",
    )
    delivery = await seed_bytes(
        store,
        data=delivery_payload(DELIVERED),
        requirement_id="delivery_confirmation",
        kind="delivery_confirmation",
        media_type="application/json",
        filename="delivery.json",
    )
    result = evaluate(
        record(),
        [ram, delivery],
        store,
        NOW,
        terms=terms,
        inspection_window_hours=24,
        ledger_balances=BALANCES,
    )
    assert [r.requirement_id for r in result.requirements] == [
        "hardware",
        "delivery_confirmation",
    ]
    assert result.passed
    assert result.rollup == "RELEASE_PERMITTED"


async def test_legacy_terms_project_legacy_requirements(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    result = evaluate(
        record(),
        [],
        store,
        NOW,
        terms=TERMS,
        inspection_window_hours=24,
        ledger_balances=BALANCES,
    )
    assert [r.requirement_id for r in result.requirements] == [
        "shipment_manifest",
        "delivery_confirmation",
    ]
    owners = {r.requirement_id: r.owner for r in result.requirements}
    assert owners == {"shipment_manifest": "seller", "delivery_confirmation": "system"}


async def test_review_wins_over_fail(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    terms = custom_terms([HARDWARE_REQUIREMENT, SERIAL_REQUIREMENT, DELIVERY_REQUIREMENT])
    failing = await seed_bytes(
        store,
        data=b"ram_gb,16\n",
        requirement_id="hardware",
        kind="other",
        media_type="text/csv",
        filename="diag.csv",
    )
    extraction = await seed_bytes(
        store,
        data=b"\xff\xd8\xff\xe0serial",
        requirement_id="serial",
        kind="other",
        media_type="image/jpeg",
        filename="serial.jpg",
    )
    result = evaluate(
        record(),
        [failing, extraction],
        store,
        NOW,
        terms=terms,
        inspection_window_hours=24,
        ledger_balances=BALANCES,
    )
    by_id = {r.requirement_id: r for r in result.requirements}
    assert by_id["hardware"].status == "fail"
    assert by_id["serial"].status == "review"
    assert result.rollup == "REVIEW_REQUIRED"


async def test_deterministic_fail_rolls_up_to_remediation(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    terms = custom_terms([HARDWARE_REQUIREMENT, DELIVERY_REQUIREMENT])
    failing = await seed_bytes(
        store,
        data=b"ram_gb,16\n",
        requirement_id="hardware",
        kind="other",
        media_type="text/csv",
        filename="diag.csv",
    )
    result = evaluate(
        record(),
        [failing],
        store,
        NOW,
        terms=terms,
        inspection_window_hours=24,
        ledger_balances=BALANCES,
    )
    assert result.rollup == "REMEDIATION_REQUIRED"


async def test_seller_missing_after_deadline_is_remediation(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    item_record = record()
    item_record.deadlines = {"evidence": (NOW - timedelta(hours=1)).isoformat()}
    terms = custom_terms([HARDWARE_REQUIREMENT, DELIVERY_REQUIREMENT])
    result = evaluate(
        item_record,
        [],
        store,
        NOW,
        terms=terms,
        inspection_window_hours=24,
        ledger_balances=BALANCES,
    )
    assert result.rollup == "REMEDIATION_REQUIRED"
    assert ReviewReason.EVIDENCE_DEADLINE_MISSED in result.reasons
    assert ReviewReason.MISSING_EVIDENCE in result.reasons


async def test_seller_missing_before_deadline_stays_pending(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    terms = custom_terms([HARDWARE_REQUIREMENT, DELIVERY_REQUIREMENT])
    result = evaluate(
        record(),
        [],
        store,
        NOW,
        terms=terms,
        inspection_window_hours=24,
        ledger_balances=BALANCES,
    )
    assert result.rollup == "PENDING"
    assert result.pending
    assert ReviewReason.EVIDENCE_DEADLINE_MISSED not in result.reasons


async def test_system_owned_miss_routes_to_review_not_remediation(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    item_record = record()
    item_record.deadlines = {"evidence": (NOW - timedelta(hours=1)).isoformat()}
    terms = custom_terms([HARDWARE_REQUIREMENT, DELIVERY_REQUIREMENT])
    ram = await seed_bytes(
        store,
        data=b"ram_gb,64\n",
        requirement_id="hardware",
        kind="other",
        media_type="text/csv",
        filename="diag.csv",
    )
    result = evaluate(
        item_record,
        [ram],
        store,
        NOW,
        terms=terms,
        inspection_window_hours=24,
        ledger_balances=BALANCES,
    )
    # The delivery requirement (owner=system) is missing: never remediation.
    assert result.rollup == "REVIEW_REQUIRED"
    assert ReviewReason.EVIDENCE_DEADLINE_MISSED in result.reasons


async def test_extraction_check_contributes_review_not_fail(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    terms = custom_terms([SERIAL_REQUIREMENT, DELIVERY_REQUIREMENT])
    serial = await seed_bytes(
        store,
        data=b"\xff\xd8\xff\xe0serial",
        requirement_id="serial",
        kind="other",
        media_type="image/jpeg",
        filename="serial.jpg",
    )
    delivery = await seed_bytes(
        store,
        data=delivery_payload(DELIVERED),
        requirement_id="delivery_confirmation",
        kind="delivery_confirmation",
        media_type="application/json",
        filename="delivery.json",
    )
    result = evaluate(
        record(),
        [serial, delivery],
        store,
        NOW,
        terms=terms,
        inspection_window_hours=24,
        ledger_balances=BALANCES,
    )
    serial_result = next(r for r in result.requirements if r.requirement_id == "serial")
    assert serial_result.status == "review"
    assert all(check.status != "fail" for check in serial_result.checks)
    assert ReviewReason.EXTRACTION_UNAVAILABLE in serial_result.checks[0].reasons
    assert result.rollup == "REVIEW_REQUIRED"


async def test_derived_expected_value_resolves_from_purchase_order(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    requirement = dict(HARDWARE_REQUIREMENT)
    requirement["checks"] = [
        {
            "check_id": "tracking_matches_po",
            "description": "Tracking matches the purchase order.",
            "expected_value": "purchase_order.tracking_number",
            "operator": "eq",
            "verification_method": "deterministic",
            "ai_derived": False,
        }
    ]
    terms = custom_terms([requirement])
    good = await seed_bytes(
        store,
        data=b"tracking_number,TRK-1\n",
        requirement_id="hardware",
        kind="other",
        media_type="text/csv",
        filename="shipping.csv",
    )
    bad = await seed_bytes(
        store,
        data=b"tracking_number,OTHER\n",
        requirement_id="hardware",
        kind="other",
        media_type="text/csv",
        filename="shipping-other.csv",
    )
    good_result = evaluate(
        record(),
        [good],
        store,
        NOW,
        terms=terms,
        inspection_window_hours=24,
        ledger_balances=BALANCES,
    )
    bad_result = evaluate(
        record(),
        [bad],
        store,
        NOW,
        terms=terms,
        inspection_window_hours=24,
        ledger_balances=BALANCES,
    )
    assert next(r for r in good_result.requirements if r.requirement_id == "hardware").status == (
        "pass"
    )
    hardware = next(r for r in bad_result.requirements if r.requirement_id == "hardware")
    assert hardware.status == "fail"
    assert bad_result.rollup == "REMEDIATION_REQUIRED"


async def test_unresolvable_derived_expected_value_routes_to_review(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    requirement = dict(HARDWARE_REQUIREMENT)
    requirement["checks"] = [
        {
            "check_id": "carrier_present",
            "description": "Carrier resolves.",
            "expected_value": "purchase_order.nonexistent_field",
            "operator": "eq",
            "verification_method": "deterministic",
            "ai_derived": False,
        }
    ]
    terms = custom_terms([requirement])
    item = await seed_bytes(
        store,
        data=b"carrier,Northwind\n",
        requirement_id="hardware",
        kind="other",
        media_type="text/csv",
        filename="carrier.csv",
    )
    result = evaluate(
        record(),
        [item],
        store,
        NOW,
        terms=terms,
        inspection_window_hours=24,
        ledger_balances=BALANCES,
    )
    assert next(r for r in result.requirements if r.requirement_id == "hardware").status == "review"


async def test_csv_gte_boundary_is_inclusive(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    terms = custom_terms([HARDWARE_REQUIREMENT])
    item = await seed_bytes(
        store,
        data=b"ram_gb,32\n",
        requirement_id="hardware",
        kind="other",
        media_type="text/csv",
        filename="diag.csv",
    )
    result = evaluate(
        record(),
        [item],
        store,
        NOW,
        terms=terms,
        inspection_window_hours=24,
        ledger_balances=BALANCES,
    )
    assert next(r for r in result.requirements if r.requirement_id == "hardware").status == "pass"


async def test_hash_mismatch_item_is_unusable(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    forged = EvidenceItem(
        evidence_id="ev_forged",
        requirement_id="shipment_manifest",
        kind="shipment_manifest",
        sha256="b" * 64,
        media_type="application/json",
        size_bytes=2,
        original_filename="manifest.json",
        created_at=NOW,
    )
    result = evaluate(
        record(),
        [forged],
        store,
        NOW,
        terms=TERMS,
        inspection_window_hours=24,
        ledger_balances=BALANCES,
    )
    assert ReviewReason.INVALID_EVIDENCE_HASH in result.reasons
    assert result.rollup == "REVIEW_REQUIRED"
