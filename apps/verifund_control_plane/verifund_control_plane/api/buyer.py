"""Buyer-facing routes — Clerk/internal principal auth (fail-closed)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile

from verifund_control_plane.api.buyer_auth import authorize_buyer_transaction

router = APIRouter(prefix="/buyer")


def _service(request: Request):
    return request.app.state.service


@router.post("/transactions/{transaction_id}/delivery-confirmed")
async def confirm_delivery(
    transaction_id: str, request: Request
) -> dict[str, Any]:
    principal, _record = await authorize_buyer_transaction(
        request, transaction_id, required_scope="txn:act"
    )
    body = await request.json()
    confirmed_at = body.get("confirmed_at")
    return await _service(request).confirm_delivery(
        transaction_id,
        buyer_id=principal.buyer_id,
        confirmed_at=confirmed_at,
        condition=body.get("condition"),
        photos=body.get("photos"),
        carrier_event_at=body.get("carrier_event_at"),
    )


@router.post("/transactions/{transaction_id}/accept")
async def accept(transaction_id: str, request: Request) -> dict[str, Any]:
    principal, _record = await authorize_buyer_transaction(
        request, transaction_id, required_scope="txn:act"
    )
    return await _service(request).buyer_accept(
        transaction_id,
        buyer_id=principal.buyer_id,
        actor=principal.actor,
    )


@router.post("/transactions/{transaction_id}/dispute")
async def dispute(transaction_id: str, request: Request) -> dict[str, Any]:
    principal, _record = await authorize_buyer_transaction(
        request, transaction_id, required_scope="txn:act"
    )
    body = await request.json()
    return await _service(request).open_dispute(
        transaction_id,
        buyer_id=principal.buyer_id,
        requirement_ids=body.get("requirement_ids") or [],
        reason_code=body.get("reason_code"),
        claim_type=body.get("claim_type"),
        claim=body.get("claim"),
        evidence=body.get("evidence") or [],
    )


@router.get("/transactions/{transaction_id}/inspection")
async def get_inspection(transaction_id: str, request: Request) -> dict[str, Any]:
    principal, _record = await authorize_buyer_transaction(
        request, transaction_id, required_scope="txn:read"
    )
    return await _service(request).get_inspection(
        transaction_id, buyer_id=principal.buyer_id
    )


@router.post("/transactions/{transaction_id}/evidence", status_code=201)
async def add_buyer_evidence(
    transaction_id: str,
    request: Request,
    requirement_id: str = Form(...),
    reference: str | None = Form(None),
    reference_type: str | None = Form(None),
    note: str | None = Form(None),
    captured_at: datetime | None = Form(None),
    agreement_version: int | None = Form(None),
    view_label: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> dict[str, Any]:
    principal, record = await authorize_buyer_transaction(
        request, transaction_id, required_scope="txn:act"
    )
    data = None
    media_type = None
    original_filename = None
    if file is not None:
        data = await file.read(request.app.state.settings.max_evidence_bytes + 1)
        media_type = file.content_type
        original_filename = file.filename
    submission = await _service(request).add_buyer_evidence(
        transaction_id,
        buyer_id=principal.buyer_id,
        agreement_hash=record.agreement_hash,
        requirement_id=requirement_id,
        reference=reference,
        reference_type=reference_type,
        media_type=media_type,
        original_filename=original_filename,
        data=data,
        note=note,
        captured_at=captured_at,
        agreement_version=agreement_version,
        view_label=view_label,
        actor=principal.actor,
    )
    return submission.model_dump(mode="json") if hasattr(submission, "model_dump") else submission
