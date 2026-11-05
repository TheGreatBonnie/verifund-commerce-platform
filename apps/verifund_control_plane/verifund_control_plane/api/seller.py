from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from verifund_contracts import EvidenceList

from verifund_control_plane.errors import VerifundError


async def _seller_rate_limit(request: Request) -> None:
    settings = request.app.state.settings
    limit = getattr(settings, "seller_rate_limit_per_minute", 0) or 0
    if limit <= 0:
        return
    buckets = request.app.state.__dict__.setdefault("_seller_rate_limits", {})
    header = request.headers.get("authorization", "")
    key = "anonymous"
    if header.startswith("Bearer "):
        try:
            claims = request.app.state.tokens.verify(
                header.removeprefix("Bearer "), required_scope=None
            )
            key = claims.seller_id
        except Exception:  # noqa: BLE001
            key = header
    now = time.time()
    window_start = now - 60.0
    bucket = [t for t in buckets.get(key, []) if t >= window_start]
    if len(bucket) >= limit:
        raise VerifundError("rate_limited", "rate limit exceeded", status_code=429)
    bucket.append(now)
    buckets[key] = bucket


router = APIRouter(prefix="/seller", dependencies=[Depends(_seller_rate_limit)])


def _service(request: Request):
    return request.app.state.service


async def authenticate(request: Request, transaction_id: str, scope: str):
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise VerifundError("unauthorized", "seller token is required", status_code=401)
    claims = request.app.state.tokens.verify(
        header.removeprefix("Bearer "), required_scope=scope
    )
    if claims.txn != transaction_id:
        raise VerifundError(
            "forbidden", "seller token is for another transaction", status_code=403
        )
    stored = await request.app.state.repo.get_seller_token(claims.jti_hash)
    if stored.get("revoked_at"):
        raise VerifundError(
            "unauthorized", "seller token has been revoked", status_code=401
        )
    if stored["seller_id"] != claims.seller_id:
        raise VerifundError("unauthorized", "seller token mismatch", status_code=401)
    record = await request.app.state.repo.get_transaction(transaction_id)
    if record.seller_id != claims.seller_id:
        raise VerifundError("forbidden", "seller does not own transaction", status_code=403)
    if record.agreement_hash != claims.agreement_hash:
        raise VerifundError(
            "hash_mismatch", "seller token agreement hash is stale", status_code=409
        )
    return claims


async def authenticate_seller(request: Request):
    """Seller-scoped authentication for the list endpoints.

    Same chain as the per-transaction routes (signature, expiry, revocation,
    seller binding) but not pinned to one transaction; rows are scoped to
    `claims.seller_id` in SQL.
    """
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise VerifundError("unauthorized", "seller token is required", status_code=401)
    claims = request.app.state.tokens.verify(
        header.removeprefix("Bearer "), required_scope="txn:read"
    )
    stored = await request.app.state.repo.get_seller_token(claims.jti_hash)
    if stored.get("revoked_at"):
        raise VerifundError(
            "unauthorized", "seller token has been revoked", status_code=401
        )
    if stored["seller_id"] != claims.seller_id:
        raise VerifundError("unauthorized", "seller token mismatch", status_code=401)
    return claims


@router.get("/transactions")
async def list_seller_transactions(
    request: Request,
    state: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    seller_id: str | None = None,
) -> dict[str, Any]:
    if seller_id is not None:
        raise VerifundError(
            "invalid_request",
            "seller_id is not an allowed filter",
            status_code=400,
        )
    claims = await authenticate_seller(request)
    return (
        await _service(request).list_seller_transactions(
            claims.seller_id, state=state, limit=limit, cursor=cursor
        )
    ).model_dump(mode="json")


@router.get("/evidence")
async def list_seller_evidence(
    request: Request,
    kind: str | None = None,
    requirement_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    seller_id: str | None = None,
) -> dict[str, Any]:
    if seller_id is not None:
        raise VerifundError(
            "invalid_request",
            "seller_id is not an allowed filter",
            status_code=400,
        )
    claims = await authenticate_seller(request)
    return (
        await _service(request).list_seller_evidence(
            claims.seller_id, kind=kind, requirement_id=requirement_id,
            limit=limit, cursor=cursor,
        )
    ).model_dump(mode="json")


@router.get("/payouts")
async def list_seller_payouts(
    request: Request,
    seller_id: str | None = None,
) -> dict[str, Any]:
    if seller_id is not None:
        raise VerifundError(
            "invalid_request",
            "seller_id is not an allowed filter",
            status_code=400,
        )
    claims = await authenticate_seller(request)
    return (
        await _service(request).list_seller_payouts(claims.seller_id)
    ).model_dump(mode="json")


@router.get("/transactions/{transaction_id}/events")
async def seller_transaction_events(
    transaction_id: str,
    request: Request,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    claims = await authenticate(request, transaction_id, "txn:read")
    return await _service(request).seller_events(
        transaction_id, seller_id=claims.seller_id, limit=limit, cursor=cursor
    )


@router.get("/agreements/{agreement_id}")
async def seller_agreement(
    agreement_id: str, request: Request
) -> dict[str, Any]:
    claims = await authenticate_seller(request)
    return await _service(request).seller_agreement(
        agreement_id, seller_id=claims.seller_id
    )


@router.get("/transactions/{transaction_id}")
async def get_seller_transaction(transaction_id: str, request: Request) -> dict[str, Any]:
    claims = await authenticate(request, transaction_id, "txn:read")
    return (
        await _service(request).seller_projection(
            transaction_id, seller_id=claims.seller_id
        )
    ).model_dump(mode="json")


@router.get("/transactions/{transaction_id}/evidence")
async def list_evidence(transaction_id: str, request: Request) -> dict[str, Any]:
    claims = await authenticate(request, transaction_id, "txn:read")
    await _service(request).seller_projection(
        transaction_id, seller_id=claims.seller_id
    )
    items = await request.app.state.repo.list_evidence(transaction_id)
    return EvidenceList(items=items).model_dump(mode="json")


@router.post("/transactions/{transaction_id}/evidence", status_code=201)
async def upload_evidence(
    transaction_id: str,
    request: Request,
    requirement_id: str | None = Form(None),
    kind: str | None = Form(None),
    file: UploadFile | None = File(None),  # noqa: B008
    reference: str | None = Form(None),
    reference_type: str | None = Form(None),
    agreement_version: int | None = Form(None),
    note: str | None = Form(None),
    captured_at: datetime | None = Form(None),  # noqa: B008
) -> dict[str, Any]:
    claims = await authenticate(request, transaction_id, "evidence:write")
    if kind is not None:
        raise VerifundError(
            "invalid_request",
            "kind is deprecated; evidence uploads are addressed by requirement_id",
            status_code=422,
        )
    if requirement_id is None:
        raise VerifundError(
            "invalid_request",
            "requirement_id is required",
            status_code=422,
        )
    data = (
        await file.read(request.app.state.settings.max_evidence_bytes + 1)
        if file is not None
        else None
    )
    receipt = await _service(request).add_evidence(
        transaction_id,
        seller_id=claims.seller_id,
        agreement_hash=claims.agreement_hash,
        requirement_id=requirement_id,
        reference=reference,
        reference_type=reference_type,
        media_type=file.content_type if file is not None else None,
        original_filename=file.filename if file is not None else None,
        data=data,
        note=note,
        captured_at=captured_at,
        agreement_version=agreement_version,
        actor=f"seller:{claims.seller_id}",
    )
    return receipt.model_dump(mode="json")


@router.post(
    "/transactions/{transaction_id}/requirements/{requirement_id}/declare",
    status_code=200,
)
async def declare_requirement(
    transaction_id: str, requirement_id: str, request: Request
) -> dict[str, Any]:
    claims = await authenticate(request, transaction_id, "evidence:write")
    return await _service(request).declare_requirement(
        transaction_id,
        requirement_id,
        seller_id=claims.seller_id,
        actor=f"seller:{claims.seller_id}",
    )


@router.get(
    "/transactions/{transaction_id}/requirements/{requirement_id}/declarations"
)
async def list_declarations(
    transaction_id: str, requirement_id: str, request: Request
) -> dict[str, Any]:
    claims = await authenticate(request, transaction_id, "txn:read")
    items = await _service(request).list_declarations(
        transaction_id, requirement_id, seller_id=claims.seller_id
    )
    return {"items": items}


@router.post(
    "/transactions/{transaction_id}/dispute-evidence", status_code=201
)
async def upload_dispute_evidence(
    transaction_id: str,
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    note: str | None = Form(None),
    captured_at: datetime | None = Form(None),  # noqa: B008
    agreement_version: int | None = Form(None),
) -> dict[str, Any]:
    claims = await authenticate(request, transaction_id, "evidence:write")
    data = await file.read(request.app.state.settings.max_evidence_bytes + 1)
    return await _service(request).add_dispute_evidence(
        transaction_id,
        seller_id=claims.seller_id,
        agreement_hash=claims.agreement_hash,
        media_type=file.content_type,
        original_filename=file.filename,
        data=data,
        note=note,
        captured_at=captured_at,
        actor=f"seller:{claims.seller_id}",
    )


@router.get("/transactions/{transaction_id}/evidence/{evidence_id}")
async def download_evidence(
    transaction_id: str, evidence_id: str, request: Request
) -> Response:
    claims = await authenticate(request, transaction_id, "txn:read")
    await _service(request).seller_projection(
        transaction_id, seller_id=claims.seller_id
    )
    item = await request.app.state.repo.get_evidence(transaction_id, evidence_id)
    return Response(
        content=request.app.state.evidence_store.read(item.sha256),
        media_type=item.media_type,
        headers={
            "content-disposition": f'attachment; filename="{item.original_filename}"'
        },
    )