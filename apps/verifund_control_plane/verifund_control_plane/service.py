from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

from verifund_contracts import (
    AcceptRequest,
    AgreementProjection,
    ApproveRequest,
    AwardRequest,
    BuyerAgreementReviewRequest,
    CancelRequest,
    EvidenceItem,
    EvidenceSummary,
    RejectRequest,
    TransactionProjection,
    TransactionState,
)
from verifund_control_plane.domain import (
    REQUIRED_EVIDENCE,
    TransactionRecord,
    agreement_hash,
    allowed_actions,
    build_agreement,
    canonical_json,
    sha256_hex,
    validate_award,
)
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import (
    AgreementReviewInput,
    AuditInput,
    EventInput,
    Repository,
)
from verifund_control_plane.settings import Settings
from verifund_control_plane.tokens import SellerTokenService

Mutation = Callable[[Any], Awaitable[dict[str, Any]]]


class VerifundService:
    def __init__(
        self,
        *,
        repo: Repository,
        settings: Settings,
        clock: Callable[[], datetime],
        tokens: SellerTokenService,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.clock = clock
        self.tokens = tokens

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
