from __future__ import annotations

from datetime import UTC, datetime

from verifund_contracts.models import EvidenceItem, Requirement, RequirementCheck, TransactionState
from verifund_control_plane.domain import TransactionRecord
from verifund_control_plane.evidence import EvidenceStore
from verifund_control_plane.policy import evaluate

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
BALANCES = {"held_funds": 100, "platform_cash": 100, "seller_paid": 0}


def _txn() -> TransactionRecord:
    return TransactionRecord(
        transaction_id="txn_cov",
        run_id="run-cov",
        buyer_id="buyer",
        seller_id="seller",
        offer_id="offer",
        state=TransactionState.VERIFICATION_PENDING,
        version=1,
        last_seq=1,
        amount_cents=100,
        currency="USD",
        agreement_id="agr",
        agreement_hash="a" * 64,
        agreement_version=1,
        buyer_agent_review=None,
        seller_decision={"status": "accepted", "reported_at": NOW.isoformat()},
        approval={"approved_by": "demo", "approved_at": NOW.isoformat()},
        cancellation=None,
        funding={"status": "captured", "capture_id": "CAP", "capture_amount_cents": 100, "capture_currency": "USD"},
        purchase_order=None,
        evidence_summary=None,
        verification=None,
        dispute=None,
        payout=None,
        tracker=None,
        receipt=None,
        deadlines={},
        last_error=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _result(requirements: list[Requirement], items: list[EvidenceItem], store: EvidenceStore, declarations=None):
    return evaluate(
        _txn(),
        items,
        store,
        NOW,
        inspection_window_hours=48,
        ledger_balances=BALANCES,
        terms={"requirements": [r.model_dump(mode="json") for r in requirements]},
        declarations=declarations,
    )


async def test_product_photos_fail_when_views_missing(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence", max_bytes=50_000)
    req = Requirement(
        requirement_id="product_photos",
        title="Photos",
        description="",
        owner="seller",
        kind="other",
        source="file",
        accepted_formats=["image/jpeg"],
        min_items=7,
        required_views=["front", "back", "left", "right", "keyboard", "screen", "underside", "serial"],
        checks=[RequirementCheck(check_id="views_cover", description="", operator="exists", verification_method="deterministic")],
        required=True,
    )
    item_a = await store.put(
        transaction_id="txn_cov", seller_id="seller", kind="other", media_type="image/jpeg",
        original_filename="a.jpg", data=b"a", note=None, captured_at=None,
    )
    item_b = await store.put(
        transaction_id="txn_cov", seller_id="seller", kind="other", media_type="image/jpeg",
        original_filename="b.jpg", data=b"b", note=None, captured_at=None,
    )
    items = [
        item_a.model_copy(update={"requirement_id": "product_photos", "purpose": "requirement", "view_label": "front"}),
        item_b.model_copy(update={"requirement_id": "product_photos", "purpose": "requirement", "view_label": "back"}),
    ]
    result = _result([req], items, store)
    photo = next(r for r in result.requirements if r.requirement_id == "product_photos")
    assert photo.status.value in {"fail", "review"}


async def test_declaration_requirement_passes_from_declared_values(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence", max_bytes=50_000)
    req = Requirement(
        requirement_id="condition_declaration",
        title="Declaration",
        description="",
        owner="seller",
        kind="other",
        source="declaration",
        checks=[
            RequirementCheck(
                check_id="locks_disabled",
                description="",
                operator="eq",
                expected_value="true",
                verification_method="deterministic",
            )
        ],
        required=True,
    )
    result = _result(
        [req],
        [],
        store,
        declarations=[
            {
                "declaration_id": "d1",
                "requirement_id": "condition_declaration",
                "attempt": 1,
                "declared_at": NOW.isoformat(),
                "submission_ids": [],
                "values": {"locks_disabled": "true"},
            }
        ],
    )
    decl = next(r for r in result.requirements if r.requirement_id == "condition_declaration")
    assert decl.status.value == "pass"
