from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from verifund_contracts import EvidenceItem, ReviewReason

from verifund_control_plane.domain import NON_OVERRIDABLE_REASONS, TransactionRecord
from verifund_control_plane.evidence import EvidenceStore

OVERRIDABLE_REASONS = frozenset(ReviewReason) - NON_OVERRIDABLE_REASONS


@dataclass(frozen=True)
class PolicyResult:
    passed: bool
    waiting: bool
    evidence_complete: bool
    reasons: tuple[ReviewReason, ...]
    override_allowed: bool
    inspection_deadline: datetime | None = None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load(store: EvidenceStore, item: EvidenceItem) -> dict[str, Any] | None:
    try:
        value = json.loads(store.read(item.sha256))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def evaluate(
    record: TransactionRecord,
    items: list[EvidenceItem],
    store: EvidenceStore,
    now: datetime,
    *,
    inspection_window_hours: int,
    ledger_balances: dict[str, int],
) -> PolicyResult:
    reasons: list[ReviewReason] = []
    by_kind: dict[str, EvidenceItem] = {}
    for item in items:
        by_kind.setdefault(item.kind, item)
        if not store.verify(item.sha256):
            reasons.append(ReviewReason.INVALID_EVIDENCE_HASH)

    required = {"shipment_manifest", "delivery_confirmation"}
    complete = required.issubset(by_kind)
    if not complete:
        reasons.append(ReviewReason.MISSING_EVIDENCE)

    manifest = (
        _load(store, by_kind["shipment_manifest"])
        if "shipment_manifest" in by_kind
        else None
    )
    delivery = (
        _load(store, by_kind["delivery_confirmation"])
        if "delivery_confirmation" in by_kind
        else None
    )
    if ("shipment_manifest" in by_kind and manifest is None) or (
        "delivery_confirmation" in by_kind and delivery is None
    ):
        reasons.append(ReviewReason.INVALID_EVIDENCE_HASH)

    funding = record.funding or {}
    if (
        funding.get("status") != "captured"
        or funding.get("capture_amount_cents") != record.amount_cents
        or funding.get("capture_currency") != record.currency
    ):
        reasons.append(ReviewReason.FUNDING_MISMATCH)

    if ledger_balances.get("held_funds", 0) != record.amount_cents:
        reasons.append(ReviewReason.LEDGER_INCOMPLETE)

    purchase_order = record.purchase_order or {}
    if manifest is not None:
        if manifest.get("seller_id") not in {None, record.seller_id}:
            reasons.append(ReviewReason.SELLER_MISMATCH)
        if manifest.get("agreement_hash") not in {None, record.agreement_hash}:
            reasons.append(ReviewReason.AGREEMENT_MISMATCH)
        tracking = manifest.get("tracking_number")
        if purchase_order.get("tracking_number") and tracking != purchase_order.get(
            "tracking_number"
        ):
            reasons.append(ReviewReason.TRACKING_MISMATCH)

    inspection_deadline: datetime | None = None
    if delivery is not None:
        delivered_at = _parse_time(delivery.get("delivered_at"))
        if delivered_at is None:
            reasons.append(ReviewReason.INVALID_EVIDENCE_HASH)
        elif delivered_at > now:
            reasons.append(ReviewReason.DELIVERY_IN_FUTURE)
        else:
            inspection_deadline = delivered_at + timedelta(
                hours=inspection_window_hours
            )
            if inspection_deadline > now:
                reasons.append(ReviewReason.INSPECTION_NOT_ELAPSED)

    evidence_deadline = _parse_time((record.deadlines or {}).get("evidence"))
    if evidence_deadline is not None and now > evidence_deadline:
        reasons.append(ReviewReason.EVIDENCE_DEADLINE_MISSED)

    existing = record.verification or {}
    if "manual_flag" in (existing.get("reasons") or []):
        reasons.append(ReviewReason.MANUAL_FLAG)

    unique = tuple(dict.fromkeys(reasons))
    waiting = (
        complete
        and inspection_deadline is not None
        and inspection_deadline > now
        and set(unique) <= {ReviewReason.INSPECTION_NOT_ELAPSED}
    )
    return PolicyResult(
        passed=not unique,
        waiting=waiting,
        evidence_complete=complete,
        reasons=unique,
        override_allowed=bool(unique) and set(unique) <= OVERRIDABLE_REASONS,
        inspection_deadline=inspection_deadline,
    )