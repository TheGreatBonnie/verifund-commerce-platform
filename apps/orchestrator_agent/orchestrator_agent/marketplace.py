"""Grounded marketplace search for the orchestrator chat tool.

The buyer's aggregation endpoint returns every seller listing for a SKU. This
module fetches that once and ranks it with pure dense retrieval from
``commerce_core.retrieval``. Deterministic filters run before ranking, and every
result is a copy of an aggregation row: nothing is invented here.
"""

from __future__ import annotations

from typing import Any

import httpx
from commerce_core.retrieval import ProductRetriever


def retrieve_products(
    products: list[dict],
    *,
    retriever: ProductRetriever,
    query: str | None = None,
    category: str | None = None,
    max_unit_price_cents: int | None = None,
    in_stock_only: bool = False,
    use_case: str | None = None,
    preferences: list[str] | None = None,
) -> tuple[list[dict], dict]:
    """Return semantically ranked products plus the retrieval trace."""
    result = retriever.search(
        products,
        query=query,
        use_case=use_case,
        preferences=preferences,
        category=category,
        max_unit_price_cents=max_unit_price_cents,
        in_stock_only=in_stock_only,
    )
    return result.products, result.trace


def shape_search_result(
    applied_filters: dict[str, Any],
    products: list[dict],
    limit: int = 12,
    retrieval: dict | None = None,
) -> dict:
    """Set total_candidates to len(products), then truncate products to limit."""
    try:
        effective_limit = int(limit)
    except (TypeError, ValueError):
        effective_limit = 12
    effective_limit = max(1, min(effective_limit, 24))
    payload = {
        "applied_filters": dict(applied_filters),
        "total_candidates": len(products),
        "products": [dict(product) for product in products[:effective_limit]],
    }
    if retrieval is not None:
        payload["retrieval"] = dict(retrieval)
    return payload


async def fetch_marketplace_products(
    *,
    base_url: str,
    internal_token: str,
    timeout: float,
    category: str | None = None,
) -> list[dict]:
    """Fetch the buyer's marketplace aggregation without a registry ``q``."""
    params: dict[str, str] = {}
    if category:
        params["category"] = category
    url = f"{base_url.rstrip('/')}/api/marketplace/products"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            url,
            params=params or None,
            headers={"x-verifund-internal-token": internal_token},
        )
        response.raise_for_status()
        payload = response.json()
    products = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(products, list):
        raise TypeError("marketplace aggregation did not return a product list")
    return [product for product in products if isinstance(product, dict)]
