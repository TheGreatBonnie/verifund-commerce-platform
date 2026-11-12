from __future__ import annotations

import inspect
import json
from copy import deepcopy
from typing import Any

import httpx
import pytest
import respx
from commerce_core.retrieval import RetrievalResult
from orchestrator_agent import agent, marketplace
from orchestrator_agent.marketplace import (
    fetch_marketplace_products,
    retrieve_products,
    shape_search_result,
)
from orchestrator_agent.settings import Settings

MACBOOK: dict[str, Any] = {
    "id": "MM-MACBOOK-AIR-M4-13",
    "sku": "MM-MACBOOK-AIR-M4-13",
    "name": "MacBook Air M4 13-inch",
    "category": "Electronics",
    "description": "Apple M4 - 16GB memory - 256GB SSD - Space Gray",
    "unit_price_cents": 99900,
    "original_unit_price_cents": 119900,
    "rating": 4.6,
    "offers": [
        {
            "seller_id": "northwind-audio",
            "seller_name": "Northwind Audio",
            "unit_price_cents": 99900,
            "currency": "USD",
            "available": True,
            "on_hand": 8,
            "incoming": 0,
        }
    ],
}

MONITOR: dict[str, Any] = {
    "id": "MM-4K-MONITOR-27",
    "sku": "MM-4K-MONITOR-27",
    "name": "4K Monitor 27-inch",
    "category": "Electronics",
    "description": "IPS panel - USB-C",
    "unit_price_cents": 32900,
    "original_unit_price_cents": None,
    "rating": 4.7,
    "offers": [
        {
            "seller_id": "circuitforge",
            "seller_name": "CircuitForge",
            "unit_price_cents": 32900,
            "currency": "USD",
            "available": False,
            "on_hand": 0,
            "incoming": 0,
        }
    ],
}

CATALOG = [MACBOOK, MONITOR]

TRACE = {
    "mode": "dense",
    "backend": "InMemoryVectorStore",
    "model": "Qwen/Qwen3-Embedding-8B",
    "dimension": 1024,
    "candidates": 2,
    "top_k": [{"sku": "MM-MACBOOK-AIR-M4-13", "score": 0.91}],
    "latency_ms": 12,
}


class StubRetriever:
    """Stand-in for ProductRetriever: records calls, returns canned output."""

    def __init__(
        self,
        *,
        products: list[dict] | None = None,
        trace: dict | None = None,
        error: Exception | None = None,
    ) -> None:
        self.products = products if products is not None else [MACBOOK]
        self.trace = trace or TRACE
        self.error = error
        self.calls: list[dict] = []

    def search(self, products: list[dict], **kwargs) -> RetrievalResult:
        self.calls.append({"products": list(products), **kwargs})
        if self.error is not None:
            raise self.error
        return RetrievalResult(products=list(self.products), trace=self.trace)


def test_retrieve_products_passes_every_constraint_to_the_retriever():
    retriever = StubRetriever()

    products, trace = retrieve_products(
        CATALOG,
        retriever=retriever,
        query="laptop",
        category="Electronics",
        max_unit_price_cents=150000,
        in_stock_only=True,
        use_case="programming",
        preferences=["quiet"],
    )

    assert products == [MACBOOK]
    assert trace == TRACE
    assert retriever.calls == [
        {
            "products": CATALOG,
            "query": "laptop",
            "use_case": "programming",
            "preferences": ["quiet"],
            "category": "Electronics",
            "max_unit_price_cents": 150000,
            "in_stock_only": True,
        }
    ]


def test_retrieve_products_does_not_mutate_the_catalog():
    before = deepcopy(CATALOG)

    retrieve_products(CATALOG, retriever=StubRetriever())

    assert CATALOG == before


def test_shape_reports_pre_limit_total_and_truncates():
    ranked = [MACBOOK, MONITOR, {**MONITOR, "sku": "X-3"}]

    shaped = shape_search_result({"category": "Electronics"}, ranked, limit=2)

    assert shaped["total_candidates"] == 3
    assert len(shaped["products"]) == 2
    assert shaped["applied_filters"] == {"category": "Electronics"}
    assert "retrieval" not in shaped


def test_shape_includes_a_copy_of_the_retrieval_trace():
    shaped = shape_search_result({}, [MACBOOK], retrieval=TRACE)

    assert shaped["retrieval"] == TRACE
    assert shaped["retrieval"] is not TRACE
    assert shaped["retrieval"]["top_k"][0]["sku"] == "MM-MACBOOK-AIR-M4-13"


def test_lexical_machinery_is_gone():
    source = inspect.getsource(marketplace)

    for name in (
        "TOKEN_SYNONYMS",
        "_tokenize",
        "_expand",
        "_first_field",
        "_haystack",
        "filter_and_rank_products",
    ):
        assert name not in source


@respx.mock
async def test_fetch_uses_the_internal_token_and_forwards_category_only():
    route = respx.get("http://buyer/api/marketplace/products").mock(
        return_value=httpx.Response(200, json={"products": [MACBOOK]})
    )

    products = await fetch_marketplace_products(
        base_url="http://buyer/",
        internal_token="internal-token",
        timeout=2.0,
        category="Electronics",
    )

    assert products == [MACBOOK]
    request = route.calls[0].request
    assert request.headers["x-verifund-internal-token"] == "internal-token"
    assert request.url.params["category"] == "Electronics"
    assert "q" not in request.url.params


@respx.mock
async def test_fetch_rejects_a_malformed_payload():
    respx.get("http://buyer/api/marketplace/products").mock(
        return_value=httpx.Response(200, json={"products": "nope"})
    )

    with pytest.raises(TypeError):
        await fetch_marketplace_products(
            base_url="http://buyer",
            internal_token="internal-token",
            timeout=2.0,
        )


@respx.mock
async def test_fetch_raises_on_an_upstream_error():
    respx.get("http://buyer/api/marketplace/products").mock(
        return_value=httpx.Response(502)
    )

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_marketplace_products(
            base_url="http://buyer",
            internal_token="internal-token",
            timeout=2.0,
        )


@pytest.mark.asyncio
async def test_tool_binds_settings_and_hides_credentials(monkeypatch):
    captured: dict = {}

    async def fake_fetch(**kwargs):
        captured.update(kwargs)
        return [MACBOOK]

    monkeypatch.setattr(marketplace, "fetch_marketplace_products", fake_fetch)
    retriever = StubRetriever()
    tool = agent._build_marketplace_search_tool(
        Settings(
            buyer_internal_url="http://buyer-configured",
            buyer_internal_token="internal-secret",
            buyer_internal_timeout_seconds=3.5,
            nebius_api_key=None,
        ),
        retriever=retriever,
    )

    assert tool.name == "search_marketplace_products"
    parameters = inspect.signature(tool.func).parameters
    for name in (
        "query",
        "category",
        "max_unit_price_cents",
        "in_stock_only",
        "use_case",
        "preferences",
        "limit",
    ):
        assert name in parameters
    assert "buyer_internal_token" not in parameters
    assert "buyer_internal_url" not in parameters

    result = await tool.func(query="laptop")

    assert captured == {
        "base_url": "http://buyer-configured",
        "internal_token": "internal-secret",
        "timeout": 3.5,
        "category": None,
    }
    assert [product["sku"] for product in result["products"]] == ["MM-MACBOOK-AIR-M4-13"]
    assert result["retrieval"]["mode"] == "dense"
    assert retriever.calls[0]["query"] == "laptop"


@pytest.mark.asyncio
async def test_tool_coerces_the_price_ceiling_and_clamps_the_limit(monkeypatch):
    async def fake_fetch(**_kwargs):
        return [MACBOOK]

    monkeypatch.setattr(marketplace, "fetch_marketplace_products", fake_fetch)
    tool = agent._build_marketplace_search_tool(
        Settings(nebius_api_key=None), retriever=StubRetriever()
    )

    coerced = await tool.func(query="laptop", max_unit_price_cents="150000")
    assert coerced["total_candidates"] == 1
    assert coerced["applied_filters"]["max_unit_price_cents"] == 150000

    too_many = [
        {**MACBOOK, "sku": f"SKU-{index}", "name": f"Gadget {index}"}
        for index in range(30)
    ]
    monkeypatch.setattr(
        marketplace, "fetch_marketplace_products", lambda **_kwargs: _async(too_many)
    )
    clamped_tool = agent._build_marketplace_search_tool(
        Settings(nebius_api_key=None), retriever=StubRetriever(products=too_many)
    )

    clamped = await clamped_tool.func(limit=999)
    assert clamped["total_candidates"] == 30
    assert len(clamped["products"]) == 24
    assert len((await clamped_tool.func(limit=0))["products"]) == 1


@pytest.mark.asyncio
async def test_tool_returns_retrieval_unavailable_when_embeddings_fail(monkeypatch):
    async def fake_fetch(**_kwargs):
        return [MACBOOK]

    monkeypatch.setattr(marketplace, "fetch_marketplace_products", fake_fetch)
    tool = agent._build_marketplace_search_tool(
        Settings(nebius_api_key=None),
        retriever=StubRetriever(error=RuntimeError("rejected internal-secret")),
    )

    result = await tool.func(query="laptop")

    assert result["error"] == "retrieval_unavailable"
    assert "internal-secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_tool_returns_retrieval_unavailable_without_an_api_key():
    tool = agent._build_marketplace_search_tool(Settings(nebius_api_key=None))

    result = await tool.func(query="laptop")

    assert result["error"] == "retrieval_unavailable"
    assert "products" not in result


@pytest.mark.asyncio
async def test_tool_returns_a_secret_free_error_when_the_catalog_fails(monkeypatch):
    async def failing_fetch(**_kwargs):
        raise RuntimeError("http://buyer-configured rejected internal-secret")

    monkeypatch.setattr(marketplace, "fetch_marketplace_products", failing_fetch)
    tool = agent._build_marketplace_search_tool(
        Settings(buyer_internal_token="internal-secret", nebius_api_key=None),
        retriever=StubRetriever(),
    )

    result = await tool.func(query="laptop")

    assert result["error"] == "marketplace_unavailable"
    serialized = json.dumps(result)
    assert "internal-secret" not in serialized
    assert "buyer-configured" not in serialized


def test_instruction_wires_discovery_and_buyer_handoff():
    instruction = agent.MARKETMESH_ORCHESTRATOR_INSTRUCTION
    assert "search_marketplace_products" in instruction
    assert "send_message_to_a2a_agent" in instruction
    assert "MarketMesh Buyer" in instruction


async def _async(value):
    return value
