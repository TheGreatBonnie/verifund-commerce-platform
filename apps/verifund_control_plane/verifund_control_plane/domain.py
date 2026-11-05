from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from verifund_contracts.models import (
    AwardRequest,
    ReviewReason,
    TransactionState,
)

from verifund_control_plane.errors import VerifundError

TERMINAL_STATES = {
    TransactionState.RELEASED,
    TransactionState.CANCELED,
    TransactionState.FAILED,
}
NON_TERMINAL_STATES = set(TransactionState) - TERMINAL_STATES

ALLOWED_TRANSITIONS: dict[TransactionState, frozenset[TransactionState]] = {
    TransactionState.AWARDED: frozenset(
        {
            TransactionState.AGREED,
            TransactionState.CANCELED,
            TransactionState.REVIEW_REQUIRED,
        }
    ),
    TransactionState.AGREED: frozenset(
        {
            TransactionState.FUNDING_PENDING,
            TransactionState.CANCELED,
            TransactionState.REVIEW_REQUIRED,
        }
    ),
    TransactionState.FUNDING_PENDING: frozenset(
        {
            TransactionState.FUNDED,
            TransactionState.FAILED,
            TransactionState.CANCELED,
            TransactionState.REVIEW_REQUIRED,
        }
    ),
    TransactionState.FUNDED: frozenset(
        {TransactionState.FULFILLMENT_PENDING, TransactionState.REVIEW_REQUIRED}
    ),
    TransactionState.FULFILLMENT_PENDING: frozenset(
        {TransactionState.VERIFICATION_PENDING, TransactionState.REVIEW_REQUIRED}
    ),
    TransactionState.VERIFICATION_PENDING: frozenset(
        {
            TransactionState.RELEASE_PERMITTED,
            TransactionState.REVIEW_REQUIRED,
            TransactionState.REMEDIATION_REQUIRED,
            TransactionState.DISPUTE_OPEN,
        }
    ),
    TransactionState.RELEASE_PERMITTED: frozenset(
        {
            TransactionState.PAYOUT_PENDING,
            TransactionState.REVIEW_REQUIRED,
            TransactionState.DISPUTE_OPEN,
        }
    ),
    TransactionState.PAYOUT_PENDING: frozenset(
        {
            TransactionState.RELEASED,
            TransactionState.FAILED,
            TransactionState.REVIEW_REQUIRED,
        }
    ),
    TransactionState.RELEASED: frozenset(
        {TransactionState.REVIEW_REQUIRED, TransactionState.DISPUTE_OPEN}
    ),
    TransactionState.REVIEW_REQUIRED: frozenset(
        {
            TransactionState.RELEASE_PERMITTED,
            TransactionState.PAYOUT_PENDING,
            TransactionState.RELEASED,
            TransactionState.CANCELED,
        }
    ),
    TransactionState.REMEDIATION_REQUIRED: frozenset(
        {
            TransactionState.VERIFICATION_PENDING,
            TransactionState.REVIEW_REQUIRED,
            TransactionState.CANCELED,
        }
    ),
    TransactionState.DISPUTE_OPEN: frozenset(
        {
            TransactionState.RELEASED,
            TransactionState.REFUNDED,
            TransactionState.REVIEW_REQUIRED,
        }
    ),
    TransactionState.REFUNDED: frozenset({TransactionState.REVIEW_REQUIRED}),
    TransactionState.CANCELED: frozenset({TransactionState.REVIEW_REQUIRED}),
    TransactionState.FAILED: frozenset({TransactionState.REVIEW_REQUIRED}),
}

NON_OVERRIDABLE_REASONS = {
    ReviewReason.FUNDING_MISMATCH,
    ReviewReason.LEDGER_INCOMPLETE,
    ReviewReason.LATE_CAPTURE,
}
EVIDENCE_UPLOAD_STATES = {
    TransactionState.FUNDED,
    TransactionState.FULFILLMENT_PENDING,
    TransactionState.VERIFICATION_PENDING,
    TransactionState.REMEDIATION_REQUIRED,
}
CAPTURELESS_CANCEL_STATES = {
    TransactionState.AWARDED,
    TransactionState.AGREED,
    TransactionState.FUNDING_PENDING,
    TransactionState.REVIEW_REQUIRED,
}

STAGE_BY_STATE: dict[TransactionState, str] = {
    TransactionState.AWARDED: "awarded",
    TransactionState.AGREED: "agreed",
    TransactionState.FUNDING_PENDING: "funding_pending",
    TransactionState.FUNDED: "funded",
    TransactionState.FULFILLMENT_PENDING: "fulfillment_pending",
    TransactionState.VERIFICATION_PENDING: "verification_pending",
    TransactionState.RELEASE_PERMITTED: "release_permitted",
    TransactionState.PAYOUT_PENDING: "payout_pending",
    TransactionState.RELEASED: "released",
    TransactionState.REVIEW_REQUIRED: "review_required",
    TransactionState.REMEDIATION_REQUIRED: "remediation_required",
    TransactionState.DISPUTE_OPEN: "dispute_open",
    TransactionState.REFUNDED: "refunded",
    TransactionState.CANCELED: "canceled",
    TransactionState.FAILED: "failed",
}


@dataclass
class TransactionRecord:
    transaction_id: str
    run_id: str
    buyer_id: str
    seller_id: str
    offer_id: str
    state: TransactionState
    version: int
    last_seq: int
    amount_cents: int
    currency: str
    agreement_id: str
    agreement_hash: str
    agreement_version: int
    buyer_agent_review: dict[str, Any] | None
    seller_decision: dict[str, Any] | None
    approval: dict[str, Any] | None
    cancellation: dict[str, Any] | None
    funding: dict[str, Any] | None
    purchase_order: dict[str, Any] | None
    evidence_summary: dict[str, Any] | None
    verification: dict[str, Any] | None
    dispute: dict[str, Any] | None
    payout: dict[str, Any] | None
    receipt: dict[str, Any] | None
    deadlines: dict[str, Any]
    last_error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


def assert_transition(current: TransactionState, target: TransactionState) -> None:
    if target == TransactionState.REFUNDED:
        return
    if target not in ALLOWED_TRANSITIONS[current]:
        raise VerifundError(
            "invalid_state",
            f"cannot transition from {current.value} to {target.value}",
            status_code=409,
        )


def allowed_transitions(state: Any, actor: str | None = None) -> list[str]:
    """Return the state values reachable from ``state``.

    ``actor`` is accepted for API compatibility with the target state-machine
    contract; reachability is governed by ``ALLOWED_TRANSITIONS``.
    """
    if isinstance(state, str):
        try:
            state = TransactionState(state)
        except ValueError:
            return []
    return sorted(target.value for target in ALLOWED_TRANSITIONS.get(state, frozenset()))


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def agreement_hash(agreement: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(agreement))


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_agreement(
    transaction_id: str, award: AwardRequest, created_at: datetime
) -> dict[str, Any]:
    return {
        "agreement_version": 1,
        "transaction_id": transaction_id,
        "run_id": award.run_id,
        "buyer_id": award.buyer_id,
        "seller_id": award.seller_id,
        "offer_id": award.offer_id,
        "currency": award.currency,
        "amount_cents": award.amount_cents,
        "quantity": award.quantity,
        "line_items": [
            {
                "sku": item.sku,
                "name": item.name,
                "quantity": item.quantity,
                "unit_price_cents": item.unit_price_cents,
                "warranty_addon_cents": item.warranty_addon_cents,
            }
            for item in award.line_items
        ],
        "shipping_cents": award.shipping_cents,
        "delivery_days": award.delivery_days,
        "warranty_months": award.warranty_months,
        "returns_days": award.returns_days,
        "created_at": _iso(created_at),
    }


def validate_award(award: AwardRequest) -> None:
    line_quantity = sum(item.quantity for item in award.line_items)
    line_total = sum(
        (item.unit_price_cents + item.warranty_addon_cents) * item.quantity
        for item in award.line_items
    )
    if line_quantity != award.quantity:
        raise VerifundError("invalid_request", "quantity does not match line items")
    if line_total + award.shipping_cents + award.tax_cents + award.fees_cents != award.amount_cents:
        raise VerifundError(
            "invalid_request", "amount does not match line items plus shipping, tax, fees"
        )
    if award.currency != "USD":
        raise VerifundError("invalid_request", "only USD is supported")


def capture_ledger_entries(
    transaction_id: str, amount_cents: int
) -> list[dict[str, Any]]:
    return [
        {
            "transaction_id": transaction_id,
            "operation": "capture",
            "account": "platform_cash",
            "debit_cents": amount_cents,
            "credit_cents": 0,
        },
        {
            "transaction_id": transaction_id,
            "operation": "capture",
            "account": "held_funds",
            "debit_cents": 0,
            "credit_cents": amount_cents,
        },
    ]


def payout_ledger_entries(
    transaction_id: str, amount_cents: int
) -> list[dict[str, Any]]:
    return [
        {
            "transaction_id": transaction_id,
            "operation": "payout",
            "account": "held_funds",
            "debit_cents": amount_cents,
            "credit_cents": 0,
        },
        {
            "transaction_id": transaction_id,
            "operation": "payout",
            "account": "seller_paid",
            "debit_cents": 0,
            "credit_cents": amount_cents,
        },
    ]


def allowed_actions(state: TransactionState, actor: str) -> list[str]:
    if actor == "seller":
        return ["upload_evidence"] if state in EVIDENCE_UPLOAD_STATES else []
    actions: dict[TransactionState, list[str]] = {
        TransactionState.AWARDED: [
            "report_accept",
            "report_reject",
            "cancel",
            "flag_review",
            "reissue_seller_token",
        ],
        TransactionState.AGREED: [
            "approve",
            "cancel",
            "flag_review",
            "reissue_seller_token",
        ],
        TransactionState.FUNDING_PENDING: [
            "refresh_funding",
            "cancel",
            "flag_review",
        ],
        TransactionState.FUNDED: ["report_purchase_order", "flag_review"],
        TransactionState.FULFILLMENT_PENDING: [
            "verify",
            "flag_review",
            "reissue_seller_token",
        ],
        TransactionState.VERIFICATION_PENDING: [
            "verify",
            "flag_review",
            "reissue_seller_token",
        ],
        TransactionState.RELEASE_PERMITTED: ["release", "flag_review"],
        TransactionState.PAYOUT_PENDING: ["refresh_payout", "flag_review"],
        TransactionState.REVIEW_REQUIRED: [
            "release",
            "retry_payout",
            "cancel",
            "flag_review",
        ],
        TransactionState.RELEASED: ["receipt"],
        TransactionState.CANCELED: [],
        TransactionState.FAILED: [],
    }
    return actions[state]


def stage_for_state(state: TransactionState) -> str:
    return STAGE_BY_STATE[state]
