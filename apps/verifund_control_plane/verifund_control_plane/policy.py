"""Agreement-driven verification policy (spec §3.2, §3.4).

`evaluate()` projects the requirement catalog from the stored agreement terms
(grandfathered `policy_version: 1` agreements are projected from their legacy
`evidence_required` list) and produces a `RequirementResult` per requirement.
The transaction-level checks (funding, ledger, manifest/agreement binding) are
kept as top-level reasons; everything else is derived from the catalog.

Determinism rules (spec §3.4, decisions 8/34):
- extraction (AI-derived or not) checks never produce PASS or FAIL; they
  contribute REVIEW with `EXTRACTION_UNAVAILABLE`;
- deterministic `exists` checks pass on any sha-verified usable submission;
- other deterministic operators compare the observed value against the
  expected literal (or a `purchase_order.`/`funding.`/`terms.` derivation)
  and FAIL only on mismatch of directly comparable fields;
- if the observed value cannot be resolved, the check contributes REVIEW,
  never FAIL.

Rollup (spec §3.2):
- any REVIEW -> REVIEW_REQUIRED;
- else any FAIL on a required seller-owned requirement -> REMEDIATION_REQUIRED
  (system-owned failures route to REVIEW; non-required requirements are advisory);
- seller-owned NOT_SUBMITTED before the evidence deadline -> pending;
- seller-owned NOT_SUBMITTED at/after the evidence deadline ->
  REMEDIATION_REQUIRED with EVIDENCE_DEADLINE_MISSED;
- a system-owned miss never becomes REMEDIATION_REQUIRED: it stays pending
  during the window and routes to REVIEW_REQUIRED once the window closes;
- all PASS -> RELEASE_PERMITTED, subject to the acceptance clock;
- PENDING_SCAN stays pending (a sweep handles timeouts; see Task 20a).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from verifund_contracts import (
    EvidenceItem,
    Requirement,
    RequirementCheck,
    RequirementCheckResult,
    RequirementResult,
    RequirementStatus,
    ReviewReason,
)
from verifund_contracts.terms import project_requirements

from verifund_control_plane.domain import NON_OVERRIDABLE_REASONS, TransactionRecord
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.evidence import EvidenceStore

OVERRIDABLE_REASONS = frozenset(ReviewReason) - NON_OVERRIDABLE_REASONS

RELEASE_PERMITTED = "RELEASE_PERMITTED"
REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
PENDING = "PENDING"

# Extra top-level reasons that force a review when present (funding, ledger,
# and legacy binding checks). These are transaction-level, not per-check.
_REVIEW_REASONS = frozenset(
    {
        ReviewReason.FUNDING_MISMATCH,
        ReviewReason.LEDGER_INCOMPLETE,
        ReviewReason.INVALID_EVIDENCE_HASH,
        ReviewReason.SELLER_MISMATCH,
        ReviewReason.AGREEMENT_MISMATCH,
        ReviewReason.TRACKING_MISMATCH,
        ReviewReason.DELIVERY_IN_FUTURE,
        ReviewReason.MANUAL_FLAG,
    }
)

# Known check-id -> payload key mappings for the canonical buyer catalog.
# Anything not listed falls back to the raw check id (with suffix stripping).
_CHECK_KEY_BY_ID = {
    "ram_gte_32gb": "ram_gb",
    "storage_gte_1tb": "storage_tb",
    "warranty_gte_90_days": "warranty_days",
    "tracking_matches_po": "tracking_number",
    "carrier_present": "carrier",
    "currency_matches": "currency",
    "seller_matches": "seller_id",
    "line_items_match": "line_items",
    "invoice_total_matches": "total_cents",
    "serial_readable": "serial",
}


@dataclass(frozen=True)
class PolicyResult:
    passed: bool
    pending: bool
    evidence_complete: bool
    requirements: tuple[RequirementResult, ...]
    rollup: str
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


def _purpose(item: EvidenceItem) -> str:
    return getattr(item, "purpose", None) or "requirement"


def _artifact_type(item: EvidenceItem) -> str:
    artifact_type = getattr(item, "artifact_type", None)
    return artifact_type or "file"


def _scan_status(item: EvidenceItem) -> str:
    return getattr(item, "scan_status", None) or "clean"


def _parse_csv_kv(raw: bytes) -> dict[str, Any] | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        rows = [row for row in csv.reader(io.StringIO(text)) if row]
    except csv.Error:
        return None
    if not rows:
        return None
    if all(len(row) == 2 for row in rows):
        return {str(row[0]).strip(): _coerce(row[1].strip()) for row in rows}
    if len(rows) >= 2:
        header = [cell.strip() for cell in rows[0]]
        payload: dict[str, Any] = {}
        for row in rows[1:]:
            if len(row) != len(header):
                continue
            for key, value in zip(header, row, strict=True):
                payload.setdefault(key, _coerce(value.strip()))
        return payload or None
    return None


def _coerce(value: str) -> Any:
    try:
        integral = int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value
    return integral


def _load(store: EvidenceStore, item: EvidenceItem) -> dict[str, Any] | None:
    filename = (item.original_filename or "").lower()
    media = (item.media_type or "").lower()
    try:
        raw = store.read(item.sha256)
    except (VerifundError, OSError, ValueError):
        return None
    if media in {"application/json", "text/plain"} or filename.endswith(".json"):
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return None
        return value if isinstance(value, dict) else None
    if media == "text/csv" or filename.endswith(".csv"):
        return _parse_csv_kv(raw)
    return None


def _resolve_expected(
    check: RequirementCheck, *, terms: dict[str, Any], record: TransactionRecord
) -> Any:
    expected = check.expected_value
    if not isinstance(expected, str) or "." not in expected:
        return expected
    root, _, rest = expected.partition(".")
    sources: dict[str, Any] = {
        "purchase_order": record.purchase_order or {},
        "funding": record.funding or {},
        "terms": terms or {},
    }
    source = sources.get(root)
    if source is None:
        return expected
    current: Any = source
    for part in rest.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _observed_key(check: RequirementCheck) -> str:
    if check.check_id in _CHECK_KEY_BY_ID:
        return _CHECK_KEY_BY_ID[check.check_id]
    for suffix in ("_gte", "_lte", "_matches", "_present", "_eq", "_exists"):
        if suffix in check.check_id:
            return check.check_id.split(suffix, 1)[0]
    return check.check_id


def _resolve_observed(
    check: RequirementCheck, artifacts: list[dict[str, Any] | None], item: EvidenceItem | None
) -> Any:
    key = _observed_key(check)
    for payload in artifacts:
        if not isinstance(payload, dict):
            continue
        if key in payload:
            return payload[key]
        lowered = {str(k).lower(): v for k, v in payload.items()}
        if key.lower() in lowered:
            return lowered[key.lower()]
    reference = getattr(item, "reference", None) if item is not None else None
    if reference:
        return reference
    return None


def _compare(operator: str, observed: Any, expected: Any) -> bool | None:
    if observed is None:
        return None
    if operator == "exists":
        return True
    if operator == "contains":
        if isinstance(observed, list):
            return expected in observed
        try:
            return str(expected) in str(observed)
        except TypeError:
            return None
    left = observed
    right = expected
    try:
        left_num = float(left)
        right_num = float(right)
    except (TypeError, ValueError):
        left_num = right_num = None  # type: ignore[assignment]
    if operator == "eq":
        if left_num is not None and right_num is not None:
            return left_num == right_num
        return str(left).strip() == str(right).strip()
    if operator == "gte" or operator == "lte":
        if left_num is None or right_num is None:
            return None
        return left_num >= right_num if operator == "gte" else left_num <= right_num
    return None


def _check_result(
    check: RequirementCheck,
    *,
    terms: dict[str, Any],
    record: TransactionRecord,
    artifacts: list[dict[str, Any] | None],
    item: EvidenceItem | None,
    has_usable: bool,
) -> RequirementCheckResult:
    if check.verification_method != "deterministic":
        return RequirementCheckResult(
            check_id=check.check_id,
            status="review",
            reasons=[ReviewReason.EXTRACTION_UNAVAILABLE],
        )
    if check.operator == "exists":
        return RequirementCheckResult(
            check_id=check.check_id,
            status="pass" if has_usable else "not_evaluated",
            observed_value="present" if has_usable else None,
        )
    expected = _resolve_expected(check, terms=terms, record=record)
    if expected is None:
        return RequirementCheckResult(
            check_id=check.check_id,
            status="review",
            reasons=[ReviewReason.EXTRACTION_UNAVAILABLE],
        )
    observed = _resolve_observed(check, artifacts, item)
    outcome = _compare(check.operator, observed, expected)
    if outcome is None:
        return RequirementCheckResult(
            check_id=check.check_id,
            status="review",
            reasons=[ReviewReason.EXTRACTION_UNAVAILABLE],
            observed_value=_observed_display(observed),
        )
    return RequirementCheckResult(
        check_id=check.check_id,
        status="pass" if outcome else "fail",
        observed_value=_observed_display(observed),
    )


def _observed_display(value: Any) -> str | int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    return str(value)


def _matches(requirement: Requirement, item: EvidenceItem) -> bool:
    if _purpose(item) != "requirement":
        return False
    if item.requirement_id == requirement.requirement_id:
        return True
    if item.requirement_id is not None:
        return False
    # Grandfathered items carry no requirement_id; match by artifact kind, but
    # never against kind == "other" (ambiguous across catalog requirements).
    return requirement.kind != "other" and item.kind == requirement.kind


def _evaluation_items(
    requirement: Requirement, matched: list[EvidenceItem]
) -> tuple[list[EvidenceItem], list[EvidenceItem]]:
    usable: list[EvidenceItem] = []
    pending: list[EvidenceItem] = []
    for item in matched:
        status = _scan_status(item)
        if status == "pending":
            pending.append(item)
            continue
        if status == "rejected":
            continue
        if _artifact_type(item) == "reference" and requirement.source != "reference":
            continue
        explicit_type = getattr(item, "artifact_type", None)
        if (
            explicit_type is not None
            and _artifact_type(item) == "file"
            and requirement.source == "reference"
        ):
            # An explicitly-marked file cannot satisfy a reference-sourced
            # requirement; unmarked (legacy) artifacts stay compatible.
            continue
        usable.append(item)
    return usable, pending


def _latest_declaration(
    declarations: list[dict[str, Any]] | None, requirement_id: str
) -> dict[str, Any] | None:
    if not declarations:
        return None
    candidates = [
        row
        for row in declarations
        if str(row.get("requirement_id")) == requirement_id
    ]
    if not candidates:
        return None

    def _attempt(row: dict[str, Any]) -> int:
        try:
            return int(row.get("attempt") or 0)
        except (TypeError, ValueError):
            return 0

    return max(candidates, key=_attempt)


def _parse_declaration_time(row: dict[str, Any]) -> datetime | None:
    return _parse_time(row.get("declared_at"))


def _inspection_deadline(
    store: EvidenceStore,
    items: list[EvidenceItem],
    catalog: list[Requirement],
    now: datetime,
    *,
    inspection_window_hours: int,
    terms: dict[str, Any],
) -> datetime | None:
    delivery_ids = {
        requirement.requirement_id
        for requirement in catalog
        if requirement.kind == "delivery_confirmation"
    }
    window_hours: float = float(inspection_window_hours)
    inspection = (terms or {}).get("inspection") or {}
    try:
        period = float(inspection.get("period_hours") or 0)
    except (TypeError, ValueError):
        period = 0.0
    if period >= 1:
        window_hours = period
    for item in items:
        if _scan_status(item) in {"pending", "rejected"}:
            continue
        matches = item.requirement_id in delivery_ids or (
            item.requirement_id is None and item.kind == "delivery_confirmation"
        )
        if not matches:
            continue
        payload = _load(store, item)
        delivered_at = _parse_time((payload or {}).get("delivered_at"))
        if delivered_at is not None:
            return delivered_at + timedelta(hours=window_hours)
    return None


def _is_required(meta: dict[str, tuple[bool, str]], result: RequirementResult) -> bool:
    return meta.get(result.requirement_id, (True, "seller"))[0]


def catalog_fulfilled(terms: dict[str, Any] | None, items: list[EvidenceItem]) -> bool:
    """True when every seller-owned, required requirement has at least one
    attributed item (any scan state). Used to gate automatic re-verification."""
    try:
        catalog = project_requirements(terms or {})
    except (ValidationError, ValueError):
        return False
    for requirement in catalog:
        if not (requirement.required and requirement.owner == "seller"):
            continue
        if not any(_matches(requirement, item) for item in items):
            return False
    return True


def evaluate(
    record: TransactionRecord,
    items: list[EvidenceItem],
    store: EvidenceStore,
    now: datetime,
    *,
    inspection_window_hours: int,
    ledger_balances: dict[str, int],
    terms: dict[str, Any] | None = None,
    declarations: list[dict[str, Any]] | None = None,
) -> PolicyResult:
    terms = terms or {}
    try:
        catalog = project_requirements(terms)
    except (ValidationError, ValueError):
        catalog = []
    reasons: list[ReviewReason] = []
    if not catalog:
        # An agreement with no catalog entry (broken/handcrafted terms) fails
        # closed to human review instead of vacuously passing.
        reasons.append(ReviewReason.MANUAL_FLAG)

    # Top-level hash verification; hash failures make the item unusable.
    verified_items: list[EvidenceItem] = []
    invalid_sha: set[str] = set()
    for item in items:
        if store.verify(item.sha256):
            verified_items.append(item)
        else:
            invalid_sha.add(item.sha256)
            reasons.append(ReviewReason.INVALID_EVIDENCE_HASH)

    delivery_deadline = _inspection_deadline(
        store,
        verified_items,
        catalog,
        now,
        inspection_window_hours=inspection_window_hours,
        terms=terms,
    )
    gate_declarations = declarations is not None

    results: list[RequirementResult] = []
    catalog_meta: dict[str, tuple[bool, str]] = {}
    for requirement in catalog:
        catalog_meta[requirement.requirement_id] = (requirement.required, requirement.owner)
        matched = [
            item
            for item in verified_items
            if _matches(requirement, item) and item.sha256 not in invalid_sha
        ]
        usable, pending_scan = _evaluation_items(requirement, matched)
        declaration = (
            _latest_declaration(declarations, requirement.requirement_id)
            if gate_declarations
            else None
        )

        artifacts = [_load(store, item) for item in usable]
        reference_item = next(
            (item for item in usable if _artifact_type(item) == "reference"), None
        )
        check_item = reference_item or (usable[0] if usable else None)

        checks = [
            _check_result(
                check,
                terms=terms,
                record=record,
                artifacts=artifacts,
                item=check_item,
                has_usable=bool(usable),
            )
            for check in requirement.checks
        ]

        if matched and not usable and pending_scan:
            status = RequirementStatus.PENDING_SCAN
            checks = [
                RequirementCheckResult(check_id=check.check_id, status="not_evaluated")
                for check in requirement.checks
            ]
            req_reasons: list[ReviewReason] = []
        elif matched and not usable:
            # Everything submitted was unusable (rejected scan, wrong artifact
            # type): surface for human review rather than hard failure.
            status = RequirementStatus.REVIEW
            checks = [
                RequirementCheckResult(
                    check_id=c.check_id,
                    status="review",
                    reasons=[ReviewReason.INVALID_EVIDENCE_HASH],
                )
                for c in checks
            ]
            req_reasons = [ReviewReason.INVALID_EVIDENCE_HASH]
        elif not matched:
            status = RequirementStatus.NOT_SUBMITTED
            checks = [
                RequirementCheckResult(check_id=c.check_id, status="not_evaluated")
                for c in checks
            ]
            req_reasons = []
        elif gate_declarations and declaration is None:
            # Decision 33: submissions accumulate until the seller declares
            # completion; until then the requirement is in progress.
            status = RequirementStatus.NOT_SUBMITTED
            checks = [
                RequirementCheckResult(check_id=c.check_id, status="not_evaluated")
                for c in checks
            ]
            req_reasons = []
        else:
            statuses = {check.status for check in checks}
            if "fail" in statuses:
                status = RequirementStatus.FAIL
            elif "review" in statuses or "not_evaluated" in statuses:
                status = RequirementStatus.REVIEW
            else:
                status = RequirementStatus.PASS
            req_reasons = list(
                dict.fromkeys(
                    reason for check in checks for reason in (check.reasons or [])
                )
            )

        if requirement.owner == "system" and status in (
            RequirementStatus.NOT_SUBMITTED,
            RequirementStatus.PENDING_SCAN,
        ):
            # Decision 32: system-owned requirements never become
            # REMEDIATION_REQUIRED; absence is pending, not a seller failure.
            req_reasons = []

        results.append(
            RequirementResult(
                requirement_id=requirement.requirement_id,
                kind=requirement.kind,
                owner=requirement.owner,
                source=requirement.source,
                status=status,
                checks=checks,
                submissions=matched,
                declared_at=_parse_declaration_time(declaration) if declaration else None,
                declared_by=(
                    str(declaration.get("actor")) if declaration and declaration.get("actor") else None
                ),
                attempt=int(declaration.get("attempt")) if declaration and str(
                    declaration.get("attempt") or ""
                ).isdigit() else None,
                reasons=req_reasons,
                checked_at=now,
            )
        )

    evidence_deadline = _parse_time((record.deadlines or {}).get("evidence"))
    deadline_missed = evidence_deadline is not None and now >= evidence_deadline

    any_missing = [
        r
        for r in results
        if _is_required(catalog_meta, r) and r.status == RequirementStatus.NOT_SUBMITTED
    ]
    pending_scan = [r for r in results if r.status == RequirementStatus.PENDING_SCAN]
    if any_missing:
        reasons.append(ReviewReason.MISSING_EVIDENCE)

    # Transaction-level checks (funding, ledger, binding, manual flags).
    funding = record.funding or {}
    if (
        funding.get("status") != "captured"
        or funding.get("capture_amount_cents") != record.amount_cents
        or funding.get("capture_currency") != record.currency
    ):
        reasons.append(ReviewReason.FUNDING_MISMATCH)
    if ledger_balances.get("held_funds", 0) != record.amount_cents:
        reasons.append(ReviewReason.LEDGER_INCOMPLETE)

    manifest = next(
        (
            item
            for item in verified_items
            if item.requirement_id is None and item.kind == "shipment_manifest"
        ),
        None,
    )
    if manifest is not None:
        payload = _load(store, manifest)
        if payload is not None:
            purchase_order = record.purchase_order or {}
            if payload.get("seller_id") not in {None, record.seller_id}:
                reasons.append(ReviewReason.SELLER_MISMATCH)
            if payload.get("agreement_hash") not in {None, record.agreement_hash}:
                reasons.append(ReviewReason.AGREEMENT_MISMATCH)
            tracking = payload.get("tracking_number")
            if purchase_order.get("tracking_number") and tracking != purchase_order.get(
                "tracking_number"
            ):
                reasons.append(ReviewReason.TRACKING_MISMATCH)
        else:
            reasons.append(ReviewReason.INVALID_EVIDENCE_HASH)

    for item in verified_items:
        if _scan_status(item) in {"pending", "rejected"}:
            continue
        matches_delivery = item.kind == "delivery_confirmation" or (
            item.requirement_id == "delivery_confirmation"
        )
        if not matches_delivery:
            continue
        payload = _load(store, item)
        if payload is None:
            # Reference-sourced system records carry no JSON; their checks
            # already cover presence. Only legacy JSON artifacts are parsed.
            if _artifact_type(item) == "file":
                reasons.append(ReviewReason.INVALID_EVIDENCE_HASH)
            continue
        delivered_at = _parse_time(payload.get("delivered_at"))
        if delivered_at is None:
            reasons.append(ReviewReason.INVALID_EVIDENCE_HASH)
        elif delivered_at > now:
            reasons.append(ReviewReason.DELIVERY_IN_FUTURE)

    existing = record.verification or {}
    if "manual_flag" in (existing.get("reasons") or []):
        reasons.append(ReviewReason.MANUAL_FLAG)

    inspection_deadline = delivery_deadline

    seller_missing = [
        r
        for r in results
        if r.owner == "seller" and _is_required(catalog_meta, r) and r.status == RequirementStatus.NOT_SUBMITTED
    ]

    def _system_miss() -> bool:
        return any(
            r.owner == "system" and _is_required(catalog_meta, r) and r.status != RequirementStatus.PASS
            for r in results
        )

    def _system_fail() -> bool:
        return any(
            r.owner == "system" and _is_required(catalog_meta, r) and r.status == RequirementStatus.FAIL
            for r in results
        )

    def _required_fail() -> bool:
        return any(
            _is_required(catalog_meta, r) and r.owner != "system" and r.status == RequirementStatus.FAIL
            for r in results
        )

    def _required_review() -> bool:
        return any(
            _is_required(catalog_meta, r) and r.status == RequirementStatus.REVIEW for r in results
        )

    def _required_pass() -> bool:
        return all(
            r.status == RequirementStatus.PASS for r in results if _is_required(catalog_meta, r)
        )

    top_review = any(reason in _REVIEW_REASONS for reason in reasons)

    if _required_review() or top_review or _system_fail():
        rollup = REVIEW_REQUIRED
    elif _required_fail():
        rollup = REMEDIATION_REQUIRED
    elif seller_missing:
        if deadline_missed:
            reasons.append(ReviewReason.EVIDENCE_DEADLINE_MISSED)
            rollup = REMEDIATION_REQUIRED
        else:
            rollup = PENDING
    elif pending_scan:
        rollup = PENDING
    elif _system_miss():
        if deadline_missed:
            # Decision 32: a system-owned miss never becomes
            # REMEDIATION_REQUIRED; it routes to REVIEW_REQUIRED once the
            # evidence window closes.
            reasons.append(ReviewReason.EVIDENCE_DEADLINE_MISSED)
            rollup = REVIEW_REQUIRED
        else:
            rollup = PENDING
    elif _required_pass():
        if inspection_deadline is not None and inspection_deadline > now:
            reasons.append(ReviewReason.INSPECTION_NOT_ELAPSED)
            rollup = PENDING
        else:
            rollup = RELEASE_PERMITTED
    else:
        rollup = PENDING

    unique = tuple(dict.fromkeys(reasons))
    passed = rollup == RELEASE_PERMITTED
    pending = rollup == PENDING
    evidence_complete = not seller_missing and not pending_scan
    override_allowed = bool(unique) and set(unique) <= OVERRIDABLE_REASONS

    return PolicyResult(
        passed=passed,
        pending=pending,
        evidence_complete=evidence_complete,
        requirements=tuple(results),
        rollup=rollup,
        reasons=unique,
        override_allowed=override_allowed,
        inspection_deadline=inspection_deadline,
    )
