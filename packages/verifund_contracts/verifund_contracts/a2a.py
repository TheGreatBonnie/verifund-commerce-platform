from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from verifund_contracts.models import (
    AgreementProjection,
    AgreementReviewDecision,
    BuyerApprovalDecision,
    ChangeOperation,
    ChangeSet,
    TransactionState,
    VerifundModel,
)

VERIFUND_SCHEMA_BASE = "https://marketmesh.example/extensions/verifund/v2/schemas"
AGREEMENT_REVIEW_REQUEST_SCHEMA = f"{VERIFUND_SCHEMA_BASE}/agreement-review-request.json"
AGREEMENT_REVIEW_RESULT_SCHEMA = f"{VERIFUND_SCHEMA_BASE}/agreement-review-result.json"
VERIFUND_TASK_REQUEST_SCHEMA = f"{VERIFUND_SCHEMA_BASE}/task-request.json"
VERIFUND_TASK_RESULT_SCHEMA = f"{VERIFUND_SCHEMA_BASE}/task-result.json"
VERIFUND_RESUME_REQUEST_SCHEMA = f"{VERIFUND_SCHEMA_BASE}/resume-request.json"


class VerifundSkill(StrEnum):
    AGREEMENT_CREATE = "verifund.agreement.create"
    TRANSACTION_STATUS = "verifund.transaction.status"
    TRANSACTION_FUND = "verifund.transaction.fund"
    EVIDENCE_REVIEW = "verifund.evidence.review"
    TRANSACTION_RELEASE = "verifund.transaction.release"
    RECEIPT_GET = "verifund.receipt.get"


class VerifundCheckpoint(StrEnum):
    BUYER_REVIEW_REQUIRED = "buyer_review_required"
    SELLER_REVIEW_REQUIRED = "seller_review_required"
    BUYER_APPROVAL_REQUIRED = "buyer_approval_required"          # NEW
    SELLER_OPERATOR_REQUIRED = "seller_operator_required"        # NEW
    AGREEMENT_CHANGES_REQUESTED = "agreement_changes_requested"  # NEW
    FUNDING_APPROVAL_REQUIRED = "funding_approval_required"
    FUNDING_PENDING = "funding_pending"
    PURCHASE_ORDER_REQUIRED = "purchase_order_required"
    EVIDENCE_PENDING = "evidence_pending"
    RELEASE_APPROVAL_REQUIRED = "release_approval_required"


class ChangeRequestEnvelope(VerifundModel):
    """Carries the change-request identity the seller needs to verify the chain."""

    change_request_id: str = Field(min_length=1)
    base_version: int = Field(ge=1)
    base_hash: str = Field(pattern="^[0-9a-f]{64}$")
    operations: list[ChangeOperation] = Field(min_length=1)
    reason: str = ""


class AgreementReviewRequest(VerifundModel):
    party: Literal["buyer", "seller"]
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    agreement: AgreementProjection
    buyer_task_id: str | None = None
    buyer_context_id: str | None = None
    seller_task_id: str | None = None
    seller_context_id: str | None = None
    requested_at: datetime
    idempotency_key: str = Field(min_length=1)
    change_request: ChangeRequestEnvelope | None = None   # NEW (for N+1)

    @model_validator(mode="after")
    def _party_task_is_present(self) -> AgreementReviewRequest:
        if self.party == "buyer" and not (
            self.buyer_task_id and self.buyer_context_id
        ):
            raise ValueError("buyer review requires buyer task and context ids")
        if self.party == "seller" and not (
            self.seller_task_id and self.seller_context_id
        ):
            raise ValueError("seller review requires seller task and context ids")
        return self


class AgreementReviewResult(VerifundModel):
    party: Literal["buyer", "seller"]
    status: AgreementReviewDecision
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    offer_hash: str = Field(pattern="^[0-9a-f]{64}$")  # NEW
    actor_type: str = Field(min_length=1)               # NEW
    actor_id: str = Field(min_length=1)                # NEW
    authority_ref: str | None = None                    # NEW
    authority_snapshot: dict[str, Any] = Field(default_factory=dict)  # NEW
    verified_change_request_id: str | None = None       # NEW
    task_id: str = Field(min_length=1)
    context_id: str = Field(min_length=1)
    reviewed_at: datetime
    reason_code: str | None = None
    note: str = ""


class BuyerAgreementApprovalDecision(VerifundModel):
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    decision: BuyerApprovalDecision
    note: str = ""
    change_set: ChangeSet | None = None
    idempotency_key: str = Field(min_length=1)


class VerifundTaskRequest(VerifundModel):
    skill: VerifundSkill
    run_id: str = Field(min_length=1)
    transaction_id: str | None = None
    agreement_version: int | None = Field(default=None, ge=1)
    agreement_hash: str | None = Field(
        default=None, pattern="^[0-9a-f]{64}$"
    )
    actor: str = "orchestrator"
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1)


class VerifundResumeRequest(VerifundModel):
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    checkpoint: VerifundCheckpoint
    value: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1)

    @model_validator(mode="after")
    def _polling_checkpoints_are_not_resumed(self) -> VerifundResumeRequest:
        if self.checkpoint in {
            VerifundCheckpoint.FUNDING_PENDING,
            VerifundCheckpoint.EVIDENCE_PENDING,
        }:
            raise ValueError(
                "funding_pending and evidence_pending are polled, not resumed"
            )
        return self


class VerifundTaskResult(VerifundModel):
    skill: VerifundSkill
    status: Literal[
        "completed", "input_required", "approval_required", "failed"
    ]
    task_id: str | None = None
    checkpoint: VerifundCheckpoint | None = None
    approval_type: Literal["funding", "release"] | None = None
    run_id: str = Field(min_length=1)
    transaction_id: str | None = None
    agreement_version: int | None = None
    agreement_hash: str | None = None
    state: TransactionState | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    retryable: bool = False
    next_action: str | None = None

    @model_validator(mode="after")
    def _checkpoint_contract(self) -> VerifundTaskResult:
        if self.status == "approval_required":
            expected = {
                VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED: "funding",
                VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED: "release",
            }.get(self.checkpoint)
            if expected is None or self.approval_type != expected:
                raise ValueError(
                    "approval_required requires a matching approval_type"
                )
        elif self.status == "input_required":
            if self.checkpoint not in {
                VerifundCheckpoint.BUYER_REVIEW_REQUIRED,
                VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
                VerifundCheckpoint.BUYER_APPROVAL_REQUIRED,
                VerifundCheckpoint.SELLER_OPERATOR_REQUIRED,
                VerifundCheckpoint.AGREEMENT_CHANGES_REQUESTED,
                VerifundCheckpoint.PURCHASE_ORDER_REQUIRED,
            }:
                raise ValueError(
                    "input_required requires a review or order checkpoint"
                )
            if self.approval_type is not None:
                raise ValueError("approval_type is only valid for approvals")
        elif self.approval_type is not None:
            raise ValueError("approval_type is only valid for approvals")
        return self


def _wrap(schema: str, model: VerifundModel) -> dict[str, Any]:
    return {
        "schema": schema,
        "schema_version": "1.0",
        "payload": model.model_dump(mode="json"),
    }


def _unwrap(
    envelope: dict[str, Any], expected_schema: str
) -> dict[str, Any]:
    if envelope.get("schema") != expected_schema:
        raise ValueError(f"unexpected schema: {envelope.get('schema')}")
    if envelope.get("schema_version") != "1.0":
        raise ValueError(
            f"unsupported schema version: {envelope.get('schema_version')}"
        )
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("envelope payload must be an object")
    return payload


def wrap_agreement_review_request(request: AgreementReviewRequest) -> dict[str, Any]:
    return _wrap(AGREEMENT_REVIEW_REQUEST_SCHEMA, request)


def parse_agreement_review_request(envelope: dict[str, Any]) -> AgreementReviewRequest:
    return AgreementReviewRequest.model_validate(
        _unwrap(envelope, AGREEMENT_REVIEW_REQUEST_SCHEMA)
    )


def wrap_agreement_review_result(result: AgreementReviewResult) -> dict[str, Any]:
    return _wrap(AGREEMENT_REVIEW_RESULT_SCHEMA, result)


def parse_agreement_review_result(
    envelope: dict[str, Any],
    *,
    expected_party: str,
    expected_transaction_id: str,
    expected_version: int,
    expected_hash: str,
) -> AgreementReviewResult:
    result = AgreementReviewResult.model_validate(
        _unwrap(envelope, AGREEMENT_REVIEW_RESULT_SCHEMA)
    )
    if result.party != expected_party:
        raise ValueError(f"expected a {expected_party} review result")
    if result.transaction_id != expected_transaction_id:
        raise ValueError("review result transaction does not match")
    if result.agreement_version != expected_version:
        raise ValueError("review result version does not match")
    if result.agreement_hash != expected_hash:
        raise ValueError("review result hash does not match")
    return result


def wrap_verifund_task_request(request: VerifundTaskRequest) -> dict[str, Any]:
    return _wrap(VERIFUND_TASK_REQUEST_SCHEMA, request)


def parse_verifund_task_request(envelope: dict[str, Any]) -> VerifundTaskRequest:
    return VerifundTaskRequest.model_validate(
        _unwrap(envelope, VERIFUND_TASK_REQUEST_SCHEMA)
    )


def wrap_verifund_task_result(result: VerifundTaskResult) -> dict[str, Any]:
    return _wrap(VERIFUND_TASK_RESULT_SCHEMA, result)


def parse_verifund_task_result(envelope: dict[str, Any]) -> VerifundTaskResult:
    return VerifundTaskResult.model_validate(
        _unwrap(envelope, VERIFUND_TASK_RESULT_SCHEMA)
    )


def wrap_verifund_resume_request(request: VerifundResumeRequest) -> dict[str, Any]:
    return _wrap(VERIFUND_RESUME_REQUEST_SCHEMA, request)


def parse_verifund_resume_request(
    envelope: dict[str, Any],
) -> VerifundResumeRequest:
    return VerifundResumeRequest.model_validate(
        _unwrap(envelope, VERIFUND_RESUME_REQUEST_SCHEMA)
    )
