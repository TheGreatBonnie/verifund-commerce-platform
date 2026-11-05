"""Buyer-facing routes (plan Task 12, scaffolded).

The three buyer actions (CONFIRM_DELIVERY, ACCEPT, DISPUTE) land in
Tasks 13, 16 and 18 respectively; this module owns the bearer-token
enforcement, ownership checks and route registration. Bodies return 501
until those tasks fill them in.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from verifund_control_plane.errors import VerifundError

router = APIRouter(prefix="/buyer")


async def authenticate_buyer(request: Request, transaction_id: str):
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise VerifundError(
            "unauthorized", "buyer token is required", status_code=401
        )
    claims = request.app.state.buyer_tokens.verify(
        header.removeprefix("Bearer "), required_scope="txn:buy"
    )
    stored = await request.app.state.repo.get_buyer_token(claims.jti_hash)
    if stored.get("revoked_at"):
        raise VerifundError(
            "unauthorized", "buyer token has been revoked", status_code=401
        )
    if stored["buyer_id"] != claims.buyer_id:
        raise VerifundError(
            "unauthorized", "buyer token mismatch", status_code=401
        )
    record = await request.app.state.repo.get_transaction(transaction_id)
    if record.buyer_id != claims.buyer_id:
        raise VerifundError(
            "forbidden", "buyer does not own this transaction", status_code=403
        )
    return claims


@router.post("/transactions/{transaction_id}/delivery-confirmed")
async def confirm_delivery(
    transaction_id: str, request: Request
) -> dict[str, Any]:
    await authenticate_buyer(request, transaction_id)
    raise VerifundError(
        "not_implemented",
        "delivery confirmation lands in Task 13",
        status_code=501,
    )


@router.post("/transactions/{transaction_id}/accept")
async def accept(transaction_id: str, request: Request) -> dict[str, Any]:
    await authenticate_buyer(request, transaction_id)
    raise VerifundError(
        "not_implemented",
        "early acceptance lands in Task 16",
        status_code=501,
    )


@router.post("/transactions/{transaction_id}/dispute")
async def dispute(transaction_id: str, request: Request) -> dict[str, Any]:
    await authenticate_buyer(request, transaction_id)
    raise VerifundError(
        "not_implemented",
        "evidence-gated dispute opens in Task 18",
        status_code=501,
    )
