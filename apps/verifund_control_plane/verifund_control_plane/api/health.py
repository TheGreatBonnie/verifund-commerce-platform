from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "verifund-control-plane"}


@router.get("/ready")
async def ready(request: Request) -> dict:
    engine = request.app.state.engine
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ready", "service": "verifund-control-plane"}


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> str:
    repo = request.app.state.repo
    count = await repo.count_transactions()
    return (
        "# HELP verifund_transactions Number of transactions.\n"
        "# TYPE verifund_transactions gauge\n"
        f"verifund_transactions {count}\n"
    )
