from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any

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
    CANCELED = "CANCELED"
    FAILED = "FAILED"


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


class CancelReason(StrEnum):
    BUYER_REJECTED = "buyer_rejected"
    BUYER_CANCELLED = "buyer_cancelled"
    REVIEWER_CANCELLED = "reviewer_cancelled"
    FUNDING_EXPIRED = "funding_expired"


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


class AwardLineItem(VerifundModel):
    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)
    warranty_addon_cents: int = Field(default=0, ge=0)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class AgreementProjection(VerifundModel):
    agreement_version: int = Field(ge=1)
    transaction_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    buyer_id: str = Field(min_length=1)
    seller_id: str = Field(min_length=1)
    offer_id: str = Field(min_length=1)
    currency: str = Field(default="USD", pattern="^USD$")
    amount_cents: int = Field(gt=0)
    quantity: int = Field(gt=0)
    line_items: list[AwardLineItem] = Field(min_length=1)
    shipping_cents: int = Field(ge=0)
    delivery_days: int = Field(ge=0)
    warranty_months: int = Field(ge=0)
    returns_days: int = Field(ge=0)
    created_at: str = Field(min_length=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"agreement_hash"})

    def recompute_hash(self) -> str:
        return sha256_hex(canonical_json(self.canonical_payload()))

    @model_validator(mode="after")
    def _hash_must_match(self) -> AgreementProjection:
        if self.recompute_hash() != self.agreement_hash:
            raise ValueError("agreement hash does not match canonical payload")
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
    delivery_days: int = Field(ge=0)
    warranty_months: int = Field(ge=0)
    returns_days: int = Field(ge=0)

    @model_validator(mode="after")
    def _totals_must_match(self) -> AwardRequest:
        line_quantity = sum(item.quantity for item in self.line_items)
        if line_quantity != self.quantity:
            raise ValueError("quantity must equal the sum of line-item quantities")
        line_total = sum(
            (item.unit_price_cents + item.warranty_addon_cents) * item.quantity
            for item in self.line_items
        )
        if line_total + self.shipping_cents != self.amount_cents:
            raise ValueError("amount_cents must equal line items plus shipping")
        return self


class AwardResponse(VerifundModel):
    transaction_id: str
    state: TransactionState
    agreement_hash: str
    agreement: AgreementProjection
    agreement_version: int = Field(ge=1)
    seller_token: str
    expires_at: datetime


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


class CancelRequest(VerifundModel):
    reason_code: CancelReason
    note: str = ""

    @model_validator(mode="after")
    def _reject_reconciler_only_reason(self) -> CancelRequest:
        if self.reason_code == CancelReason.FUNDING_EXPIRED:
            raise ValueError("funding_expired is set by the reconciler")
        return self


class FundRequest(VerifundModel):
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
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
    kind: str
    sha256: str
    media_type: str
    size_bytes: int
    original_filename: str
    note: str | None = None
    created_at: datetime


class EvidenceSummary(VerifundModel):
    required: list[str]
    received: list[str]
    complete: bool
    deadline: datetime | None = None
    items: list[EvidenceItem]


class VerificationProjection(VerifundModel):
    status: str
    reasons: list[str] = Field(default_factory=list)
    checked_at: datetime | None = None
    override_allowed: bool = False


class PayoutProjection(VerifundModel):
    status: str
    batch_id: str | None = None
    item_id: str | None = None
    amount_cents: int | None = None
    updated_at: datetime | None = None


class EvidenceList(VerifundModel):
    items: list[EvidenceItem]


class TransactionProjection(VerifundModel):
    transaction_id: str
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
    payout: PayoutProjection | None = None
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
    agreement_hash: str
    agreement_version: int
    quantity: int
    line_items: list[AwardLineItem]
    delivery_days: int
    warranty_months: int
    returns_days: int
    purchase_order: PurchaseOrderProjection | None = None
    evidence: EvidenceSummary | None = None
    deadlines: dict[str, datetime | None]
    allowed_actions: list[str] = Field(default_factory=list)
    updated_at: datetime


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
