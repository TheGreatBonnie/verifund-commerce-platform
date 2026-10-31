from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from verifund_contracts import EvidenceList

from verifund_control_plane.errors import VerifundError

router = APIRouter(prefix="/seller")


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
    kind: str = Form(...),
    file: UploadFile = File(...),  # noqa: B008
    note: str | None = Form(None),
    captured_at: datetime | None = Form(None),  # noqa: B008
) -> dict[str, Any]:
    claims = await authenticate(request, transaction_id, "evidence:write")
    data = await file.read(request.app.state.settings.max_evidence_bytes + 1)
    item = await _service(request).add_evidence(
        transaction_id,
        seller_id=claims.seller_id,
        agreement_hash=claims.agreement_hash,
        kind=kind,
        media_type=file.content_type or "application/octet-stream",
        original_filename=file.filename or "evidence",
        data=data,
        note=note,
        captured_at=captured_at,
        actor=f"seller:{claims.seller_id}",
    )
    return item.model_dump(mode="json")


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