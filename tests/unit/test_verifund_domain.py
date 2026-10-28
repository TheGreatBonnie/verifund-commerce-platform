from datetime import UTC, datetime

import pytest

from verifund_contracts import (
    AwardRequest,
    CancelReason,
    ReviewReason,
    TransactionState,
)
from verifund_control_plane.domain import (
    ALLOWED_TRANSITIONS,
    NON_OVERRIDABLE_REASONS,
    agreement_hash,
    allowed_actions,
    assert_transition,
    build_agreement,
    capture_ledger_entries,
    payout_ledger_entries,
    stage_for_state,
    validate_award,
)
from verifund_control_plane.errors import VerifundError

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def award() -> AwardRequest:
    return AwardRequest(
        run_id="run-1",
        buyer_id="demo-buyer",
        seller_id="northwind-audio",
        offer_id="offer-1",
        currency="USD",
        amount_cents=123400,
        shipping_cents=3400,
        quantity=12,
        line_items=[
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        delivery_days=7,
        warranty_months=24,
        returns_days=30,
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TransactionState.AWARDED, TransactionState.AGREED),
        (TransactionState.AWARDED, TransactionState.CANCELED),
        (TransactionState.AGREED, TransactionState.FUNDING_PENDING),
        (TransactionState.FUNDING_PENDING, TransactionState.FUNDED),
        (TransactionState.FUNDED, TransactionState.FULFILLMENT_PENDING),
        (TransactionState.FULFILLMENT_PENDING, TransactionState.VERIFICATION_PENDING),
        (TransactionState.VERIFICATION_PENDING, TransactionState.RELEASE_PERMITTED),
        (TransactionState.VERIFICATION_PENDING, TransactionState.REVIEW_REQUIRED),
        (TransactionState.RELEASE_PERMITTED, TransactionState.PAYOUT_PENDING),
        (TransactionState.PAYOUT_PENDING, TransactionState.RELEASED),
        (TransactionState.PAYOUT_PENDING, TransactionState.FAILED),
        (TransactionState.REVIEW_REQUIRED, TransactionState.PAYOUT_PENDING),
        (TransactionState.REVIEW_REQUIRED, TransactionState.CANCELED),
        (TransactionState.CANCELED, TransactionState.REVIEW_REQUIRED),
        (TransactionState.FAILED, TransactionState.REVIEW_REQUIRED),
        (TransactionState.RELEASED, TransactionState.REVIEW_REQUIRED),
    ],
)
def test_allowed_transitions(current, target):
    assert target in ALLOWED_TRANSITIONS[current]


def test_illegal_transition_returns_conflict():
    with pytest.raises(VerifundError) as raised:
        assert_transition(TransactionState.AWARDED, TransactionState.RELEASED)
    assert raised.value.code == "invalid_state"
    assert raised.value.status_code == 409


def test_agreement_hash_is_stable_and_order_independent():
    agreement = build_agreement("vf_1", award(), NOW)
    reordered = dict(reversed(list(agreement.items())))
    assert agreement_hash(agreement) == agreement_hash(reordered)
    assert len(agreement_hash(agreement)) == 64


def test_build_agreement_excludes_shipping_address_and_secrets():
    agreement = build_agreement("vf_1", award(), NOW)
    assert "shipping_address" not in agreement
    assert "card" not in agreement
    assert agreement["amount_cents"] == 123400
    assert agreement["created_at"] == "2026-10-27T12:00:00Z"


def test_validate_award_rejects_total_mismatch():
    request = award().model_copy(update={"amount_cents": 123401})
    with pytest.raises(VerifundError) as raised:
        validate_award(request)
    assert raised.value.code == "invalid_request"


def test_ledger_entries_balance():
    capture = capture_ledger_entries("txn-1", 123400)
    assert sum(entry["debit_cents"] for entry in capture) == 123400
    assert sum(entry["credit_cents"] for entry in capture) == 123400
    payout = payout_ledger_entries("txn-1", 123400)
    assert sum(entry["debit_cents"] for entry in payout) == 123400
    assert sum(entry["credit_cents"] for entry in payout) == 123400


def test_non_overridable_reasons_match_spec():
    assert NON_OVERRIDABLE_REASONS == {
        ReviewReason.FUNDING_MISMATCH,
        ReviewReason.LEDGER_INCOMPLETE,
        ReviewReason.LATE_CAPTURE,
    }


def test_allowed_actions_are_actor_specific():
    assert "upload_evidence" in allowed_actions(TransactionState.FUNDED, "seller")
    assert "release" not in allowed_actions(TransactionState.FUNDED, "seller")
    assert "release" in allowed_actions(TransactionState.RELEASE_PERMITTED, "buyer")
    assert "refund" not in allowed_actions(TransactionState.RELEASED, "buyer")


def test_stage_mapping():
    assert stage_for_state(TransactionState.REVIEW_REQUIRED) == "review_required"
    assert stage_for_state(TransactionState.CANCELED) == "canceled"
    assert stage_for_state(TransactionState.RELEASED) == "released"
