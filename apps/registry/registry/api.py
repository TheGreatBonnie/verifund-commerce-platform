from __future__ import annotations

import re
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from commerce_core.cards import (
    fetch_agent_card,
    validate_agent_card,
    validate_generic_agent_card,
)
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
    organization_id: str | None = None
    verified: bool = True
    card_json: dict[str, Any] | None = None


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str | None = None
    card_url: str
    name: str | None = None
    skills: list[str] = Field(default_factory=list)
    card_json: dict[str, Any] | None = None
    organization_id: str | None = None
    published: bool = True


class AgentDiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill: str
    limit: int = Field(default=20, ge=1, le=100)


class DiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str
    required_extension: str
    limit: int = Field(default=20, ge=1, le=100)
    product_sku: str | None = None


def _canonical_card_url(value: str) -> str:
    try:
        return str(httpx.URL(value)).rstrip("/")
    except httpx.InvalidURL:
        return value.rstrip("/")


def assert_card_url_owned(
    seller_id: str,
    card_url: str,
    allowed_card_urls: tuple[str, ...] = (),
) -> None:
    if f"/{seller_id}/a2a" in card_url or f"/{seller_id}/" in card_url:
        return
    if _canonical_card_url(card_url) in {
        _canonical_card_url(url) for url in allowed_card_urls
    }:
        return
    raise HTTPException(
        status_code=400,
        detail={
            "code": "card_url_not_owned",
            "message": "card url does not match seller id",
        },
    )


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


def _agent_view(row: dict[str, Any], include_card: bool = False) -> dict[str, Any]:
    view = {
        "agent_id": row["agent_id"],
        "name": row["name"],
        "card_url": row["card_url"],
        "skills": row["skills"],
        "card_hash": row["card_hash"],
        "last_seen_at": row["last_seen_at"],
        "healthy": row["healthy"],
        "last_error": row.get("last_error"),
    }
    if include_card:
        view["card_json"] = row["card_json"]
    return view


async def _load_agent_card(card_url: str, settings: Settings):
    card = await fetch_agent_card(
        card_url, allowed_hosts=settings.allowed_card_hosts
    )
    errors = validate_generic_agent_card(card)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    return card


def seller_path_base(card_url: str) -> str:
    url = httpx.URL(card_url)
    suffix = "/.well-known/agent-card.json"
    path = url.path
    path = path.removesuffix(suffix)
    return str(url.copy_with(path=path or "/", query=None, fragment=None)).rstrip("/")


def seller_catalog_url(card_url: str) -> str:
    return f"{seller_path_base(card_url)}/api/catalog"


async def _fetch_catalog(card_url: str) -> list[dict[str, Any]]:
    catalog_url = seller_catalog_url(card_url)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(catalog_url)
        response.raise_for_status()
    products = response.json().get("products", [])
    if not isinstance(products, list):
        raise TypeError("seller catalog must contain a products list")
    seen: set[str] = set()
    for product in products:
        if not isinstance(product, dict) or not all(
            isinstance(product.get(field), str) and product[field]
            for field in ("sku", "name", "category")
        ):
            raise ValueError("seller catalog entries require sku, name, and category")
        if product["sku"] in seen:
            raise ValueError(f"seller catalog contains duplicate SKU {product['sku']}")
        seen.add(product["sku"])
    return products


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
        return JSONResponse(
            {"error": exc.detail, "detail": exc.detail}, status_code=exc.status_code
        )

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
        seller_id = body.seller_id or ""
        if seller_id:
            assert_card_url_owned(
                seller_id,
                body.card_url,
                allowed_card_urls=settings.allowed_card_urls,
            )
        if body.card_json is not None:
            if not seller_id:
                raise HTTPException(status_code=400, detail="invalid seller_id")
            card_json = body.card_json
            name = card_json.get("name", seller_id)
            listings: list[dict[str, Any]] = []
        else:
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
            name = card.name
            try:
                listings = await _fetch_catalog(body.card_url)
            except (httpx.HTTPError, TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"seller catalog unavailable: {exc}") from exc
        row = await store.upsert(
            seller_id=seller_id,
            name=name,
            card_url=body.card_url,
            categories=body.categories,
            card_json=card_json,
            card_hash=canonical_card_hash(card_json),
            healthy=True,
            error=None,
            organization_id=body.organization_id,
            verified=body.verified,
        )
        if listings:
            await store.replace_listings(seller_id, listings)
        return _seller_view(row, include_card=True)

    @app.get("/v1/sellers")
    async def list_sellers() -> dict[str, Any]:
        return {
            "sellers": [
                _seller_view(row, include_card=True)
                for row in await store.list_sellers()
            ]
        }

    @app.get("/v1/sellers/{seller_id}")
    async def get_seller(seller_id: str) -> dict[str, Any]:
        row = await store.get(seller_id)
        if row is None:
            raise HTTPException(status_code=404, detail="seller not found")
        return _seller_view(row, include_card=True)

    @app.get("/v1/products")
    async def search_products(
        category: str | None = None,
        q: str | None = None,
        sku: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        listings = await store.search_listings(
            category=category, query=q, sku=sku, limit=limit
        )
        return {"products": listings}

    @app.post("/v1/discover")
    async def discover(body: DiscoverRequest) -> dict[str, Any]:
        rows = await store.discover(
            body.category, body.required_extension, body.limit, body.product_sku
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
        try:
            listings = await _fetch_catalog(existing["card_url"])
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            await store.mark_health(seller_id, False, str(exc))
            raise HTTPException(status_code=400, detail=f"seller catalog unavailable: {exc}") from exc
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
        await store.replace_listings(seller_id, listings)
        return _seller_view(row, include_card=True)


    @app.post("/v1/agents", status_code=201)
    async def register_agent(
        body: AgentCreate,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        if body.card_json is not None:
            agent_id = body.agent_id or ""
            if not SELLER_ID_PATTERN.fullmatch(agent_id):
                raise HTTPException(status_code=400, detail="invalid agent id")
            payload = body.card_json
            name = body.name or payload.get("name", agent_id)
            skills = body.skills or payload.get("skills", [])
            row = await store.upsert_agent(
                agent_id=agent_id,
                name=name,
                card_url=body.card_url,
                skills=skills,
                card_json=payload,
                card_hash=canonical_card_hash(payload),
                healthy=True,
                error=None,
                organization_id=body.organization_id,
                published=body.published,
            )
            return _agent_view(row, include_card=True)
        try:
            card = await _load_agent_card(body.card_url, settings)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        agent_id = body.agent_id or _slug(card.name)
        if not SELLER_ID_PATTERN.fullmatch(agent_id):
            raise HTTPException(status_code=400, detail="invalid agent id")
        payload = json_format.MessageToDict(card, preserving_proto_field_name=False)
        row = await store.upsert_agent(
            agent_id=agent_id,
            name=card.name,
            card_url=body.card_url,
            skills=sorted(skill.id for skill in card.skills),
            card_json=payload,
            card_hash=canonical_card_hash(payload),
            healthy=True,
            error=None,
            organization_id=body.organization_id,
            published=body.published,
        )
        return _agent_view(row, include_card=True)

    @app.get("/v1/agents")
    async def list_agents(
        _: None = Depends(require_admin),
        skill: str | None = None,
    ) -> dict[str, Any]:
        rows = await store.list_agents(skill=skill, published_only=True)
        return {
            "agents": [_agent_view(row) for row in rows],
            "items": [_agent_view(row) for row in rows],
        }

    @app.get("/v1/agents/{agent_id}")
    async def get_agent(
        agent_id: str,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        row = await store.get_agent(agent_id)
        if row is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return _agent_view(row, include_card=True)

    @app.post("/v1/agents/{agent_id}/refresh")
    async def refresh_agent(
        agent_id: str,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        row = await store.get_agent(agent_id)
        if row is None:
            raise HTTPException(status_code=404, detail="agent not found")
        try:
            card = await _load_agent_card(row["card_url"], settings)
        except Exception as exc:
            await store.mark_agent_health(agent_id, False, str(exc))
            raise HTTPException(status_code=400, detail=f"agent card unavailable: {exc}") from exc
        payload = json_format.MessageToDict(card, preserving_proto_field_name=False)
        row = await store.upsert_agent(
            agent_id=agent_id,
            name=card.name,
            card_url=row["card_url"],
            skills=sorted(skill.id for skill in card.skills),
            card_json=payload,
            card_hash=canonical_card_hash(payload),
            healthy=True,
            error=None,
        )
        return _agent_view(row, include_card=True)

    @app.post("/v1/agents/discover")
    async def discover_agents(
        body: AgentDiscoverRequest,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        rows = await store.list_agents(skill=body.skill, published_only=True)
        return {
            "agents": [
                _agent_view(row)
                for row in rows
                if row["healthy"]
            ][: body.limit]
        }

    return app
