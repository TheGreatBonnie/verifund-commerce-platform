"""Grounded marketplace search for the orchestrator chat tool.

The registry's ``q`` filter is a substring match over seller catalog text, so
generic shopping words (``laptop``, ``programming``) return nothing. This module
fetches the aggregation once (optionally by category) and matches locally with a
small, documented demo synonym table. It never invents products: every result is
a copy of an aggregation row.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

# Demo heuristic, not a general ontology. The catalog calls the laptop a
# "MacBook Air"; "programming" is expressed through memory/SSD/CPU attributes.
TOKEN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "laptop": ("macbook", "notebook", "portable computer"),
    "notebook": ("macbook", "laptop"),
    "programming": ("memory", "ssd", "cpu", "m4", "developer"),
    "developer": ("memory", "ssd", "cpu", "m4", "programming"),
}

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)


def _tokenize(value: str | None) -> list[str]:
    if not value:
        return []
    cleaned = _PUNCTUATION.sub(" ", value.casefold())
    tokens = [token for token in cleaned.split() if len(token) > 1]
    return list(dict.fromkeys(tokens))


def _expand(token: str) -> tuple[str, ...]:
    return (token, *TOKEN_SYNONYMS.get(token, ()))


def _text_fields(product: dict) -> dict[str, str]:
    offers = product.get("offers") or []
    seller_names = [
        str(offer.get("seller_name") or "")
        for offer in offers
        if isinstance(offer, dict)
    ]
    seller_names.append(str(product.get("seller") or ""))
    return {
        "name": str(product.get("name") or "").casefold(),
        "description": str(product.get("description") or "").casefold(),
        "category": str(product.get("category") or "").casefold(),
        "seller": " ".join(seller_names).casefold(),
    }


def _contains(haystack: str, needle: str) -> bool:
    """Whole-word containment so filler words cannot match inside other words."""
    return re.search(
        rf"(?<!\w){re.escape(needle)}(?!\w)", haystack, re.UNICODE
    ) is not None


def _first_field(token: str, fields: dict[str, str]) -> str | None:
    for name in ("name", "description", "category", "seller"):
        if any(_contains(fields[name], expansion) for expansion in _expand(token)):
            return name
    return None


def _haystack(fields: dict[str, str]) -> str:
    return " ".join(fields.values())


def _offer_available(product: dict) -> bool:
    offers = product.get("offers") or []
    return any(
        isinstance(offer, dict) and offer.get("available") is True
        for offer in offers
    )


def _price(product: dict) -> int:
    value = product.get("unit_price_cents")
    return int(value) if isinstance(value, (int, float)) else 0


def _currency(product: dict) -> str:
    offers = product.get("offers") or []
    if offers and isinstance(offers[0], dict):
        return str(offers[0].get("currency") or "USD")
    return "USD"


def _seller(product: dict) -> str:
    seller = product.get("seller")
    if seller:
        return str(seller)
    offers = product.get("offers") or []
    if offers and isinstance(offers[0], dict):
        return str(offers[0].get("seller_name") or "")
    return ""


def _matches(
    product: dict,
    *,
    fields: dict[str, str],
    query_tokens: list[str],
    category: str | None,
    max_unit_price_cents: int | None,
    in_stock_only: bool,
) -> bool:
    if query_tokens:
        haystack = _haystack(fields)
        if not any(
            _contains(haystack, expansion)
            for token in query_tokens
            for expansion in _expand(token)
        ):
            return False
    if category and fields["category"] != category.casefold():
        return False
    if (
        max_unit_price_cents is not None
        and _price(product) > max_unit_price_cents
    ):
        return False
    if in_stock_only and not _offer_available(product):
        return False
    return True


def filter_and_rank_products(
    products: list[dict],
    *,
    query: str | None = None,
    category: str | None = None,
    max_unit_price_cents: int | None = None,
    in_stock_only: bool = False,
    use_case: str | None = None,
    preferences: list[str] | None = None,
) -> list[dict]:
    """Return every match, ranked. No truncation: callers shape the page."""
    query_tokens = _tokenize(query)
    use_case_tokens = _tokenize(use_case)
    preference_tokens = [
        token for value in (preferences or []) for token in _tokenize(value)
    ]
    ranked: list[tuple[int, int, str, dict]] = []

    for product in products:
        if not isinstance(product, dict):
            continue
        fields = _text_fields(product)
        if not _matches(
            product,
            fields=fields,
            query_tokens=query_tokens,
            category=category,
            max_unit_price_cents=max_unit_price_cents,
            in_stock_only=in_stock_only,
        ):
            continue

        score = 0
        rationale: list[str] = []
        for token in query_tokens:
            field = _first_field(token, fields)
            if field == "name":
                score += 4
                rationale.append(f"query:{token}:name")
            elif field in {"description", "category"}:
                score += 2
                rationale.append(f"query:{token}:{field}")

        for prefix, tokens in (
            ("use_case", use_case_tokens),
            ("preferences", preference_tokens),
        ):
            for token in tokens:
                field = _first_field(token, fields)
                if field:
                    score += 1
                    rationale.append(f"{prefix}:{token}:{field}")

        if _offer_available(product):
            score += 2
            rationale.append("offers:available")

        rating = product.get("rating")
        if isinstance(rating, (int, float)) and rating >= 4.5:
            score += 1
            rationale.append(f"rating:{rating}")

        original = product.get("original_unit_price_cents")
        if (
            isinstance(original, (int, float))
            and original > _price(product)
        ):
            score += 1
            rationale.append("price:discounted")

        copy = dict(product)
        copy["currency"] = _currency(product)
        copy["source"] = "marketmesh_registry"
        copy["seller"] = _seller(product)
        if rationale:
            copy["match_rationale"] = rationale
        ranked.append((score, _price(product), str(product.get("sku") or ""), copy))

    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
    return [row[3] for row in ranked]


def shape_search_result(
    applied_filters: dict[str, Any],
    products: list[dict],
    limit: int = 12,
) -> dict:
    """Set total_candidates to len(products), then truncate products to limit."""
    try:
        effective_limit = int(limit)
    except (TypeError, ValueError):
        effective_limit = 12
    effective_limit = max(1, min(effective_limit, 24))
    return {
        "applied_filters": dict(applied_filters),
        "total_candidates": len(products),
        "products": [dict(product) for product in products[:effective_limit]],
    }


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
        raise ValueError("marketplace aggregation did not return a product list")
    return [product for product in products if isinstance(product, dict)]
