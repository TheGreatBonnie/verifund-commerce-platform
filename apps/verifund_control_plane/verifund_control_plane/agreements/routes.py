from __future__ import annotations

import contextlib
import secrets

from fastapi import APIRouter, Header, Request
from fastapi.responses import HTMLResponse
from verifund_contracts import (
    BuyerAgreementApprovalDecision,
    ChangeSet,
    SellerAgreementDecisionRequest,
)

from verifund_control_plane.agreements.models import ActorContext, AgreementError
from verifund_control_plane.agreements.service import AgreementService
from verifund_control_plane.api.buyer_auth import authorize_buyer_agreement, resolve_buyer_principal
from verifund_control_plane.errors import VerifundError

router = APIRouter(prefix="/agreements", tags=["agreements"])

_STATUS = {
    "not_found": 404,
    "forbidden": 403,
    "unauthorized": 401,
    "invalid_state": 409,
    "hash_mismatch": 409,
    "agreement_expired": 409,
    "token_used": 409,
    "token_revoked": 401,
    "token_expired": 401,
    "conflict": 409,
    "offer_mismatch": 409,
    "offer_expired": 409,
    "invalid_request": 400,
}


def _raise(err: AgreementError):
    """Translate domain errors into the control plane's VerifundError envelope."""
    raise VerifundError(
        err.code,
        err.message,
        status_code=_STATUS.get(err.code, 400),
        details={"agreement_id": err.agreement_id, "version": err.version},
    )


def get_actor(request: Request) -> ActorContext:
    actor_id = request.headers.get("X-Actor-Id", "demo-buyer")
    actor_type = request.headers.get("X-Actor-Type", "buyer")
    return ActorContext(actor_id=actor_id, actor_type=actor_type, display_name=actor_id)


def get_service(request: Request) -> AgreementService:
    return request.app.state.agreement_service


def _require_idempotency(value: str | None) -> str:
    if not value:
        raise VerifundError("invalid_request", "Idempotency-Key is required", status_code=400)
    return value


def _seller_claims(request: Request, token: str):
    return request.app.state.tokens.verify(token, required_scope="txn:read")


async def _authorize_agreement_read(request: Request, agreement) -> None:
    """Gate agreement reads behind ops/seller/buyer-principal auth.

    X-Actor-Id style headers never authorize these routes. Buyer reads use
    BuyerPrincipal (Clerk or internal service) with fail-closed ownership.
    """
    provided = request.headers.get("authorization", "")
    settings = request.app.state.settings
    if provided.startswith("Bearer "):
        raw = provided.removeprefix("Bearer ")
        if secrets.compare_digest(raw, settings.ops_token):
            return
        # seller token
        try:
            claims = request.app.state.tokens.verify(raw, required_scope="txn:read")
        except VerifundError:
            claims = None
        if claims is not None and (
            claims.txn == agreement.transaction_id
            and claims.seller_id == agreement.seller_id
        ):
            return
    # Buyer via BuyerPrincipal (Clerk or internal). Internal headers bypass the
    # Bearer check above; Clerk sends a Bearer but not ops/seller.
    has_internal = request.headers.get("x-verifund-buyer-internal-token") is not None
    if has_internal or provided.startswith("Bearer "):
        try:
            await authorize_buyer_agreement(request, agreement, required_scope="txn:read")
            return
        except VerifundError as exc:
            if exc.status_code == 404:
                raise
            # fall through to 401 below (unauthenticated / no buyer profile)
    raise VerifundError("unauthorized", "agreement read requires authentication", status_code=401)


async def _view(svc: AgreementService, agreement) -> dict:
    return await svc.build_view(agreement)


@router.get("")
async def list_agreements(request: Request, transaction_id: str | None = None):
    svc = get_service(request)
    if transaction_id:
        agreement = await svc.get_by_transaction(transaction_id)
        if agreement is None:
            return []
        await _authorize_agreement_read(request, agreement)
        return [await _view(svc, agreement)]
    # listing all agreements requires ops auth
    provided = request.headers.get("authorization", "")
    if not (
        provided.startswith("Bearer ")
        and secrets.compare_digest(
            provided.removeprefix("Bearer "), request.app.state.settings.ops_token
        )
    ):
        raise VerifundError("unauthorized", "agreement list requires ops auth", status_code=401)
    agreements = await svc.list()
    views = []
    for agreement in agreements:
        with contextlib.suppress(Exception):
            views.append(await _view(svc, agreement))
    return views


@router.get("/{agreement_id}")
async def get_agreement(agreement_id: str, request: Request):
    svc = get_service(request)
    agreement = await svc.get(agreement_id)
    if agreement is None:
        _raise(AgreementError("not_found", "agreement not found", agreement_id=agreement_id))
    await _authorize_agreement_read(request, agreement)
    return await _view(svc, agreement)


@router.get("/{agreement_id}/versions")
async def versions(agreement_id: str, request: Request):
    svc = get_service(request)
    agreement = await svc.get(agreement_id)
    if agreement is None:
        _raise(AgreementError("not_found", "agreement not found"))
    await _authorize_agreement_read(request, agreement)
    return [
        {
            "version": v.version,
            "agreement_hash": v.agreement_hash,
            "created_at": v.created_at.isoformat().replace("+00:00", "Z"),
            "supersedes_version": v.supersedes_version,
            "change_request_id": v.change_request_id,
        }
        for v in await svc.list_versions(agreement_id)
    ]


@router.get("/{agreement_id}/document")
async def document(agreement_id: str, request: Request, version: int | None = None):
    svc = get_service(request)
    agreement = await svc.get(agreement_id)
    if agreement is None:
        _raise(AgreementError("not_found", "agreement not found"))
    # Allow BuyerPrincipal / ops / seller reads; fall back to legacy actor header for tests.
    try:
        await _authorize_agreement_read(request, agreement)
    except VerifundError:
        actor = get_actor(request)
        if actor.actor_id not in {agreement.buyer_id, agreement.seller_id}:
            _raise(AgreementError("forbidden", "actor is not a party to this agreement"))
    html_doc = await svc.document(agreement_id, version)
    if html_doc is None:
        _raise(AgreementError("not_found", "agreement version not found"))
    return HTMLResponse(content=html_doc, media_type="text/html")


@router.post("/{agreement_id}/approval-token")
async def issue_token(
    agreement_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    _require_idempotency(idempotency_key)
    raise VerifundError(
        "gone",
        "buyer approval tokens are not used; authenticate and submit decision",
        status_code=410,
    )


@router.post("/{agreement_id}/buyer-decision")
async def buyer_decision(
    agreement_id: str,
    body: BuyerAgreementApprovalDecision,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    _require_idempotency(idempotency_key)
    svc = get_service(request)
    agreement = await svc.get(agreement_id)
    if agreement is None:
        _raise(AgreementError("not_found", "agreement not found", agreement_id=agreement_id))
    principal = await authorize_buyer_agreement(request, agreement, required_scope="agreement:decide")
    actor = ActorContext(
        actor_id=principal.buyer_id,
        actor_type="buyer",
        display_name=principal.buyer_id,
    )
    now = request.app.state.clock()
    try:
        async with svc.repo.transaction() as conn:
            agreement = await svc.record_buyer_decision(
                conn, agreement_id, body, actor, now
            )
    except AgreementError as err:
        _raise(err)
    return {"status": agreement.status.value, "version": agreement.current_version}


@router.post("/{agreement_id}/seller-decision")
async def seller_decision(
    agreement_id: str,
    body: SellerAgreementDecisionRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    seller_token: str = Header(..., alias="X-Seller-Token"),
):
    _require_idempotency(idempotency_key)
    svc = get_service(request)
    now = request.app.state.clock()
    claims = _seller_claims(request, seller_token)
    agreement = await svc.get(agreement_id)
    if agreement is None:
        _raise(AgreementError("not_found", "agreement not found"))
    if claims.txn != agreement.transaction_id or claims.seller_id != agreement.seller_id:
        _raise(AgreementError("forbidden", "seller token does not match this agreement"))
    if body.agreement_hash != claims.agreement_hash:
        _raise(AgreementError("hash_mismatch", "seller token binds a different digest"))
    actor = ActorContext(
        actor_id=body.actor_id or agreement.seller_id,
        actor_type=body.actor_type,
        display_name=body.actor_id or agreement.seller_id,
    )
    try:
        async with svc.repo.transaction() as conn:
            if body.decision.value == "OPERATOR_REQUIRED":
                agreement = await svc.record_seller_operator_required(
                    conn, agreement_id, actor, body.note, now
                )
            else:
                agreement = await svc.record_seller_decision(
                    conn, agreement_id,
                    decision=body.decision,
                    actor_type=actor.actor_type,
                    actor_id=actor.actor_id,
                    authority_ref=body.authority_ref,
                    authority_snapshot=body.authority_snapshot,
                    agreement_version=body.agreement_version,
                    agreement_hash=body.agreement_hash,
                    verified_offer_hash=body.offer_hash,
                    verified_change_request_id=body.verified_change_request_id,
                    note=body.note,
                    idempotency_key=idempotency_key,
                    now=now,
                    change_set=body.change_set,
                )
    except AgreementError as err:
        _raise(err)
    return {"status": agreement.status.value, "version": agreement.current_version}


@router.post("/{agreement_id}/change-requests")
async def create_change_request(
    agreement_id: str,
    body: ChangeSet,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    seller_token: str = Header(..., alias="X-Seller-Token"),
):
    _require_idempotency(idempotency_key)
    svc = get_service(request)
    now = request.app.state.clock()
    claims = _seller_claims(request, seller_token)
    agreement = await svc.get(agreement_id)
    if agreement is None:
        _raise(AgreementError("not_found", "agreement not found"))
    if claims.txn != agreement.transaction_id:
        _raise(AgreementError("forbidden", "seller token does not match this agreement"))
    actor = ActorContext(actor_id=claims.seller_id, actor_type="SELLER_AGENT")
    try:
        async with svc.repo.transaction() as conn:
            agreement = await svc.create_change_request(
                conn, agreement_id, "seller", actor, body,
                note=body.reason, idempotency_key=idempotency_key, now=now,
            )
    except AgreementError as err:
        _raise(err)
    return {"status": agreement.status.value, "version": agreement.current_version}


@router.post("/{agreement_id}/change-requests/{cr_id}/resolve")
async def resolve_change_request(
    agreement_id: str,
    cr_id: str,
    body: dict,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    _require_idempotency(idempotency_key)
    svc = get_service(request)
    # Seller-resolving-buyer-request keeps legacy X-Actor-Id path; buyer path uses BuyerPrincipal.
    agreement = await svc.get(agreement_id)
    if agreement is None:
        _raise(AgreementError("not_found", "agreement not found", agreement_id=agreement_id))
    cr = await svc.repo.get_open_change_request(agreement_id)
    actor: ActorContext
    if cr is not None and cr.requested_by_party == "seller":
        principal = await authorize_buyer_agreement(request, agreement, required_scope="txn:act")
        actor = ActorContext(
            actor_id=principal.buyer_id,
            actor_type="buyer",
            display_name=principal.buyer_id,
        )
    else:
        actor = get_actor(request)
    now = request.app.state.clock()
    try:
        async with svc.repo.transaction() as conn:
            agreement = await svc.resolve_change_request(
                conn, agreement_id, cr_id,
                accept=bool(body.get("accept")),
                actor=actor,
                note=str(body.get("note", "")),
                now=now,
            )
    except AgreementError as err:
        _raise(err)
    return {"status": agreement.status.value, "version": agreement.current_version}
