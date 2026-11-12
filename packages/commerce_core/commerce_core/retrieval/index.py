"""Catalog-hash-keyed in-memory vector index.

One store per cache key (production: ``"<model>:<dimensions>"``) is rebuilt only
when the catalog content changes. The hash includes price and availability so
metadata cannot go stale even though those fields are not embedded.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore

from .documents import product_document
from .filters import offer_available, price_cents, seller_name

_CACHE: dict[str, tuple[str, InMemoryVectorStore]] = {}


def _row(product: dict) -> str:
    return "|".join(
        (
            str(product.get("sku") or ""),
            str(product.get("name") or ""),
            str(product.get("description") or ""),
            str(product.get("category") or ""),
            seller_name(product),
            str(price_cents(product)),
            "1" if offer_available(product) else "0",
        )
    )


def catalog_hash(products: Iterable[dict]) -> str:
    rows = sorted(_row(product) for product in products if isinstance(product, dict))
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def build_store(products: Iterable[dict], *, embeddings: Embeddings) -> InMemoryVectorStore:
    documents: dict[str, Document] = {}
    for product in products:
        if not isinstance(product, dict):
            continue
        document = product_document(product)
        if document.id:
            documents.setdefault(document.id, document)

    store = InMemoryVectorStore(embeddings)
    if documents:
        store.add_documents(list(documents.values()))
    return store


def get_store(
    products: Iterable[dict],
    *,
    embeddings: Embeddings,
    cache_key: str,
) -> InMemoryVectorStore:
    rows = [product for product in products if isinstance(product, dict)]
    digest = catalog_hash(rows)
    cached = _CACHE.get(cache_key)
    if cached is not None and cached[0] == digest:
        return cached[1]

    store = build_store(rows, embeddings=embeddings)
    _CACHE[cache_key] = (digest, store)
    return store


def clear_cache(cache_key: str | None = None) -> None:
    if cache_key is None:
        _CACHE.clear()
    else:
        _CACHE.pop(cache_key, None)
