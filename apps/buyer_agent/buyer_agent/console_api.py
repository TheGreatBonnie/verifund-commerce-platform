from __future__ import annotations

import secrets
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

router = APIRouter()


def _services(request: Request):
    return request.app.state.services


def _run(row: dict) -> dict:
    return {
        "run_id": row.get("run_id"),
        "stage": row.get("stage"),
        "mandate": row.get("mandate_json"),
        "award": row.get("award_json"),
        "order": row.get("order_json"),
        "error": row.get("error"),
        "organization_id": row.get("organization_id"),
        "user_id": row.get("user_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "buyer"}


@router.get("/ready")
async def ready(request: Request) -> dict:
    services = _services(request)
    engine = getattr(services, "engine", None)
    if engine is not None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    return {"status": "ready", "service": "buyer"}


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> str:
    services = _services(request)
    trace = getattr(services, "trace", None)
    runs = 0
    if trace is not None:
        try:
            runs = len(await trace.list_runs(limit=1000))
        except Exception:  # noqa: BLE001
            runs = 0
    return (
        "# HELP marketmesh_buyer_runs Number of persisted runs.\n"
        "# TYPE marketmesh_buyer_runs gauge\n"
        f"marketmesh_buyer_runs {runs}\n"
    )


@router.get("/api/runs")
async def list_runs(
    request: Request,
    organization_id: str = "",
    limit: int = 50,
) -> list[dict]:
    settings = request.app.state.settings
    expected = settings.internal_api_token
    provided = request.headers.get("x-verifund-internal-token", "")
    if not expected or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="unauthorized")
    if not organization_id:
        raise HTTPException(status_code=400, detail="organization_id is required")
    trace = getattr(_services(request), "trace", None)
    if trace is None:
        return []
    rows = await trace.list_runs(
        organization_id, limit=max(1, min(limit, 200))
    )
    return [_run(row) for row in rows]


@router.get("/api/marketplace/products")
async def marketplace_products(request: Request) -> dict:
    settings = request.app.state.settings
    provided = request.headers.get("x-marketmesh-console-token", "")
    if not settings.console_api_token or not secrets.compare_digest(
        provided, settings.console_api_token
    ):
        raise HTTPException(status_code=401, detail="unauthorized")
    registry = getattr(_services(request), "registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="seller registry unavailable")
    try:
        return {
            "products": await registry.marketplace_products(
                category=request.query_params.get("category"),
                query=request.query_params.get("q"),
            )
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail="marketplace catalog unavailable") from exc


@router.get("/api/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> dict:
    trace = getattr(_services(request), "trace", None)
    row = await trace.get_run(run_id) if trace is not None else None
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    response = _run(row)
    from buyer_agent.settlement_api import console_authorized, load_settlement_projection

    if console_authorized(request):
        projection = await load_settlement_projection(
            request, run_id, refresh=False
        )
        if projection is not None:
            response["settlement"] = projection
    return response


@router.get("/api/runs/{run_id}/trace")
async def get_trace(
    run_id: str,
    request: Request,
    after_seq: int = 0,
    limit: int = 200,
) -> list[dict]:
    trace = getattr(_services(request), "trace", None)
    if trace is None:
        return []
    events = await trace.list(
        run_id, after_seq=max(0, after_seq), limit=max(1, min(limit, 500))
    )
    return [asdict(event) for event in events]


@router.get("/api/sellers/{seller_id}/dashboard")
async def get_seller_dashboard(seller_id: str, request: Request) -> dict:
    settings = request.app.state.settings
    expected = settings.console_api_token
    provided = request.headers.get("x-marketmesh-console-token", "")
    if not expected or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="unauthorized")

    registry = getattr(_services(request), "registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="seller registry unavailable")
    try:
        return await registry.fetch_seller_dashboard(seller_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="seller dashboard unavailable") from exc
