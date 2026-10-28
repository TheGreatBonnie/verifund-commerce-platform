from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

from verifund_contracts import (
    AcceptRequest,
    AgreementProjection,
    ApproveRequest,
    AwardLineItem,
    AwardRequest,
    BuyerAgreementReviewRequest,
    CancelRequest,
    EvidenceItem,
    EvidenceKind,
    EvidenceSummary,
    FundRequest,
    FundResponse,
    ReviewReason,
    RejectRequest,
    SellerProjection,
    TransactionProjection,
    TransactionState,
)
from verifund_control_plane.domain import (
    EVIDENCE_UPLOAD_STATES,
    REQUIRED_EVIDENCE,
    TransactionRecord,
    capture_ledger_entries,
    agreement_hash,
    allowed_actions,
    build_agreement,
    canonical_json,
    sha256_hex,
    validate_award,
)
from verifund_control_plane.evidence import EvidenceStore
from verifund_control_plane.policy import evaluate
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import (
    AgreementReviewInput,
    AuditInput,
    EventInput,
    Repository,
)
from verifund_control_plane.settings import Settings
from verifund_control_plane.paypal.port import CaptureResult, PaymentPort
from verifund_control_plane.tokens import LinkSigner, SellerTokenService

Mutation = Callable[[Any], Awaitable[dict[str, Any]]]


class VerifundService:
    def __init__(
        self,
        *,
        repo: Repository,
        settings: Settings,
        clock: Callable[[], datetime],
        tokens: SellerTokenService,
        evidence_store: EvidenceStore,
        payments: PaymentPort,
        links: LinkSigner,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.clock = clock
        self.tokens = tokens
        self.evidence_store = evidence_store
        self.payments = payments
        self.links = links

    def _now(self) -> datetime:
        return self.clock()

    def _iso(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    async def _replay(
        self, scope: str, key: str | None, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not key:
            return None
        return await self.repo.get_idempotency(
            scope, key, sha256_hex(canonical_json(body))
        )

    async def _mutate(
        self,
        *,
        scope: str,
        key: str | None,
        body: dict[str, Any],
        operation: Mutation,
    ) -> dict[str, Any]:
        request_hash = sha256_hex(canonical_json(body))
        cached = await self._replay(scope, key, body)
        if cached is not None:
            return cached
        async with self.repo.transaction() as conn:
            if key:
                cached = await self.repo.get_idempotency_on(
                    conn, scope, key, request_hash
                )
                if cached is not None:
                    return cached
            result = await operation(conn)
            if key:
                await self.repo.put_idempotency(
                    conn, scope, key, request_hash, result
                )
            return result

    @staticmethod
    def _pick(
        value: dict[str, Any] | None, fields: tuple[str, ...]
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        return {key: value[key] for key in fields if key in value}

    async def _projection(
        self,
        record: TransactionRecord,
        actor: str,
        *,
        items: list[EvidenceItem] | None = None,
    ) -> TransactionProjection:
        evidence_items = items or []
        received = sorted({item.kind for item in evidence_items})
        deadlines = {
            key: (
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                if isinstance(value, str)
                else value
            )
            for key, value in (record.deadlines or {}).items()
        }
        summary = EvidenceSummary(
            required=list(REQUIRED_EVIDENCE),
            received=received,
            complete=all(kind in received for kind in REQUIRED_EVIDENCE),
            deadline=deadlines.get("evidence"),
            items=evidence_items,
        )
        return TransactionProjection(
            transaction_id=record.transaction_id,
            run_id=record.run_id,
            state=record.state,
            last_seq=record.last_seq,
            amount_cents=record.amount_cents,
            currency=record.currency,
            buyer_id=record.buyer_id,
            seller_id=record.seller_id,
            agreement_hash=record.agreement_hash,
            agreement_version=record.agreement_version,
            buyer_agent_review=self._pick(
                record.buyer_agent_review,
                (
                    "status",
                    "agreement_version",
                    "agreement_hash",
                    "task_id",
                    "reviewed_at",
                    "reason_code",
                    "note",
                ),
            ),
            seller_decision=self._pick(
                record.seller_decision,
                ("status", "reported_at", "reason_code", "note"),
            ),
            approval=self._pick(
                record.approval, ("approved_by", "approved_at", "note")
            ),
            cancellation=self._pick(
                record.cancellation, ("reason_code", "note", "at")
            ),
            funding=self._pick(
                record.funding,
                (
                    "status",
                    "provider_order_id",
                    "capture_id",
                    "payer_action_url",
                    "completed_at",
                ),
            ),
            purchase_order=self._pick(
                record.purchase_order,
                ("seller_order_id", "tracking_number", "carrier", "eta"),
            ),
            evidence=summary,
            verification=self._pick(
                record.verification,
                ("status", "reasons", "checked_at", "override_allowed"),
            ),
            payout=self._pick(
                record.payout,
                ("status", "batch_id", "item_id", "amount_cents", "updated_at"),
            ),
            receipt_available=record.receipt is not None,
            deadlines=deadlines,
            allowed_actions=allowed_actions(record.state, actor),
            updated_at=record.updated_at,
        )

    async def _projection_for(
        self, transaction_id: str, actor: str
    ) -> TransactionProjection:
        record = await self.repo.get_transaction(transaction_id)
        items = await self.repo.list_evidence(transaction_id)
        return await self._projection(record, actor, items=items)

    async def award(
        self, request: AwardRequest, *, actor: str, idempotency_key: str | None
    ) -> dict[str, Any]:
        validate_award(request)
        if self.settings.is_sandbox and not self.settings.payout_email_for(
            request.seller_id
        ):
            raise VerifundError(
                "invalid_request",
                f"no payout email configured for {request.seller_id}",
                status_code=400,
            )
        now = self._now()
        transaction_id = f"vf_{uuid.uuid4().hex}"
        agreement = build_agreement(transaction_id, request, now)
        digest = agreement_hash(agreement)
        record = TransactionRecord(
            transaction_id=transaction_id,
            run_id=request.run_id,
            buyer_id=request.buyer_id,
            seller_id=request.seller_id,
            offer_id=request.offer_id,
            state=TransactionState.AWARDED,
            version=1,
            last_seq=0,
            amount_cents=request.amount_cents,
            currency=request.currency,
            agreement_id=f"agr_{uuid.uuid4().hex}",
            agreement_hash=digest,
            agreement_version=1,
            buyer_agent_review=None,
            seller_decision=None,
            approval=None,
            cancellation=None,
            funding=None,
            purchase_order=None,
            evidence_summary=None,
            verification=None,
            payout=None,
            receipt=None,
            deadlines={"funding": None, "evidence": None, "inspection": None},
            last_error=None,
            created_at=now,
            updated_at=now,
        )
        issued = self.tokens.issue(
            transaction_id, request.seller_id, digest
        )
        projection = AgreementProjection(
            **agreement,
            agreement_hash=digest,
        )
        response = {
            "transaction_id": transaction_id,
            "state": TransactionState.AWARDED.value,
            "agreement_hash": digest,
            "agreement_version": projection.agreement_version,
            "agreement": projection.model_dump(mode="json"),
            "seller_token": issued.token,
            "expires_at": self._iso(issued.expires_at),
        }

        async def operation(conn):
            await self.repo.insert_transaction(
                conn,
                record,
                agreement=agreement,
                events=[
                    EventInput(
                        "award_created",
                        {
                            "run_id": request.run_id,
                            "seller_id": request.seller_id,
                            "amount_cents": request.amount_cents,
                        },
                        actor,
                    )
                ],
                audit=AuditInput(actor, "award_created"),
            )
            await self.repo.save_seller_token(
                conn,
                issued.jti_hash,
                transaction_id,
                request.seller_id,
                digest,
                ["txn:read", "evidence:write"],
                issued.expires_at,
            )
            return response

        return await self._mutate(
            scope="award",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )

    async def list_transactions(
        self,
        *,
        actor: str,
        run_id: str | None = None,
        state: str | None = None,
        seller_id: str | None = None,
    ) -> list[dict[str, Any]]:
        records = await self.repo.list_transactions(
            run_id=run_id, state=state, seller_id=seller_id
        )
        result = []
        for record in records:
            items = await self.repo.list_evidence(record.transaction_id)
            result.append(
                (
                    await self._projection(record, actor, items=items)
                ).model_dump(mode="json")
            )
        return result

    async def get_transaction(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]:
        return (
            await self._projection_for(transaction_id, actor)
        ).model_dump(mode="json")

    async def events(
        self, transaction_id: str, *, after_seq: int = 0
    ) -> list[dict[str, Any]]:
        await self.repo.get_transaction(transaction_id)
        return await self.repo.events(transaction_id, after_seq=after_seq)

    def _check_hash(self, record: TransactionRecord, digest: str) -> None:
        if record.agreement_hash != digest:
            raise VerifundError(
                "hash_mismatch",
                "agreement hash does not match the stored agreement",
                status_code=409,
            )

    async def record_buyer_review(
        self,
        transaction_id: str,
        request: BuyerAgreementReviewRequest,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        items = await self.repo.list_evidence(transaction_id)
        async def operation(conn):
            record = await self.repo.get_transaction(transaction_id, conn)
            if record.buyer_id != request.buyer_id:
                raise VerifundError(
                    "forbidden",
                    "buyer does not own this transaction",
                    status_code=403,
                )
            if (
                request.agreement_version != record.agreement_version
                or request.agreement_hash != record.agreement_hash
            ):
                raise VerifundError(
                    "hash_mismatch",
                    "agreement hash does not match the stored agreement",
                    status_code=409,
                )
            review = {
                "status": request.decision.value,
                "agreement_version": request.agreement_version,
                "agreement_hash": request.agreement_hash,
                "task_id": request.buyer_task_id,
                "reviewed_at": self._iso(request.reviewed_at),
                "reason_code": request.reason_code,
                "note": request.note,
            }
            if record.state == TransactionState.CANCELED and (
                record.buyer_agent_review or {}
            ).get("task_id") == request.buyer_task_id:
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state not in {
                TransactionState.AWARDED,
                TransactionState.AGREED,
            }:
                raise VerifundError(
                    "invalid_state",
                    "transaction is not awaiting buyer review",
                    status_code=409,
                )
            if request.decision.value == "accepted":
                changes = {"buyer_agent_review": review}
                events = [
                    EventInput(
                        "buyer_accepted",
                        {"buyer_task_id": request.buyer_task_id},
                        actor,
                    )
                ]
                if (
                    record.state == TransactionState.AWARDED
                    and (record.seller_decision or {}).get("status") == "accepted"
                ):
                    updated = await self.repo.transition(
                        conn,
                        transaction_id,
                        expected_version=record.version,
                        expected_state=TransactionState.AWARDED,
                        new_state=TransactionState.AGREED,
                        changes=changes,
                        events=events,
                        audit=AuditInput(
                            actor, "buyer_accepted"
                        ),
                    )
                else:
                    updated = await self.repo.update_transaction(
                        conn,
                        transaction_id,
                        expected_version=record.version,
                        changes=changes,
                        events=events,
                        audit=AuditInput(
                            actor, "buyer_accepted"
                        ),
                    )
            else:
                cancellation = {
                    "reason_code": "buyer_rejected",
                    "note": request.note,
                    "at": self._iso(request.reviewed_at),
                }
                changes = {
                    "buyer_agent_review": review,
                    "cancellation": cancellation,
                }
                updated = await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=record.version,
                    expected_state=record.state,
                    new_state=TransactionState.CANCELED,
                    changes=changes,
                    events=[
                        EventInput(
                            "buyer_rejected",
                            {
                                "reason_code": request.reason_code,
                                "buyer_task_id": request.buyer_task_id,
                            },
                            actor,
                        ),
                        EventInput("canceled", cancellation, actor),
                    ],
                    audit=AuditInput(
                        actor, "buyer_rejected", note=request.note
                    ),
                )
                await self.repo.revoke_seller_tokens(conn, transaction_id, self._now())
            await self.repo.record_agreement_review(
                conn,
                AgreementReviewInput(
                    transaction_id=transaction_id,
                    agreement_version=request.agreement_version,
                    agreement_hash=request.agreement_hash,
                    party="buyer",
                    decision=request.decision.value,
                    task_id=request.buyer_task_id,
                    note=request.note,
                    reason_code=request.reason_code,
                    idempotency_key=idempotency_key or f"buyer:{transaction_id}:{request.buyer_task_id}:{request.decision.value}",
                    reviewed_at=request.reviewed_at,
                ),
            )
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")

        return await self._mutate(
            scope=f"buyer-review:{transaction_id}",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )

    async def accept(
        self,
        transaction_id: str,
        request: AcceptRequest,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        items = await self.repo.list_evidence(transaction_id)
        async def operation(conn):
            record = await self.repo.get_transaction(transaction_id, conn)
            if record.seller_id != request.seller_id:
                raise VerifundError(
                    "forbidden", "seller does not own this transaction", status_code=403
                )
            self._check_hash(record, request.agreement_hash)
            if request.accepted_total_cents != record.amount_cents:
                raise VerifundError(
                    "invalid_request", "accepted total does not match", status_code=400
                )
            if record.state == TransactionState.AGREED:
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state != TransactionState.AWARDED:
                raise VerifundError(
                    "invalid_state", "transaction is not awaiting acceptance", status_code=409
                )
            changes = {
                "seller_decision": {
                    "status": "accepted",
                    "reported_at": self._iso(request.accepted_at),
                    "seller_task_id": request.seller_task_id,
                    "agreement_hash": request.agreement_hash,
                }
            }
            events = [
                EventInput(
                    "seller_accepted",
                    {"seller_task_id": request.seller_task_id},
                    actor,
                )
            ]
            if (record.buyer_agent_review or {}).get("status") == "accepted":
                updated = await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=record.version,
                    expected_state=TransactionState.AWARDED,
                    new_state=TransactionState.AGREED,
                    changes=changes,
                    events=events,
                    audit=AuditInput(actor, "seller_accepted"),
                )
            else:
                updated = await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=record.version,
                    changes=changes,
                    events=events,
                    audit=AuditInput(actor, "seller_accepted_waiting_for_buyer_review"),
                )
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")

        return await self._mutate(
            scope=f"accept:{transaction_id}",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )

    async def reject(
        self,
        transaction_id: str,
        request: RejectRequest,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        items = await self.repo.list_evidence(transaction_id)
        async def operation(conn):
            record = await self.repo.get_transaction(transaction_id, conn)
            if record.seller_id != request.seller_id:
                raise VerifundError(
                    "forbidden", "seller does not own this transaction", status_code=403
                )
            self._check_hash(record, request.agreement_hash)
            if record.state == TransactionState.CANCELED and (
                record.cancellation or {}
            ).get("reason_code") == "seller_rejected":
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state != TransactionState.AWARDED:
                raise VerifundError(
                    "invalid_state", "transaction is not awaiting acceptance", status_code=409
                )
            cancellation = {
                "reason_code": "seller_rejected",
                "seller_reason_code": request.reason_code.value,
                "note": request.note,
                "at": self._iso(request.rejected_at),
                "seller_task_id": request.seller_task_id,
            }
            updated = await self.repo.transition(
                conn,
                transaction_id,
                expected_version=record.version,
                expected_state=TransactionState.AWARDED,
                new_state=TransactionState.CANCELED,
                changes={
                    "seller_decision": {
                        "status": "rejected",
                        "reported_at": self._iso(request.rejected_at),
                        "reason_code": request.reason_code.value,
                        "note": request.note,
                        "seller_task_id": request.seller_task_id,
                    },
                    "cancellation": cancellation,
                },
                events=[
                    EventInput(
                        "seller_rejected",
                        {
                            "reason_code": request.reason_code.value,
                            "seller_task_id": request.seller_task_id,
                        },
                        actor,
                    ),
                    EventInput("canceled", cancellation, actor),
                ],
                audit=AuditInput(
                    actor, "seller_rejected", note=request.note
                ),
            )
            await self.repo.revoke_seller_tokens(conn, transaction_id, self._now())
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")

        return await self._mutate(
            scope=f"reject:{transaction_id}",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )

    async def approve(
        self,
        transaction_id: str,
        request: ApproveRequest,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        items = await self.repo.list_evidence(transaction_id)
        async def operation(conn):
            record = await self.repo.get_transaction(transaction_id, conn)
            self._check_hash(record, request.agreement_hash)
            if (record.approval or {}).get("approval_id") == request.approval_id:
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state == TransactionState.AWARDED and (
                record.seller_decision or {}
            ).get("status") == "accepted":
                deadline = self._now() + timedelta(
                    hours=self.settings.funding_timeout_hours
                )
                updated = await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=record.version,
                    expected_state=TransactionState.AWARDED,
                    new_state=TransactionState.AGREED,
                    changes={
                        "approval": {
                            "approval_id": request.approval_id,
                            "approved_by": request.approved_by,
                            "approved_at": self._iso(request.approved_at),
                            "note": request.note,
                        },
                        "deadlines": {
                            **(record.deadlines or {}),
                            "funding": self._iso(deadline),
                        },
                    },
                    events=[
                        EventInput(
                            "buyer_approved",
                            {
                                "approval_id": request.approval_id,
                                "approved_by": request.approved_by,
                            },
                            actor,
                        )
                    ],
                    audit=AuditInput(
                        actor,
                        "buyer_approved",
                        note=request.note,
                        payload={"approval_id": request.approval_id},
                    ),
                )
                return (
                    await self._projection(updated, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state != TransactionState.AGREED:
                raise VerifundError(
                    "invalid_state", "transaction is not awaiting approval", status_code=409
                )
            deadline = self._now() + timedelta(
                hours=self.settings.funding_timeout_hours
            )
            updated = await self.repo.update_transaction(
                conn,
                transaction_id,
                expected_version=record.version,
                changes={
                    "approval": {
                        "approval_id": request.approval_id,
                        "approved_by": request.approved_by,
                        "approved_at": self._iso(request.approved_at),
                        "note": request.note,
                    },
                    "deadlines": {
                        **(record.deadlines or {}),
                        "funding": self._iso(deadline),
                    },
                },
                events=[
                    EventInput(
                        "buyer_approved",
                        {
                            "approval_id": request.approval_id,
                            "approved_by": request.approved_by,
                        },
                        actor,
                    )
                ],
                audit=AuditInput(
                    actor,
                    "buyer_approved",
                    note=request.note,
                    payload={"approval_id": request.approval_id},
                ),
            )
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")

        return await self._mutate(
            scope=f"approve:{transaction_id}",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )

    async def cancel(
        self,
        transaction_id: str,
        request: CancelRequest,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        items = await self.repo.list_evidence(transaction_id)
        allowed_states = {
            TransactionState.AWARDED,
            TransactionState.AGREED,
            TransactionState.FUNDING_PENDING,
            TransactionState.REVIEW_REQUIRED,
        }
        async def operation(conn):
            record = await self.repo.get_transaction(transaction_id, conn)
            if record.state == TransactionState.CANCELED:
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state not in allowed_states:
                raise VerifundError(
                    "invalid_state", "transaction cannot be canceled", status_code=409
                )
            funding = record.funding or {}
            if funding.get("status") in {"captured", "refunded"} or funding.get(
                "capture_id"
            ):
                raise VerifundError(
                    "forbidden",
                    "captured funds cannot be canceled; flag review instead",
                    status_code=403,
                )
            if record.state == TransactionState.REVIEW_REQUIRED:
                balances = await self.repo.ledger_balances(transaction_id)
                if balances.get("held_funds", 0) != 0:
                    raise VerifundError(
                        "forbidden", "ledger has captured funds", status_code=403
                    )
            cancellation = {
                "reason_code": request.reason_code.value,
                "note": request.note,
                "at": self._iso(self._now()),
            }
            updated = await self.repo.transition(
                conn,
                transaction_id,
                expected_version=record.version,
                expected_state=record.state,
                new_state=TransactionState.CANCELED,
                changes={"cancellation": cancellation},
                events=[EventInput("canceled", cancellation, actor)],
                audit=AuditInput(actor, "canceled", note=request.note),
            )
            await self.repo.revoke_seller_tokens(conn, transaction_id, self._now())
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")

        return await self._mutate(
            scope=f"cancel:{transaction_id}",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )

    async def add_evidence(
        self,
        transaction_id: str,
        *,
        seller_id: str,
        agreement_hash: str,
        kind: str,
        media_type: str,
        original_filename: str,
        data: bytes,
        note: str | None,
        captured_at: datetime | None,
        actor: str,
    ) -> EvidenceItem:
        record = await self.repo.get_transaction(transaction_id)
        if record.seller_id != seller_id:
            raise VerifundError(
                "forbidden", "seller does not own this transaction", status_code=403
            )
        if record.agreement_hash != agreement_hash:
            raise VerifundError(
                "hash_mismatch", "seller token hash is stale", status_code=409
            )
        if record.state not in EVIDENCE_UPLOAD_STATES:
            raise VerifundError(
                "invalid_state",
                "evidence cannot be uploaded in the current state",
                status_code=409,
            )
        item = await self.evidence_store.put(
            transaction_id=transaction_id,
            seller_id=seller_id,
            kind=kind,
            media_type=media_type,
            original_filename=original_filename,
            data=data,
            note=note,
            captured_at=captured_at,
        )
        new_state = record.state
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state not in EVIDENCE_UPLOAD_STATES:
                raise VerifundError(
                    "invalid_state",
                    "evidence cannot be uploaded in the current state",
                    status_code=409,
                )
            stored, created = await self.repo.add_evidence(
                conn,
                transaction_id,
                seller_id,
                item,
                captured_at=captured_at,
            )
            if not created:
                return stored
            event = EventInput(
                "evidence_received",
                {
                    "evidence_id": stored.evidence_id,
                    "kind": stored.kind,
                    "sha256": stored.sha256,
                },
                actor,
            )
            if current.state == TransactionState.FULFILLMENT_PENDING:
                updated = await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.VERIFICATION_PENDING,
                    changes={},
                    events=[event],
                    audit=AuditInput(actor, "evidence_received"),
                )
                new_state = updated.state
            else:
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes={},
                    events=[event],
                    audit=AuditInput(actor, "evidence_received"),
                )
        if new_state == TransactionState.VERIFICATION_PENDING:
            await self.verify_if_ready(transaction_id, actor="system")
        return stored

    async def seller_projection(
        self, transaction_id: str, *, seller_id: str
    ) -> SellerProjection:
        record = await self.repo.get_transaction(transaction_id)
        if record.seller_id != seller_id:
            raise VerifundError(
                "forbidden", "seller does not own this transaction", status_code=403
            )
        agreement = await self.repo.get_agreement(transaction_id)
        items = await self.repo.list_evidence(transaction_id)
        received = sorted({item.kind for item in items})
        deadlines = {
            key: (
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                if isinstance(value, str)
                else value
            )
            for key, value in (record.deadlines or {}).items()
        }
        return SellerProjection(
            transaction_id=record.transaction_id,
            run_id=record.run_id,
            state=record.state,
            seller_id=record.seller_id,
            amount_cents=record.amount_cents,
            currency=record.currency,
            agreement_hash=record.agreement_hash,
            agreement_version=record.agreement_version,
            quantity=agreement["quantity"],
            line_items=[
                AwardLineItem.model_validate(item)
                for item in agreement["line_items"]
            ],
            delivery_days=agreement["delivery_days"],
            warranty_months=agreement["warranty_months"],
            returns_days=agreement["returns_days"],
            purchase_order=self._pick(
                record.purchase_order,
                ("seller_order_id", "tracking_number", "carrier", "eta"),
            ),
            evidence=EvidenceSummary(
                required=list(REQUIRED_EVIDENCE),
                received=received,
                complete=all(kind in received for kind in REQUIRED_EVIDENCE),
                deadline=deadlines.get("evidence"),
                items=items,
            ),
            deadlines=deadlines,
            allowed_actions=allowed_actions(record.state, "seller"),
            updated_at=record.updated_at,
        )

    async def verify_if_ready(self, transaction_id: str, *, actor: str) -> None:
        record = await self.repo.get_transaction(transaction_id)
        if record.state != TransactionState.VERIFICATION_PENDING:
            return
        items = await self.repo.list_evidence(transaction_id)
        received = {item.kind for item in items}
        if not {"shipment_manifest", "delivery_confirmation"}.issubset(received):
            return
        await self.verify(transaction_id, actor=actor)

    async def verify(self, transaction_id: str, *, actor: str) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.state in {
            TransactionState.RELEASE_PERMITTED,
            TransactionState.REVIEW_REQUIRED,
        }:
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        items = await self.repo.list_evidence(transaction_id)
        if record.state == TransactionState.FULFILLMENT_PENDING:
            if not items:
                return (
                    await self._projection_for(transaction_id, "buyer")
                ).model_dump(mode="json")
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                if current.state == TransactionState.FULFILLMENT_PENDING:
                    await self.repo.transition(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        expected_state=TransactionState.FULFILLMENT_PENDING,
                        new_state=TransactionState.VERIFICATION_PENDING,
                        changes={},
                        audit=AuditInput(actor, "verification_started"),
                    )
            record = await self.repo.get_transaction(transaction_id)
        if record.state != TransactionState.VERIFICATION_PENDING:
            raise VerifundError(
                "invalid_state", "transaction is not awaiting verification", status_code=409
            )
        balances = await self.repo.ledger_balances(transaction_id)
        result = evaluate(
            record,
            items,
            self.evidence_store,
            self._now(),
            inspection_window_hours=self.settings.inspection_window_hours,
            ledger_balances=balances,
        )
        if result.waiting:
            deadline = result.inspection_deadline or (
                self._now()
                + timedelta(hours=self.settings.inspection_window_hours)
            )
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes={
                        "verification": {
                            "status": "pending",
                            "reasons": [reason.value for reason in result.reasons],
                            "checked_at": self._iso(self._now()),
                            "override_allowed": False,
                        },
                        "deadlines": {
                            **(current.deadlines or {}),
                            "inspection": self._iso(deadline),
                        },
                    },
                )
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        deadline = None
        raw_deadline = (record.deadlines or {}).get("evidence")
        if raw_deadline:
            try:
                deadline = datetime.fromisoformat(
                    str(raw_deadline).replace("Z", "+00:00")
                )
            except ValueError:
                deadline = None
        if not result.evidence_complete and deadline is not None and self._now() <= deadline:
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        reasons = list(result.reasons)
        if not result.evidence_complete and deadline is not None and self._now() > deadline:
            reasons.append(ReviewReason.EVIDENCE_DEADLINE_MISSED)
        if result.passed:
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                updated = await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=TransactionState.VERIFICATION_PENDING,
                    new_state=TransactionState.RELEASE_PERMITTED,
                    changes={
                        "verification": {
                            "status": "passed",
                            "reasons": [],
                            "checked_at": self._iso(self._now()),
                            "override_allowed": False,
                        }
                    },
                    events=[
                        EventInput("verification_passed", {}, actor),
                        EventInput("release_permitted", {}, actor),
                    ],
                    audit=AuditInput(actor, "verification_passed"),
                )
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            updated = await self.repo.transition(
                conn,
                transaction_id,
                expected_version=current.version,
                expected_state=TransactionState.VERIFICATION_PENDING,
                new_state=TransactionState.REVIEW_REQUIRED,
                changes={
                    "verification": {
                        "status": "failed",
                        "reasons": [reason.value for reason in reasons],
                        "checked_at": self._iso(self._now()),
                        "override_allowed": result.override_allowed,
                    }
                },
                events=[
                    EventInput(
                        "verification_failed",
                        {"reasons": [reason.value for reason in reasons]},
                        actor,
                    ),
                    EventInput("review_required", {}, actor),
                ],
                audit=AuditInput(
                    actor,
                    "verification_failed",
                    payload={"reasons": [reason.value for reason in reasons]},
                ),
            )
        return (
            await self._projection(updated, "buyer", items=items)
        ).model_dump(mode="json")

    def _validate_console_url(self, value: str) -> None:
        from urllib.parse import urlsplit

        allowed = urlsplit(self.settings.console_base_url)
        candidate = urlsplit(value)
        if not candidate.scheme or not candidate.netloc:
            raise VerifundError(
                "invalid_request", "return and cancel URLs must be absolute", status_code=400
            )
        allowed_netlocs = {
            allowed.netloc,
            urlsplit(self.settings.public_base_url).netloc,
            "127.0.0.1:3000",
            "localhost:3000",
        }
        if candidate.netloc not in allowed_netlocs:
            raise VerifundError(
                "invalid_request",
                "return and cancel URLs must use the console origin",
                status_code=400,
            )

    def _funding_deadline(self, record: TransactionRecord) -> datetime:
        value = (record.deadlines or {}).get("funding")
        if value:
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                pass
        return self._now() + timedelta(hours=self.settings.funding_timeout_hours)

    async def fund(
        self,
        transaction_id: str,
        request: FundRequest,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> FundResponse:
        body = request.model_dump(mode="json")
        scope = f"fund:{transaction_id}"
        cached = await self._replay(scope, idempotency_key, body)
        if cached is not None:
            return FundResponse.model_validate(cached)
        record = await self.repo.get_transaction(transaction_id)
        self._check_hash(record, request.agreement_hash)
        self._validate_console_url(request.return_url)
        self._validate_console_url(request.cancel_url)
        funding = record.funding or {}
        if record.state == TransactionState.FUNDING_PENDING and funding.get(
            "provider_order_id"
        ):
            return FundResponse(
                transaction_id=transaction_id,
                state=record.state,
                checkout_url=funding.get("checkout_url")
                or funding.get("payer_action_url")
                or "",
                expires_at=self._funding_deadline(record),
            )
        if record.state != TransactionState.AGREED:
            raise VerifundError(
                "invalid_state", "transaction is not ready for funding", status_code=409
            )
        if not record.approval:
            raise VerifundError(
                "invalid_state", "buyer approval is required", status_code=409
            )
        checkout_link = self.links.issue("checkout", transaction_id)
        return_link = self.links.issue("return", transaction_id)
        cancel_link = self.links.issue("cancel", transaction_id)
        if self.settings.is_fake:
            checkout_url = (
                f"{self.settings.public_base_url.rstrip('/')}"
                f"/checkout/fake/{checkout_link.token}"
            )
            provider_return = checkout_url
            provider_cancel = (
                f"{self.settings.public_base_url.rstrip('/')}"
                f"/cancel/{cancel_link.token}"
            )
        else:
            checkout_url = ""
            provider_return = (
                f"{self.settings.public_base_url.rstrip('/')}"
                f"/return/{return_link.token}"
            )
            provider_cancel = (
                f"{self.settings.public_base_url.rstrip('/')}"
                f"/cancel/{cancel_link.token}"
            )
        deadline = self._funding_deadline(record)
        operation_id = f"op_{uuid.uuid4().hex}"
        order_key = f"fund:{transaction_id}:v1"
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state == TransactionState.FUNDING_PENDING and (
                current.funding or {}
            ).get("provider_order_id"):
                return FundResponse(
                    transaction_id=transaction_id,
                    state=current.state,
                    checkout_url=(current.funding or {}).get("checkout_url")
                    or (current.funding or {}).get("payer_action_url")
                    or "",
                    expires_at=self._funding_deadline(current),
                )
            if current.state != TransactionState.AGREED:
                raise VerifundError(
                    "invalid_state",
                    "transaction is not ready for funding",
                    status_code=409,
                )
            await self.repo.transition(
                conn,
                transaction_id,
                expected_version=current.version,
                expected_state=TransactionState.AGREED,
                new_state=TransactionState.FUNDING_PENDING,
                changes={
                    "funding": {"status": "creating"},
                    "deadlines": {
                        **(current.deadlines or {}),
                        "funding": self._iso(deadline),
                    },
                },
                events=[EventInput("funding_required", {}, actor)],
                audit=AuditInput(actor, "funding_started"),
            )
            await self.repo.create_provider_operation(
                conn,
                operation_id,
                transaction_id,
                "create_order",
                order_key,
                {
                    "return_url": provider_return,
                    "cancel_url": provider_cancel,
                    "amount_cents": current.amount_cents,
                    "currency": current.currency,
                },
            )
            for kind, link in (
                ("checkout", checkout_link),
                ("return", return_link),
                ("cancel", cancel_link),
            ):
                await self.repo.create_checkout_link(
                    conn, link.jti, transaction_id, kind, link.expires_at
                )
        try:
            order = await self.payments.create_order(
                record,
                return_url=provider_return,
                cancel_url=provider_cancel,
                idempotency_key=order_key,
            )
        except VerifundError as exc:
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                if current.state == TransactionState.FUNDING_PENDING:
                    await self.repo.update_transaction(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        changes={
                            "funding": {
                                "status": "create_failed",
                                "last_error": exc.message,
                            },
                            "last_error": {
                                "code": exc.code,
                                "message": exc.message,
                            },
                        },
                    )
            await self.repo.update_provider_operation(
                operation_id,
                status="failed",
                last_error=exc.message,
                increment_attempts=True,
            )
            raise
        payer_url = order.payer_action_url or checkout_url
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state == TransactionState.FUNDING_PENDING:
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes={
                        "funding": {
                            "status": "pending",
                            "provider_order_id": order.order_id,
                            "payer_action_url": payer_url,
                            "checkout_url": payer_url,
                        }
                    },
                )
            response = FundResponse(
                transaction_id=transaction_id,
                state=TransactionState.FUNDING_PENDING,
                checkout_url=payer_url,
                expires_at=deadline,
            ).model_dump(mode="json")
            if idempotency_key:
                await self.repo.put_idempotency(
                    conn,
                    scope,
                    idempotency_key,
                    sha256_hex(canonical_json(body)),
                    response,
                )
        await self.repo.update_provider_operation(
            operation_id,
            status="completed",
            provider_id=order.order_id,
            response=order.raw,
        )
        return FundResponse.model_validate(response)

    async def refresh_funding(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.state in {
            TransactionState.FUNDED,
            TransactionState.FULFILLMENT_PENDING,
            TransactionState.VERIFICATION_PENDING,
            TransactionState.RELEASE_PERMITTED,
            TransactionState.PAYOUT_PENDING,
            TransactionState.RELEASED,
        }:
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        if record.state != TransactionState.FUNDING_PENDING:
            raise VerifundError(
                "invalid_state", "transaction is not awaiting funding", status_code=409
            )
        order_id = (record.funding or {}).get("provider_order_id")
        if not order_id:
            raise VerifundError(
                "provider_unavailable",
                "funding order is not yet available",
                status_code=503,
                retryable=True,
            )
        order = await self.payments.get_order(str(order_id))
        for capture in order.captures:
            await self.apply_capture(transaction_id, capture, actor=actor)
        return (await self._projection_for(transaction_id, "buyer")).model_dump(
            mode="json"
        )

    async def apply_capture(
        self, transaction_id: str, capture: CaptureResult, *, actor: str
    ) -> None:
        record = await self.repo.get_transaction(transaction_id)
        funding = dict(record.funding or {})
        if funding.get("capture_id") == capture.capture_id and record.state in {
            TransactionState.FUNDED,
            TransactionState.REVIEW_REQUIRED,
            TransactionState.RELEASED,
            TransactionState.PAYOUT_PENDING,
        }:
            return
        funding.update(
            {
                "provider_order_id": capture.order_id,
                "capture_id": capture.capture_id,
                "capture_status": capture.status,
                "capture_amount_cents": capture.amount_cents,
                "capture_currency": capture.currency,
            }
        )
        if capture.status in {"REFUNDED", "REVERSED"}:
            if record.state in {
                TransactionState.CANCELED,
                TransactionState.FAILED,
                TransactionState.REVIEW_REQUIRED,
                TransactionState.RELEASED,
                TransactionState.PAYOUT_PENDING,
                TransactionState.RELEASE_PERMITTED,
            }:
                async with self.repo.transaction() as conn:
                    current = await self.repo.get_transaction(transaction_id, conn)
                    if current.state in {
                        TransactionState.CANCELED,
                        TransactionState.FAILED,
                        TransactionState.RELEASE_PERMITTED,
                        TransactionState.PAYOUT_PENDING,
                        TransactionState.RELEASED,
                    }:
                        await self.repo.transition(
                            conn,
                            transaction_id,
                            expected_version=current.version,
                            expected_state=current.state,
                            new_state=TransactionState.REVIEW_REQUIRED,
                            changes={
                                "funding": {**funding, "status": "reversed"},
                                "verification": {
                                    "status": "failed",
                                    "reasons": ["late_capture"],
                                    "checked_at": self._iso(self._now()),
                                    "override_allowed": False,
                                },
                            },
                            events=[
                                EventInput(
                                    "review_required",
                                    {"reason": "capture_reversed"},
                                    actor,
                                )
                            ],
                            audit=AuditInput(actor, "capture_reversed"),
                        )
            return
        if capture.status == "PENDING":
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes={"funding": {**funding, "status": "pending"}},
                )
            return
        if capture.status != "COMPLETED":
            if record.state == TransactionState.FUNDING_PENDING:
                async with self.repo.transaction() as conn:
                    current = await self.repo.get_transaction(transaction_id, conn)
                    if current.state == TransactionState.FUNDING_PENDING:
                        await self.repo.transition(
                            conn,
                            transaction_id,
                            expected_version=current.version,
                            expected_state=current.state,
                            new_state=TransactionState.FAILED,
                            changes={
                                "funding": {**funding, "status": "declined"},
                                "last_error": {
                                    "code": "provider_rejected",
                                    "message": f"capture {capture.status.lower()}",
                                },
                            },
                            events=[EventInput("failed", {}, actor)],
                            audit=AuditInput(actor, "capture_declined"),
                        )
            return
        funds_match = (
            capture.amount_cents == record.amount_cents
            and capture.currency == record.currency
        )
        if record.state in {TransactionState.CANCELED, TransactionState.FAILED}:
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.REVIEW_REQUIRED,
                    changes={
                        "funding": {**funding, "status": "captured"},
                        "verification": {
                            "status": "failed",
                            "reasons": ["late_capture"],
                            "checked_at": self._iso(self._now()),
                            "override_allowed": False,
                        },
                    },
                    events=[
                        EventInput("review_required", {"reason": "late_capture"}, actor)
                    ],
                    ledger_entries=capture_ledger_entries(
                        transaction_id, capture.amount_cents
                    ),
                    audit=AuditInput(actor, "late_capture"),
                )
            return
        if record.state != TransactionState.FUNDING_PENDING:
            return
        reasons = [] if funds_match else [ReviewReason.FUNDING_MISMATCH.value]
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state != TransactionState.FUNDING_PENDING:
                return
            if funds_match:
                await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.FUNDED,
                    changes={"funding": {**funding, "status": "captured"}},
                    events=[EventInput("funded", {}, actor)],
                    ledger_entries=capture_ledger_entries(
                        transaction_id, capture.amount_cents
                    ),
                    audit=AuditInput(actor, "funded"),
                )
            else:
                await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.REVIEW_REQUIRED,
                    changes={
                        "funding": {**funding, "status": "captured"},
                        "verification": {
                            "status": "failed",
                            "reasons": reasons,
                            "checked_at": self._iso(self._now()),
                            "override_allowed": False,
                        },
                    },
                    events=[
                        EventInput(
                            "review_required",
                            {"reasons": reasons},
                            actor,
                        )
                    ],
                    ledger_entries=capture_ledger_entries(
                        transaction_id, capture.amount_cents
                    ),
                    audit=AuditInput(actor, "funding_mismatch"),
                )

    async def apply_capture_by_order(
        self, order_id: str, capture: CaptureResult, *, actor: str
    ) -> bool:
        record = await self.repo.find_transaction_by_order_id(order_id)
        if record is None:
            return False
        await self.apply_capture(record.transaction_id, capture, actor=actor)
        return True
