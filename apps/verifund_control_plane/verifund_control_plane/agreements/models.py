from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from verifund_contracts.models import AgreementDecision, AgreementState, ChangeOperation


@dataclass
class ActorContext:
    actor_id: str
    actor_type: str
    display_name: str = ""


@dataclass
class AgreementVersion:
    agreement_id: str
    version: int
    terms: dict[str, Any]
    agreement_hash: str
    rendered_html: str
    renderer_version: str
    created_at: datetime
    supersedes_version: int | None = None
    change_request_id: str | None = None
    superseded_at: datetime | None = None


@dataclass
class Agreement:
    agreement_id: str
    transaction_id: str
    run_id: str
    buyer_id: str
    seller_id: str
    current_version: int
    status: AgreementState
    offer_id: str
    offer_round: int
    offer_hash: str
    offer_valid_until: datetime
    expires_at: datetime | None
    agreed_at: datetime | None
    rejected_at: datetime | None
    expired_at: datetime | None
    terminated_at: datetime | None
    terminal_reason: str | None
    seller_operator_required: bool
    row_version: int
    created_at: datetime
    updated_at: datetime
    current_version_record: AgreementVersion | None = None


@dataclass
class AgreementDecisionRecord:
    decision_id: str
    agreement_id: str
    version: int
    party: str
    decision: AgreementDecision
    actor_type: str
    actor_id: str
    authority_ref: str | None
    authority_snapshot: dict[str, Any]
    agreement_hash: str
    verified_offer_hash: str | None
    verified_change_request_id: str | None
    reason_code: str | None
    note: str
    change_request_id: str | None
    idempotency_key: str
    decided_at: datetime


@dataclass
class ChangeRequest:
    change_request_id: str
    agreement_id: str
    base_version: int
    base_hash: str
    requested_by_party: str
    requested_by_actor_type: str
    requested_by_actor_id: str
    operations: list[ChangeOperation]
    reason: str
    status: str
    resolved_by_party: str | None = None
    resolved_by_actor_type: str | None = None
    resolved_by_actor_id: str | None = None
    resolution_note: str = ""
    resulting_version: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(__import__("datetime").timezone.utc))
    resolved_at: datetime | None = None


@dataclass
class ApprovalTokenRecord:
    jti: str
    agreement_id: str
    version: int
    agreement_hash: str
    subject_id: str
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    revoked_at: datetime | None = None
    issued_by_actor_type: str = ""
    issued_by_actor_id: str = ""
    consumed_by_decision_id: str | None = None


@dataclass
class AgreementEvent:
    event_id: int | None
    agreement_id: str
    version: int | None
    event_type: str
    payload: dict[str, Any]
    actor_type: str
    actor_id: str
    created_at: datetime


class AgreementError(Exception):
    def __init__(self, code: str, message: str, *, agreement_id: str | None = None,
                 version: int | None = None, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.agreement_id = agreement_id
        self.version = version
        self.field = field
