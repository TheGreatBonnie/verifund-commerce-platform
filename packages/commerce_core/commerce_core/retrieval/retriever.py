"""Pure dense product retrieval.

The shopper's hard constraints are applied first; only the surviving products
are eligible for semantic ranking. That ordering is deliberate: retrieving a
fixed ``k`` before filtering silently drops valid cheap products.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings

from .filters import (
    currency,
    matches_filters,
    offer_available,
    price_cents,
    seller_name,
)
from .index import get_store
from .taxonomy import resolve_categories

logger = logging.getLogger(__name__)

MIN_SIMILARITY = 0.60
RELATIVE_MARGIN = 0.10
BACKEND = "InMemoryVectorStore"
MAX_TRACE_HITS = 24


@dataclass
class RetrievalResult:
    products: list[dict]
    trace: dict


def compose_query(
    query: str | None,
    use_case: str | None,
    preferences: list[str] | None,
) -> str:
    parts = [query or "", use_case or "", *(preferences or [])]
    return " ".join(part.strip() for part in parts if part and part.strip())


def _browse_key(product: dict) -> tuple[int, float, int, str]:
    rating = product.get("rating")
    rating_value = float(rating) if isinstance(rating, (int, float)) else 0.0
    return (
        0 if offer_available(product) else 1,
        -rating_value,
        price_cents(product),
        str(product.get("sku") or ""),
    )


class ProductRetriever:
    """Filters a marketplace catalog, then ranks it by embedding similarity."""

    def __init__(
        self,
        embeddings: Embeddings,
        *,
        model: str,
        dimensions: int,
        cache_key: str | None = None,
        min_similarity: float = MIN_SIMILARITY,
        relative_margin: float = RELATIVE_MARGIN,
    ) -> None:
        self._embeddings = embeddings
        self._model = model
        self._dimensions = dimensions
        self._cache_key = cache_key or f"{model}:{dimensions}"
        self._min_similarity = min_similarity
        self._relative_margin = relative_margin

    def search(
        self,
        products: Iterable[dict],
        *,
        query: str | None = None,
        use_case: str | None = None,
        preferences: list[str] | None = None,
        category: str | None = None,
        max_unit_price_cents: int | None = None,
        in_stock_only: bool = False,
    ) -> RetrievalResult:
        started = time.perf_counter()
        rows = [product for product in products if isinstance(product, dict)]
        resolved = resolve_categories(category)
        category_trace = None
        if category:
            category_trace = {
                "requested": category,
                "resolved": list(resolved) if resolved is not None else None,
            }
        candidates = [
            product
            for product in rows
            if matches_filters(
                product,
                category=None if resolved is not None else category,
                categories=resolved,
                max_unit_price_cents=max_unit_price_cents,
                in_stock_only=in_stock_only,
            )
        ]
        if not candidates:
            return self._finish(
                "dense",
                [],
                0,
                started,
                cutoff=self._min_similarity,
                category=category_trace,
            )

        text = compose_query(query, use_case, preferences)
        if not text:
            ranked = sorted(candidates, key=_browse_key)
            return self._finish(
                "browse",
                [self._decorate(product) for product in ranked],
                len(candidates),
                started,
                category=category_trace,
            )

        allowed = {str(product.get("sku") or "") for product in candidates}
        store = get_store(rows, embeddings=self._embeddings, cache_key=self._cache_key)
        vector = self._embeddings.embed_query(text)
        hits = store.similarity_search_with_score_by_vector(
            vector,
            k=len(candidates),
            filter=lambda document: str(document.metadata.get("sku") or "") in allowed,
        )

        by_sku = {str(product.get("sku") or ""): product for product in candidates}
        scored: list[tuple[float, int, str, dict]] = []
        for document, score in hits:
            sku = str(document.metadata.get("sku") or "")
            product = by_sku.get(sku)
            if product is None or score < self._min_similarity:
                continue
            scored.append((float(score), price_cents(product), sku, product))
        scored.sort(key=lambda row: (-row[0], row[1], row[2]))

        cutoff = self._min_similarity
        if scored:
            cutoff = max(self._min_similarity, scored[0][0] - self._relative_margin)
            scored = [row for row in scored if row[0] >= cutoff]

        top_k = [
            {"sku": row[2], "score": round(row[0], 4)} for row in scored[:MAX_TRACE_HITS]
        ]
        ranked_products = [self._decorate(row[3], score=row[0]) for row in scored]
        return self._finish(
            "dense",
            ranked_products,
            len(candidates),
            started,
            top_k=top_k,
            cutoff=cutoff,
            category=category_trace,
        )

    def _decorate(self, product: dict, *, score: float | None = None) -> dict:
        copy = dict(product)
        copy["currency"] = currency(product)
        copy["source"] = "marketmesh_registry"
        copy["seller"] = seller_name(product)

        rationale: list[str] = []
        if score is not None:
            rationale.append(f"semantic:{score:.2f}")
        if offer_available(product):
            rationale.append("offers:available")
        rating = product.get("rating")
        if isinstance(rating, (int, float)) and rating >= 4.5:
            rationale.append(f"rating:{rating}")
        original = product.get("original_unit_price_cents")
        if isinstance(original, (int, float)) and original > price_cents(product):
            rationale.append("price:discounted")
        if rationale:
            copy["match_rationale"] = rationale
        return copy

    def _finish(
        self,
        mode: str,
        products: list[dict],
        candidates: int,
        started: float,
        *,
        top_k: list[dict] | None = None,
        cutoff: float | None = None,
        category: dict | None = None,
    ) -> RetrievalResult:
        trace = {
            "mode": mode,
            "backend": BACKEND,
            "model": self._model,
            "dimension": self._dimensions,
            "candidates": candidates,
            "top_k": list(top_k or []),
            "cutoff": round(cutoff, 4) if cutoff is not None else None,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
        if category is not None:
            trace["category"] = category
        logger.info(
            "product_retrieval mode=%s candidates=%d returned=%d latency_ms=%d",
            mode,
            candidates,
            len(products),
            trace["latency_ms"],
        )
        return RetrievalResult(products=products, trace=trace)
