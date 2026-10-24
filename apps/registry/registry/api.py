from __future__ import annotations

import re
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Any

from commerce_core.cards import fetch_agent_card, validate_agent_card
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from google.protobuf import json_format
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from registry.settings import Settings
from registry.store import RegistryStore, canonical_card_hash

SELLER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


class SellerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seller_id: str | None = None
    card_url: str
    categories: list[str] = Field(min_length=1)


class DiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str
    required_extension: str
    limit: int = Field(default=20, ge=1, le=100)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _seller_view(row: dict[str, Any], include_card: bool = False) -> dict[str, Any]:
    view = {
        "seller_id": row["seller_id"],
        "name": row["name"],
        "card_url": row["card_url"],
        "categories": row["categories"],
        "card_hash": row["card_hash"],
        "last_seen_at": row["last_seen_at"],
        "healthy": row["healthy"],
        "last_error": row.get("last_error"),
    }
    if include_card:
        view["card_json"] = row["card_json"]
    return view


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = create_async_engine(settings.database_url)
    store = RegistryStore(engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            await store.create_schema()
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="MarketMesh Registry", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.store = store

    def require_admin(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        expected = f"Bearer {settings.admin_token}"
        if authorization is None or not secrets.compare_digest(
            authorization, expected
        ):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/sellers", status_code=201)
    async def register_seller(
        body: SellerCreate,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        try:
            card = await fetch_agent_card(
                body.card_url, allowed_hosts=settings.allowed_card_hosts
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        errors = validate_agent_card(card)
        if errors:
            raise HTTPException(status_code=400, detail="; ".join(errors))
        seller_id = body.seller_id or _slug(card.name)
        if not SELLER_ID_PATTERN.fullmatch(seller_id):
            raise HTTPException(status_code=400, detail="invalid seller_id")
        card_json = json_format.MessageToDict(
            card, preserving_proto_field_name=False
        )
        row = await store.upsert(
            seller_id=seller_id,
            name=card.name,
            card_url=body.card_url,
            categories=body.categories,
            card_json=card_json,
            card_hash=canonical_card_hash(card_json),
            healthy=True,
            error=None,
        )
        return _seller_view(row, include_card=True)

    @app.get("/v1/sellers")
    async def list_sellers() -> dict[str, Any]:
        return {
            "sellers": [
                _seller_view(row, include_card=True)
                for row in await store.list_sellers()
            ]
        }

    @app.post("/v1/discover")
    async def discover(body: DiscoverRequest) -> dict[str, Any]:
        rows = await store.discover(
            body.category, body.required_extension, body.limit
        )
        return {"sellers": [_seller_view(row) for row in rows]}

    @app.post("/v1/sellers/{seller_id}/refresh")
    async def refresh_seller(
        seller_id: str,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        existing = await store.get(seller_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="seller not found")
        try:
            card = await fetch_agent_card(
                existing["card_url"],
                allowed_hosts=settings.allowed_card_hosts,
            )
        except Exception as exc:
            await store.mark_health(seller_id, False, str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        errors = validate_agent_card(card)
        if errors:
            await store.mark_health(seller_id, False, "; ".join(errors))
            raise HTTPException(status_code=400, detail="; ".join(errors))
        card_json = json_format.MessageToDict(
            card, preserving_proto_field_name=False
        )
        row = await store.upsert(
            seller_id=seller_id,
            name=card.name,
            card_url=existing["card_url"],
            categories=existing["categories"],
            card_json=card_json,
            card_hash=canonical_card_hash(card_json),
            healthy=True,
            error=None,
        )
        return _seller_view(row, include_card=True)

    return app
