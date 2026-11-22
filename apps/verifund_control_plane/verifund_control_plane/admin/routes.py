from __future__ import annotations

from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Request

from verifund_control_plane.api.platform_auth import authorize_platform_transaction
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.tenancy.identity import Identity, require_identity
from verifund_control_plane.tenancy.routes import PayoutReleaseRequest

router = APIRouter(prefix="/v1/admin")


async def require_admin(request: Request) -> Identity:
    identity = await require_identity(request)
    if not identity.is_platform_admin:
        raise VerifundError("forbidden", "platform admin required", status_code=403)
    return identity


def _platform_email(request: Request) -> str:
    return request.app.state.settings.paypal_platform_email


def _redact_email(email: str) -> str:
    if "@" not in email:
        return "(unset)"
    local, domain = email.split("@", 1)
    return f"{local[:2]}***@{domain}"


def _participant_name(party: Any) -> str | None:
    if not isinstance(party, dict):
        return None
    return party.get("display_name") or party.get("name") or None


async def _serialize(txn, agreement_service) -> dict[str, Any]:
    buyer_name = None
    seller_name = None
    with suppress(Exception):
        agreement = await agreement_service.get_by_transaction(txn.transaction_id)
        if agreement is not None:
            projection = await agreement_service.build_projection(agreement)
            terms = projection.terms if isinstance(projection.terms, dict) else {}
            parties = terms.get("parties") if isinstance(terms, dict) else {}
            if isinstance(parties, dict):
                buyer_name = _participant_name(parties.get("buyer"))
                seller_name = _participant_name(parties.get("seller"))
    return {
        "transaction_id": txn.transaction_id,
        "state": txn.state.value if hasattr(txn.state, "value") else txn.state,
        "buyer_id": txn.buyer_id,
        "seller_id": txn.seller_id,
        "buyer_name": buyer_name,
        "seller_name": seller_name,
        "amount_cents": txn.amount_cents,
        "currency": txn.currency,
        "platform_account_email": txn.platform_account_email,
        "agreement_id": txn.agreement_id,
        "dispute": txn.dispute,
        "created_at": txn.created_at.isoformat(),
    }


@router.get("/overview")
async def overview(request: Request) -> dict[str, Any]:
    await require_admin(request)
    pending = await request.app.state.tenancy.list_seller_verifications(
        status="pending"
    )
    transactions = await request.app.state.repo.list_platform_transactions(
        _platform_email(request), limit=500
    )
    held = 0
    for txn in transactions:
        balances = await request.app.state.repo.ledger_balances(txn.transaction_id)
        held += balances.get("platform_cash", 0)
    return {
        "pending_verifications": len(pending),
        "platform_transaction_count": len(transactions),
        "platform_held_cents": held,
    }


@router.get("/transactions")
async def list_platform_transactions(
    request: Request,
    state: str | None = None,
    seller_id: str | None = None,
    buyer_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    await require_admin(request)
    txns = await request.app.state.repo.list_platform_transactions(
        _platform_email(request),
        state=state,
        seller_id=seller_id,
        buyer_id=buyer_id,
        limit=limit,
    )
    return [
        await _serialize(txn, request.app.state.agreement_service) for txn in txns
    ]


@router.get("/transactions/{transaction_id}")
async def get_platform_transaction(transaction_id: str, request: Request) -> dict:
    await require_admin(request)
    repo = request.app.state.repo
    txn = await repo.get_transaction(transaction_id)
    authorize_platform_transaction(txn, _platform_email(request))
    evidence = await repo.list_evidence(transaction_id)
    return {
        **await _serialize(txn, request.app.state.agreement_service),
        "ledger": await repo.ledger_entries(transaction_id),
        "events": await repo.events(transaction_id),
        "evidence": [item.model_dump(mode="json") for item in evidence],
    }


@router.get("/transactions/{transaction_id}/audit")
async def platform_transaction_audit(
    transaction_id: str, request: Request
) -> list[dict]:
    await require_admin(request)
    repo = request.app.state.repo
    txn = await repo.get_transaction(transaction_id)
    authorize_platform_transaction(txn, _platform_email(request))
    return await request.app.state.tenancy.list_audit(
        scope="transaction", resource_id=transaction_id
    )


@router.post("/transactions/{transaction_id}/payout-release", status_code=201)
async def admin_payout_release(
    transaction_id: str, body: PayoutReleaseRequest, request: Request
) -> dict:
    identity = await require_admin(request)
    repo = request.app.state.repo
    txn = await repo.get_transaction(transaction_id)
    authorize_platform_transaction(txn, _platform_email(request))
    store = request.app.state.tenancy
    seller_org_id = txn.seller_organization_id
    if seller_org_id is None:
        org = await store.ensure_seed_organization(
            seller_id=txn.seller_id, kind="business", verified=False
        )
        seller_org_id = org["id"]
    release = await store.create_payout_release(
        transaction_id, seller_org_id, identity.user_id, body.reason
    )
    await store.record_audit(
        scope="organization",
        organization_id=seller_org_id,
        transaction_id=transaction_id,
        actor_user_id=identity.user_id,
        actor_type="user",
        action="payout.release_approved",
        resource_id=transaction_id,
        payload={
            "reason": body.reason,
            "actor": (
                f"user:{identity.clerk_user_id} acting for platform:"
                f"{_platform_email(request)}"
            ),
        },
    )
    return release


@router.get("/payouts")
async def platform_payouts(request: Request) -> list[dict]:
    await require_admin(request)
    rows = await request.app.state.tenancy.list_audit()
    return [
        row for row in rows if row.get("action") == "payout.release_approved"
    ]


@router.get("/disputes")
async def platform_disputes(request: Request) -> list[dict]:
    await require_admin(request)
    txns = await request.app.state.repo.list_platform_transactions(
        _platform_email(request), limit=500
    )
    return [
        {"transaction_id": txn.transaction_id, "dispute": txn.dispute}
        for txn in txns
        if txn.dispute
    ]


@router.get("/disputes/{transaction_id}")
async def platform_dispute_detail(transaction_id: str, request: Request) -> dict:
    await require_admin(request)
    repo = request.app.state.repo
    txn = await repo.get_transaction(transaction_id)
    authorize_platform_transaction(txn, _platform_email(request))
    evidence = await repo.list_evidence(transaction_id)
    return {
        "transaction_id": transaction_id,
        "dispute": txn.dispute,
        "evidence": [item.model_dump(mode="json") for item in evidence],
    }


@router.get("/verification/pending")
async def pending_verifications(request: Request) -> list[dict]:
    await require_admin(request)
    return await request.app.state.tenancy.list_seller_verifications(status="pending")


@router.get("/audit")
async def platform_audit(
    request: Request, scope: str | None = None, actor_type: str | None = None
) -> list[dict]:
    await require_admin(request)
    return await request.app.state.tenancy.list_audit(
        scope=scope, actor_type=actor_type
    )


@router.get("/settings")
async def platform_settings(request: Request) -> dict:
    await require_admin(request)
    return {"platform_account_email": _redact_email(_platform_email(request))}
