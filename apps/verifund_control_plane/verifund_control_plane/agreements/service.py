from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from verifund_contracts.models import (
    AgreementDecision,
    AgreementDecisionView,
    AgreementProjection,
    AgreementState,
    AgreementVersionView,
    AgreementView,
    AwardLineItem,
    BuyerApprovalDecision,
    ChangeRequestView,
    ChangeSet,
    EvidenceKind,
    RemedyPolicy,
    RemedyTerms,
)

from verifund_control_plane.agreements.digest import agreement_hash
from verifund_control_plane.agreements.generator import (
    apply_change_set,
    build_terms,
    validate_award,
    validate_terms,
)
from verifund_control_plane.agreements.models import (
    Agreement,
    AgreementDecisionRecord,
    AgreementError,
    AgreementEvent,
    AgreementVersion,
    ChangeRequest,
)
from verifund_control_plane.agreements.renderer import RENDERER_VERSION, render_agreement
from verifund_control_plane.agreements.repository import AgreementRepository, _iso
from verifund_control_plane.agreements.states import is_terminal, next_state
from verifund_control_plane.agreements.tokens import ApprovalTokenService
from verifund_control_plane.settings import Settings


class AgreementService:
    def __init__(self, *, repo: AgreementRepository, token_service: ApprovalTokenService,
                 settings: Settings, clock: Callable[[], datetime],
                 sync_transaction: Callable[..., Any] | None = None):
        self.repo = repo
        self.token_service = token_service
        self.settings = settings
        self.clock = clock
        self.sync_transaction = sync_transaction

    def _now(self): return self.clock()

    @staticmethod
    def _current_record(agreement: Agreement) -> AgreementVersion:
        current = agreement.current_version_record
        if current is None:
            raise AgreementError(
                "invalid_state",
                "agreement has no current version",
                agreement_id=agreement.agreement_id,
            )
        return current

    async def create_from_award(self, conn, award, transaction_id, run_id, now):
        validate_award(award, now)
        from commerce_core.binding import binding_from_award, offer_hash
        computed_offer_hash = offer_hash(binding_from_award(award.model_dump(mode="json")))
        if award.offer_hash != computed_offer_hash:
            raise AgreementError(
                "offer_mismatch",
                "offer_hash does not bind the award terms",
            )
        terms = build_terms(award, now)
        validate_terms(terms, award)
        agreement_id = f"agr_{uuid.uuid4().hex}"
        h = agreement_hash(agreement_id, 1, terms)
        html_doc = render_agreement(terms, agreement_id, 1, h)
        seller_hours = getattr(self.settings, "agreement_seller_acceptance_hours", 24)
        expires_at = now + timedelta(hours=seller_hours)
        from verifund_contracts.models import AgreementState as AS
        agreement = Agreement(
            agreement_id=agreement_id, transaction_id=transaction_id, run_id=run_id,
            buyer_id=award.buyer_id, seller_id=award.seller_id, current_version=1,
            status=AS.PENDING_SELLER, offer_id=award.offer_id,
            offer_round=award.offer_round, offer_hash=award.offer_hash,
            offer_valid_until=award.offer_valid_until, expires_at=expires_at,
            agreed_at=None, rejected_at=None, expired_at=None, terminated_at=None,
            terminal_reason=None, seller_operator_required=False, row_version=1,
            created_at=now, updated_at=now,
        )
        from .models import AgreementVersion
        version = AgreementVersion(
            agreement_id=agreement_id, version=1, terms=terms, agreement_hash=h,
            rendered_html=html_doc, renderer_version=RENDERER_VERSION, created_at=now,
        )
        await self.repo.create(conn, agreement, version)
        agreement.current_version_record = version
        await self.repo.append_event(conn, AgreementEvent(
            event_id=None, agreement_id=agreement_id, version=1,
            event_type="agreement.created", payload={"offer_id": award.offer_id},
            actor_type="system", actor_id="control-plane", created_at=now,
        ))
        return agreement

    async def record_seller_decision(self, conn, agreement_id, *, decision, actor_type,
                                     actor_id, authority_ref, authority_snapshot,
                                     agreement_version, agreement_hash, verified_offer_hash,
                                     note, idempotency_key, now, change_set=None,
                                     verified_change_request_id: str | None = None):
        replay = await self.repo.get_decision_by_idempotency(idempotency_key)
        if replay is not None:
            return await self.repo.get(agreement_id, conn=conn)
        agreement = await self.repo.get(agreement_id, conn=conn)
        if agreement is None:
            raise AgreementError("not_found", "agreement not found", agreement_id=agreement_id)
        if is_terminal(agreement.status):
            raise AgreementError("invalid_state", "agreement is terminal", agreement_id=agreement_id)
        if agreement.status != AgreementState.PENDING_SELLER:
            raise AgreementError("invalid_state", "seller decision only in PENDING_SELLER")
        if agreement.current_version != agreement_version:
            raise AgreementError("hash_mismatch", "stale version", agreement_id=agreement_id, version=agreement_version)
        cur = agreement.current_version_record
        if cur is None or cur.agreement_hash != agreement_hash:
            raise AgreementError("hash_mismatch", "stale digest", agreement_id=agreement_id, version=agreement_version)
        await self._ensure_not_expired(conn, agreement, now)
        if verified_offer_hash is not None and verified_offer_hash != agreement.offer_hash:
            raise AgreementError("offer_mismatch", "seller did not verify the bound offer")
        if decision == AgreementDecision.ACCEPT:
            new_status = next_state(agreement.status, "SELLER_ACCEPT")
            seller_hours = getattr(self.settings, "agreement_buyer_approval_hours", 24)
            new_expires = now + timedelta(hours=seller_hours)
            await self.repo.append_decision(conn, AgreementDecisionRecord(
                decision_id=f"dec_{uuid.uuid4().hex}", agreement_id=agreement_id,
                version=agreement_version, party="seller", decision=AgreementDecision.ACCEPT,
                actor_type=actor_type, actor_id=actor_id, authority_ref=authority_ref,
                authority_snapshot=authority_snapshot or {}, agreement_hash=agreement_hash,
                verified_offer_hash=verified_offer_hash,
                verified_change_request_id=verified_change_request_id,
                reason_code=None, note=note, change_request_id=None,
                idempotency_key=idempotency_key, decided_at=now,
            ))
            ok = await self.repo.update_status_cas(
                conn, agreement_id, expected_status=agreement.status,
                expected_row_version=agreement.row_version, new_status=new_status,
                new_row_version=agreement.row_version + 1, expires_at=new_expires, now=now,
            )
            if not ok:
                raise AgreementError("conflict", "concurrent update", agreement_id=agreement_id)
            await self.repo.append_event(conn, AgreementEvent(
                event_id=None, agreement_id=agreement_id, version=agreement_version,
                event_type="seller.accepted", payload={}, actor_type=actor_type,
                actor_id=actor_id, created_at=now,
            ))
            agreement.status = new_status
            agreement.expires_at = new_expires
            agreement.row_version += 1
            return agreement
        if decision == AgreementDecision.REJECT:
            await self.repo.append_decision(conn, AgreementDecisionRecord(
                decision_id=f"dec_{uuid.uuid4().hex}", agreement_id=agreement_id,
                version=agreement_version, party="seller", decision=AgreementDecision.REJECT,
                actor_type=actor_type, actor_id=actor_id, authority_ref=authority_ref,
                authority_snapshot=authority_snapshot or {}, agreement_hash=agreement_hash,
                verified_offer_hash=verified_offer_hash,
                verified_change_request_id=verified_change_request_id,
                reason_code=None, note=note, change_request_id=None,
                idempotency_key=idempotency_key, decided_at=now,
            ))
            ok = await self.repo.update_status_cas(
                conn, agreement_id, expected_status=agreement.status,
                expected_row_version=agreement.row_version, new_status=AgreementState.REJECTED,
                new_row_version=agreement.row_version + 1, expires_at=None, now=now,
                extra={"rejected_at": _iso(now)},
            )
            if not ok:
                raise AgreementError("conflict", "concurrent update", agreement_id=agreement_id)
            await self.repo.append_event(conn, AgreementEvent(
                event_id=None, agreement_id=agreement_id, version=agreement_version,
                event_type="seller.rejected", payload={}, actor_type=actor_type,
                actor_id=actor_id, created_at=now,
            ))
            agreement.status = AgreementState.REJECTED
            agreement.row_version += 1
            agreement.expires_at = None
            return agreement
        if decision == AgreementDecision.REQUEST_CHANGES:
            if change_set is None:
                raise AgreementError("invalid_request", "change_set required")
            cr_id = f"cr_{uuid.uuid4().hex}"
            cr = ChangeRequest(
                change_request_id=cr_id, agreement_id=agreement_id,
                base_version=agreement_version, base_hash=agreement_hash,
                requested_by_party="seller", requested_by_actor_type=actor_type,
                requested_by_actor_id=actor_id, operations=change_set.operations,
                reason=change_set.reason, status="PENDING", created_at=now,
            )
            await self.repo.create_change_request(conn, cr)
            await self.repo.append_decision(conn, AgreementDecisionRecord(
                decision_id=f"dec_{uuid.uuid4().hex}", agreement_id=agreement_id,
                version=agreement_version, party="seller",
                decision=AgreementDecision.REQUEST_CHANGES, actor_type=actor_type,
                actor_id=actor_id, authority_ref=authority_ref,
                authority_snapshot=authority_snapshot or {}, agreement_hash=agreement_hash,
                verified_offer_hash=verified_offer_hash,
                verified_change_request_id=verified_change_request_id,
                reason_code=None, note=note, change_request_id=cr_id,
                idempotency_key=idempotency_key, decided_at=now,
            ))
            change_hours = getattr(self.settings, "agreement_change_response_hours", 24)
            new_expires = now + timedelta(hours=change_hours)
            ok = await self.repo.update_status_cas(
                conn, agreement_id, expected_status=agreement.status,
                expected_row_version=agreement.row_version,
                new_status=AgreementState.CHANGES_REQUESTED,
                new_row_version=agreement.row_version + 1, expires_at=new_expires, now=now,
            )
            if not ok:
                raise AgreementError("conflict", "concurrent update", agreement_id=agreement_id)
            await self.repo.append_event(conn, AgreementEvent(
                event_id=None, agreement_id=agreement_id, version=agreement_version,
                event_type="seller.requested_changes", payload={"change_request_id": cr_id},
                actor_type=actor_type, actor_id=actor_id, created_at=now,
            ))
            agreement.status = AgreementState.CHANGES_REQUESTED
            agreement.expires_at = new_expires
            agreement.row_version += 1
            return agreement
        raise AgreementError("invalid_request", "unsupported decision")

    async def _expire_one(self, conn, agreement, now) -> bool:
        ok = await self.repo.expire(conn, agreement.agreement_id, agreement.row_version, now)
        if ok:
            await self.repo.revoke_tokens(conn, agreement.agreement_id, agreement.current_version, now)
            await self.repo.append_event(conn, AgreementEvent(
                event_id=None, agreement_id=agreement.agreement_id,
                version=agreement.current_version, event_type="agreement.expired",
                payload={}, actor_type="system", actor_id="reconciler", created_at=now,
            ))
        return ok

    async def _ensure_not_expired(self, conn, agreement, now) -> None:
        if agreement.expires_at is not None and now >= agreement.expires_at:
            await self._expire_one(conn, agreement, now)
            raise AgreementError(
                "agreement_expired", "agreement expired",
                agreement_id=agreement.agreement_id,
            )

    async def sync_transaction_pointer(self, agreement, conn, now, *,
                                      version: int | None = None,
                                      digest: str | None = None) -> None:
        if self.sync_transaction is None:
            return
        await self.sync_transaction(
            conn,
            agreement.transaction_id,
            version if version is not None else agreement.current_version,
            digest if digest is not None else self._current_record(agreement).agreement_hash,
            now,
        )

    async def issue_buyer_token(self, conn, agreement_id, actor, now):
        agreement = await self.repo.get(agreement_id, conn=conn)
        if agreement is None or agreement.status != AgreementState.PENDING_BUYER:
            raise AgreementError("invalid_state", "not pending buyer")
        if actor.actor_type != "buyer" or actor.actor_id != agreement.buyer_id:
            raise AgreementError("forbidden", "only the agreement buyer may issue an approval token")
        cur = agreement.current_version_record
        if cur is None:
            raise AgreementError("invalid_state", "agreement has no current version")
        raw, record = self.token_service.issue(
            agreement.agreement_id, agreement.current_version, cur.agreement_hash,
            agreement.buyer_id, actor.actor_type, actor.actor_id, now,
            agreement_expires_at=agreement.expires_at,
        )
        await self.repo.issue_token(conn, record)
        return raw, record

    async def record_buyer_decision(self, conn, agreement_id, raw_token, request, actor, now):
        agreement = await self.repo.get(agreement_id, conn=conn)
        if agreement is None:
            raise AgreementError("not_found", "agreement not found")
        if is_terminal(agreement.status):
            raise AgreementError("invalid_state", "terminal")
        if agreement.status != AgreementState.PENDING_BUYER:
            raise AgreementError("invalid_state", "buyer decision only in PENDING_BUYER")
        await self._ensure_not_expired(conn, agreement, now)
        if actor.actor_type != "buyer" or actor.actor_id != agreement.buyer_id:
            raise AgreementError("forbidden", "only the agreement buyer may decide")
        try:
            token_claims = self.token_service.verify(raw_token)
        except ValueError as exc:
            raise AgreementError("token_revoked", str(exc)) from exc
        jti = token_claims.get("jti")
        if not isinstance(jti, str):
            raise AgreementError("token_revoked", "token is missing its identifier")
        token = await self.repo.get_token(jti, conn=conn)
        if token is None:
            raise AgreementError("token_revoked", "unknown token")
        if token.token_hash != self.token_service.token_hash(raw_token):
            raise AgreementError("token_revoked", "token hash mismatch")
        if token.used_at is not None:
            raise AgreementError("token_used", "token already used")
        if token.revoked_at is not None:
            raise AgreementError("token_revoked", "token revoked")
        if token.expires_at < now:
            raise AgreementError("token_expired", "token expired")
        if token.subject_id != agreement.buyer_id:
            raise AgreementError("forbidden", "token subject mismatch")
        current_hash = self._current_record(agreement).agreement_hash
        if token.version != agreement.current_version or token.agreement_hash != current_hash:
            raise AgreementError("hash_mismatch", "token does not bind current version")
        if request.agreement_version != agreement.current_version or request.agreement_hash != current_hash:
            raise AgreementError("hash_mismatch", "stale version/digest")
        decision = request.decision
        decision_id = f"dec_{uuid.uuid4().hex}"
        ok = await self.token_service.consume(
            self.repo, conn, raw_token, jti, decision_id, now
        )
        if not ok:
            raise AgreementError("token_used", "token already used")
        if decision == BuyerApprovalDecision.APPROVE:
            await self.repo.append_decision(conn, AgreementDecisionRecord(
                decision_id=decision_id, agreement_id=agreement_id,
                version=agreement.current_version, party="buyer",
                decision=AgreementDecision.ACCEPT, actor_type=actor.actor_type,
                actor_id=actor.actor_id, authority_ref=None,
                authority_snapshot={}, agreement_hash=current_hash,
                verified_offer_hash=None, verified_change_request_id=None,
                reason_code=None, note=request.note, change_request_id=None,
                idempotency_key=request.idempotency_key, decided_at=now,
            ))
            ok = await self.repo.update_status_cas(
                conn, agreement_id, expected_status=agreement.status,
                expected_row_version=agreement.row_version, new_status=AgreementState.AGREED,
                new_row_version=agreement.row_version + 1, expires_at=None, now=now,
                extra={"agreed_at": _iso(now)},
            )
            if not ok:
                raise AgreementError("conflict", "concurrent update")
            await self.sync_transaction_pointer(
                agreement, conn, now,
                version=agreement.current_version,
                digest=current_hash,
            )
            await self.repo.revoke_tokens(conn, agreement_id, agreement.current_version, now)
            await self.repo.append_event(conn, AgreementEvent(
                event_id=None, agreement_id=agreement_id, version=agreement.current_version,
                event_type="agreement.agreed", payload={}, actor_type=actor.actor_type,
                actor_id=actor.actor_id, created_at=now,
            ))
            agreement.status = AgreementState.AGREED
            return agreement
        if decision == BuyerApprovalDecision.REJECT:
            await self.repo.append_decision(conn, AgreementDecisionRecord(
                decision_id=decision_id, agreement_id=agreement_id,
                version=agreement.current_version, party="buyer",
                decision=AgreementDecision.REJECT, actor_type=actor.actor_type,
                actor_id=actor.actor_id, authority_ref=None,
                authority_snapshot={}, agreement_hash=current_hash,
                verified_offer_hash=None, verified_change_request_id=None,
                reason_code=None, note=request.note, change_request_id=None,
                idempotency_key=request.idempotency_key, decided_at=now,
            ))
            ok = await self.repo.update_status_cas(
                conn, agreement_id, expected_status=agreement.status,
                expected_row_version=agreement.row_version, new_status=AgreementState.REJECTED,
                new_row_version=agreement.row_version + 1, expires_at=None, now=now,
                extra={"rejected_at": _iso(now)},
            )
            if not ok:
                raise AgreementError("conflict", "concurrent update")
            agreement.status = AgreementState.REJECTED
            agreement.row_version += 1
            agreement.expires_at = None
            return agreement
        if decision == BuyerApprovalDecision.REQUEST_CHANGES:
            if request.change_set is None:
                raise AgreementError("invalid_request", "change_set required")
            cr_id = f"cr_{uuid.uuid4().hex}"
            cr = ChangeRequest(
                change_request_id=cr_id, agreement_id=agreement_id,
                base_version=agreement.current_version, base_hash=current_hash,
                requested_by_party="buyer", requested_by_actor_type=actor.actor_type,
                requested_by_actor_id=actor.actor_id, operations=request.change_set.operations,
                reason=request.change_set.reason, status="PENDING", created_at=now,
            )
            await self.repo.create_change_request(conn, cr)
            await self.repo.append_decision(conn, AgreementDecisionRecord(
                decision_id=decision_id, agreement_id=agreement_id,
                version=agreement.current_version, party="buyer",
                decision=AgreementDecision.REQUEST_CHANGES, actor_type=actor.actor_type,
                actor_id=actor.actor_id, authority_ref=None,
                authority_snapshot={}, agreement_hash=current_hash,
                verified_offer_hash=None, verified_change_request_id=None,
                reason_code=None, note=request.note, change_request_id=cr_id,
                idempotency_key=request.idempotency_key, decided_at=now,
            ))
            change_hours = getattr(self.settings, "agreement_change_response_hours", 24)
            new_expires = now + timedelta(hours=change_hours)
            ok = await self.repo.update_status_cas(
                conn, agreement_id, expected_status=agreement.status,
                expected_row_version=agreement.row_version,
                new_status=AgreementState.CHANGES_REQUESTED,
                new_row_version=agreement.row_version + 1, expires_at=new_expires, now=now,
            )
            if not ok:
                raise AgreementError("conflict", "concurrent update")
            agreement.status = AgreementState.CHANGES_REQUESTED
            agreement.expires_at = new_expires
            agreement.row_version += 1
            return agreement
        raise AgreementError("invalid_request", "unsupported decision")

    async def create_change_request(self, conn, agreement_id, party, actor, change_set,
                                    note, idempotency_key, now):
        agreement = await self.repo.get(agreement_id, conn=conn)
        if agreement is None:
            raise AgreementError("not_found", "agreement not found")
        if is_terminal(agreement.status):
            raise AgreementError("invalid_state", "terminal")
        if party == "seller" and agreement.status != AgreementState.PENDING_SELLER:
            raise AgreementError("invalid_state", "seller change request only in PENDING_SELLER")
        if party == "buyer":
            raise AgreementError(
                "forbidden",
                "buyer change requests require an approval token; use record_buyer_decision",
            )
        if not change_set.operations:
            raise AgreementError("invalid_request", "change_set.operations is required")
        return await self.record_seller_decision(
            conn, agreement_id, decision=AgreementDecision.REQUEST_CHANGES,
            actor_type=actor.actor_type, actor_id=actor.actor_id,
            authority_ref=None, authority_snapshot={},
            agreement_version=agreement.current_version,
            agreement_hash=self._current_record(agreement).agreement_hash,
            verified_offer_hash=agreement.offer_hash, note=note,
            idempotency_key=idempotency_key, now=now, change_set=change_set,
        )

    async def record_seller_operator_required(self, conn, agreement_id, actor, note, now):
        agreement = await self.repo.get(agreement_id, conn=conn)
        if agreement is None:
            raise AgreementError("not_found", "agreement not found")
        if agreement.status != AgreementState.PENDING_SELLER:
            raise AgreementError("invalid_state", "operator flag only in PENDING_SELLER")
        await self._ensure_not_expired(conn, agreement, now)
        ok = await self.repo.set_operator_required(
            conn, agreement_id, agreement.row_version, now
        )
        if not ok:
            raise AgreementError("conflict", "concurrent update")
        await self.repo.append_event(conn, AgreementEvent(
            event_id=None, agreement_id=agreement_id,
            version=agreement.current_version, event_type="seller.operator_required",
            payload={"note": note}, actor_type=actor.actor_type,
            actor_id=actor.actor_id, created_at=now,
        ))
        return await self.repo.get(agreement_id, conn=conn)

    async def resolve_change_request(self, conn, agreement_id, change_request_id, accept,
                                     actor, note, now, *, raw_token: str | None = None):
        agreement = await self.repo.get(agreement_id, conn=conn)
        if agreement is None:
            raise AgreementError("not_found", "agreement not found")
        cr = await self.repo.get_open_change_request(agreement_id, conn=conn)
        if cr is None or cr.change_request_id != change_request_id:
            raise AgreementError("not_found", "change request not found")
        if cr.requested_by_party == "buyer":
            if actor.actor_type not in ("SELLER_AGENT", "SELLER_OPERATOR"):
                raise AgreementError("forbidden", "only seller may resolve buyer request")
        else:
            if actor.actor_type != "buyer" or actor.actor_id != agreement.buyer_id:
                raise AgreementError("forbidden", "only the agreement buyer may resolve seller request")
            if not raw_token:
                raise AgreementError("forbidden", "buyer change resolution requires an approval token")
            if agreement.status != AgreementState.CHANGES_REQUESTED:
                raise AgreementError("invalid_state", "no open change request")
            current_hash = self._current_record(agreement).agreement_hash
            if (cr.base_version != agreement.current_version
                    or cr.base_hash != current_hash):
                raise AgreementError("hash_mismatch", "change request base is stale")
            claims = self.token_service.verify(raw_token)
            if claims.get("sub") != agreement.buyer_id:
                raise AgreementError("forbidden", "approval token subject mismatch")
            if (claims.get("version") != agreement.current_version
                    or claims.get("agreement_hash") != current_hash):
                raise AgreementError("hash_mismatch", "approval token binds a different version")
            await self._ensure_not_expired(conn, agreement, now)
            consumed = await self.token_service.consume(
                self.repo, conn, raw_token, claims["jti"], change_request_id, now
            )
            if not consumed:
                raise AgreementError("token_used", "approval token already used")
        if not accept:
            requester_pending = (
                AgreementState.PENDING_SELLER if cr.requested_by_party == "seller"
                else AgreementState.PENDING_BUYER
            )
            await self.repo.resolve_change_request(
                conn, change_request_id, status="REJECTED",
                resolved_by_party="seller" if cr.requested_by_party == "buyer" else "buyer",
                resolved_by_actor_type=actor.actor_type, resolved_by_actor_id=actor.actor_id,
                resolution_note=note, resulting_version=None, resolved_at=now,
            )
            change_hours = getattr(self.settings, "agreement_change_response_hours", 24)
            ok = await self.repo.update_status_cas(
                conn, agreement_id, expected_status=AgreementState.CHANGES_REQUESTED,
                expected_row_version=agreement.row_version, new_status=requester_pending,
                new_row_version=agreement.row_version + 1,
                expires_at=now + timedelta(hours=change_hours), now=now,
            )
            if not ok:
                raise AgreementError("conflict", "concurrent update")
            await self.repo.append_event(conn, AgreementEvent(
                event_id=None, agreement_id=agreement_id, version=agreement.current_version,
                event_type="changes_rejected", payload={"change_request_id": change_request_id},
                actor_type=actor.actor_type, actor_id=actor.actor_id, created_at=now,
            ))
            return await self.repo.get(agreement_id, conn=conn)
        base_version = await self.repo.get_version(agreement_id, cr.base_version)
        if base_version is None:
            raise AgreementError("not_found", "base version not found")
        change_set = ChangeSet(operations=cr.operations, reason=cr.reason)
        new_terms = apply_change_set(base_version.terms, change_set)
        validate_terms(new_terms, None)
        new_version_number = agreement.current_version + 1
        new_hash = agreement_hash(agreement_id, new_version_number, new_terms)
        new_html = render_agreement(new_terms, agreement_id, new_version_number, new_hash)
        from .models import AgreementVersion
        new_ver = AgreementVersion(
            agreement_id=agreement_id, version=new_version_number, terms=new_terms,
            agreement_hash=new_hash, rendered_html=new_html, renderer_version=RENDERER_VERSION,
            created_at=now, supersedes_version=cr.base_version,
            change_request_id=change_request_id,
        )
        await self.repo.create_version(conn, new_ver)
        await self.repo.resolve_change_request(
            conn, change_request_id, status="ACCEPTED",
            resolved_by_party="seller" if cr.requested_by_party == "buyer" else "buyer",
            resolved_by_actor_type=actor.actor_type, resolved_by_actor_id=actor.actor_id,
            resolution_note=note, resulting_version=new_version_number, resolved_at=now,
        )
        seller_hours = getattr(self.settings, "agreement_seller_acceptance_hours", 24)
        ok = await self.repo.update_status_cas(
            conn, agreement_id, expected_status=AgreementState.CHANGES_REQUESTED,
            expected_row_version=agreement.row_version,
            new_status=AgreementState.PENDING_SELLER,
            new_row_version=agreement.row_version + 1,
            expires_at=now + timedelta(hours=seller_hours), now=now,
            extra={"current_version": new_version_number},
        )
        if not ok:
            raise AgreementError("conflict", "concurrent update")
        await self.sync_transaction_pointer(agreement, conn, now,
                                            version=new_version_number, digest=new_hash)
        await self.repo.append_event(conn, AgreementEvent(
            event_id=None, agreement_id=agreement_id, version=new_version_number,
            event_type="changes_accepted", payload={"change_request_id": change_request_id},
            actor_type=actor.actor_type, actor_id=actor.actor_id, created_at=now,
        ))
        return await self.repo.get(agreement_id, conn=conn)

    async def expire_due(self, now):
        ids = await self.repo.list_expired(now)
        expired = []
        for aid in ids:
            agreement = await self.repo.get(aid)
            if agreement is None:
                continue
            async with self.repo.transaction() as conn:
                if await self._expire_one(conn, agreement, now):
                    expired.append(aid)
        return expired

    async def terminate(self, conn, agreement_id, reason, now):
        agreement = await self.repo.get(agreement_id, conn=conn)
        if agreement is None or agreement.status != AgreementState.AGREED:
            return agreement
        ok = await self.repo.update_status_cas(
            conn, agreement_id, expected_status=AgreementState.AGREED,
            expected_row_version=agreement.row_version, new_status=AgreementState.TERMINATED,
            new_row_version=agreement.row_version + 1, expires_at=None, now=now,
            extra={"terminated_at": _iso(now), "terminal_reason": reason},
        )
        if not ok:
            raise AgreementError("conflict", "concurrent update")
        await self.repo.append_event(conn, AgreementEvent(
            event_id=None, agreement_id=agreement_id, version=agreement.current_version,
            event_type="agreement.terminated", payload={"reason": reason},
            actor_type="system", actor_id="control-plane", created_at=now,
        ))
        return await self.repo.get(agreement_id, conn=conn)

    async def cancel_pending(self, conn, agreement_id, reason, now):
        agreement = await self.repo.get(agreement_id, conn=conn)
        if agreement is None:
            return None
        if agreement.status not in {
            AgreementState.PENDING_SELLER,
            AgreementState.PENDING_BUYER,
            AgreementState.CHANGES_REQUESTED,
        }:
            return agreement
        ok = await self.repo.update_status_cas(
            conn, agreement_id, expected_status=agreement.status,
            expected_row_version=agreement.row_version, new_status=AgreementState.REJECTED,
            new_row_version=agreement.row_version + 1, expires_at=None, now=now,
            extra={"rejected_at": _iso(now), "terminal_reason": reason},
        )
        if not ok:
            raise AgreementError("conflict", "concurrent update")
        await self.repo.revoke_tokens(conn, agreement_id, agreement.current_version, now)
        await self.repo.append_event(conn, AgreementEvent(
            event_id=None, agreement_id=agreement_id, version=agreement.current_version,
            event_type="agreement.canceled", payload={"reason": reason},
            actor_type="system", actor_id="control-plane", created_at=now,
        ))
        return await self.repo.get(agreement_id, conn=conn)

    async def get(self, agreement_id, conn=None):
        return await self.repo.get(agreement_id, conn=conn)

    async def get_by_transaction(self, transaction_id, conn=None):
        return await self.repo.get_by_transaction(transaction_id, conn=conn)

    async def list(self, conn=None):
        return await self.repo.list_all(conn=conn)

    async def list_versions(self, agreement_id):
        return await self.repo.list_versions(agreement_id)

    async def document(self, agreement_id, version=None):
        agr = await self.repo.get(agreement_id)
        if agr is None:
            return None
        v = version or agr.current_version
        ver = await self.repo.get_version(agreement_id, v)
        return ver.rendered_html if ver else None

    async def build_view(self, agreement) -> dict[str, Any]:
        versions = await self.repo.list_versions(agreement.agreement_id)
        decisions = await self.repo.list_decisions(agreement.agreement_id)
        current = next(
            (v for v in versions if v.version == agreement.current_version), None
        )
        if current is None:
            raise AgreementError("invalid_state", "agreement has no current version")
        decision_views = [
            AgreementDecisionView(
                decision_id=d.decision_id, party=d.party, decision=d.decision,
                actor_type=d.actor_type, actor_id=d.actor_id,
                authority_ref=d.authority_ref, agreement_hash=d.agreement_hash,
                version=d.version, note=d.note, decided_at=d.decided_at,
            )
            for d in decisions
        ]
        open_cr = await self.repo.get_open_change_request(agreement.agreement_id)
        change_view = None
        if open_cr is not None:
            change_view = ChangeRequestView(
                change_request_id=open_cr.change_request_id,
                base_version=open_cr.base_version, base_hash=open_cr.base_hash,
                requested_by_party=open_cr.requested_by_party,
                requested_by_actor_type=open_cr.requested_by_actor_type,
                requested_by_actor_id=open_cr.requested_by_actor_id,
                operations=open_cr.operations, reason=open_cr.reason,
                status=open_cr.status, resolved_by_party=open_cr.resolved_by_party,
                resolution_note=open_cr.resolution_note,
                resulting_version=open_cr.resulting_version,
                created_at=open_cr.created_at, resolved_at=open_cr.resolved_at,
            )
        version_view = AgreementVersionView(
            version=current.version, agreement_hash=current.agreement_hash,
            created_at=current.created_at,
            supersedes_version=current.supersedes_version,
            change_request_id=current.change_request_id,
            superseded_at=current.superseded_at,
            decisions=[d for d in decision_views if d.version == current.version],
            is_current=True,
        )
        return AgreementView(
            agreement_id=agreement.agreement_id,
            transaction_id=agreement.transaction_id,
            run_id=agreement.run_id,
            buyer_id=agreement.buyer_id,
            seller_id=agreement.seller_id,
            status=agreement.status,
            current_version=agreement.current_version,
            expires_at=agreement.expires_at,
            agreed_at=agreement.agreed_at,
            offer_id=agreement.offer_id,
            offer_round=agreement.offer_round,
            offer_hash=agreement.offer_hash,
            offer_valid_until=agreement.offer_valid_until,
            seller_operator_required=agreement.seller_operator_required,
            version=version_view,
            decisions=decision_views,
            change_request=change_view,
            review_url=f"/agreements/{agreement.agreement_id}",
        ).model_dump(mode="json")

    async def build_projection(self, agreement) -> AgreementProjection:
        cur = agreement.current_version_record
        if cur is None:
            cur = await self.repo.get_version(agreement.agreement_id, agreement.current_version)
        if cur is None:
            raise AgreementError(
                "invalid_state",
                "agreement has no current version",
                agreement_id=agreement.agreement_id,
            )
        terms = cur.terms
        totals = terms.get("totals", {}) if isinstance(terms, dict) else {}
        items = terms.get("items", []) if isinstance(terms, dict) else []
        line_items = [
            AwardLineItem(
                sku=i.get("sku", ""),
                name=i.get("name", ""),
                quantity=i.get("quantity", 1),
                unit_price_cents=i.get("unit_price_cents", 0),
                warranty_addon_cents=i.get("warranty_addon_cents", 0),
                attributes=i.get("attributes") or {},
            )
            for i in items
        ]
        quantity = sum(i.get("quantity", 0) for i in items) or 1
        evidence_raw = terms.get("evidence_required", []) if isinstance(terms, dict) else []
        evidence = []
        for e in evidence_raw:
            val = e.value if hasattr(e, "value") else str(e)
            try:
                evidence.append(EvidenceKind(val))
            except ValueError:
                evidence.append(EvidenceKind.OTHER)
        if not evidence:
            evidence = [EvidenceKind.DELIVERY_CONFIRMATION]
        remedies_raw = terms.get("remedies", {}) if isinstance(terms, dict) else {}
        try:
            remedies = RemedyTerms.model_validate(remedies_raw)
        except Exception:  # noqa
            remedies = RemedyTerms(
                non_delivery=RemedyPolicy.CANCEL_AND_REFUND,
                late_delivery=RemedyPolicy.CANCEL_AND_REFUND,
                damaged_goods=RemedyPolicy.REFUND_OR_REPLACEMENT,
            )
        inspection = terms.get("inspection", {}) if isinstance(terms, dict) else {}
        delivery = terms.get("delivery", {}) if isinstance(terms, dict) else {}
        status = agreement.status
        created_at = _iso(agreement.created_at)
        supersedes = cur.supersedes_version
        change_request_id = cur.change_request_id
        agreement_hash = cur.agreement_hash
        return AgreementProjection(
            agreement_id=agreement.agreement_id,
            agreement_version=agreement.current_version,
            transaction_id=agreement.transaction_id,
            run_id=agreement.run_id,
            buyer_id=agreement.buyer_id,
            seller_id=agreement.seller_id,
            offer_id=agreement.offer_id,
            offer_round=agreement.offer_round,
            offer_hash=agreement.offer_hash,
            offer_valid_until=agreement.offer_valid_until,
            currency=totals.get("currency", "USD"),
            amount_cents=totals.get("total_cents", 0) or 1,
            quantity=quantity,
            line_items=line_items
            if line_items
            else [AwardLineItem(sku="x", name="x", quantity=1, unit_price_cents=1, attributes={})],
            shipping_cents=totals.get("shipping_cents", 0),
            tax_cents=totals.get("tax_cents", 0),
            fees_cents=totals.get("fees_cents", 0),
            delivery_days=delivery.get("delivery_days", 1),
            warranty_months=terms.get("warranty_months", 0) if isinstance(terms, dict) else 0,
            returns_days=terms.get("returns_days", 0) if isinstance(terms, dict) else 0,
            inspection_period_hours=inspection.get("period_hours", 1),
            inspection_starts_on=inspection.get("starts_on", "DELIVERY_CONFIRMED"),
            evidence_required=evidence,
            remedies=remedies,
            dispute_window_hours=terms.get("dispute_window_hours", 1) if isinstance(terms, dict) else 1,
            terms=terms if isinstance(terms, dict) else {},
            status=status,
            expires_at=agreement.expires_at,
            supersedes_version=supersedes,
            change_request_id=change_request_id,
            created_at=created_at,
            agreement_hash=agreement_hash,
        )

    async def verify_funding_binding(self, agreement, transaction, version, digest):
        if agreement is None or agreement.status is not AgreementState.AGREED:
            raise AgreementError("invalid_state", "agreement is not AGREED",
                                 agreement_id=agreement.agreement_id if agreement else None)
        if agreement.current_version != version:
            raise AgreementError("hash_mismatch", "stale agreement version")
        cur = agreement.current_version_record
        if cur is None or cur.agreement_hash != digest:
            raise AgreementError("hash_mismatch", "stale agreement digest")
        decisions = await self.repo.list_decisions(agreement.agreement_id)
        buyer = next((d for d in decisions
                      if d.party == "buyer" and d.version == version
                      and d.decision is AgreementDecision.ACCEPT), None)
        seller = next((d for d in decisions
                       if d.party == "seller" and d.version == version
                       and d.decision is AgreementDecision.ACCEPT), None)
        if buyer is None or seller is None:
            raise AgreementError("invalid_state", "both acceptances are required")
        for d in (buyer, seller):
            if d.agreement_hash != digest:
                raise AgreementError("hash_mismatch", "acceptance does not bind this version")
        if transaction.agreement_id != agreement.agreement_id:
            raise AgreementError("invalid_state", "transaction is bound to another agreement")
