from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VerifundModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TransactionState(StrEnum):
    AWARDED = "AWARDED"
    AGREED = "AGREED"
    FUNDING_PENDING = "FUNDING_PENDING"
    FUNDED = "FUNDED"
    FULFILLMENT_PENDING = "FULFILLMENT_PENDING"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    RELEASE_PERMITTED = "RELEASE_PERMITTED"
    PAYOUT_PENDING = "PAYOUT_PENDING"
    RELEASED = "RELEASED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    DISPUTE_OPEN = "DISPUTE_OPEN"
    REFUNDED = "REFUNDED"
    CANCELED = "CANCELED"
    FAILED = "FAILED"


class AgreementState(StrEnum):
    PENDING_SELLER = "PENDING_SELLER"
    PENDING_BUYER = "PENDING_BUYER"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    AGREED = "AGREED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class AgreementDecision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    OPERATOR_REQUIRED = "OPERATOR_REQUIRED"  # not persisted as a decision row


class BuyerApprovalDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class RemedyPolicy(StrEnum):
    CANCEL_AND_REFUND = "cancel_and_refund"
    REFUND_OR_REPLACEMENT = "refund_or_replacement"
    REPAIR_OR_REPLACEMENT = "repair_or_replacement"


class RemedyTerms(VerifundModel):
    # Grandfathered agreements carry three remedy keys. `not_as_described` is
    # omitted from dumps when unset so stored terms and `model_dump()` stay
    # comparable with what grandfathered agreements contain.
    non_delivery: RemedyPolicy
    late_delivery: RemedyPolicy
    damaged_goods: RemedyPolicy
    not_as_described: RemedyPolicy | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class EvidenceKind(StrEnum):
    SHIPMENT_MANIFEST = "shipment_manifest"
    DELIVERY_CONFIRMATION = "delivery_confirmation"
    INVOICE = "invoice"
    OTHER = "other"


class RejectReason(StrEnum):
    TERMS_MISMATCH = "terms_mismatch"
    OUT_OF_STOCK = "out_of_stock"
    CANNOT_FULFILL = "cannot_fulfill"
    VERIFICATION_FAILED = "verification_failed"
    OTHER = "other"


class AgreementReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    OPERATOR_REQUIRED = "operator_required"   # NEW
    CHANGES_REQUESTED = "changes_requested"  # NEW


class CancelReason(StrEnum):
    BUYER_REJECTED = "buyer_rejected"
    BUYER_CANCELLED = "buyer_cancelled"
    REVIEWER_CANCELLED = "reviewer_cancelled"
    FUNDING_EXPIRED = "funding_expired"
    AGREEMENT_EXPIRED = "agreement_expired"  # NEW; reconciler only
    SELLER_REJECTED = "seller_rejected"      # NEW; seller decision path


class RequirementStatus(StrEnum):
    NOT_SUBMITTED = "not_submitted"
    PENDING_SCAN = "pending_scan"
    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"


class ReviewReason(StrEnum):
    MISSING_EVIDENCE = "missing_evidence"
    INVALID_EVIDENCE_HASH = "invalid_evidence_hash"
    SELLER_MISMATCH = "seller_mismatch"
    AGREEMENT_MISMATCH = "agreement_mismatch"
    TRACKING_MISMATCH = "tracking_mismatch"
    DELIVERY_IN_FUTURE = "delivery_in_future"
    INSPECTION_NOT_ELAPSED = "inspection_not_elapsed"
    FUNDING_MISMATCH = "funding_mismatch"
    EVIDENCE_DEADLINE_MISSED = "evidence_deadline_missed"
    LEDGER_INCOMPLETE = "ledger_incomplete"
    MANUAL_FLAG = "manual_flag"
    LATE_CAPTURE = "late_capture"
    EXTRACTION_UNAVAILABLE = "extraction_unavailable"


class VerifundErrorCode(StrEnum):
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    INVALID_REQUEST = "invalid_request"
    INVALID_STATE = "invalid_state"
    HASH_MISMATCH = "hash_mismatch"
    TOKEN_EXPIRED = "token_expired"
    TOKEN_SCOPE_DENIED = "token_scope_denied"
    EVIDENCE_TOO_LARGE = "evidence_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_AMBIGUOUS = "provider_ambiguous"
    INTERNAL = "internal"


class RequirementCheck(VerifundModel):
    check_id: str
    description: str
    expected_value: str | int | float | None = None
    operator: str  # eq | gte | lte | contains | exists
    unit: str | None = None
    verification_method: str
    ai_derived: bool = False


class Requirement(VerifundModel):
    requirement_id: str
    title: str
    description: str
    owner: str  # seller | system | buyer
    kind: str
    source: str  # file | reference
    accepted_formats: list[str] = Field(default_factory=list)
    checks: list[RequirementCheck] = Field(default_factory=list)
    required: bool = True


class RequirementCheckResult(VerifundModel):
    check_id: str
    status: str  # pass | fail | review | not_evaluated
    reasons: list[ReviewReason] = Field(default_factory=list)
    observed_value: str | int | float | None = None


class AwardLineItem(VerifundModel):
    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)
    warranty_addon_cents: int = Field(default=0, ge=0)
    attributes: dict[str, str]

    @model_validator(mode="before")
    @classmethod
    def _default_attributes(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("attributes"):
            return {**data, "attributes": {}}
        return data


def _normalize_numbers(value: Any) -> Any:
    """Collapse integral floats to ints so hashes survive JSON/A2A round trips.

    Protobuf-backed A2A envelopes decode every JSON number as a float. Without
    this normalization ``terms`` (a free-form mapping) would hash differently
    after transport and the agreement digest would fail verification.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _normalize_numbers(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_numbers(item) for item in value]
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        _normalize_numbers(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class AgreementProjection(VerifundModel):
    agreement_id: str = Field(min_length=1)            # NEW
    agreement_version: int = Field(ge=1)
    transaction_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    buyer_id: str = Field(min_length=1)
    seller_id: str = Field(min_length=1)
    offer_id: str = Field(min_length=1)
    offer_round: int = Field(ge=1)                     # NEW
    offer_hash: str = Field(pattern="^[0-9a-f]{64}$")  # NEW
    offer_valid_until: datetime                        # NEW
    currency: str = Field(default="USD", pattern="^USD$")
    amount_cents: int = Field(gt=0)
    quantity: int = Field(gt=0)
    line_items: list[AwardLineItem] = Field(min_length=1)
    shipping_cents: int = Field(ge=0)
    tax_cents: int = Field(ge=0)                      # NEW
    fees_cents: int = Field(ge=0)                      # NEW
    delivery_days: int = Field(ge=0)
    warranty_months: int = Field(ge=0)
    returns_days: int = Field(ge=0)
    inspection_period_hours: int = Field(ge=1)          # NEW
    inspection_starts_on: str = Field(min_length=1)     # NEW
    evidence_required: list[EvidenceKind] = Field(min_length=1)  # NEW
    remedies: RemedyTerms                              # NEW
    dispute_window_hours: int = Field(ge=1)             # NEW
    terms: dict[str, Any]                             # NEW
    status: AgreementState                            # NEW
    expires_at: datetime | None = None                 # NEW
    supersedes_version: int | None = None              # NEW
    change_request_id: str | None = None               # NEW
    created_at: str = Field(min_length=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")

    def canonical_payload(self) -> dict[str, Any]:
        # §5.5 digest envelope
        return {
            "schema": "verifund.agreement.v1",
            "agreement_id": self.agreement_id,
            "version": self.agreement_version,
            "agreement_type": self.terms.get("agreement_type", "goods") if self.terms else "goods",
            "terms_version": self.terms.get("terms_version", 1) if self.terms else 1,
            "terms": self.terms or {},
            "amount_cents": self.amount_cents,
            "shipping_cents": self.shipping_cents,
            "tax_cents": self.tax_cents,
            "fees_cents": self.fees_cents,
            "total_cents": self.amount_cents,
            "offer_id": self.offer_id,
            "offer_round": self.offer_round,
            "offer_hash": self.offer_hash,
        }

    def recompute_hash(self) -> str:
        return sha256_hex(canonical_json(self.canonical_payload()))

    @model_validator(mode="after")
    def _hash_must_match(self) -> AgreementProjection:
        if self.recompute_hash() != self.agreement_hash:
            raise ValueError("agreement hash does not match canonical payload")
        return self

    @model_validator(mode="after")
    def _summary_must_match_terms(self) -> AgreementProjection:
        terms = self.terms or {}
        totals = terms.get("totals") or {}

        def _match(term_value: Any, field_value: Any, label: str) -> None:
            if term_value is None or field_value is None:
                return
            if term_value != field_value:
                raise ValueError(f"{label} must match terms")

        _match(totals.get("total_cents"), self.amount_cents, "amount_cents")
        _match(totals.get("shipping_cents"), self.shipping_cents, "shipping_cents")
        _match(totals.get("tax_cents"), self.tax_cents, "tax_cents")
        _match(totals.get("fees_cents"), self.fees_cents, "fees_cents")
        _match((terms.get("delivery") or {}).get("delivery_days"), self.delivery_days, "delivery_days")
        _match((terms.get("warranty") or {}).get("warranty_months"), self.warranty_months, "warranty_months")
        _match((terms.get("returns") or {}).get("returns_days"), self.returns_days, "returns_days")
        _match((terms.get("inspection") or {}).get("period_hours"), self.inspection_period_hours, "inspection_period_hours")
        _match((terms.get("inspection") or {}).get("starts_on"), self.inspection_starts_on, "inspection_starts_on")
        _match(list(terms.get("evidence_required") or []), list(self.evidence_required or []), "evidence_required")
        _match(terms.get("remedies"), self.remedies.model_dump(mode="json") if self.remedies else None, "remedies")
        _match(terms.get("dispute_window_hours"), self.dispute_window_hours, "dispute_window_hours")
        return self


class AwardRequest(VerifundModel):
    run_id: str = Field(min_length=1)
    buyer_id: str = Field(min_length=1)
    seller_id: str = Field(min_length=1)
    offer_id: str = Field(min_length=1)
    currency: str = Field(default="USD", pattern="^USD$")
    amount_cents: int = Field(gt=0)
    shipping_cents: int = Field(ge=0)
    quantity: int = Field(gt=0)
    line_items: list[AwardLineItem] = Field(min_length=1)
    delivery_days: int = Field(ge=1)                    # NEW (was ge=0)
    warranty_months: int = Field(ge=0)
    returns_days: int = Field(ge=0)
    offer_round: int = Field(ge=1)                     # NEW
    offer_hash: str = Field(pattern="^[0-9a-f]{64}$")  # NEW
    offer_valid_until: datetime                        # NEW
    inspection_period_hours: int = Field(default=48, ge=1)  # NEW
    inspection_starts_on: str = Field(default="DELIVERY_CONFIRMED", min_length=1)  # NEW
    requirements: list[Requirement] = Field(default_factory=list)  # NEW
    # DEPRECATED mirror of `requirements`; retained for grandfathered callers.
    evidence_required: list[EvidenceKind] = Field(      # NEW
        default_factory=lambda: [EvidenceKind.SHIPMENT_MANIFEST,
                                 EvidenceKind.DELIVERY_CONFIRMATION,
                                 EvidenceKind.INVOICE],
        min_length=1,
        description="Deprecated: use `requirements` instead",
    )
    remedies: RemedyTerms = Field(              # NEW; default keeps existing callers working
        default_factory=lambda: RemedyTerms(
            non_delivery=RemedyPolicy.CANCEL_AND_REFUND,
            late_delivery=RemedyPolicy.CANCEL_AND_REFUND,
            damaged_goods=RemedyPolicy.REFUND_OR_REPLACEMENT,
        )
    )
    dispute_window_hours: int = Field(default=72, ge=1)  # NEW
    tax_cents: int = Field(ge=0)                       # NEW
    fees_cents: int = Field(ge=0)                      # NEW
    request_id: str = Field(min_length=1)               # NEW
    buyer_display_name: str = Field(min_length=1)       # NEW
    seller_display_name: str = Field(min_length=1)      # NEW
    binding_version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _totals_must_match(self) -> AwardRequest:
        line_quantity = sum(item.quantity for item in self.line_items)
        if line_quantity != self.quantity:
            raise ValueError("quantity must equal the sum of line-item quantities")
        line_total = sum(
            (item.unit_price_cents + item.warranty_addon_cents) * item.quantity
            for item in self.line_items
        )
        if line_total + self.shipping_cents + self.tax_cents + self.fees_cents != self.amount_cents:
            raise ValueError("amount_cents must equal line items plus shipping, tax, fees")
        if EvidenceKind.DELIVERY_CONFIRMATION not in self.evidence_required:
            raise ValueError("evidence_required must include delivery_confirmation")
        return self


class AwardResponse(VerifundModel):
    transaction_id: str
    state: TransactionState
    agreement_hash: str
    agreement: AgreementProjection
    agreement_version: int = Field(ge=1)
    seller_token: str
    expires_at: datetime


class ChangeOperationType(StrEnum):
    SET_UNIT_PRICE = "set_unit_price"
    SET_QUANTITY = "set_quantity"
    SET_SHIPPING = "set_shipping"
    SET_TAX = "set_tax"
    SET_FEES = "set_fees"
    SET_DELIVERY_DAYS = "set_delivery_days"
    SET_WARRANTY_MONTHS = "set_warranty_months"
    SET_RETURNS_DAYS = "set_returns_days"
    SET_INSPECTION_PERIOD = "set_inspection_period"
    SET_EVIDENCE_REQUIRED = "set_evidence_required"
    SET_REMEDIES = "set_remedies"


class ChangeOperation(VerifundModel):
    op: ChangeOperationType
    sku: str | None = None
    unit_price_cents: int | None = Field(default=None, ge=0)
    quantity: int | None = Field(default=None, gt=0)
    shipping_cents: int | None = Field(default=None, ge=0)
    tax_cents: int | None = Field(default=None, ge=0)
    fees_cents: int | None = Field(default=None, ge=0)
    delivery_days: int | None = Field(default=None, ge=1)
    warranty_months: int | None = Field(default=None, ge=0)
    returns_days: int | None = Field(default=None, ge=0)
    inspection_period_hours: int | None = Field(default=None, ge=1)
    evidence_required: list[EvidenceKind] | None = None
    remedies: RemedyTerms | None = None
    dispute_window_hours: int | None = Field(default=None, ge=1)


class ChangeSet(VerifundModel):
    operations: list[ChangeOperation] = Field(min_length=1)
    reason: str = ""


class AgreementDecisionView(VerifundModel):
    decision_id: str
    party: Literal["buyer", "seller"]
    decision: AgreementDecision
    actor_type: str
    actor_id: str
    authority_ref: str | None = None
    agreement_hash: str
    version: int
    note: str = ""
    decided_at: datetime


class ChangeRequestView(VerifundModel):
    change_request_id: str
    base_version: int
    base_hash: str
    requested_by_party: Literal["buyer", "seller"]
    requested_by_actor_type: str
    requested_by_actor_id: str
    operations: list[ChangeOperation]
    reason: str = ""
    status: Literal["PENDING", "ACCEPTED", "REJECTED", "EXPIRED"]
    resolved_by_party: Literal["buyer", "seller"] | None = None
    resolution_note: str = ""
    resulting_version: int | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class AgreementVersionView(VerifundModel):
    version: int
    agreement_hash: str
    created_at: datetime
    supersedes_version: int | None = None
    change_request_id: str | None = None
    superseded_at: datetime | None = None
    decisions: list[AgreementDecisionView] = Field(default_factory=list)
    is_current: bool


class ApprovalTokenResponse(VerifundModel):
    token: str
    review_url: str
    expires_at: datetime
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")


class AgreementView(VerifundModel):
    agreement_id: str
    transaction_id: str
    run_id: str
    buyer_id: str
    seller_id: str
    status: AgreementState
    current_version: int = Field(ge=1)
    expires_at: datetime | None = None
    agreed_at: datetime | None = None
    offer_id: str
    offer_round: int = Field(ge=1)
    offer_hash: str = Field(pattern="^[0-9a-f]{64}$")
    offer_valid_until: datetime
    seller_operator_required: bool = False
    version: AgreementVersionView
    decisions: list[AgreementDecisionView] = Field(default_factory=list)
    change_request: ChangeRequestView | None = None
    review_url: str | None = None


class SellerAgreementDecisionRequest(VerifundModel):
    decision: AgreementDecision
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    offer_hash: str = Field(pattern="^[0-9a-f]{64}$")
    actor_type: str = Field(default="SELLER_AGENT", min_length=1)
    actor_id: str = Field(min_length=1)
    authority_ref: str | None = None
    authority_snapshot: dict[str, Any] = Field(default_factory=dict)
    verified_change_request_id: str | None = None
    note: str = ""
    change_set: ChangeSet | None = None


class BuyerAgreementRequest(VerifundModel):
    award: AwardRequest
    buyer_task_id: str = Field(min_length=1)
    buyer_context_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class BuyerAgreementResponse(VerifundModel):
    transaction_id: str = Field(min_length=1)
    state: TransactionState
    agreement: AgreementProjection
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    seller_token_ref: str = Field(min_length=1)
    seller_token_expires_at: datetime | None = None

    @model_validator(mode="after")
    def _binding_must_match(self) -> BuyerAgreementResponse:
        if self.agreement.transaction_id != self.transaction_id:
            raise ValueError("agreement transaction does not match response")
        if self.agreement.agreement_version != self.agreement_version:
            raise ValueError("agreement version does not match response")
        if self.agreement.agreement_hash != self.agreement_hash:
            raise ValueError("agreement hash does not match response")
        return self


class BuyerPurchaseOrderRequest(VerifundModel):
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1)


class BuyerPurchaseOrderResponse(VerifundModel):
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    seller_id: str = Field(min_length=1)
    offer_id: str = Field(min_length=1)
    amount_cents: int = Field(gt=0)
    seller_token_ref: str = Field(min_length=1)
    purchase_order: dict[str, Any]

    @model_validator(mode="after")
    def _purchase_order_must_match(self) -> BuyerPurchaseOrderResponse:
        po = self.purchase_order
        expected = {
            "run_id": self.run_id,
            "seller_id": self.seller_id,
            "offer_id": self.offer_id,
            "expected_total_cents": self.amount_cents,
            "settlement_transaction_id": self.transaction_id,
            "agreement_hash": self.agreement_hash,
        }
        for key, value in expected.items():
            if po.get(key) != value:
                raise ValueError(f"purchase order {key} does not match")
        if po.get("settlement_token"):
            raise ValueError("buyer purchase order must not contain a token")
        return self


class BuyerOrderReportRequest(VerifundModel):
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1)
    order: dict[str, Any]


class BuyerOrderReportResponse(VerifundModel):
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    state: TransactionState
    projection: dict[str, Any]

    @model_validator(mode="after")
    def _projection_must_match(self) -> BuyerOrderReportResponse:
        if self.projection.get("transaction_id") != self.transaction_id:
            raise ValueError("projection transaction does not match")
        if self.projection.get("state") != self.state:
            raise ValueError("projection state does not match")
        return self


class FundingApprovalDecision(VerifundModel):
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    approved: bool
    approved_by: str = Field(min_length=1)
    note: str = ""
    decided_at: datetime
    idempotency_key: str = Field(min_length=1)


class CheckoutDecision(VerifundModel):
    status: Literal["completed", "canceled", "fallback"]
    transaction_id: str = Field(min_length=1)
    order_id: str | None = None
    capture_id: str | None = None
    # Advisory only. The verifund agent re-reads the authoritative settlement
    # before advancing, so an LLM relay may omit this nested object.
    projection: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1)


class ReleaseApprovalDecision(VerifundModel):
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    approved: bool
    released_by: str = Field(min_length=1)
    note: str = ""
    override: bool = False
    decided_at: datetime
    idempotency_key: str = Field(min_length=1)

    @model_validator(mode="after")
    def _override_requires_a_note(self) -> ReleaseApprovalDecision:
        if self.override and not self.note.strip():
            raise ValueError("an override release requires a note")
        return self


class AcceptRequest(VerifundModel):
    seller_id: str
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    accepted_total_cents: int = Field(gt=0)
    seller_task_id: str = Field(min_length=1)
    accepted_at: datetime
    agreement_version: int | None = Field(default=None, ge=1)  # NEW
    offer_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")  # NEW
    actor_type: str = "SELLER_AGENT"  # NEW
    actor_id: str | None = None       # NEW; defaults to seller_id in the service
    authority_ref: str | None = None  # NEW
    authority_snapshot: dict[str, Any] = Field(default_factory=dict)  # NEW


class BuyerAgreementReviewRequest(VerifundModel):
    buyer_id: str = Field(min_length=1)
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    decision: AgreementReviewDecision
    reason_code: str | None = None
    note: str = ""
    buyer_task_id: str = Field(min_length=1)
    reviewed_at: datetime


class RejectRequest(VerifundModel):
    seller_id: str
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    reason_code: RejectReason
    note: str = ""
    seller_task_id: str = Field(min_length=1)
    rejected_at: datetime


class ApproveRequest(VerifundModel):
    approval_id: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approved_at: datetime
    note: str = ""
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    agreement_version: int = Field(ge=1)   # NEW


class CancelRequest(VerifundModel):
    reason_code: CancelReason
    note: str = ""

    @model_validator(mode="after")
    def _reject_reconciler_only_reason(self) -> CancelRequest:
        if self.reason_code in {CancelReason.FUNDING_EXPIRED, CancelReason.AGREEMENT_EXPIRED}:
            raise ValueError("reconciler-only cancellation reasons must not be buyer-set")
        return self


class FundRequest(VerifundModel):
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    agreement_version: int = Field(ge=1)   # NEW
    return_url: str
    cancel_url: str


class FundResponse(VerifundModel):
    transaction_id: str
    state: TransactionState
    checkout_url: str
    expires_at: datetime


class PurchaseOrderLineItem(VerifundModel):
    sku: str
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)
    warranty_addon_cents: int = Field(default=0, ge=0)


class PurchaseOrderReport(VerifundModel):
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    seller_order_id: str
    offer_id: str
    quantity: int = Field(gt=0)
    total_cents: int = Field(gt=0)
    currency: str = Field(default="USD", pattern="^USD$")
    tracking_number: str
    carrier: str
    reserved_at: datetime
    eta: datetime
    line_items: list[PurchaseOrderLineItem] = Field(min_length=1)


class ReleaseRequest(VerifundModel):
    released_by: str = Field(min_length=1)
    note: str = ""
    override: bool = False


class FlagReviewRequest(VerifundModel):
    reason: str = Field(min_length=1)
    note: str = ""


class VerifyRequest(VerifundModel):
    note: str = ""


class SellerTokenRequest(VerifundModel):
    run_id: str
    transaction_id: str
    seller_id: str
    purpose: str


class SellerTokenResponse(VerifundModel):
    seller_token: str
    expires_at: datetime


class SellerDecisionProjection(VerifundModel):
    status: str
    reported_at: datetime
    reason_code: RejectReason | None = None
    note: str | None = None


class AgreementReviewProjection(VerifundModel):
    status: AgreementReviewDecision
    agreement_version: int
    agreement_hash: str
    task_id: str
    reviewed_at: datetime
    reason_code: str | None = None
    note: str | None = None


class ApprovalProjection(VerifundModel):
    approved_by: str
    approved_at: datetime
    note: str | None = None
    agreement_version: int | None = None   # NEW; binds the consuming approval to a version
    agreement_hash: str | None = None      # NEW; binds the consuming approval to a digest


class CancellationProjection(VerifundModel):
    reason_code: str
    note: str | None = None
    at: datetime


class FundingProjection(VerifundModel):
    status: str
    provider_order_id: str | None = None
    capture_id: str | None = None
    payer_action_url: str | None = None
    completed_at: datetime | None = None


class PurchaseOrderProjection(VerifundModel):
    seller_order_id: str
    tracking_number: str | None = None
    carrier: str | None = None
    eta: datetime | None = None


class EvidenceItem(VerifundModel):
    evidence_id: str
    requirement_id: str | None = None
    kind: str
    sha256: str
    media_type: str
    size_bytes: int
    original_filename: str
    note: str | None = None
    origin: str | None = None  # seller | buyer | carrier | system
    attributed_to: str | None = None
    purpose: str = "requirement"  # requirement | dispute
    captured_at: datetime | None = None
    scan_status: str | None = None  # pending | clean | rejected
    agreement_version: int | None = None
    artifact_type: str | None = None  # file | reference
    reference: str | None = None  # reference payload, e.g. a tracking number
    submission_attempt: int | None = None  # the open attempt the upload belongs to
    created_at: datetime


class EvidenceSubmission(VerifundModel):
    """Typed receipt for a requirement-addressed upload (Task 9a).

    `receipt_id` derives from the content hash of the submission (stable for
    identical bytes); `submission_id` is the per-upload attempt record.
    """

    submission_id: str
    attempt: int
    evidence_id: str
    requirement_id: str
    receipt_id: str
    artifact_type: str  # file | reference
    scan_status: str  # pending | clean


class RequirementResult(VerifundModel):
    requirement_id: str
    kind: str
    owner: str
    source: str
    status: RequirementStatus
    checks: list[RequirementCheckResult] = Field(default_factory=list)
    submissions: list[EvidenceItem] = Field(default_factory=list)
    declared_at: datetime | None = None
    declared_by: str | None = None
    attempt: int | None = None
    reasons: list[ReviewReason] = Field(default_factory=list)
    checked_at: datetime | None = None
    remediation: dict[str, Any] | None = None


class EvidenceSummary(VerifundModel):
    requirements: list[RequirementResult] = Field(default_factory=list)
    deadline: datetime | None = None
    items: list[EvidenceItem]


class VerificationProjection(VerifundModel):
    status: str
    reasons: list[str] = Field(default_factory=list)
    checked_at: datetime | None = None
    override_allowed: bool = False
    requirements: list[RequirementResult] = Field(default_factory=list)
    rollup: str | None = None


class PayoutProjection(VerifundModel):
    status: str
    batch_id: str | None = None
    item_id: str | None = None
    amount_cents: int | None = None
    updated_at: datetime | None = None


class DisputeProjection(VerifundModel):
    # Surfaced to the seller only while the transaction is in DISPUTE_OPEN,
    # so the seller can read the buyer's claim and respond.
    status: str
    reason_code: str
    requirement_ids: list[str] = Field(default_factory=list)
    claim: str
    opened_at: datetime
    escalation_rung: int = 0


class EvidenceList(VerifundModel):
    items: list[EvidenceItem]


class TrackerProjection(VerifundModel):
    """Merchant-pushed PayPal tracker shown to ops and disputes only."""

    tracker_id: str
    last_status: str | None = None
    status_source: str = "merchant_push"
    updated_at: datetime | None = None


class TransactionProjection(VerifundModel):
    transaction_id: str
    agreement_id: str | None = None   # NEW; written on award, read by funding binding
    run_id: str
    state: TransactionState
    last_seq: int
    amount_cents: int
    currency: str
    buyer_id: str
    seller_id: str
    agreement_hash: str
    agreement_version: int
    buyer_agent_review: AgreementReviewProjection | None = None
    seller_decision: SellerDecisionProjection | None = None
    approval: ApprovalProjection | None = None
    cancellation: CancellationProjection | None = None
    funding: FundingProjection | None = None
    purchase_order: PurchaseOrderProjection | None = None
    evidence: EvidenceSummary | None = None
    verification: VerificationProjection | None = None
    dispute: DisputeProjection | None = None
    payout: PayoutProjection | None = None
    tracker: TrackerProjection | None = None
    receipt_available: bool = False
    deadlines: dict[str, datetime | None]
    allowed_actions: list[str] = Field(default_factory=list)
    updated_at: datetime


class SellerProjection(VerifundModel):
    transaction_id: str
    run_id: str
    state: TransactionState
    seller_id: str
    amount_cents: int
    currency: str
    agreement_id: str | None = None
    agreement_hash: str
    agreement_version: int
    quantity: int
    line_items: list[AwardLineItem]
    delivery_days: int
    warranty_months: int
    returns_days: int
    purchase_order: PurchaseOrderProjection | None = None
    evidence: EvidenceSummary | None = None
    requirements: list[Requirement] = Field(default_factory=list)
    payout: PayoutProjection | None = None
    dispute: DisputeProjection | None = None
    deadlines: dict[str, datetime | None]
    allowed_actions: list[str] = Field(default_factory=list)
    updated_at: datetime


class SellerLineItem(VerifundModel):
    sku: str
    name: str
    quantity: int


class SellerEvidenceCount(VerifundModel):
    submitted: int = 0
    required: int = 0
    complete: bool = False
    received_kinds: list[str] = Field(default_factory=list)


class SellerPayoutStatus(VerifundModel):
    status: str  # pending | paid | failed | none
    amount_cents: int
    updated_at: datetime | None = None


class SellerTransactionSummary(VerifundModel):
    transaction_id: str
    run_id: str
    state: TransactionState
    agreement_id: str | None = None
    agreement_version: int
    amount_cents: int
    currency: str
    quantity: int
    line_items: list[SellerLineItem] = Field(default_factory=list)
    delivery_days: int
    warranty_months: int
    returns_days: int
    deadlines: dict[str, datetime | None] = Field(default_factory=dict)
    evidence: SellerEvidenceCount = Field(default_factory=SellerEvidenceCount)
    allowed_actions: list[str] = Field(default_factory=list)
    next_action: str = "none"
    payout: SellerPayoutStatus | None = None
    updated_at: datetime


class SellerTransactionList(VerifundModel):
    items: list[SellerTransactionSummary]
    counts_by_state: dict[str, int] = Field(default_factory=dict)
    next_cursor: str | None = None


class SellerEvidenceEntry(VerifundModel):
    evidence_id: str
    transaction_id: str
    requirement_id: str | None = None
    kind: str
    media_type: str
    size_bytes: int
    original_filename: str
    note: str | None = None
    captured_at: datetime | None = None
    created_at: datetime
    scan_status: str | None = None
    transaction_state: TransactionState
    verification: dict[str, Any] | None = None


class SellerEvidenceLibrary(VerifundModel):
    items: list[SellerEvidenceEntry]
    next_cursor: str | None = None


class SellerPayoutEntry(VerifundModel):
    transaction_id: str
    amount_cents: int
    currency: str
    state: TransactionState
    payout: SellerPayoutStatus | None = None


class SellerPayoutTotals(VerifundModel):
    pending_cents: int = 0
    paid_cents: int = 0
    failed_cents: int = 0


class SellerPayoutView(VerifundModel):
    transactions: list[SellerPayoutEntry]
    totals: SellerPayoutTotals


class ReceiptPayload(VerifundModel):
    receipt_version: int = 1
    transaction_id: str
    agreement_hash: str
    amount_cents: int
    currency: str
    buyer_id: str
    seller_id: str
    capture_id: str
    payout_item_id: str
    evidence_hashes: list[str]
    released_at: datetime


class ReceiptResponse(VerifundModel):
    payload: ReceiptPayload
    payload_hash: str
    signature: str
    kid: str
    verified: bool


class TransactionEvent(VerifundModel):
    seq: int
    type: str
    payload: dict[str, Any]
    actor: str
    created_at: datetime


class ErrorDetail(VerifundModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorEnvelope(VerifundModel):
    error: ErrorDetail
