from __future__ import annotations

import base64
import binascii
import json
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from verifund_contracts import (
    AcceptRequest,
    ApproveRequest,
    AwardRequest,
    BuyerAgreementReviewRequest,
    CancelRequest,
    EvidenceItem,
    EvidenceKind,
    EvidenceSubmission,
    EvidenceSummary,
    FlagReviewRequest,
    FundRequest,
    FundResponse,
    PayoutProjection,
    PurchaseOrderReport,
    ReceiptResponse,
    RejectRequest,
    ReleaseRequest,
    RequirementResult,
    RequirementStatus,
    ReviewReason,
    SellerEvidenceCount,
    SellerEvidenceEntry,
    SellerEvidenceLibrary,
    SellerLineItem,
    SellerPayoutEntry,
    SellerPayoutStatus,
    SellerPayoutTotals,
    SellerPayoutView,
    SellerProjection,
    SellerTokenRequest,
    SellerTokenResponse,
    SellerTransactionList,
    SellerTransactionSummary,
    TransactionProjection,
    TransactionState,
    VerificationProjection,
)
from verifund_contracts.terms import policy_version_of, project_requirements

from verifund_control_plane.domain import (
    EVIDENCE_UPLOAD_STATES,
    NON_OVERRIDABLE_REASONS,
    TransactionRecord,
    allowed_actions,
    canonical_json,
    capture_ledger_entries,
    payout_ledger_entries,
    sha256_hex,
)
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.evidence import EvidenceStore
from verifund_control_plane.paypal.port import CaptureResult, PaymentPort, PayoutResult
from verifund_control_plane.paypal_tracking import PayPalTrackingClient
from verifund_control_plane.policy import evaluate, matches_requirement
from verifund_control_plane.receipts import ReceiptSigner, build_receipt_payload
from verifund_control_plane.repository import (
    AuditInput,
    EventInput,
    Repository,
)
from verifund_control_plane.settings import Settings
from verifund_control_plane.tokens import LinkSigner, SellerTokenService

Mutation = Callable[[Any], Awaitable[dict[str, Any]]]


# Re-exported so the catalog projection is available on the service surface
# (Task 6 interface) and shared with downstream verification (Tasks 7-8).
__all__ = ["policy_version_of", "project_requirements"]


def _requirement_results_from_stored(value: Any) -> list[RequirementResult]:
    """Rebuild slim per-requirement results persisted on the verification dict."""
    if not isinstance(value, list):
        return []
    results: list[RequirementResult] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        with suppress(ValidationError):  # skip unreadable entries from older rows
            results.append(RequirementResult.model_validate(entry))
    return results


_VERIFICATION_FIELDS = {
    "status",
    "reasons",
    "checked_at",
    "override_allowed",
    "requirements",
    "rollup",
}


_PAID_PAYOUT_STATUSES = {"SUCCESS", "SUCCEEDED", "PAID", "COMPLETED"}
_FAILED_PAYOUT_STATUSES = {"FAILED", "DENIED", "CANCELED", "CREATE_FAILED"}


def _payout_status(raw: Any) -> str:
    value = str(raw or "").upper()
    if value in _PAID_PAYOUT_STATUSES:
        return "paid"
    if value in _FAILED_PAYOUT_STATUSES:
        return "failed"
    return "pending"


def _payout_summary(record: TransactionRecord) -> SellerPayoutStatus | None:
    payout = record.payout or None
    if not payout:
        return None
    try:
        amount = int(payout.get("amount_cents") or record.amount_cents)
    except (TypeError, ValueError):
        amount = record.amount_cents
    raw_updated = payout.get("updated_at")
    updated = datetime.fromisoformat(raw_updated) if isinstance(raw_updated, str) else raw_updated
    return SellerPayoutStatus(
        status=_payout_status(payout.get("status")),
        amount_cents=amount,
        updated_at=updated if isinstance(updated, datetime) else None,
    )


def _payout_projection(value: dict[str, Any] | None) -> PayoutProjection | None:
    if not value:
        return None
    filtered = {
        key: value[key]
        for key in ("status", "batch_id", "item_id", "amount_cents", "updated_at")
        if key in value
    }
    try:
        return PayoutProjection.model_validate(filtered)
    except ValidationError:
        return None


def _encode_cursor(created_at_iso: str, row_id: str) -> str:
    raw = json.dumps(
        {"created_at": created_at_iso, "id": row_id}, separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str) -> dict[str, str] | None:
    padding = "=" * (-len(value) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(value + padding))
    except (ValueError, binascii.Error):
        return None
    if not isinstance(data, dict):
        return None
    created_at, row_id = data.get("created_at"), data.get("id")
    if not isinstance(created_at, str) or not isinstance(row_id, str):
        return None
    try:
        datetime.fromisoformat(created_at)
    except ValueError:
        return None
    return {"created_at": created_at, "id": row_id}



def _dispute_projection(value: dict[str, Any] | None):
    if not value:
        return None
    try:
        return __import__(
            "verifund_contracts.models", fromlist=["DisputeProjection"]
        ).DisputeProjection(**value)
    except Exception:  # noqa: BLE001
        return None


def _tracker_projection(value: dict[str, Any] | None):
    if not value or not value.get("tracker_id"):
        return None
    return __import__(
        "verifund_contracts.models", fromlist=["TrackerProjection"]
    ).TrackerProjection(
        tracker_id=str(value["tracker_id"]),
        last_status=value.get("last_status"),
        status_source=value.get("status_source") or "merchant_push",
        updated_at=value.get("updated_at"),
    )


def _verification_projection(value: dict[str, Any] | None) -> VerificationProjection | None:
    if not value:
        return None
    # Stored rows predate `requirements`/`rollup` or carry legacy keys; keep
    # only fields the projection declares so old rows keep loading.
    filtered = {key: value[key] for key in _VERIFICATION_FIELDS if key in value}
    try:
        return VerificationProjection.model_validate(filtered)
    except ValidationError:
        fallback = {
            key: filtered[key]
            for key in ("status", "reasons", "checked_at", "override_allowed")
            if key in filtered
        }
        if "status" not in fallback:
            return None
        return VerificationProjection.model_validate(fallback)


def _slim_requirement_results(results: tuple[RequirementResult, ...]) -> list[dict[str, Any]]:
    """Persist per-requirement results without the submission payloads.

    `EvidenceSummary.items` already carries the full evidence log; dropping
    `submissions` keeps the transactions row lean while round-tripping every
    client-visible field of `RequirementResult`.
    """
    slim: list[dict[str, Any]] = []
    for result in results:
        data = result.model_dump(mode="json")
        data.pop("submissions", None)
        slim.append(data)
    return slim


class VerifundService:
    def __init__(
        self,
        *,
        repo: Repository,
        settings: Settings,
        clock: Callable[[], datetime],
        tokens: SellerTokenService,
        buyer_tokens: Any = None,
        invitation_tokens: Any = None,
        evidence_store: EvidenceStore,
        payments: PaymentPort,
        links: LinkSigner,
        receipts: ReceiptSigner,
        agreement_service: Any = None,
        tracking: PayPalTrackingClient | None = None,
        tenancy: Any = None,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.clock = clock
        self.tokens = tokens
        self.buyer_tokens = buyer_tokens
        self.invitation_tokens = invitation_tokens
        self.evidence_store = evidence_store
        self.payments = payments
        self.links = links
        self.receipts = receipts
        self.agreement_service = agreement_service
        self.tracking = tracking
        self.tenancy = tenancy

    async def seller_status(self, seller_id: str) -> str | None:
        if self.tenancy is None:
            return None
        profile = await self.tenancy.get_seller_profile(seller_id)
        return profile["verification_status"] if profile else None

    async def _payout_email(self, seller_id: str) -> str | None:
        if getattr(self.settings, "tenancy_enabled", False) and self.tenancy is not None:
            try:
                from verifund_control_plane.tenancy.repository import (
                    resolve_payout_account_for_seller,
                )

                account = await resolve_payout_account_for_seller(self.tenancy, seller_id)
                return account["provider_account_id"]
            except Exception:
                return None
        return self.settings.payout_email_for(seller_id)

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
        deadlines = {
            key: (
                datetime.fromisoformat(value)
                if isinstance(value, str)
                else value
            )
            for key, value in (record.deadlines or {}).items()
        }
        stored_requirements = _requirement_results_from_stored(
            (record.verification or {}).get("requirements")
        )
        summary = EvidenceSummary(
            requirements=stored_requirements,
            deadline=deadlines.get("evidence"),
            items=evidence_items,
        )
        return TransactionProjection(
            transaction_id=record.transaction_id,
            agreement_id=record.agreement_id,
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
            verification=_verification_projection(record.verification),
            dispute=_dispute_projection(record.dispute),
            payout=self._pick(
                record.payout,
                ("status", "batch_id", "item_id", "amount_cents", "updated_at"),
            ),
            tracker=_tracker_projection(record.tracker),
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

    async def _agreement_terms(self, transaction_id: str) -> dict[str, Any]:
        agreement = await self.agreement_service.get_by_transaction(transaction_id)
        current = getattr(agreement, "current_version_record", None) if agreement else None
        terms = getattr(current, "terms", None)
        return dict(terms or {})

    async def award(
        self, request: AwardRequest, *, actor: str, idempotency_key: str | None
    ) -> dict[str, Any]:
        from verifund_control_plane.domain import validate_award as _validate_award
        _validate_award(request)
        if getattr(self.settings, "tenancy_enabled", False) and self.tenancy is not None:
            status = await self.seller_status(request.seller_id)
            if status != "verified":
                raise VerifundError(
                    "seller_not_verified",
                    "seller is not verified for new transactions",
                    status_code=403,
                )
            from verifund_control_plane.tenancy.repository import (
                resolve_payout_account_for_seller,
            )

            await resolve_payout_account_for_seller(self.tenancy, request.seller_id)
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
        buyer_org_id = None
        seller_org_id = None
        if self.tenancy is not None:
            seller_org = await self.tenancy.ensure_seed_organization(
                seller_id=request.seller_id, kind="business", verified=False
            )
            buyer_org = await self.tenancy.ensure_seed_buyer_organization(
                request.buyer_id
            )
            seller_org_id = seller_org["id"]
            buyer_org_id = buyer_org["id"]

        async def operation(conn):
            agreement = await self.agreement_service.create_from_award(
                conn, request, transaction_id, request.run_id, now
            )
            digest = agreement.current_version_record.agreement_hash
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
                agreement_id=agreement.agreement_id,
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
                dispute=None,
                payout=None,
                tracker=None,
                receipt=None,
                deadlines={"funding": None, "evidence": None, "inspection": None},
                last_error=None,
                created_at=now,
                updated_at=now,
                buyer_organization_id=buyer_org_id,
                seller_organization_id=seller_org_id,
            )
            issued = self.tokens.issue(
                transaction_id, request.seller_id, digest
            )
            projection = await self.agreement_service.build_projection(agreement)
            response = {
                "transaction_id": transaction_id,
                "state": TransactionState.AWARDED.value,
                "agreement_hash": digest,
                "agreement_version": projection.agreement_version,
                "agreement": projection.model_dump(mode="json"),
                "seller_token": issued.token,
                "expires_at": self._iso(issued.expires_at),
            }
            await self.repo.insert_transaction(
                conn,
                record,
                agreement=projection.model_dump(mode="json"),
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
                ["txn:read", "evidence:write", "agreement:decide"],
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
                        "buyer_precheck",
                        {"buyer_task_id": request.buyer_task_id},
                        actor,
                    )
                ]
                updated = await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=record.version,
                    changes=changes,
                    events=events,
                    audit=AuditInput(
                        actor, "buyer_precheck"
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
        async def operation(conn):
            items = await self.repo.list_evidence(transaction_id)
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
            if record.state != TransactionState.AWARDED:
                raise VerifundError(
                    "invalid_state", "transaction is not awaiting acceptance", status_code=409
                )
            agreement = await self.agreement_service.get_by_transaction(
                transaction_id
            )
            agreement_version = request.agreement_version or record.agreement_version
            offer_hash = request.offer_hash or getattr(agreement, "offer_hash", None) or record.agreement_hash
            if agreement is None:
                raise VerifundError("not_found", "agreement not found", status_code=404)
            if agreement.status.value == "PENDING_BUYER" and (record.seller_decision or {}).get("status") == "accepted":
                return (await self._projection(record, "buyer", items=items)).model_dump(mode="json")
            if agreement.status.value != "PENDING_SELLER":
                raise VerifundError("invalid_state", "agreement is not pending seller", status_code=409)
            await self.agreement_service.record_seller_decision(
                conn,
                agreement.agreement_id,
                decision=__import__("verifund_contracts.models", fromlist=["AgreementDecision"]).AgreementDecision.ACCEPT,
                actor_type=request.actor_type,
                actor_id=request.actor_id or request.seller_id,
                authority_ref=request.authority_ref or f"seller-token:{request.seller_task_id}",
                authority_snapshot=request.authority_snapshot or {},
                agreement_version=agreement_version,
                agreement_hash=request.agreement_hash,
                verified_offer_hash=offer_hash,
                note="",
                idempotency_key=idempotency_key or f"accept:{transaction_id}:{request.seller_task_id}",
                now=self._now(),
            )
            changes = {
                "seller_decision": {
                    "status": "accepted",
                    "reported_at": self._iso(request.accepted_at),
                    "seller_task_id": request.seller_task_id,
                    "agreement_hash": request.agreement_hash,
                    "agreement_version": agreement_version,
                }
            }
            events = [
                EventInput(
                    "seller_accepted",
                    {"seller_task_id": request.seller_task_id},
                    actor,
                )
            ]
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
        async def operation(conn):
            items = await self.repo.list_evidence(transaction_id)
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
 
        result = await self._mutate(
            scope=f"reject:{transaction_id}",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )
        try:
            agreement = await self.agreement_service.get_by_transaction(transaction_id)
            if agreement is not None:
                async with self.agreement_service.repo.transaction() as conn:
                    await self.agreement_service.cancel_pending(
                        conn, agreement.agreement_id, reason="seller_rejected", now=self._now()
                    )
        except Exception:  # noqa: BLE001, S110
            pass
        return result

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
            # Funding binding: agreement must be AGREED and bind this version/digest.
            agreement = await self.agreement_service.get_by_transaction(transaction_id, conn=conn)
            if agreement is None:
                raise VerifundError("not_found", "agreement not found", status_code=404)
            txn_proj = await self._projection(record, "buyer", items=items)
            try:
                await self.agreement_service.verify_funding_binding(
                    agreement, txn_proj, request.agreement_version, request.agreement_hash
                )
            except Exception as exc:
                from verifund_control_plane.agreements.models import AgreementError
                if isinstance(exc, AgreementError):
                    code = exc.code
                    status = 409
                    raise VerifundError(code, exc.message, status_code=status)
                raise
            if (record.approval or {}).get("approval_id") == request.approval_id:
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state != TransactionState.AGREED:
                raise VerifundError(
                    "invalid_state", "transaction is not awaiting approval", status_code=409
                )
            deadline = self._now() + timedelta(
                hours=self.settings.funding_timeout_hours
            )
            approval = {
                "approval_id": request.approval_id,
                "approved_by": request.approved_by,
                "approved_at": self._iso(request.approved_at),
                "note": request.note,
                "agreement_version": request.agreement_version,
                "agreement_hash": request.agreement_hash,
            }
            updated = await self.repo.update_transaction(
                conn,
                transaction_id,
                expected_version=record.version,
                changes={
                    "approval": approval,
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
        allowed_states = {
            TransactionState.AWARDED,
            TransactionState.AGREED,
            TransactionState.FUNDING_PENDING,
            TransactionState.REVIEW_REQUIRED,
        }
        async def operation(conn):
            items = await self.repo.list_evidence(transaction_id)
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
 
        result = await self._mutate(
            scope=f"cancel:{transaction_id}",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )
        # Map cancellation onto the agreement state outside the transaction.
        try:
            agreement = await self.agreement_service.get_by_transaction(transaction_id)
            if agreement is not None:
                if agreement.status.value in {"PENDING_SELLER", "PENDING_BUYER", "CHANGES_REQUESTED"}:
                    async with self.agreement_service.repo.transaction() as conn:
                        await self.agreement_service.cancel_pending(
                            conn, agreement.agreement_id, reason=request.reason_code.value, now=self._now()
                        )
                elif agreement.status.value == "AGREED":
                    async with self.agreement_service.repo.transaction() as conn:
                        await self.agreement_service.terminate(
                            conn, agreement.agreement_id, reason=request.reason_code.value, now=self._now()
                        )
        except Exception:  # noqa: BLE001, S110
            pass
        return result

    async def add_evidence(
        self,
        transaction_id: str,
        *,
        seller_id: str,
        agreement_hash: str,
        requirement_id: str,
        reference: str | None,
        reference_type: str | None,
        media_type: str | None,
        original_filename: str | None,
        data: bytes | None,
        note: str | None,
        captured_at: datetime | None,
        agreement_version: int | None,
        actor: str,
    ) -> EvidenceSubmission:
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
        # Validate against the requirement catalog in effect for this agreement.
        terms = await self._agreement_terms(transaction_id)
        try:
            catalog = project_requirements(terms)
        except (ValidationError, ValueError):
            raise VerifundError(
                "invalid_request",
                "agreement requirements are invalid",
                status_code=422,
            ) from None
        requirement = next(
            (entry for entry in catalog if entry.requirement_id == requirement_id),
            None,
        )
        if requirement is None:
            raise VerifundError(
                "invalid_request",
                f"unknown requirement_id for this agreement: {requirement_id}",
                status_code=422,
            )
        if requirement.owner != "seller":
            raise VerifundError(
                "invalid_request",
                f"requirement {requirement_id} is not seller-owned",
                status_code=422,
            )
        # A submission against a superseded agreement version is rejected so a
        # stale seller client can never satisfy the current catalog.
        if agreement_version is not None and agreement_version != record.agreement_version:
            raise VerifundError(
                "hash_mismatch",
                "agreement version does not match the current terms",
                status_code=409,
            )

        is_reference = requirement.source == "reference"
        if is_reference:
            if reference is None or reference_type not in {"tracking", "url"}:
                raise VerifundError(
                    "invalid_request",
                    f"{requirement_id} expects a reference artifact "
                    "(reference, reference_type=tracking|url)",
                    status_code=422,
                )
            if data is not None:
                raise VerifundError(
                    "invalid_request",
                    f"{requirement_id} expects a reference, not a file",
                    status_code=422,
                )
            artifact_type = "reference"
            payload = reference.encode("utf-8")
            resolved_media_type = "text/plain"
            resolved_filename = f"{requirement_id}.reference.txt"
        else:
            if data is None:
                raise VerifundError(
                    "invalid_request",
                    f"{requirement_id} expects a file upload",
                    status_code=422,
                )
            if reference is not None:
                raise VerifundError(
                    "invalid_request",
                    f"{requirement_id} expects a file, not a reference",
                    status_code=422,
                )
            artifact_type = "file"
            payload = data
            resolved_media_type = (media_type or "application/octet-stream").lower()
            resolved_filename = original_filename or "evidence"
            if (
                requirement.accepted_formats
                and resolved_media_type not in requirement.accepted_formats
            ):
                raise VerifundError(
                    "unsupported_media_type",
                    f"media type {resolved_media_type} is not accepted for "
                    f"{requirement_id}; accepted: {', '.join(requirement.accepted_formats)}",
                    status_code=415,
                )

        # `kind` stays in the legacy EvidenceKind vocabulary for the store's
        # validation; anything else is stored as `other`. The catalog addresses
        # artifacts by requirement_id, so `kind` is display metadata only.
        try:
            store_kind = EvidenceKind(requirement.kind).value
        except ValueError:
            store_kind = EvidenceKind.OTHER.value

        item = await self.evidence_store.put(
            transaction_id=transaction_id,
            seller_id=seller_id,
            kind=store_kind,
            media_type=resolved_media_type,
            original_filename=resolved_filename,
            data=payload,
            note=note,
            captured_at=captured_at,
            organization_id=record.seller_organization_id,
        )
        scan_status = "clean" if is_reference else "pending"

        new_state = record.state
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state not in EVIDENCE_UPLOAD_STATES:
                raise VerifundError(
                    "invalid_state",
                    "evidence cannot be uploaded in the current state",
                    status_code=409,
                )
            open_attempt = await self.repo.open_attempt(conn, transaction_id, requirement_id)
            item = item.model_copy(
                update={
                    "requirement_id": requirement_id,
                    "submission_attempt": open_attempt,
                    "origin": "seller",
                    "attributed_to": seller_id,
                    "agreement_version": current.agreement_version,
                    "artifact_type": artifact_type,
                    "reference": reference if is_reference else None,
                    "scan_status": scan_status,
                }
            )
            stored, created = await self.repo.add_evidence(
                conn,
                transaction_id,
                seller_id,
                item,
                captured_at=captured_at,
            )
            submission_id = f"sub_{uuid.uuid4().hex}"
            await self.repo.add_evidence_submission(
                conn,
                submission_id=submission_id,
                transaction_id=transaction_id,
                evidence_id=stored.evidence_id,
                requirement_id=requirement_id,
                attempt=open_attempt,
            )
            if created:
                event = EventInput(
                    "evidence_received",
                    {
                        "evidence_id": stored.evidence_id,
                        "kind": stored.kind,
                        "sha256": stored.sha256,
                        "requirement_id": requirement_id,
                        "submission_id": submission_id,
                        "attempt": open_attempt,
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
        if is_reference and reference_type == "tracking" and reference:
            await self.register_tracker(
                transaction_id,
                tracking_number=reference,
                carrier=(record.purchase_order or {}).get("carrier"),
                actor=actor,
            )
        return EvidenceSubmission(
            submission_id=submission_id,
            attempt=open_attempt,
            evidence_id=stored.evidence_id,
            requirement_id=requirement_id,
            receipt_id=f"rcpt_{stored.sha256[:32]}",
            artifact_type=artifact_type,
            scan_status=scan_status,
        )

    async def seller_projection(
        self, transaction_id: str, *, seller_id: str
    ) -> SellerProjection:
        record = await self.repo.get_transaction(transaction_id)
        if record.seller_id != seller_id:
            raise VerifundError(
                "forbidden", "seller does not own this transaction", status_code=403
            )
        agreement_record = await self.agreement_service.get_by_transaction(transaction_id)
        if agreement_record is None:
            raise VerifundError(
                "not_found",
                "agreement not found for transaction",
                status_code=404,
            )
        agreement = await self.agreement_service.build_projection(agreement_record)
        terms = await self._agreement_terms(transaction_id)
        try:
            catalog = project_requirements(terms)
        except (ValidationError, ValueError):
            catalog = []
        items = await self.repo.list_evidence(transaction_id)
        stored_requirements = _requirement_results_from_stored(
            (record.verification or {}).get("requirements")
        )
        deadlines = {
            key: (
                datetime.fromisoformat(value)
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
            agreement_id=record.agreement_id,
            agreement_hash=record.agreement_hash,
            agreement_version=record.agreement_version,
            quantity=agreement.quantity,
            line_items=agreement.line_items,
            delivery_days=agreement.delivery_days,
            warranty_months=agreement.warranty_months,
            returns_days=agreement.returns_days,
            purchase_order=self._pick(
                record.purchase_order,
                ("seller_order_id", "tracking_number", "carrier", "eta"),
            ),
            evidence=EvidenceSummary(
                requirements=stored_requirements,
                deadline=deadlines.get("evidence"),
                items=items,
            ),
            requirements=list(catalog),
            payout=_payout_projection(record.payout),
            dispute=_dispute_projection(record.dispute),
            deadlines=deadlines,
            allowed_actions=allowed_actions(record.state, "seller"),
            updated_at=record.updated_at,
        )

    @staticmethod
    def _evidence_count(
        record: TransactionRecord, items: list[EvidenceItem], terms: dict[str, Any]
    ) -> SellerEvidenceCount:
        try:
            catalog = project_requirements(terms or {})
        except (ValidationError, ValueError):
            catalog = []
        required_ids = {
            requirement.requirement_id
            for requirement in catalog
            if requirement.owner == "seller" and requirement.required
        }
        required = len(required_ids)
        stored = _requirement_results_from_stored(
            (record.verification or {}).get("requirements")
        )
        if stored:
            submitted_results = [
                result
                for result in stored
                if result.requirement_id in required_ids
                and result.status != RequirementStatus.NOT_SUBMITTED
            ]
            submitted = len(submitted_results)
            received_kinds = sorted({result.kind for result in submitted_results})
        else:
            submitted = 0
            received_kinds = []
            for requirement in catalog:
                if requirement.requirement_id not in required_ids:
                    continue
                if any(matches_requirement(requirement, item) for item in items):
                    submitted += 1
                    received_kinds.append(requirement.kind)
            received_kinds = sorted(set(received_kinds))
        return SellerEvidenceCount(
            submitted=submitted,
            required=required,
            complete=required > 0 and submitted == required,
            received_kinds=received_kinds,
        )

    @staticmethod
    def _next_action(state: TransactionState, complete: bool) -> str:
        if state in {
            TransactionState.FUNDED,
            TransactionState.FULFILLMENT_PENDING,
        }:
            return "submit_evidence"
        if state == TransactionState.VERIFICATION_PENDING:
            return "none" if complete else "submit_evidence"
        if state == TransactionState.REVIEW_REQUIRED:
            return "replace_evidence"
        if state == TransactionState.REMEDIATION_REQUIRED:
            return "submit_evidence"
        if state == TransactionState.DISPUTE_OPEN:
            return "respond_to_dispute"
        return "none"

    async def _seller_transaction_summary(
        self,
        record: TransactionRecord,
        items: list[EvidenceItem],
        terms: dict[str, Any],
    ) -> SellerTransactionSummary:
        agreement_id = record.agreement_id
        line_items: list[SellerLineItem] = []
        quantity = 0
        delivery_days = 0
        warranty_months = 0
        returns_days = 0
        with suppress(Exception):  # agreement projection is best-effort for the list
            agreement = await self.agreement_service.get_by_transaction(
                record.transaction_id
            )
            if agreement is not None:
                projection = await self.agreement_service.build_projection(agreement)
                line_items = [
                    SellerLineItem(sku=item.sku, name=item.name, quantity=item.quantity)
                    for item in projection.line_items
                ]
                quantity = projection.quantity
                delivery_days = projection.delivery_days
                warranty_months = projection.warranty_months
                returns_days = projection.returns_days
        deadlines = {
            key: (
                datetime.fromisoformat(value)
                if isinstance(value, str)
                else value
            )
            for key, value in (record.deadlines or {}).items()
        }
        evidence = self._evidence_count(record, items, terms)
        return SellerTransactionSummary(
            transaction_id=record.transaction_id,
            run_id=record.run_id,
            state=record.state,
            agreement_id=agreement_id,
            agreement_version=record.agreement_version,
            amount_cents=record.amount_cents,
            currency=record.currency,
            quantity=quantity,
            line_items=line_items,
            delivery_days=delivery_days,
            warranty_months=warranty_months,
            returns_days=returns_days,
            deadlines=deadlines,
            evidence=evidence,
            allowed_actions=allowed_actions(record.state, "seller"),
            next_action=self._next_action(record.state, evidence.complete),
            payout=_payout_summary(record),
            updated_at=record.updated_at,
        )

    async def list_seller_transactions(
        self,
        seller_id: str,
        *,
        state: str | None,
        limit: int,
        cursor: str | None,
    ) -> SellerTransactionList:
        if state is not None:
            try:
                TransactionState(state)
            except ValueError:
                raise VerifundError(
                    "invalid_request", f"unknown state: {state}", status_code=400
                ) from None
        if not 1 <= limit <= 200:
            raise VerifundError(
                "invalid_request", "limit must be between 1 and 200", status_code=400
            )
        parsed = _decode_cursor(cursor) if cursor else None
        if cursor and parsed is None:
            raise VerifundError(
                "invalid_request", "invalid cursor", status_code=400
            )
        rows = await self.repo.list_transactions_keyset(
            seller_id,
            state=state,
            created_before=parsed["created_at"] if parsed else None,
            id_before=parsed["id"] if parsed else None,
            limit=limit,
        )
        batch = await self.repo.list_evidence_for_transactions(
            [record.transaction_id for record in rows]
        )
        items_by_txn: dict[str, list[EvidenceItem]] = {}
        for txn_id, item in batch:
            items_by_txn.setdefault(txn_id, []).append(item)
        items = []
        for record in rows:
            terms = await self._agreement_terms(record.transaction_id)
            items.append(
                await self._seller_transaction_summary(
                    record, items_by_txn.get(record.transaction_id, []), terms
                )
            )
        next_cursor = None
        if len(rows) == limit and rows:
            last = rows[-1]
            next_cursor = _encode_cursor(self._iso(last.created_at), last.transaction_id)
        counts = await self.repo.counts_by_state(seller_id)
        return SellerTransactionList(
            items=items, counts_by_state=counts, next_cursor=next_cursor
        )

    async def list_seller_evidence(
        self,
        seller_id: str,
        *,
        kind: str | None,
        requirement_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> SellerEvidenceLibrary:
        if not 1 <= limit <= 200:
            raise VerifundError(
                "invalid_request", "limit must be between 1 and 200", status_code=400
            )
        parsed = _decode_cursor(cursor) if cursor else None
        if cursor and parsed is None:
            raise VerifundError(
                "invalid_request", "invalid cursor", status_code=400
            )
        rows = await self.repo.list_evidence_keyset(
            seller_id,
            kind=kind,
            requirement_id=requirement_id,
            created_before=parsed["created_at"] if parsed else None,
            id_before=parsed["id"] if parsed else None,
            limit=limit,
        )
        states = await self.repo.transactions_for_evidence(
            list({txn_id for txn_id, _ in rows})
        )
        items = []
        for txn_id, item in rows:
            record = states.get(txn_id)
            if record is None:
                # Evidence rows always reference a transaction; skip orphans.
                continue
            verification = record.verification
            items.append(
                SellerEvidenceEntry(
                    evidence_id=item.evidence_id,
                    transaction_id=txn_id,
                    requirement_id=item.requirement_id,
                    kind=item.kind,
                    media_type=item.media_type,
                    size_bytes=item.size_bytes,
                    original_filename=item.original_filename,
                    note=item.note,
                    captured_at=item.captured_at,
                    created_at=item.created_at,
                    scan_status=item.scan_status,
                    transaction_state=record.state,
                    verification=(
                        {
                            "status": verification.get("status"),
                            "reasons": verification.get("reasons") or [],
                            "checked_at": verification.get("checked_at"),
                        }
                        if verification
                        else None
                    ),
                )
            )
        next_cursor = None
        if len(rows) == limit and rows:
            last = rows[-1]
            next_cursor = _encode_cursor(self._iso(last.created_at), last.evidence_id)
        return SellerEvidenceLibrary(items=items, next_cursor=next_cursor)

    async def list_seller_payouts(self, seller_id: str) -> SellerPayoutView:
        rows = await self.repo.list_transactions(seller_id=seller_id, limit=500)
        transactions = []
        pending_cents = paid_cents = failed_cents = 0
        for record in rows:
            payout = _payout_summary(record)
            transactions.append(
                SellerPayoutEntry(
                    transaction_id=record.transaction_id,
                    amount_cents=record.amount_cents,
                    currency=record.currency,
                    state=record.state,
                    payout=payout,
                )
            )
            if payout is None:
                continue
            if payout.status == "paid":
                paid_cents += payout.amount_cents
            elif payout.status == "failed":
                failed_cents += payout.amount_cents
            else:
                pending_cents += payout.amount_cents
        return SellerPayoutView(
            transactions=transactions,
            totals=SellerPayoutTotals(
                pending_cents=pending_cents,
                paid_cents=paid_cents,
                failed_cents=failed_cents,
            ),
        )

    async def seller_events(
        self,
        transaction_id: str,
        *,
        seller_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.seller_id != seller_id:
            raise VerifundError(
                "forbidden", "seller does not own this transaction", status_code=403
            )
        if not 1 <= limit <= 200:
            raise VerifundError(
                "invalid_request", "limit must be between 1 and 200", status_code=400
            )
        after_seq = 0
        if cursor is not None:
            try:
                after_seq = int(cursor)
            except (TypeError, ValueError):
                raise VerifundError(
                    "invalid_request", "invalid cursor", status_code=400
                ) from None
        rows = await self.repo.events(
            transaction_id, after_seq=after_seq, limit=limit + 1
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = str(items[-1]["seq"]) if (has_more and items) else None
        return {"items": items, "next_cursor": next_cursor}

    async def seller_agreement(
        self, agreement_id: str, *, seller_id: str
    ) -> dict[str, Any]:
        agreement = await self.agreement_service.get(agreement_id)
        if agreement is None:
            raise VerifundError(
                "not_found", "agreement not found", status_code=404
            )
        if agreement.seller_id != seller_id:
            raise VerifundError(
                "forbidden", "seller does not own this agreement", status_code=403
            )
        view = await self.agreement_service.build_view(agreement)
        terms = await self.agreement_service.current_terms(agreement)
        try:
            requirements = project_requirements(terms)
        except (ValidationError, ValueError):
            requirements = []
        view["terms"] = {
            **terms,
            "requirements": [
                requirement.model_dump(mode="json") for requirement in requirements
            ],
        }
        return view

    async def declare_requirement(
        self,
        transaction_id: str,
        requirement_id: str,
        *,
        seller_id: str,
        actor: str,
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.seller_id != seller_id:
            raise VerifundError(
                "forbidden", "seller does not own this transaction", status_code=403
            )
        if record.state == TransactionState.FUNDED:
            raise VerifundError(
                "invalid_state",
                "declarations require fulfillment to have started",
                status_code=409,
            )
        if record.state == TransactionState.FULFILLMENT_PENDING:
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
        if record.state not in {
            TransactionState.VERIFICATION_PENDING,
            TransactionState.REMEDIATION_REQUIRED,
        }:
            raise VerifundError(
                "invalid_state",
                "declarations are only allowed while verification is open",
                status_code=409,
            )
        terms = await self._agreement_terms(transaction_id)
        catalog = project_requirements(terms)
        requirement = next(
            (item for item in catalog if item.requirement_id == requirement_id), None
        )
        if requirement is None or requirement.owner != "seller":
            raise VerifundError(
                "invalid_request",
                f"unknown seller requirement: {requirement_id}",
                status_code=422,
            )

        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            open_att = await self.repo.open_attempt(
                conn, transaction_id, requirement_id
            )

        submissions = await self.repo.list_submissions(
            transaction_id, requirement_id, attempt=open_att
        )
        submission_ids = [row["submission_id"] for row in submissions]
        if not submission_ids:
            raise VerifundError(
                "invalid_request",
                "declaration requires at least one open-attempt submission",
                status_code=400,
            )

        async with self.repo.transaction() as conn:
            declaration = await self.repo.add_declaration(
                conn,
                transaction_id,
                requirement_id,
                open_att,
                actor=actor,
                submission_ids=submission_ids,
            )

        declaration_rows = await self.repo.list_declarations(transaction_id)
        await self.verify(
            transaction_id,
            actor=actor,
            declarations=[dict(row) for row in declaration_rows],
        )
        return declaration

    async def list_declarations(
        self, transaction_id: str, requirement_id: str, *, seller_id: str
    ) -> list[dict[str, Any]]:
        record = await self.repo.get_transaction(transaction_id)
        if record.seller_id != seller_id:
            raise VerifundError(
                "forbidden", "seller does not own this transaction", status_code=403
            )
        rows = await self.repo.list_declarations(transaction_id, requirement_id)
        return sorted(rows, key=lambda row: row.get("attempt", 0), reverse=True)

    async def issue_buyer_token(
        self, transaction_id: str, *, actor: str
    ) -> str:
        record = await self.repo.get_transaction(transaction_id)
        if self.buyer_tokens is None:
            raise VerifundError(
                "not_implemented", "buyer tokens are not configured", status_code=501
            )
        issued = self.buyer_tokens.issue(record.buyer_id, transaction_id)
        async with self.repo.transaction() as conn:
            await self.repo.save_buyer_token(
                conn,
                jti_hash=issued.jti_hash,
                transaction_id=transaction_id,
                buyer_id=record.buyer_id,
                scopes=["txn:buy"],
                expires_at=issued.expires_at,
            )
            await self.repo.audit(
                conn,
                transaction_id,
                AuditInput(actor, "buyer_token_issued"),
            )
        return issued.token

    async def issue_invitation(
        self, transaction_id: str, *, actor: str
    ) -> str:
        record = await self.repo.get_transaction(transaction_id)
        if getattr(self.settings, "tenancy_enabled", False) and self.tenancy is not None:
            status = await self.seller_status(record.seller_id)
            if status != "verified":
                raise VerifundError(
                    "seller_not_verified",
                    "seller is not verified for new transactions",
                    status_code=403,
                )
        if self.invitation_tokens is None:
            raise VerifundError(
                "not_implemented",
                "invitation tokens are not configured",
                status_code=501,
            )
        issued = self.invitation_tokens.issue(record.seller_id, transaction_id)
        async with self.repo.transaction() as conn:
            await self.repo.save_invitation_token(
                conn,
                jti_hash=issued.jti_hash,
                transaction_id=transaction_id,
                seller_id=record.seller_id,
                scopes=["txn:read", "evidence:write"],
                expires_at=issued.expires_at,
            )
            await self.repo.audit(
                conn,
                transaction_id,
                AuditInput(actor, "invitation_issued"),
            )
        return issued.token

    async def exchange_invitation(self, token: str) -> dict[str, Any]:
        if self.invitation_tokens is None or self.tokens is None:
            raise VerifundError(
                "not_implemented",
                "invitation exchange is not configured",
                status_code=501,
            )
        claims = self.invitation_tokens.verify(token)
        stored = await self.repo.get_invitation_token(claims.jti_hash)
        if stored.get("revoked_at") or stored.get("used_at"):
            raise VerifundError(
                "token_used", "invitation has already been used", status_code=409
            )
        expires_at = datetime.fromisoformat(stored["expires_at"])
        if expires_at <= self._now():
            raise VerifundError(
                "token_expired", "invitation has expired", status_code=401
            )
        if stored["seller_id"] != claims.seller_id:
            raise VerifundError(
                "forbidden", "invitation does not match this seller", status_code=403
            )
        record = await self.repo.get_transaction(claims.txn)
        if record.seller_id != claims.seller_id:
            raise VerifundError(
                "forbidden", "invitation does not match this transaction", status_code=403
            )

        issued = self.tokens.issue(
            claims.txn, record.seller_id, record.agreement_hash,
            scopes=("txn:read", "evidence:write"),
        )
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(claims.txn, conn)
            if current.version != record.version:
                raise VerifundError(
                    "conflict", "transaction changed; retry", status_code=409
                )
            await self.repo.save_seller_token(
                conn,
                issued.jti_hash,
                claims.txn,
                record.seller_id,
                record.agreement_hash,
                ["txn:read", "evidence:write"],
                issued.expires_at,
            )
            await self.repo.mark_invitation_used(
                conn, claims.jti_hash, self._now()
            )
            await self.repo.audit(
                conn,
                claims.txn,
                AuditInput(
                    f"seller:{record.seller_id}",
                    "invitation_exchanged",
                ),
            )
        return {
            "token": issued.token,
            "expires_at": issued.expires_at.isoformat().replace("+00:00", "Z"),
            "allowed_actions": [
                "submit_evidence",
                "replace_evidence",
                "respond_to_dispute",
            ],
        }

    async def confirm_delivery(
        self,
        transaction_id: str,
        buyer_id: str | None = None,
        confirmed_at: Any = None,
        *,
        buyer: str | None = None,
        condition: str | None = None,
        photos: list[Any] | None = None,
        carrier_event_at: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if buyer_id is None:
            buyer_id = buyer or kwargs.get("buyer_id") or kwargs.get("buyer")
        if confirmed_at is None:
            confirmed_at = kwargs.get("confirmed_at")
        if isinstance(confirmed_at, str):
            confirmed_at = datetime.fromisoformat(confirmed_at)
        if confirmed_at is None:
            confirmed_at = self._now()
        if not isinstance(confirmed_at, datetime):
            raise VerifundError(
                "invalid_request", "confirmed_at must be a datetime", status_code=422
            )
        if carrier_event_at is not None and isinstance(carrier_event_at, str):
            carrier_event_at = datetime.fromisoformat(carrier_event_at)

        record = await self.repo.get_transaction(transaction_id)
        if record.buyer_id != buyer_id:
            raise VerifundError(
                "forbidden", "buyer does not own this transaction", status_code=403
            )
        now = self._now()
        if confirmed_at > now + timedelta(hours=1):
            raise VerifundError(
                "invalid_request",
                "confirmed_at cannot be in the future",
                status_code=422,
            )
        if carrier_event_at is not None and abs(
            (confirmed_at - carrier_event_at).total_seconds()
        ) > 24 * 3600:
            raise VerifundError(
                    "invalid_request",
                    "confirmed_at is outside the carrier event window",
                    status_code=422,
                )

        payload = json.dumps(
            {
                "buyer_id": buyer_id,
                "confirmed_at": confirmed_at.isoformat(),
                "condition": condition,
                "photos": photos or [],
                "origin": "system",
                "attributed_to": buyer_id,
            },
            default=str,
        )
        item = await self.evidence_store.put(
            transaction_id=transaction_id,
            seller_id=record.seller_id,
            kind=EvidenceKind.DELIVERY_CONFIRMATION.value,
            media_type="application/json",
            original_filename="delivery_confirmation.json",
            data=payload.encode("utf-8"),
            note="buyer-attested delivery confirmation",
            captured_at=confirmed_at,
            organization_id=record.seller_organization_id,
        )

        new_state = record.state
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state not in EVIDENCE_UPLOAD_STATES and current.state not in {
                TransactionState.FULFILLMENT_PENDING,
                TransactionState.VERIFICATION_PENDING,
            }:
                raise VerifundError(
                        "invalid_state",
                        "delivery confirmation is not allowed in the current state",
                        status_code=409,
                    )
            open_attempt = await self.repo.open_attempt(
                conn, transaction_id, "delivery_confirmation"
            )
            item = item.model_copy(
                update={
                    "requirement_id": "delivery_confirmation",
                    "submission_attempt": open_attempt,
                    "origin": "system",
                    "attributed_to": buyer_id,
                    "agreement_version": current.agreement_version,
                    "artifact_type": "system",
                    "scan_status": "clean",
                }
            )
            stored, _created = await self.repo.add_evidence(
                conn, transaction_id, record.seller_id, item, captured_at=confirmed_at
            )
            await self.repo.add_evidence_submission(
                conn,
                submission_id=f"sub_{uuid.uuid4().hex}",
                transaction_id=transaction_id,
                evidence_id=stored.evidence_id,
                requirement_id="delivery_confirmation",
                attempt=open_attempt,
            )
            if current.state == TransactionState.FULFILLMENT_PENDING:
                updated = await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.VERIFICATION_PENDING,
                    changes={},
                    audit=AuditInput(
                        f"buyer:{buyer_id}", "delivery_confirmed"
                    ),
                )
                new_state = updated.state
            else:
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes={},
                    audit=AuditInput(f"buyer:{buyer_id}", "delivery_confirmed"),
                )
        if new_state == TransactionState.VERIFICATION_PENDING:
            await self.verify_if_ready(transaction_id, actor="system")
        return {
            "evidence_id": stored.evidence_id,
            "requirement_id": "delivery_confirmation",
            "status": "recorded",
        }

    async def open_dispute(
        self,
        transaction_id: str,
        buyer_id: str | None = None,
        requirement_ids: list[str] | None = None,
        reason_code: str | None = None,
        claim: str | None = None,
        evidence: list[Any] | None = None,
        *,
        buyer: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if buyer_id is None:
            buyer_id = buyer or kwargs.get("buyer_id") or kwargs.get("buyer")
        requirement_ids = requirement_ids or kwargs.get("requirement_ids") or []
        reason_code = reason_code or kwargs.get("reason_code")
        claim = claim if claim is not None else kwargs.get("claim")
        evidence = evidence if evidence is not None else kwargs.get("evidence") or []

        record = await self.repo.get_transaction(transaction_id)
        if record.buyer_id != buyer_id:
            raise VerifundError(
                "forbidden", "buyer does not own this transaction", status_code=403
            )
        if record.state not in {
            TransactionState.VERIFICATION_PENDING,
            TransactionState.RELEASE_PERMITTED,
        }:
            raise VerifundError(
                "invalid_state",
                "dispute cannot be opened in the current state",
                status_code=409,
            )

        valid = bool(evidence) and bool(str(claim or "").strip())
        if not valid:
            async with self.repo.transaction() as conn:
                await self.repo.audit(
                    conn,
                    transaction_id,
                    AuditInput(
                        f"buyer:{buyer_id}",
                        "dispute_invalid",
                        payload={
                            "reason_code": reason_code,
                            "requirement_ids": requirement_ids,
                        },
                    ),
                )
            return {"transitioned": False, "state": record.state.value}

        dispute_block = {
            "status": "open",
            "reason_code": reason_code,
            "requirement_ids": requirement_ids,
            "claim": claim,
            "opened_at": self._iso(self._now()),
            "escalation_rung": 1,
            "action_required": "respond_to_dispute",
        }
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            await self.repo.transition(
                conn,
                transaction_id,
                expected_version=current.version,
                expected_state=current.state,
                new_state=TransactionState.DISPUTE_OPEN,
                changes={"dispute": dispute_block},
                audit=AuditInput(
                    f"buyer:{buyer_id}",
                    "dispute_opened",
                    payload={
                        "reason_code": reason_code,
                        "requirement_ids": requirement_ids,
                    },
                ),
            )
        return {"transitioned": True, "state": TransactionState.DISPUTE_OPEN.value}

    async def add_dispute_evidence(
        self,
        transaction_id: str,
        *,
        seller_id: str,
        agreement_hash: str,
        media_type: str | None,
        original_filename: str | None,
        data: bytes | None,
        note: str | None = None,
        captured_at: datetime | None = None,
        actor: str,
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.seller_id != seller_id:
            raise VerifundError(
                "forbidden", "seller does not own this transaction", status_code=403
            )
        if record.agreement_hash != agreement_hash:
            raise VerifundError(
                "hash_mismatch", "seller token hash is stale", status_code=409
            )
        if record.state != TransactionState.DISPUTE_OPEN:
            raise VerifundError(
                "invalid_state",
                "dispute evidence is only allowed while a dispute is open",
                status_code=409,
            )
        if data is None:
            raise VerifundError(
                "invalid_request", "dispute evidence requires a file", status_code=422
            )
        item = await self.evidence_store.put(
            transaction_id=transaction_id,
            seller_id=seller_id,
            kind=EvidenceKind.OTHER.value,
            media_type=(media_type or "application/octet-stream").lower(),
            original_filename=original_filename or "dispute_evidence",
            data=data,
            note=note,
            captured_at=captured_at,
            organization_id=record.seller_organization_id,
        )
        item = item.model_copy(
            update={
                "requirement_id": None,
                "origin": "seller",
                "attributed_to": seller_id,
                "agreement_version": record.agreement_version,
                "artifact_type": "file",
                "scan_status": "clean",
                "purpose": "dispute",
            }
        )
        async with self.repo.transaction() as conn:
            await self.repo.get_transaction(transaction_id, conn)
            stored, _created = await self.repo.add_evidence(
                conn, transaction_id, seller_id, item, captured_at=captured_at
            )
            await self.repo.audit(
                conn,
                transaction_id,
                AuditInput(actor, "dispute_evidence_received"),
            )
        return stored.model_dump(mode="json")

    async def verify_if_ready(self, transaction_id: str, *, actor: str) -> None:
        """Evaluate the worklist as submissions arrive.

        The target design evaluates per requirement and keeps
        `VERIFICATION_PENDING` with a mix of `PASS`/`NOT_SUBMITTED`/`PENDING_SCAN`
        (spec §3.9.4), so verification runs on every submission instead of
        waiting for the whole catalog. Declarations (Task 10b) and scan
        settlement (Task 20a) re-enter through the same path.
        """
        record = await self.repo.get_transaction(transaction_id)
        if record.state != TransactionState.VERIFICATION_PENDING:
            return
        items = await self.repo.list_evidence(transaction_id)
        if not items:
            return
        await self.verify(transaction_id, actor=actor)

    async def verify(self, transaction_id: str, *, actor: str, declarations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
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
        terms = await self._agreement_terms(transaction_id)
        result = evaluate(
            record,
            items,
            self.evidence_store,
            self._now(),
            inspection_window_hours=self.settings.inspection_window_hours,
            ledger_balances=balances,
            terms=terms,
            declarations=declarations,
        )
        slim_requirements = _slim_requirement_results(result.requirements)
        if result.pending:
            if result.reasons or result.inspection_deadline is not None:
                async with self.repo.transaction() as conn:
                    current = await self.repo.get_transaction(transaction_id, conn)
                    changes: dict[str, Any] = {
                        "verification": {
                            "status": "pending",
                            "reasons": [reason.value for reason in result.reasons],
                            "rollup": result.rollup,
                            "checked_at": self._iso(self._now()),
                            "override_allowed": False,
                            "requirements": slim_requirements,
                        },
                    }
                    if result.inspection_deadline is not None:
                        changes["deadlines"] = {
                            **(current.deadlines or {}),
                            "inspection": self._iso(result.inspection_deadline),
                        }
                    await self.repo.update_transaction(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        changes=changes,
                    )
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        reasons = list(result.reasons)
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
                            "rollup": result.rollup,
                            "checked_at": self._iso(self._now()),
                            "override_allowed": False,
                            "requirements": slim_requirements,
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
        # An objective FAIL rollup maps to REMEDIATION_REQUIRED in the target
        # design; the state lands with the state-machine task (Task 16), so the
        # failure path routes to REVIEW_REQUIRED until then.
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
                        "rollup": result.rollup,
                        "checked_at": self._iso(self._now()),
                        "override_allowed": result.override_allowed,
                        "requirements": slim_requirements,
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
                return datetime.fromisoformat(str(value))
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
        # Funding binding: prove the transaction still points at the agreed version.
        agreement = await self.agreement_service.get_by_transaction(transaction_id)
        if agreement is None:
            raise VerifundError("not_found", "agreement not found", status_code=404)
        txn_proj = await self._projection(record, "buyer")
        try:
            await self.agreement_service.verify_funding_binding(
                agreement, txn_proj, request.agreement_version, request.agreement_hash
            )
        except Exception as exc:
            from verifund_control_plane.agreements.models import AgreementError
            if isinstance(exc, AgreementError):
                raise VerifundError(exc.code, exc.message, status_code=409)
            raise
        approval = record.approval or {}
        if approval.get("agreement_version") not in (None, request.agreement_version) or (
            approval.get("agreement_hash") is not None
            and approval.get("agreement_hash") != request.agreement_hash
        ):
            raise VerifundError(
                "hash_mismatch", "funding approval binds a different version", status_code=409
            )
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

    def _funding_session(self, record: TransactionRecord) -> dict[str, Any]:
        funding = record.funding or {}
        return {
            "transaction_id": record.transaction_id,
            "amount_cents": record.amount_cents,
            "currency": record.currency,
            "expires_at": self._iso(self._funding_deadline(record)),
            "agreement_version": record.agreement_version,
            "agreement_hash": record.agreement_hash,
            "order_attempt": int(funding.get("order_attempt") or 0),
            "provider_order_id": funding.get("provider_order_id"),
        }

    async def prepare_funding(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]:
        """Validate funding and pin the deadline without calling PayPal.

        The transaction is left in ``AGREED`` so the redirect fallback can still
        call :meth:`fund`; ``attach_funding_order`` owns the transition.
        """
        record = await self.repo.get_transaction(transaction_id)
        if record.state == TransactionState.FUNDING_PENDING:
            return self._funding_session(record)
        if record.state != TransactionState.AGREED:
            raise VerifundError(
                "invalid_state", "transaction is not ready for funding", status_code=409
            )
        if not record.approval:
            raise VerifundError(
                "invalid_state", "buyer approval is required", status_code=409
            )

        agreement = await self.agreement_service.get_by_transaction(transaction_id)
        if agreement is None:
            raise VerifundError("not_found", "agreement not found", status_code=404)
        txn_proj = await self._projection(record, "buyer")
        try:
            await self.agreement_service.verify_funding_binding(
                agreement,
                txn_proj,
                record.agreement_version,
                record.agreement_hash,
            )
        except Exception as exc:
            from verifund_control_plane.agreements.models import AgreementError
            if isinstance(exc, AgreementError):
                raise VerifundError(exc.code, exc.message, status_code=409)
            raise
        approval = record.approval or {}
        if approval.get("agreement_version") not in (
            None,
            record.agreement_version,
        ) or (
            approval.get("agreement_hash") is not None
            and approval.get("agreement_hash") != record.agreement_hash
        ):
            raise VerifundError(
                "hash_mismatch",
                "funding approval binds a different version",
                status_code=409,
            )

        if (record.deadlines or {}).get("funding"):
            return self._funding_session(record)
        deadline = self._funding_deadline(record)
        try:
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes={
                        "deadlines": {
                            **(current.deadlines or {}),
                            "funding": self._iso(deadline),
                        }
                    },
                    audit=AuditInput(actor, "funding_prepared"),
                )
        except VerifundError as exc:
            # A concurrent prepare already stored the deadline.
            if exc.code != "conflict":
                raise
        return self._funding_session(
            await self.repo.get_transaction(transaction_id)
        )

    async def _funding_order_is_dead(self, order_id: str) -> bool:
        try:
            order = await self.payments.get_order(order_id)
        except VerifundError as exc:
            return exc.code == "not_found"
        return order.status in {"VOIDED", "EXPIRED"} or bool(order.captures)

    async def attach_funding_order(
        self, transaction_id: str, order_id: str, *, actor: str
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.state not in {
            TransactionState.AGREED,
            TransactionState.FUNDING_PENDING,
        }:
            raise VerifundError(
                "invalid_state", "transaction is not awaiting funding", status_code=409
            )
        funding = dict(record.funding or {})
        existing = funding.get("provider_order_id")
        attempt = int(funding.get("order_attempt") or 0)
        replaced = False
        if existing and existing != order_id:
            past_deadline = self._now() >= self._funding_deadline(record)
            if not past_deadline and not await self._funding_order_is_dead(existing):
                raise VerifundError(
                    "conflict", "funding order already attached", status_code=409
                )
            attempt = max(attempt, 1) + 1
            replaced = True
        elif not existing:
            attempt = max(attempt, 1)
        elif record.state == TransactionState.FUNDING_PENDING:
            # Replaying the same attach must not bump the version.
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            current_funding = dict(current.funding or {})
            current_order = current_funding.get("provider_order_id")
            if current_order and current_order not in {order_id, existing}:
                raise VerifundError(
                    "conflict", "funding order changed; reload and retry", status_code=409
                )
            deadline = (
                self._now()
                + timedelta(hours=self.settings.funding_timeout_hours)
                if replaced
                else self._funding_deadline(current)
            )
            changes = {
                "funding": {
                    **current_funding,
                    "status": "pending",
                    "provider_order_id": order_id,
                    "order_attempt": attempt,
                },
                "deadlines": {
                    **(current.deadlines or {}),
                    "funding": self._iso(deadline),
                },
            }
            if current.state == TransactionState.AGREED:
                await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=TransactionState.AGREED,
                    new_state=TransactionState.FUNDING_PENDING,
                    changes=changes,
                    events=[EventInput("funding_required", {}, actor)],
                    audit=AuditInput(actor, "funding_order_attached"),
                )
            elif current.state == TransactionState.FUNDING_PENDING:
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes=changes,
                    audit=AuditInput(actor, "funding_order_attached"),
                )
            else:
                raise VerifundError(
                    "invalid_state",
                    "transaction is not awaiting funding",
                    status_code=409,
                )
        return (await self._projection_for(transaction_id, "buyer")).model_dump(
            mode="json"
        )

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
        attempt = int((record.funding or {}).get("order_attempt") or 1)
        captures = order.captures
        if order.status == "APPROVED" and not captures:
            captures = (
                await self.payments.capture_order(
                    str(order_id),
                    idempotency_key=f"capture:{transaction_id}:v{attempt}",
                ),
            )
        for capture in captures:
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
    def _validate_purchase_order(
        self,
        record: TransactionRecord,
        agreement: dict[str, Any],
        request: PurchaseOrderReport,
    ) -> None:
        if (
            request.total_cents != record.amount_cents
            or request.currency != record.currency
            or request.offer_id != record.offer_id
        ):
            raise VerifundError(
                "conflict",
                "purchase order total, currency, or offer does not match",
                status_code=409,
            )
        if request.quantity != sum(
            item.quantity for item in request.line_items
        ):
            raise VerifundError(
                "invalid_request",
                "purchase order quantity does not match line items",
                status_code=400,
            )
        expected = sorted(
            (
                item["sku"],
                item["quantity"],
                item["unit_price_cents"],
                item["warranty_addon_cents"],
            )
            for item in agreement["line_items"]
        )
        actual = sorted(
            (
                item.sku,
                item.quantity,
                item.unit_price_cents,
                item.warranty_addon_cents,
            )
            for item in request.line_items
        )
        if expected != actual:
            raise VerifundError(
                "conflict",
                "purchase order line items do not match the agreement",
                status_code=409,
            )

    async def report_purchase_order(
        self,
        transaction_id: str,
        request: PurchaseOrderReport,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        body = request.model_dump(mode="json")
        cached = await self._replay(
            f"purchase-order:{transaction_id}", idempotency_key, body
        )
        if cached is not None:
            return cached
        items = await self.repo.list_evidence(transaction_id)

        async def operation(conn):
            record = await self.repo.get_transaction(transaction_id, conn)
            self._check_hash(record, request.agreement_hash)
            existing = record.purchase_order or {}
            settled_states = {
                TransactionState.FULFILLMENT_PENDING,
                TransactionState.VERIFICATION_PENDING,
                TransactionState.RELEASE_PERMITTED,
                TransactionState.PAYOUT_PENDING,
                TransactionState.RELEASED,
                TransactionState.REVIEW_REQUIRED,
            }
            if (
                existing.get("seller_order_id") == request.seller_order_id
                and record.state in settled_states
            ):
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state != TransactionState.FUNDED:
                raise VerifundError(
                    "invalid_state",
                    "transaction is not ready for a purchase order",
                    status_code=409,
                )
            agreement_record = await self.agreement_service.get_by_transaction(transaction_id)
            agreement = (await self.agreement_service.build_projection(agreement_record)).model_dump(mode="json") if agreement_record is not None else {}
            self._validate_purchase_order(record, agreement, request)
            deadline = self._now() + timedelta(
                hours=self.settings.evidence_deadline_hours
            )
            snapshot = {
                "seller_order_id": request.seller_order_id,
                "offer_id": request.offer_id,
                "quantity": request.quantity,
                "total_cents": request.total_cents,
                "currency": request.currency,
                "tracking_number": request.tracking_number,
                "carrier": request.carrier,
                "reserved_at": self._iso(request.reserved_at),
                "eta": self._iso(request.eta),
                "line_items": [
                    item.model_dump(mode="json")
                    for item in request.line_items
                ],
            }
            updated = await self.repo.transition(
                conn,
                transaction_id,
                expected_version=record.version,
                expected_state=TransactionState.FUNDED,
                new_state=TransactionState.FULFILLMENT_PENDING,
                changes={
                    "purchase_order": snapshot,
                    "deadlines": {
                        **(record.deadlines or {}),
                        "evidence": self._iso(deadline),
                    },
                },
                events=[
                    EventInput(
                        "purchase_order_reported",
                        {
                            "seller_order_id": request.seller_order_id,
                            "tracking_number": request.tracking_number,
                        },
                        actor,
                    )
                ],
                audit=AuditInput(actor, "purchase_order_reported"),
            )
            if items:
                updated = await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=updated.version,
                    expected_state=TransactionState.FULFILLMENT_PENDING,
                    new_state=TransactionState.VERIFICATION_PENDING,
                    changes={},
                    audit=AuditInput(actor, "verification_started"),
                )
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")

        result = await self._mutate(
            scope=f"purchase-order:{transaction_id}",
            key=idempotency_key,
            body=body,
            operation=operation,
        )
        if request.tracking_number:
            await self.register_tracker(
                transaction_id,
                tracking_number=request.tracking_number,
                carrier=request.carrier,
                actor=actor,
            )
        if result["state"] == TransactionState.VERIFICATION_PENDING.value:
            await self.verify_if_ready(transaction_id, actor=actor)
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        return result

    async def flag_review(
        self,
        transaction_id: str,
        request: FlagReviewRequest,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        items = await self.repo.list_evidence(transaction_id)

        async def operation(conn):
            record = await self.repo.get_transaction(transaction_id, conn)
            if record.state == TransactionState.REVIEW_REQUIRED:
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state in {
                TransactionState.CANCELED,
                TransactionState.FAILED,
                TransactionState.RELEASED,
            }:
                raise VerifundError(
                    "invalid_state",
                    "terminal transactions cannot be flagged",
                    status_code=409,
                )
            reasons = list(
                (record.verification or {}).get("reasons") or []
            )
            if "manual_flag" not in reasons:
                reasons.append("manual_flag")
            updated = await self.repo.transition(
                conn,
                transaction_id,
                expected_version=record.version,
                expected_state=record.state,
                new_state=TransactionState.REVIEW_REQUIRED,
                changes={
                    "verification": {
                        "status": "failed",
                        "reasons": reasons,
                        "checked_at": self._iso(self._now()),
                        "override_allowed": True,
                    }
                },
                events=[
                    EventInput(
                        "review_required",
                        {"reasons": reasons, "note": request.note},
                        actor,
                    )
                ],
                audit=AuditInput(
                    actor,
                    "manual_flag",
                    note=request.note,
                    payload={"reason": request.reason},
                ),
            )
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")

        return await self._mutate(
            scope=f"flag-review:{transaction_id}",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )

    def _seller_token_states(self) -> set[TransactionState]:
        return {
            TransactionState.AWARDED,
            TransactionState.AGREED,
            TransactionState.FUNDING_PENDING,
            TransactionState.FUNDED,
            TransactionState.FULFILLMENT_PENDING,
            TransactionState.VERIFICATION_PENDING,
        }

    async def reissue_seller_token(
        self,
        transaction_id: str,
        request: SellerTokenRequest | None = None,
        *,
        actor: str = "system",
        **kwargs: Any,
    ) -> dict[str, Any]:
        if getattr(self.settings, "tenancy_enabled", False) and self.tenancy is not None:
            _rec = await self.repo.get_transaction(transaction_id)
            _sid = request.seller_id if request is not None else _rec.seller_id
            if await self.seller_status(_sid) != "verified":
                raise VerifundError(
                    "seller_not_verified",
                    "seller is not verified for new transactions",
                    status_code=403,
                )
        if request is None:
            record = await self.repo.get_transaction(transaction_id)
            request = SellerTokenRequest(
                transaction_id=transaction_id,
                run_id=record.run_id,
                seller_id=record.seller_id,
                purpose=kwargs.get("purpose", "version_bump"),
            )
        record = await self.repo.get_transaction(transaction_id)
        if (
            record.run_id != request.run_id
            or record.seller_id != request.seller_id
            or transaction_id != request.transaction_id
        ):
            raise VerifundError(
                "forbidden",
                "seller token request does not match the transaction",
                status_code=403,
            )
        if record.state not in self._seller_token_states():
            raise VerifundError(
                "forbidden",
                "seller token cannot be reissued after release authorization",
                status_code=403,
            )
        issued = self.tokens.issue(
            transaction_id, record.seller_id, record.agreement_hash
        )
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.version != record.version:
                raise VerifundError(
                    "conflict", "transaction changed; retry", status_code=409
                )
            await self.repo.revoke_seller_tokens(
                conn, transaction_id, self._now()
            )
            await self.repo.save_seller_token(
                conn,
                issued.jti_hash,
                transaction_id,
                record.seller_id,
                record.agreement_hash,
                ["txn:read", "evidence:write"],
                issued.expires_at,
            )
            await self.repo.audit(
                conn,
                transaction_id,
                AuditInput(
                    actor,
                    "seller_token_reissued",
                    payload={"purpose": request.purpose},
                ),
            )
        return SellerTokenResponse(
            seller_token=issued.token, expires_at=issued.expires_at
        ).model_dump(mode="json")

    async def revoke_seller_token(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]:
        async with self.repo.transaction() as conn:
            await self.repo.get_transaction(transaction_id, conn)
            await self.repo.revoke_seller_tokens(
                conn, transaction_id, self._now()
            )
            await self.repo.audit(
                conn,
                transaction_id,
                AuditInput(actor, "seller_token_revoked"),
            )
        return {"revoked": True}
    async def extend_deadline(
        self,
        transaction_id: str,
        *,
        hours: int | None = None,
        deadline: Any = None,
        actor: str = "system",
        **kwargs: Any,
    ) -> dict[str, Any]:
        if hours is None:
            hours = kwargs.get("hours") or kwargs.get("additional_hours") or 0
        record = await self.repo.get_transaction(transaction_id)
        deadlines = dict(record.deadlines or {})
        now = self._now()
        current_raw = deadlines.get("inspection")
        try:
            current = (
                datetime.fromisoformat(str(current_raw)) if current_raw is not None else now
            )
        except (TypeError, ValueError):
            current = now
        if deadline is not None:
            if isinstance(deadline, str):
                new_deadline = datetime.fromisoformat(deadline)
            else:
                new_deadline = deadline
        else:
            new_deadline = current + timedelta(hours=int(hours or 0))
        deadlines["inspection"] = new_deadline.isoformat()
        async with self.repo.transaction() as conn:
            await self.repo.update_transaction(
                conn,
                transaction_id,
                expected_version=record.version,
                changes={"deadlines": deadlines},
                audit=AuditInput(actor, "deadline_extended"),
            )
        return (
            await self._projection_for(transaction_id, "buyer")
        ).model_dump(mode="json")

    async def refund(
        self,
        transaction_id: str,
        remedy: str | None = None,
        *,
        actor: str = "system",
        **kwargs: Any,
    ) -> dict[str, Any]:
        if remedy is None:
            remedy = kwargs.get("remedy") or kwargs.get("reason") or "refund"
        await self.repo.get_transaction(transaction_id)
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            await self.repo.transition(
                conn,
                transaction_id,
                expected_version=current.version,
                expected_state=current.state,
                new_state=TransactionState.REFUNDED,
                changes={"refund": {"remedy": remedy, "at": self._iso(self._now())}},
                audit=AuditInput(actor, "refunded", payload={"remedy": remedy}),
            )
        return (
            await self._projection_for(transaction_id, "buyer")
        ).model_dump(mode="json")

    async def dispute_decision(
        self,
        transaction_id: str,
        decision: str | None = None,
        *,
        remedy: str | None = None,
        reviewer: str | None = None,
        actor: str = "ops",
        **kwargs: Any,
    ) -> dict[str, Any]:
        if decision is None:
            decision = kwargs.get("decision")
        record = await self.repo.get_transaction(transaction_id)
        if record.state != TransactionState.DISPUTE_OPEN:
            raise VerifundError(
                "invalid_state",
                "transaction is not in dispute",
                status_code=409,
            )
        decision = str(decision or "").lower()
        if decision == "dismissed":
            target = TransactionState.RELEASE_PERMITTED
        elif decision == "upheld":
            target = (
                TransactionState.REFUNDED
                if remedy == "refund"
                else TransactionState.REMEDIATION_REQUIRED
            )
        elif decision == "settled":
            target = TransactionState.RELEASE_PERMITTED
        else:
            raise VerifundError(
                "invalid_request", "unknown dispute decision", status_code=422
            )

        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if target == TransactionState.REFUNDED:
                await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.REFUNDED,
                    changes={"dispute": {**(current.dispute or {}), "decision": decision, "remedy": remedy}},
                    audit=AuditInput(actor, "dispute_decision", payload={"decision": decision, "remedy": remedy}),
                )
            else:
                await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=target,
                    changes={"dispute": {**(current.dispute or {}), "decision": decision, "remedy": remedy}},
                    audit=AuditInput(actor, "dispute_decision", payload={"decision": decision, "remedy": remedy}),
                )
        if target == TransactionState.REFUNDED and remedy == "refund":
            # Apply refund path if not already terminal.
            pass
        return (
            await self._projection_for(transaction_id, "buyer")
        ).model_dump(mode="json")

    async def resolve_system_failure(
        self,
        transaction_id: str,
        *,
        resolution: str = "release",
        actor: str = "ops",
        **kwargs: Any,
    ) -> dict[str, Any]:
        resolution = kwargs.get("resolution", resolution)
        await self.repo.get_transaction(transaction_id)
        if resolution == "release":
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.RELEASE_PERMITTED,
                    changes={},
                    audit=AuditInput(actor, "system_failure_resolved", payload={"resolution": "release"}),
                )
        elif resolution == "cancel":
            await self.cancel(
                transaction_id,
                __import__("verifund_contracts.models", fromlist=["CancelRequest"]).CancelRequest(
                    reason_code=__import__("verifund_contracts", fromlist=["CancelReason"]).CancelReason.MANUAL_FLAG
                ),
                actor=actor,
                idempotency_key=f"resolve:{transaction_id}",
            )
        else:
            raise VerifundError("invalid_request", "unknown resolution", status_code=422)
        return (
            await self._projection_for(transaction_id, "buyer")
        ).model_dump(mode="json")

    async def return_to_remediation(
        self,
        transaction_id: str,
        *,
        note: str,
        actor: str = "ops",
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not note or not note.strip():
            raise VerifundError(
                "invalid_request", "note is required", status_code=400
            )
        record = await self.repo.get_transaction(transaction_id)
        if record.state != TransactionState.REVIEW_REQUIRED:
            raise VerifundError(
                "invalid_state",
                "return-to-remediation requires REVIEW_REQUIRED",
                status_code=409,
            )
        deadlines = dict(record.deadlines or {})
        deadlines["remediation"] = (self._now() + timedelta(hours=72)).isoformat()
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            await self.repo.revoke_seller_tokens(conn, transaction_id, self._now())
            await self.repo.transition(
                conn,
                transaction_id,
                expected_version=current.version,
                expected_state=current.state,
                new_state=TransactionState.REMEDIATION_REQUIRED,
                changes={"deadlines": deadlines},
                audit=AuditInput(actor, "ops.returned_to_remediation", note=note),
            )
        return (
            await self._projection_for(transaction_id, "buyer")
        ).model_dump(mode="json")

    async def release(
        self,
        transaction_id: str,
        request: ReleaseRequest,
        *,
        actor: str,
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if (record.dispute or {}).get("status") == "open" or (
            record.state == TransactionState.DISPUTE_OPEN
        ):
            raise VerifundError(
                "conflict",
                "release is blocked while a dispute is open",
                status_code=409,
            )
        if record.state in {
            TransactionState.PAYOUT_PENDING,
            TransactionState.RELEASED,
        }:
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        if record.state == TransactionState.REVIEW_REQUIRED:
            if not request.override or not request.note.strip():
                raise VerifundError(
                    "forbidden",
                    "override and a note are required in review",
                    status_code=403,
                )
            verification = record.verification or {}
            reasons = verification.get("reasons") or []
            non_overridable = {
                reason.value for reason in NON_OVERRIDABLE_REASONS
            }
            if not verification.get("override_allowed") or any(
                reason in non_overridable for reason in reasons
            ):
                raise VerifundError(
                    "forbidden",
                    "review reasons cannot be overridden",
                    status_code=403,
                )
        elif record.state != TransactionState.RELEASE_PERMITTED:
            raise VerifundError(
                "invalid_state",
                "transaction is not ready for release",
                status_code=409,
            )
        return await self._start_payout(
            transaction_id,
            actor=actor,
            events=[
                EventInput(
                    "release_authorized",
                    {
                        "released_by": request.released_by,
                        "override": request.override,
                    },
                    actor,
                ),
                EventInput("payout_pending", {}, actor),
            ],
            audit=AuditInput(
                actor,
                "release_authorized",
                note=request.note,
                payload={"override": request.override},
            ),
        )

    async def buyer_accept(
        self,
        transaction_id: str,
        *,
        buyer_id: str,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Early buyer acceptance (spec §3.6).

        ACCEPT releases immediately and is final: the transaction moves from
        `VERIFICATION_PENDING`/`RELEASE_PERMITTED` straight to `PAYOUT_PENDING`,
        so a later dispute cannot be opened.
        """
        actor = actor or f"buyer:{buyer_id}"
        record = await self.repo.get_transaction(transaction_id)
        if record.buyer_id != buyer_id:
            raise VerifundError(
                "forbidden", "buyer does not own this transaction", status_code=403
            )
        if (record.dispute or {}).get("status") == "open":
            raise VerifundError(
                "conflict",
                "acceptance is blocked while a dispute is open",
                status_code=409,
            )
        if record.state in {
            TransactionState.PAYOUT_PENDING,
            TransactionState.RELEASED,
        }:
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        if record.state not in {
            TransactionState.VERIFICATION_PENDING,
            TransactionState.RELEASE_PERMITTED,
        }:
            raise VerifundError(
                "invalid_state",
                "acceptance requires VERIFICATION_PENDING or RELEASE_PERMITTED",
                status_code=409,
            )
        return await self._start_payout(
            transaction_id,
            actor=actor,
            events=[
                EventInput(
                    "buyer_accepted",
                    {"buyer_id": buyer_id, "final": True},
                    actor,
                ),
                EventInput("payout_pending", {}, actor),
            ],
            audit=AuditInput(
                actor,
                "buyer_accepted",
                payload={"buyer_id": buyer_id, "final": True},
            ),
        )

    async def _start_payout(
        self,
        transaction_id: str,
        *,
        actor: str,
        events: list[EventInput],
        audit: AuditInput,
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        funding = record.funding or {}
        if funding.get("status") != "captured" or not funding.get("capture_id"):
            raise VerifundError(
                "invalid_state", "captured funds are required", status_code=409
            )
        balances = await self.repo.ledger_balances(transaction_id)
        if balances.get("held_funds", 0) != record.amount_cents:
            raise VerifundError(
                "invalid_state",
                "held funds do not match the agreement amount",
                status_code=409,
            )
        operation_id = f"op_{uuid.uuid4().hex}"
        batch_id = f"batch_{transaction_id}"
        sender_item_id = f"item_{transaction_id}"
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state in {
                TransactionState.PAYOUT_PENDING,
                TransactionState.RELEASED,
            }:
                return (
                    await self._projection(current, "buyer")
                ).model_dump(mode="json")
            now = self._now()
            payout = {
                "status": "pending",
                "batch_id": batch_id,
                "item_id": None,
                "amount_cents": current.amount_cents,
                "updated_at": self._iso(now),
                "operation_id": operation_id,
                "sender_item_id": sender_item_id,
            }
            await self.repo.transition(
                conn,
                transaction_id,
                expected_version=current.version,
                expected_state=current.state,
                new_state=TransactionState.PAYOUT_PENDING,
                changes={"payout": payout},
                events=events,
                audit=audit,
            )
            await self.repo.create_provider_operation(
                conn,
                operation_id,
                transaction_id,
                "create_payout",
                batch_id,
                {
                    "sender_item_id": sender_item_id,
                    "amount_cents": current.amount_cents,
                    "currency": current.currency,
                },
            )
        await self._execute_payout(
            transaction_id,
            operation_id=operation_id,
            batch_id=batch_id,
            sender_item_id=sender_item_id,
            actor=actor,
        )
        return (
            await self._projection_for(transaction_id, "buyer")
        ).model_dump(mode="json")

    async def _tracking_items(
        self, record: TransactionRecord
    ) -> list[dict[str, Any]]:
        purchase_order = record.purchase_order or {}
        items = [
            {
                "sku": str(item.get("sku") or ""),
                "quantity": str(item.get("quantity") or 1),
            }
            for item in (purchase_order.get("line_items") or [])
            if item.get("sku")
        ]
        if items:
            return items
        if self.agreement_service is not None:
            with suppress(Exception):
                agreement = await self.agreement_service.get_by_transaction(
                    record.transaction_id
                )
                if agreement is not None:
                    projection = await self.agreement_service.build_projection(
                        agreement
                    )
                    return [
                        {"sku": item.sku, "quantity": str(item.quantity)}
                        for item in projection.line_items
                    ]
        return []

    async def register_tracker(
        self,
        transaction_id: str,
        *,
        tracking_number: str,
        carrier: str | None,
        actor: str = "system",
    ) -> dict[str, Any] | None:
        """Register one post-capture tracker; best-effort and idempotent."""
        if self.tracking is None or not tracking_number:
            return None
        record = await self.repo.get_transaction(transaction_id)
        funding = record.funding or {}
        capture_id = funding.get("capture_id")
        if funding.get("status") != "captured" or not capture_id:
            return None
        existing = record.tracker or {}
        if (
            existing.get("tracker_id")
            and existing.get("tracking_number") == tracking_number
        ):
            return existing
        items = await self._tracking_items(record)
        try:
            tracker_id = await self.tracking.sync(
                transaction_id=transaction_id,
                capture_id=str(capture_id),
                tracking_number=tracking_number,
                carrier=carrier or "OTHER",
                items=items,
            )
        except VerifundError as exc:
            async with self.repo.transaction() as conn:
                await self.repo.audit(
                    conn,
                    transaction_id,
                    AuditInput(
                        actor,
                        "paypal.tracker_registration_failed",
                        payload={
                            "code": exc.code,
                            "message": exc.message,
                            "tracking_number": tracking_number,
                        },
                    ),
                )
            return None
        block = {
            "tracker_id": tracker_id,
            "tracking_number": tracking_number,
            "carrier": carrier or "OTHER",
            "last_status": "SHIPPED",
            "status_source": "merchant_push",
            "updated_at": self._iso(self._now()),
        }
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state in {
                TransactionState.CANCELED,
                TransactionState.FAILED,
            }:
                return None
            await self.repo.update_transaction(
                conn,
                transaction_id,
                expected_version=current.version,
                changes={"tracker": block},
                audit=AuditInput(
                    actor,
                    "paypal.tracker_registered",
                    payload={"tracker_id": tracker_id},
                ),
            )
        return block

    async def refresh_tracker(
        self, transaction_id: str
    ) -> dict[str, Any] | None:
        """Refresh persisted merchant-pushed tracker status; failures are non-fatal."""
        record = await self.repo.get_transaction(transaction_id)
        tracker = record.tracker or {}
        tracker_id = tracker.get("tracker_id")
        if self.tracking is None or not tracker_id:
            return tracker or None
        try:
            refreshed = await self.tracking.fetch(str(tracker_id))
        except Exception:  # noqa: BLE001 - tracker display refresh is best-effort
            return tracker
        if not refreshed:
            return tracker
        block = {
            **tracker,
            **refreshed,
            "status_source": "merchant_push",
            "updated_at": self._iso(self._now()),
        }
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            await self.repo.update_transaction(
                conn,
                transaction_id,
                expected_version=current.version,
                changes={"tracker": block},
            )
        return block

    async def dispute_decision_context(
        self, transaction_id: str
    ) -> dict[str, Any]:
        """Read-only decision view: transaction projection plus tracker."""
        projection = await self._projection_for(transaction_id, "buyer")
        return projection.model_dump(mode="json")

    async def _execute_payout(
        self,
        transaction_id: str,
        *,
        operation_id: str,
        batch_id: str,
        sender_item_id: str,
        actor: str,
    ) -> None:
        record = await self.repo.get_transaction(transaction_id)
        seller_email = (await self._payout_email(record.seller_id)) or f"{record.seller_id}@example.test"
        try:
            result = await self.payments.create_payout(
                record,
                seller_email=seller_email,
                batch_id=batch_id,
                item_id=sender_item_id,
            )
        except VerifundError as exc:
            await self.repo.update_provider_operation(
                operation_id,
                status="failed",
                last_error=exc.message,
                increment_attempts=True,
            )
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(
                    transaction_id, conn
                )
                if current.state == TransactionState.PAYOUT_PENDING:
                    await self.repo.update_transaction(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        changes={
                            "payout": {
                                **(current.payout or {}),
                                "status": "create_failed",
                                "last_error": exc.message,
                                "updated_at": self._iso(self._now()),
                            }
                        },
                        audit=AuditInput(
                            actor,
                            "payout_create_failed",
                            payload={"code": exc.code},
                        ),
                    )
            return
        await self.repo.update_provider_operation(
            operation_id,
            status="completed",
            provider_id=result.item_id,
            response=result.raw,
        )
        await self.apply_payout(transaction_id, result, actor=actor)

    async def apply_payout(
        self, transaction_id: str, result: PayoutResult, *, actor: str
    ) -> None:
        record = await self.repo.get_transaction(transaction_id)
        status = result.status.upper()
        current_payout = record.payout or {}
        payout = {
            **current_payout,
            "status": result.status,
            "batch_id": result.batch_id or current_payout.get("batch_id"),
            "item_id": result.item_id or current_payout.get("item_id"),
            "amount_cents": result.amount_cents,
            "updated_at": self._iso(self._now()),
        }
        seller_email = (await self._payout_email(record.seller_id)) or f"{record.seller_id}@example.test"
        sender_item_id = str(
            current_payout.get("sender_item_id") or f"item_{transaction_id}"
        )
        if status in {"PENDING", "ONHOLD", "UNCLAIMED"}:
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                if current.state == TransactionState.PAYOUT_PENDING:
                    await self.repo.update_transaction(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        changes={"payout": payout},
                        events=[
                            EventInput(
                                "payout_pending",
                                {"status": result.status},
                                actor,
                            )
                        ],
                        audit=AuditInput(actor, "payout_pending"),
                    )
            return
        if status == "SUCCESS":
            if (
                result.amount_cents != record.amount_cents
                or result.currency != record.currency
            ):
                await self._payout_review(
                    transaction_id,
                    payout,
                    actor=actor,
                    reason="manual_flag",
                    note="payout amount or currency mismatch",
                )
                return
            balances = await self.repo.ledger_balances(transaction_id)
            items = await self.repo.list_evidence(transaction_id)
            signed = self.receipts.sign(
                build_receipt_payload(
                    transaction_id=transaction_id,
                    agreement_hash=record.agreement_hash,
                    amount_cents=record.amount_cents,
                    currency=record.currency,
                    buyer_id=record.buyer_id,
                    seller_id=record.seller_id,
                    capture_id=str(
                        (record.funding or {}).get("capture_id") or ""
                    ),
                    payout_item_id=result.item_id,
                    evidence_hashes=[item.sha256 for item in items],
                    released_at=self._now(),
                )
            )
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                await self.repo.upsert_payout_item(
                    conn,
                    result.item_id,
                    transaction_id,
                    result.batch_id,
                    sender_item_id,
                    seller_email,
                    result.amount_cents,
                    result.currency,
                    result.status,
                    result.raw,
                )
                if current.state == TransactionState.RELEASED:
                    return
                if balances.get("held_funds", 0) != current.amount_cents:
                    await self.repo.transition(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        expected_state=current.state,
                        new_state=TransactionState.REVIEW_REQUIRED,
                        changes={
                            "payout": payout,
                            "verification": {
                                "status": "failed",
                                "reasons": ["ledger_incomplete"],
                                "checked_at": self._iso(self._now()),
                                "override_allowed": False,
                            },
                        },
                        events=[
                            EventInput(
                                "review_required",
                                {"reason": "ledger_incomplete"},
                                actor,
                            )
                        ],
                        audit=AuditInput(actor, "ledger_incomplete"),
                    )
                    return
                if current.state not in {
                    TransactionState.PAYOUT_PENDING,
                    TransactionState.REVIEW_REQUIRED,
                }:
                    return
                await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.RELEASED,
                    changes={
                        "payout": payout,
                        "receipt": {
                            "kid": signed.kid,
                            "payload_hash": signed.payload_hash,
                            "signed_at": self._iso(self._now()),
                        },
                    },
                    events=[
                        EventInput(
                            "released",
                            {
                                "payout_item_id": result.item_id,
                                "amount_cents": result.amount_cents,
                            },
                            actor,
                        )
                    ],
                    ledger_entries=payout_ledger_entries(
                        transaction_id, current.amount_cents
                    ),
                    audit=AuditInput(
                        actor,
                        "released",
                        note=f"payout {result.item_id}",
                    ),
                )
                await self.repo.save_receipt(
                    conn,
                    transaction_id,
                    signed.payload,
                    signed.payload_hash,
                    signed.signature,
                    signed.kid,
                )
            return
        if status in {"FAILED", "BLOCKED", "DENIED", "RETURNED"}:
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                await self.repo.upsert_payout_item(
                    conn,
                    result.item_id,
                    transaction_id,
                    result.batch_id,
                    sender_item_id,
                    seller_email,
                    result.amount_cents,
                    result.currency,
                    result.status,
                    result.raw,
                )
                if current.state == TransactionState.RELEASED:
                    await self.repo.transition(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        expected_state=current.state,
                        new_state=TransactionState.REVIEW_REQUIRED,
                        changes={
                            "payout": payout,
                            "verification": {
                                "status": "failed",
                                "reasons": ["manual_flag"],
                                "checked_at": self._iso(self._now()),
                                "override_allowed": False,
                            },
                        },
                        events=[
                            EventInput(
                                "review_required",
                                {"reason": "payout_returned"},
                                actor,
                            )
                        ],
                        audit=AuditInput(actor, "payout_returned"),
                    )
                elif current.state == TransactionState.PAYOUT_PENDING:
                    await self.repo.transition(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        expected_state=current.state,
                        new_state=TransactionState.FAILED,
                        changes={
                            "payout": payout,
                            "last_error": {
                                "code": "provider_rejected",
                                "message": f"payout {result.status.lower()}",
                            },
                        },
                        events=[
                            EventInput(
                                "failed",
                                {"status": result.status},
                                actor,
                            )
                        ],
                        audit=AuditInput(actor, "payout_failed"),
                    )
            return
        if status in {"REFUNDED", "REVERSED"}:
            await self._payout_review(
                transaction_id,
                payout,
                actor=actor,
                reason="manual_flag",
                note=f"payout {status.lower()}",
            )

    async def _payout_review(
        self,
        transaction_id: str,
        payout: dict[str, Any],
        *,
        actor: str,
        reason: str,
        note: str,
    ) -> None:
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state == TransactionState.REVIEW_REQUIRED:
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes={"payout": payout},
                    audit=AuditInput(actor, "payout_review", note=note),
                )
                return
            await self.repo.transition(
                conn,
                transaction_id,
                expected_version=current.version,
                expected_state=current.state,
                new_state=TransactionState.REVIEW_REQUIRED,
                changes={
                    "payout": payout,
                    "verification": {
                        "status": "failed",
                        "reasons": [reason],
                        "checked_at": self._iso(self._now()),
                        "override_allowed": False,
                    },
                },
                events=[
                    EventInput(
                        "review_required", {"reason": note}, actor
                    )
                ],
                audit=AuditInput(actor, "payout_review", note=note),
            )

    async def retry_payout(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.state == TransactionState.RELEASED:
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        if record.state not in {
            TransactionState.PAYOUT_PENDING,
            TransactionState.REVIEW_REQUIRED,
        }:
            raise VerifundError(
                "invalid_state",
                "transaction is not awaiting payout",
                status_code=409,
            )
        payout = record.payout or {}
        if not payout.get("operation_id") or not payout.get("batch_id"):
            raise VerifundError(
                "invalid_state",
                "payout has not been authorized by a reviewer",
                status_code=409,
            )
        if record.state == TransactionState.REVIEW_REQUIRED and payout.get(
            "status"
        ) not in {
            "pending",
            "create_failed",
            "PENDING",
            "ONHOLD",
            "UNCLAIMED",
            "FAILED",
            "BLOCKED",
            "DENIED",
            "RETURNED",
        }:
            raise VerifundError(
                "invalid_state",
                "transaction is not awaiting a payout retry",
                status_code=409,
            )
        if payout.get("item_id"):
            result = await self.payments.get_payout_item(
                str(payout["item_id"])
            )
            await self.apply_payout(transaction_id, result, actor=actor)
        else:
            await self._execute_payout(
                transaction_id,
                operation_id=str(payout["operation_id"]),
                batch_id=str(payout["batch_id"]),
                sender_item_id=str(
                    payout.get("sender_item_id")
                    or f"item_{transaction_id}"
                ),
                actor=actor,
            )
        return (
            await self._projection_for(transaction_id, "buyer")
        ).model_dump(mode="json")

    async def refresh_payout(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.state not in {
            TransactionState.PAYOUT_PENDING,
            TransactionState.REVIEW_REQUIRED,
            TransactionState.RELEASED,
        }:
            raise VerifundError(
                "invalid_state",
                "transaction has no payout to refresh",
                status_code=409,
            )
        item_id = (record.payout or {}).get("item_id")
        if item_id:
            try:
                result = await self.payments.get_payout_item(str(item_id))
            except VerifundError as exc:
                if exc.code != "not_found":
                    raise
            else:
                await self.apply_payout(
                    transaction_id, result, actor=actor
                )
        return (
            await self._projection_for(transaction_id, "buyer")
        ).model_dump(mode="json")

    async def get_receipt(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]:
        await self.repo.get_transaction(transaction_id)
        data = await self.repo.get_receipt(transaction_id)
        verified = self.receipts.verify(
            data["payload"],
            data["payload_hash"],
            data["signature"],
            data["kid"],
        )
        return ReceiptResponse(
            payload=data["payload"],
            payload_hash=data["payload_hash"],
            signature=data["signature"],
            kid=data["kid"],
            verified=verified,
        ).model_dump(mode="json")

    async def recover_operation(
        self, operation: dict[str, Any], *, actor: str
    ) -> bool:
        kind = str(operation.get("kind") or "")
        transaction_id = str(operation.get("transaction_id") or "")
        operation_id = str(operation.get("operation_id") or "")
        if not transaction_id or not operation_id:
            return False
        record = await self.repo.get_transaction(transaction_id)
        if kind == "create_order":
            funding = record.funding or {}
            if (
                record.state != TransactionState.FUNDING_PENDING
                or funding.get("provider_order_id")
            ):
                return False
            request = operation.get("request") or {}
            order = await self.payments.create_order(
                record,
                return_url=str(request.get("return_url") or ""),
                cancel_url=str(request.get("cancel_url") or ""),
                idempotency_key=str(operation.get("idempotency_key") or ""),
            )
            payer_url = str(
                order.payer_action_url or request.get("return_url") or ""
            )
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(
                    transaction_id, conn
                )
                if current.state == TransactionState.FUNDING_PENDING:
                    await self.repo.update_transaction(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        changes={
                            "funding": {
                                **(current.funding or {}),
                                "status": "pending",
                                "provider_order_id": order.order_id,
                                "payer_action_url": payer_url,
                                "checkout_url": payer_url,
                            }
                        },
                        audit=AuditInput(actor, "funding_order_recovered"),
                    )
            await self.repo.update_provider_operation(
                operation_id,
                status="completed",
                provider_id=order.order_id,
                response=order.raw,
            )
            return True
        if kind == "create_payout":
            payout = record.payout or {}
            if record.state not in {
                TransactionState.PAYOUT_PENDING,
                TransactionState.REVIEW_REQUIRED,
            } or payout.get("item_id"):
                return False
            request = operation.get("request") or {}
            await self._execute_payout(
                transaction_id,
                operation_id=operation_id,
                batch_id=str(
                    payout.get("batch_id")
                    or operation.get("idempotency_key")
                    or f"batch_{transaction_id}"
                ),
                sender_item_id=str(
                    request.get("sender_item_id") or f"item_{transaction_id}"
                ),
                actor=actor,
            )
            return True
        return False

    async def backfill_receipt(
        self, transaction_id: str, *, actor: str
    ) -> bool:
        record = await self.repo.get_transaction(transaction_id)
        if record.state != TransactionState.RELEASED or record.receipt:
            return False
        item_id = str((record.payout or {}).get("item_id") or "")
        if not item_id:
            return False
        try:
            await self.repo.get_payout_item(item_id)
        except VerifundError:
            return False
        items = await self.repo.list_evidence(transaction_id)
        signed = self.receipts.sign(
            build_receipt_payload(
                transaction_id=transaction_id,
                agreement_hash=record.agreement_hash,
                amount_cents=record.amount_cents,
                currency=record.currency,
                buyer_id=record.buyer_id,
                seller_id=record.seller_id,
                capture_id=str(
                    (record.funding or {}).get("capture_id") or ""
                ),
                payout_item_id=item_id,
                evidence_hashes=[item.sha256 for item in items],
                released_at=self._now(),
            )
        )
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state != TransactionState.RELEASED or current.receipt:
                return False
            await self.repo.save_receipt(
                conn,
                transaction_id,
                signed.payload,
                signed.payload_hash,
                signed.signature,
                signed.kid,
            )
            await self.repo.update_transaction(
                conn,
                transaction_id,
                expected_version=current.version,
                changes={
                    "receipt": {
                        "kid": signed.kid,
                        "payload_hash": signed.payload_hash,
                        "signed_at": self._iso(self._now()),
                    }
                },
                audit=AuditInput(actor, "receipt_backfilled"),
            )
        return True
