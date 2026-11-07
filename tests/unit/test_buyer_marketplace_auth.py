from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from buyer_agent import console_api
from fastapi import FastAPI


class Settings:
    console_api_token = "console-token"
    internal_api_token = "internal-token"


class Registry:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def marketplace_products(
        self, category: str | None = None, query: str | None = None
    ) -> list[dict]:
        self.calls.append({"category": category, "query": query})
        return [{"sku": "MM-MACBOOK-AIR-M4-13"}]


def build(registry: Registry) -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings()
    app.state.services = SimpleNamespace(registry=registry)
    app.include_router(console_api.router)
    return app


@pytest.fixture
async def api():
    registry = Registry()
    transport = httpx.ASGITransport(app=build(registry))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://buyer"
    ) as http:
        yield http, registry


async def test_console_token_is_accepted(api):
    http, _ = api
    response = await http.get(
        "/api/marketplace/products",
        headers={"x-marketmesh-console-token": "console-token"},
    )
    assert response.status_code == 200
    assert response.json()["products"] == [{"sku": "MM-MACBOOK-AIR-M4-13"}]


async def test_internal_token_is_accepted(api):
    http, _ = api
    response = await http.get(
        "/api/marketplace/products",
        headers={"x-verifund-internal-token": "internal-token"},
    )
    assert response.status_code == 200


async def test_both_tokens_are_accepted(api):
    http, _ = api
    response = await http.get(
        "/api/marketplace/products",
        headers={
            "x-marketmesh-console-token": "console-token",
            "x-verifund-internal-token": "internal-token",
        },
    )
    assert response.status_code == 200


async def test_missing_token_is_rejected(api):
    http, _ = api
    response = await http.get("/api/marketplace/products")
    assert response.status_code == 401


async def test_wrong_console_token_is_rejected(api):
    http, _ = api
    response = await http.get(
        "/api/marketplace/products",
        headers={"x-marketmesh-console-token": "wrong"},
    )
    assert response.status_code == 401


async def test_wrong_internal_token_is_rejected(api):
    http, _ = api
    response = await http.get(
        "/api/marketplace/products",
        headers={"x-verifund-internal-token": "wrong"},
    )
    assert response.status_code == 401


async def test_query_parameters_are_forwarded(api):
    http, registry = api
    response = await http.get(
        "/api/marketplace/products",
        params={"category": "Electronics", "q": "macbook"},
        headers={"x-verifund-internal-token": "internal-token"},
    )
    assert response.status_code == 200
    assert registry.calls == [{"category": "Electronics", "query": "macbook"}]
