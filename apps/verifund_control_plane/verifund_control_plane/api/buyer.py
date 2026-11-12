"""Buyer-facing routes — Clerk/internal principal auth (fail-closed)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

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
