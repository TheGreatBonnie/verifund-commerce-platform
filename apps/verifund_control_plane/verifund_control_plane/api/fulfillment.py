"""Invitation exchange (plan Task 12b)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


def _service(request: Request):
    return request.app.state.service


@router.post("/fulfillment/access/{token}")
async def exchange_invitation(token: str, request: Request) -> dict[str, Any]:
    service = _service(request)
    return await service.exchange_invitation(token)
