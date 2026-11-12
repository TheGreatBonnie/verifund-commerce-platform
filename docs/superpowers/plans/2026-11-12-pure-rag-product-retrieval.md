# Pure RAG Product Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the orchestrator's lexical product scorer with pure dense retrieval — Nebius `Qwen/Qwen3-Embedding-8B` embeddings stored in `InMemoryVectorStore` — so `search_marketplace_products` ranks products semantically while deterministic filters and the existing CopilotKit product cards stay unchanged.

**Architecture:** A new `commerce_core.retrieval` package owns embeddings, document construction, hard filters, a catalog-hash-keyed vector index, and a `ProductRetriever` that returns products plus a retrieval trace. `apps/orchestrator_agent/orchestrator_agent/marketplace.py` loses all lexical scoring and becomes fetch + retrieve + shape. The orchestrator tool builds one retriever from settings and surfaces `retrieval_unavailable` when embeddings cannot be produced.

**Tech Stack:** Python 3.12, `langchain-core` 1.6.13 (`InMemoryVectorStore`, `Embeddings`, `Document`), `openai` 2.54 SDK pointed at Nebius Token Factory, pytest + `pytest-asyncio`, ruff.

**Spec:** `docs/superpowers/specs/2026-11-12-pure-rag-product-retrieval-design.md`

## Global Constraints

- **Pure dense only.** No lexical scoring, no synonym table, no hybrid fusion, no LLM query rewrite, no lexical fallback. If embeddings fail, return an error — never silently degrade to substring matching.
- **Filter before rank.** Category, price ceiling, and in-stock checks run before similarity scoring. Never retrieve `k` first and filter afterwards.
- **No budget or floor leakage.** The retriever only sees marketplace product rows. Seller floor prices and buyer budgets never enter document text, metadata, rationale, or trace.
- **Inbound seller content is untrusted.** Product name/description/seller/category are embedded as data only; never interpret them as instructions.
- **No input mutation.** `ProductRetriever.search` and `marketplace.retrieve_products` must not mutate the product dicts they receive.
- **Determinism.** Equal similarity scores tie-break by `(price_cents, sku)`.
- **No network in unit tests.** Every test injects a fake `Embeddings` implementation or a stub retriever. The only network-touching artifact is the manual smoke script.
- **Cache isolation in tests.** The vector index cache is module-level. Any test that builds a real index must use a unique `cache_key` or call `clear_cache()`.
- **Line length 100, target py312.** `uv run ruff check` must pass on every touched file.
- **Do not stage unrelated dirty files.** Only stage the files named in each task.

## File Structure

- Create: `packages/commerce_core/commerce_core/retrieval/__init__.py` — public surface (`NebiusEmbeddings`, `ProductRetriever`, `RetrievalResult`, `MIN_SIMILARITY`).
- Create: `packages/commerce_core/commerce_core/retrieval/embeddings.py` — `NebiusEmbeddings` (OpenAI-compatible SDK adapter with internal batching).
- Create: `packages/commerce_core/commerce_core/retrieval/documents.py` — `product_document()`.
- Create: `packages/commerce_core/commerce_core/retrieval/filters.py` — hard filters and product field helpers.
- Create: `packages/commerce_core/commerce_core/retrieval/index.py` — `catalog_hash()`, `build_store()`, `get_store()`, `clear_cache()`.
- Create: `packages/commerce_core/commerce_core/retrieval/retriever.py` — `ProductRetriever.search()` and trace.
- Modify: `packages/commerce_core/pyproject.toml` — declare `langchain-core`, `openai`, and `numpy`.
- Modify: `apps/orchestrator_agent/orchestrator_agent/marketplace.py` — delete lexical machinery; add `retrieve_products`; extend `shape_search_result`.
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py` — build the retriever, wire the trace, surface `retrieval_unavailable`.
- Modify: `apps/orchestrator_agent/orchestrator_agent/settings.py` — `embedding_model`, `embedding_dimensions`.
- Test: `tests/unit/test_retrieval_embeddings.py` (new).
- Test: `tests/unit/test_retrieval_documents.py` (new).
- Test: `tests/unit/test_retrieval_filters.py` (new).
- Test: `tests/unit/test_retrieval_index.py` (new).
- Test: `tests/unit/test_retrieval_pure_rag.py` (new).
- Test: `tests/unit/test_orchestrator_marketplace.py` (rewrite).
- Create: `scripts/rag_smoke.py` (manual, not collected by pytest).

Execution order matters: each task leaves the suite green, so tasks 1–5 add a dormant package, task 6 switches `marketplace.py` over, and task 7 switches the agent tool over.

---

## Task 1: Embedding adapter

**Files:**
- Create: `packages/commerce_core/commerce_core/retrieval/__init__.py`
- Create: `packages/commerce_core/commerce_core/retrieval/embeddings.py`
- Modify: `packages/commerce_core/pyproject.toml`
- Test: `tests/unit/test_retrieval_embeddings.py`

**Interfaces:**
- Produces: `NebiusEmbeddings(api_key, base_url, model, dimensions=1024, batch_size=64, client=None)` implementing `langchain_core.embeddings.Embeddings`.
- Produces: `embed_documents(texts: list[str]) -> list[list[float]]`, `embed_query(text: str) -> list[float]`.
- The optional `client` is the only test seam; it must expose `client.embeddings.create(model=..., input=..., dimensions=...)` returning an object with `.data`, where each item has `.index` and `.embedding`.

- [ ] **Step 1: Declare the dependencies**

Edit `packages/commerce_core/pyproject.toml` so `dependencies` reads:

```toml
dependencies = [
  "pydantic>=2.10,<3",
  "a2a-sdk==1.2.3",
  "httpx>=0.27,<1",
  "sqlalchemy[asyncio]>=2.0,<3",
  "aiosqlite>=0.20,<1",
  "langchain-core>=1.0,<2",
  "openai>=1.100,<3",
  "numpy>=1.26,<3",
]
```

`numpy` is mandatory: `InMemoryVectorStore` delegates cosine similarity to
`langchain_core.vectorstores.utils._cosine_similarity`, which raises
`ImportError("cosine_similarity requires numpy to be installed")` without it.
This was verified against the installed environment — do not skip it.

Then run `uv sync --quiet` once from the repo root and confirm imports still resolve:

```bash
uv run python -c "import numpy, openai, langchain_core; print(openai.__version__, langchain_core.__version__)"
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_retrieval_embeddings.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from commerce_core.retrieval.embeddings import NebiusEmbeddings


@dataclass
class _Item:
    index: int
    embedding: list[float]


@dataclass
class _Response:
    data: list[_Item]


@dataclass
class _EmbeddingsApi:
    calls: list[dict] = field(default_factory=list)

    def create(self, *, model: str, input: list[str], dimensions: int) -> _Response:
        self.calls.append({"model": model, "input": list(input), "dimensions": dimensions})
        # Return deliberately out of order to prove the adapter sorts by index.
        items = [
            _Item(index=offset, embedding=[float(len(text)), float(offset)])
            for offset, text in enumerate(input)
        ]
        return _Response(data=list(reversed(items)))


@dataclass
class _Client:
    embeddings: _EmbeddingsApi


def _embeddings(*, batch_size: int = 64) -> tuple[NebiusEmbeddings, _EmbeddingsApi]:
    api = _EmbeddingsApi()
    adapter = NebiusEmbeddings(
        api_key="test-key",
        base_url="http://embed.local/v1",
        model="Qwen/Qwen3-Embedding-8B",
        dimensions=1024,
        batch_size=batch_size,
        client=_Client(embeddings=api),
    )
    return adapter, api


def test_embed_query_sends_the_configured_model_and_dimensions():
    adapter, api = _embeddings()

    vector = adapter.embed_query("a good laptop for programming")

    assert vector == [29.0, 0.0]
    assert api.calls == [
        {
            "model": "Qwen/Qwen3-Embedding-8B",
            "input": ["a good laptop for programming"],
            "dimensions": 1024,
        }
    ]


def test_embed_documents_batches_and_preserves_input_order():
    adapter, api = _embeddings(batch_size=2)

    vectors = adapter.embed_documents(["doc-a", "doc-bb", "doc-ccc", "doc-dddd", "doc-eeeee"])

    assert [vector[0] for vector in vectors] == [5.0, 6.0, 7.0, 8.0, 9.0]
    assert [len(call["input"]) for call in api.calls] == [2, 2, 1]
    assert api.calls[0]["input"] == ["doc-a", "doc-bb"]
    assert api.calls[2]["input"] == ["doc-eeeee"]


def test_embed_documents_returns_empty_for_empty_input():
    adapter, api = _embeddings()

    assert adapter.embed_documents([]) == []
    assert api.calls == []


def test_dimensions_must_be_positive():
    with pytest.raises(ValueError):
        NebiusEmbeddings(
            api_key="test-key",
            base_url="http://embed.local/v1",
            model="m",
            dimensions=0,
            client=_Client(embeddings=_EmbeddingsApi()),
        )
```

- [ ] **Step 3: Run the test to confirm it fails**

```bash
uv run pytest tests/unit/test_retrieval_embeddings.py -q
```

Expected: `ModuleNotFoundError: No module named 'commerce_core.retrieval'`.

- [ ] **Step 4: Implement the adapter**

Create `packages/commerce_core/commerce_core/retrieval/embeddings.py`:

```python
"""Nebius Token Factory embedding adapter.

The Nebius endpoint is OpenAI-compatible, so we call the `openai` SDK directly
instead of `OpenAIEmbeddings`: that keeps the request shape identical to the
documented sample and avoids tiktoken preprocessing that does not match the
Qwen tokenizer.
"""

from __future__ import annotations

from typing import Any, Sequence

from langchain_core.embeddings import Embeddings
from openai import OpenAI

DEFAULT_BATCH_SIZE = 64


class NebiusEmbeddings(Embeddings):
    """Batch-friendly `Embeddings` implementation for Nebius-hosted models."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimensions: int = 1024,
        batch_size: int = DEFAULT_BATCH_SIZE,
        client: Any | None = None,
    ) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._client = client or OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._dimensions = dimensions
        self._batch_size = batch_size

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _create(self, inputs: Sequence[str]) -> list[list[float]]:
        response = self._client.embeddings.create(
            model=self._model,
            input=list(inputs),
            dimensions=self._dimensions,
        )
        ordered = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in ordered]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            vectors.extend(self._create(texts[start : start + self._batch_size]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._create([text])[0]
```

Create `packages/commerce_core/commerce_core/retrieval/__init__.py` with only what exists at this point:

```python
from .embeddings import NebiusEmbeddings

__all__ = ["NebiusEmbeddings"]
```

- [ ] **Step 5: Run the test to confirm it passes**

```bash
uv run pytest tests/unit/test_retrieval_embeddings.py -q
uv run ruff check packages/commerce_core/commerce_core/retrieval tests/unit/test_retrieval_embeddings.py
```

Expected: 4 passed; ruff reports no issues.

- [ ] **Step 6: Commit**

```bash
git add packages/commerce_core/pyproject.toml uv.lock \
  packages/commerce_core/commerce_core/retrieval/__init__.py \
  packages/commerce_core/commerce_core/retrieval/embeddings.py \
  tests/unit/test_retrieval_embeddings.py
git commit -m "feat(retrieval): add Nebius embedding adapter"
```

`uv sync` rewrites the root `uv.lock` (numpy, langchain-core, openai). Commit that lockfile with this task so other machines resolve the same graph.

---

## Task 2: Deterministic filters

**Files:**
- Create: `packages/commerce_core/commerce_core/retrieval/filters.py`
- Test: `tests/unit/test_retrieval_filters.py`

**Interfaces:**
- Produces: `price_cents(product) -> int`, `offer_available(product) -> bool`, `currency(product) -> str`, `seller_name(product) -> str`.
- Produces: `matches_filters(product, *, category=None, max_unit_price_cents=None, in_stock_only=False) -> bool`.
- Semantics are copied from the old lexical module: category compares casefolded equality; the price ceiling excludes products above `unit_price_cents`; in-stock requires at least one offer with `available is True`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_retrieval_filters.py`:

```python
from __future__ import annotations

from commerce_core.retrieval.filters import (
    currency,
    matches_filters,
    offer_available,
    price_cents,
    seller_name,
)

PRODUCT = {
    "id": "MM-MACBOOK-AIR-M4-13",
    "sku": "MM-MACBOOK-AIR-M4-13",
    "name": "MacBook Air M4 13-inch",
    "category": "Electronics",
    "description": "Apple M4 - 16GB memory",
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
        }
    ],
}

UNAVAILABLE = {
    **PRODUCT,
    "sku": "MM-4K-MONITOR-27",
    "unit_price_cents": 32900,
    "offers": [{**PRODUCT["offers"][0], "available": False, "on_hand": 0}],
}


def test_field_helpers_read_the_marketplace_row_shape():
    assert price_cents(PRODUCT) == 99900
    assert offer_available(PRODUCT) is True
    assert offer_available(UNAVAILABLE) is False
    assert currency(PRODUCT) == "USD"
    assert seller_name(PRODUCT) == "Northwind Audio"


def test_field_helpers_fall_back_safely_for_partial_rows():
    assert price_cents({}) == 0
    assert offer_available({}) is False
    assert currency({}) == "USD"
    assert seller_name({}) == ""


def test_category_filter_is_case_insensitive():
    assert matches_filters(PRODUCT, category="electronics") is True
    assert matches_filters(PRODUCT, category="Furniture") is False


def test_price_ceiling_excludes_expensive_products():
    assert matches_filters(PRODUCT, max_unit_price_cents=99900) is True
    assert matches_filters(PRODUCT, max_unit_price_cents=99899) is False


def test_in_stock_filter_requires_an_available_offer():
    assert matches_filters(UNAVAILABLE, in_stock_only=True) is False
    assert matches_filters(UNAVAILABLE, in_stock_only=False) is True


def test_filters_combine_conjunctively():
    assert matches_filters(
        PRODUCT,
        category="Electronics",
        max_unit_price_cents=120000,
        in_stock_only=True,
    ) is True
    assert matches_filters(
        PRODUCT,
        category="Electronics",
        max_unit_price_cents=50000,
        in_stock_only=True,
    ) is False


def test_seller_column_wins_over_the_offer_row():
    assert seller_name({**PRODUCT, "seller": "CircuitForge"}) == "CircuitForge"
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run pytest tests/unit/test_retrieval_filters.py -q
```

Expected: `ModuleNotFoundError: No module named 'commerce_core.retrieval.filters'`.

- [ ] **Step 3: Implement the filters**

Create `packages/commerce_core/commerce_core/retrieval/filters.py`:

```python
"""Deterministic filters for marketplace product rows.

Rows come from the buyer agent's `/api/marketplace/products` aggregation and
carry `sku`, `category`, `unit_price_cents` (the cheapest available offer) and
an `offers` list. These checks stay deterministic so retrieval only ever ranks
products that already satisfy the shopper's hard constraints.
"""

from __future__ import annotations


def price_cents(product: dict) -> int:
    value = product.get("unit_price_cents")
    return int(value) if isinstance(value, (int, float)) else 0


def offer_available(product: dict) -> bool:
    offers = product.get("offers") or []
    return any(
        isinstance(offer, dict) and offer.get("available") is True for offer in offers
    )


def currency(product: dict) -> str:
    offers = product.get("offers") or []
    if offers and isinstance(offers[0], dict):
        return str(offers[0].get("currency") or "USD")
    return "USD"


def seller_name(product: dict) -> str:
    seller = product.get("seller")
    if seller:
        return str(seller)
    offers = product.get("offers") or []
    if offers and isinstance(offers[0], dict):
        return str(offers[0].get("seller_name") or "")
    return ""


def matches_filters(
    product: dict,
    *,
    category: str | None = None,
    max_unit_price_cents: int | None = None,
    in_stock_only: bool = False,
) -> bool:
    """Return True when the row satisfies every hard constraint."""
    if category and str(product.get("category") or "").casefold() != category.casefold():
        return False
    if (
        max_unit_price_cents is not None
        and price_cents(product) > max_unit_price_cents
    ):
        return False
    if in_stock_only and not offer_available(product):
        return False
    return True
```

Update `packages/commerce_core/commerce_core/retrieval/__init__.py`:

```python
from .embeddings import NebiusEmbeddings
from .filters import matches_filters, offer_available, price_cents, seller_name

__all__ = [
    "NebiusEmbeddings",
    "matches_filters",
    "offer_available",
    "price_cents",
    "seller_name",
]
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
uv run pytest tests/unit/test_retrieval_filters.py -q
uv run ruff check packages/commerce_core/commerce_core/retrieval tests/unit/test_retrieval_filters.py
```

Expected: 7 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/retrieval/filters.py \
  packages/commerce_core/commerce_core/retrieval/__init__.py \
  tests/unit/test_retrieval_filters.py
git commit -m "feat(retrieval): add deterministic product filters"
```

---

## Task 3: Product documents

**Files:**
- Create: `packages/commerce_core/commerce_core/retrieval/documents.py`
- Test: `tests/unit/test_retrieval_documents.py`

**Interfaces:**
- Produces: `product_document(product: dict) -> langchain_core.documents.Document`.
- Embedded text order: name, category, SKU, description, `Seller: <name>` — one per line, empty fields skipped.
- Metadata: `sku`, `name`, `category`, `price_cents`, `available`, `rating`.
- Price and availability must **not** appear in `page_content` (they change often and carry no semantic meaning).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_retrieval_documents.py`:

```python
from __future__ import annotations

from commerce_core.retrieval.documents import product_document

PRODUCT = {
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
            "seller_name": "Northwind Audio",
            "unit_price_cents": 99900,
            "currency": "USD",
            "available": True,
            "on_hand": 8,
        }
    ],
}


def test_embedded_text_contains_every_semantic_field():
    document = product_document(PRODUCT)

    assert "MacBook Air M4 13-inch" in document.page_content
    assert "Electronics" in document.page_content
    assert "MM-MACBOOK-AIR-M4-13" in document.page_content
    assert "16GB memory" in document.page_content
    assert "Seller: Northwind Audio" in document.page_content


def test_embedded_text_excludes_price_and_availability():
    document = product_document(PRODUCT).page_content.casefold()

    assert "99900" not in document
    assert "119900" not in document
    assert "price" not in document
    assert "stock" not in document
    assert "available" not in document


def test_metadata_carries_filter_and_rationale_fields():
    document = product_document(PRODUCT)

    assert document.metadata == {
        "sku": "MM-MACBOOK-AIR-M4-13",
        "name": "MacBook Air M4 13-inch",
        "category": "Electronics",
        "price_cents": 99900,
        "available": True,
        "rating": 4.6,
    }
    assert document.id == "MM-MACBOOK-AIR-M4-13"


def test_sparse_rows_do_not_produce_blank_lines():
    document = product_document({"sku": "SKU-1", "name": "Widget"})

    assert document.page_content == "Widget\nSKU-1"
    assert document.metadata["available"] is False
    assert document.metadata["price_cents"] == 0


def test_documents_are_deterministic():
    assert product_document(PRODUCT).page_content == product_document(PRODUCT).page_content
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run pytest tests/unit/test_retrieval_documents.py -q
```

Expected: `ModuleNotFoundError: No module named 'commerce_core.retrieval.documents'`.

- [ ] **Step 3: Implement the documents**

Create `packages/commerce_core/commerce_core/retrieval/documents.py`:

```python
"""Turn marketplace product rows into embeddable documents."""

from __future__ import annotations

from langchain_core.documents import Document

from .filters import offer_available, price_cents, seller_name


def product_document(product: dict) -> Document:
    sku = str(product.get("sku") or "")
    name = str(product.get("name") or "")
    category = str(product.get("category") or "")
    description = str(product.get("description") or "")
    seller = seller_name(product)

    lines = [value for value in (name, category, sku, description) if value]
    if seller:
        lines.append(f"Seller: {seller}")

    rating = product.get("rating")
    metadata = {
        "sku": sku,
        "name": name,
        "category": category,
        "price_cents": price_cents(product),
        "available": offer_available(product),
        "rating": rating if isinstance(rating, (int, float)) else None,
    }
    return Document(id=sku or None, page_content="\n".join(lines), metadata=metadata)
```

Update `packages/commerce_core/commerce_core/retrieval/__init__.py`:

```python
from .documents import product_document
from .embeddings import NebiusEmbeddings
from .filters import matches_filters, offer_available, price_cents, seller_name

__all__ = [
    "NebiusEmbeddings",
    "matches_filters",
    "offer_available",
    "price_cents",
    "product_document",
    "seller_name",
]
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
uv run pytest tests/unit/test_retrieval_documents.py -q
uv run ruff check packages/commerce_core/commerce_core/retrieval tests/unit/test_retrieval_documents.py
```

Expected: 5 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/retrieval/documents.py \
  packages/commerce_core/commerce_core/retrieval/__init__.py \
  tests/unit/test_retrieval_documents.py
git commit -m "feat(retrieval): build embeddable product documents"
```

---

## Task 4: Catalog-hash vector index

**Files:**
- Create: `packages/commerce_core/commerce_core/retrieval/index.py`
- Test: `tests/unit/test_retrieval_index.py`

**Interfaces:**
- Produces: `catalog_hash(products) -> str` (sha256 over sorted `sku|name|description|category|seller|price_cents|available`).
- Produces: `build_store(products, *, embeddings) -> InMemoryVectorStore` (deduplicates by SKU, preserves first occurrence).
- Produces: `get_store(products, *, embeddings, cache_key)` — returns the cached store when the catalog hash is unchanged.
- Produces: `clear_cache(cache_key=None)`.
- The module-level `_CACHE: dict[str, tuple[str, InMemoryVectorStore]]` is keyed by the caller's `cache_key` (production uses `f"{model}:{dimensions}"`; tests use unique strings).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_retrieval_index.py`:

```python
from __future__ import annotations

import pytest
from langchain_core.embeddings import Embeddings

from commerce_core.retrieval.index import build_store, catalog_hash, clear_cache, get_store


class CountingEmbeddings(Embeddings):
    def __init__(self) -> None:
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls.append(list(texts))
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return [1.0, 0.0]


def product(sku: str, *, name: str = "Widget", price: int = 1000) -> dict:
    return {
        "id": sku,
        "sku": sku,
        "name": name,
        "category": "Tools",
        "description": "A useful widget",
        "unit_price_cents": price,
        "rating": 4.2,
        "offers": [
            {
                "seller_name": "Seller",
                "unit_price_cents": price,
                "currency": "USD",
                "available": True,
            }
        ],
    }


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    clear_cache()
    yield
    clear_cache()


def test_store_is_built_once_and_reused():
    embeddings = CountingEmbeddings()
    catalog = [product("A"), product("B")]

    first = get_store(catalog, embeddings=embeddings, cache_key="reuse")
    second = get_store(catalog, embeddings=embeddings, cache_key="reuse")

    assert first is second
    assert [len(call) for call in embeddings.document_calls] == [2]


def test_metadata_change_rebuilds_the_store():
    embeddings = CountingEmbeddings()

    get_store([product("A", price=1000)], embeddings=embeddings, cache_key="rebuild")
    get_store([product("A", price=2000)], embeddings=embeddings, cache_key="rebuild")

    assert [len(call) for call in embeddings.document_calls] == [1, 1]


def test_cache_keys_are_isolated():
    embeddings = CountingEmbeddings()
    catalog = [product("A")]

    get_store(catalog, embeddings=embeddings, cache_key="model:1024")
    get_store(catalog, embeddings=embeddings, cache_key="model:512")

    assert len(embeddings.document_calls) == 2


def test_catalog_hash_ignores_input_order_and_detects_price_changes():
    first = product("A")
    second = product("B")

    assert catalog_hash([first, second]) == catalog_hash([second, first])
    assert catalog_hash([first]) != catalog_hash([{**first, "unit_price_cents": 1}])


def test_catalog_hash_tracks_availability():
    available = product("A")
    unavailable = {
        **available,
        "offers": [{**available["offers"][0], "available": False}],
    }

    assert catalog_hash([available]) != catalog_hash([unavailable])


def test_duplicate_skus_are_embedded_once():
    embeddings = CountingEmbeddings()
    catalog = [product("A"), product("A", name="Duplicate row")]

    build_store(catalog, embeddings=embeddings)

    assert [len(call) for call in embeddings.document_calls] == [1]


def test_get_store_accepts_a_generator():
    embeddings = CountingEmbeddings()

    get_store((row for row in [product("A"), product("B")]), embeddings=embeddings, cache_key="gen")

    assert [len(call) for call in embeddings.document_calls] == [2]


def test_clear_cache_can_drop_a_single_key():
    embeddings = CountingEmbeddings()

    get_store([product("A")], embeddings=embeddings, cache_key="one")
    get_store([product("B")], embeddings=embeddings, cache_key="two")
    clear_cache("one")
    get_store([product("A")], embeddings=embeddings, cache_key="one")

    assert len(embeddings.document_calls) == 3
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run pytest tests/unit/test_retrieval_index.py -q
```

Expected: `ModuleNotFoundError: No module named 'commerce_core.retrieval.index'`.

- [ ] **Step 3: Implement the index**

Create `packages/commerce_core/commerce_core/retrieval/index.py`:

```python
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
    rows = sorted(
        _row(product) for product in products if isinstance(product, dict)
    )
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
```

Update `packages/commerce_core/commerce_core/retrieval/__init__.py`:

```python
from .documents import product_document
from .embeddings import NebiusEmbeddings
from .filters import matches_filters, offer_available, price_cents, seller_name
from .index import build_store, catalog_hash, clear_cache, get_store

__all__ = [
    "NebiusEmbeddings",
    "build_store",
    "catalog_hash",
    "clear_cache",
    "get_store",
    "matches_filters",
    "offer_available",
    "price_cents",
    "product_document",
    "seller_name",
]
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
uv run pytest tests/unit/test_retrieval_index.py -q
uv run ruff check packages/commerce_core/commerce_core/retrieval tests/unit/test_retrieval_index.py
```

Expected: 8 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/retrieval/index.py \
  packages/commerce_core/commerce_core/retrieval/__init__.py \
  tests/unit/test_retrieval_index.py
git commit -m "feat(retrieval): add catalog-hash vector index"
```

---

## Task 5: Pure dense retriever

**Files:**
- Create: `packages/commerce_core/commerce_core/retrieval/retriever.py`
- Test: `tests/unit/test_retrieval_pure_rag.py`

**Interfaces:**
- Produces: `MIN_SIMILARITY = 0.25`, `compose_query(query, use_case, preferences) -> str`.
- Produces: `RetrievalResult(products: list[dict], trace: dict)`.
- Produces: `ProductRetriever(embeddings, *, model, dimensions, cache_key=None, min_similarity=MIN_SIMILARITY)`.
- Produces: `ProductRetriever.search(products, *, query=None, use_case=None, preferences=None, category=None, max_unit_price_cents=None, in_stock_only=False) -> RetrievalResult`.
- The query embedding is computed by the retriever (`embed_query`) and passed to `similarity_search_with_score_by_vector`, so a cached store never holds a stale client.
- Trace shape: `{mode, backend, model, dimension, candidates, top_k, latency_ms}`; `top_k` entries are `{"sku": str, "score": float}` capped at 24.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_retrieval_pure_rag.py`:

```python
from __future__ import annotations

import uuid
from copy import deepcopy

import pytest
from langchain_core.embeddings import Embeddings

from commerce_core.retrieval.documents import product_document
from commerce_core.retrieval.index import clear_cache
from commerce_core.retrieval.retriever import (
    MIN_SIMILARITY,
    ProductRetriever,
    compose_query,
)


class MappingEmbeddings(Embeddings):
    """Deterministic embedder: returns the vectors the test declares."""

    def __init__(self, *, query_vectors: dict, document_vectors: dict) -> None:
        self.query_vectors = query_vectors
        self.document_vectors = document_vectors
        self.queries: list[str] = []
        self.document_calls: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls.append(list(texts))
        return [self.document_vectors[text] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return self.query_vectors[text]


def product(
    sku: str,
    name: str,
    description: str = "",
    *,
    category: str = "Electronics",
    price: int = 100000,
    rating: float = 4.5,
    available: bool = True,
    original: int | None = None,
) -> dict:
    return {
        "id": sku,
        "sku": sku,
        "name": name,
        "category": category,
        "description": description,
        "unit_price_cents": price,
        "original_unit_price_cents": original,
        "rating": rating,
        "offers": [
            {
                "seller_id": "seller-1",
                "seller_name": "Northwind Audio",
                "unit_price_cents": price,
                "currency": "USD",
                "available": available,
                "on_hand": 5 if available else 0,
                "incoming": 0,
            }
        ],
    }


LAPTOP = product(
    "NW-LAPTOP-01",
    "MacBook Air M4 13-inch",
    "16GB memory - 256GB SSD",
    price=99900,
    rating=4.6,
    original=119900,
)
WORKSTATION = product(
    "NW-WORKSTATION-01",
    "Precision Developer Workstation",
    "64GB memory - 1TB SSD",
    price=189900,
    rating=4.8,
)
MONITOR = product("NW-MONITOR-01", "4K Monitor 27-inch", "IPS panel", price=32900, rating=4.7)
CHAIR = product(
    "NW-CHAIR-01",
    "Ergonomic Mesh Chair",
    "Adjustable lumbar support",
    category="Ergonomic Chair",
    price=45900,
    rating=4.4,
)

CATALOG = [LAPTOP, WORKSTATION, MONITOR, CHAIR]

SEMANTIC_VECTORS = {
    "NW-LAPTOP-01": [1.0, 0.0],
    "NW-WORKSTATION-01": [0.95, 0.31],
    "NW-MONITOR-01": [0.1, 0.995],
    "NW-CHAIR-01": [0.05, 0.999],
}


def vector_map(catalog: list[dict], mapping: dict[str, list[float]]) -> dict[str, list[float]]:
    return {product_document(row).page_content: mapping[row["sku"]] for row in catalog}


def make_retriever(
    *,
    catalog: list[dict],
    mapping: dict[str, list[float]],
    query_vectors: dict[str, list[float]],
) -> tuple[ProductRetriever, MappingEmbeddings]:
    embeddings = MappingEmbeddings(
        query_vectors=query_vectors,
        document_vectors=vector_map(catalog, mapping),
    )
    retriever = ProductRetriever(
        embeddings,
        model="Qwen/Qwen3-Embedding-8B",
        dimensions=2,
        cache_key=uuid.uuid4().hex,
    )
    return retriever, embeddings


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    clear_cache()
    yield
    clear_cache()


def test_compose_query_joins_query_use_case_and_preferences():
    assert compose_query("laptop", "programming", ["quiet", "lightweight"]) == (
        "laptop programming quiet lightweight"
    )
    assert compose_query(None, None, []) == ""
    assert compose_query("  ", "", ["  "]) == ""


def test_ranks_semantically_and_drops_distant_products():
    retriever, _ = make_retriever(
        catalog=CATALOG,
        mapping=SEMANTIC_VECTORS,
        query_vectors={"good laptop for programming": [1.0, 0.0]},
    )

    result = retriever.search(CATALOG, query="good laptop for programming")

    assert [row["sku"] for row in result.products] == [
        "NW-LAPTOP-01",
        "NW-WORKSTATION-01",
    ]
    assert result.trace["mode"] == "dense"
    assert result.trace["candidates"] == 4
    assert [hit["sku"] for hit in result.trace["top_k"]] == [
        "NW-LAPTOP-01",
        "NW-WORKSTATION-01",
    ]


def test_price_ceiling_is_applied_before_ranking():
    retriever, _ = make_retriever(
        catalog=CATALOG,
        mapping=SEMANTIC_VECTORS,
        query_vectors={"good laptop for programming": [1.0, 0.0]},
    )

    result = retriever.search(
        CATALOG, query="good laptop for programming", max_unit_price_cents=100000
    )

    assert [row["sku"] for row in result.products] == ["NW-LAPTOP-01"]
    assert result.trace["candidates"] == 1


def test_in_stock_filter_excludes_unavailable_products():
    catalog = [{**LAPTOP, "offers": [{**LAPTOP["offers"][0], "available": False}]}, WORKSTATION]
    retriever, _ = make_retriever(
        catalog=catalog,
        mapping={"NW-LAPTOP-01": [1.0, 0.0], "NW-WORKSTATION-01": [0.95, 0.31]},
        query_vectors={"good laptop for programming": [1.0, 0.0]},
    )

    result = retriever.search(
        catalog, query="good laptop for programming", in_stock_only=True
    )

    assert [row["sku"] for row in result.products] == ["NW-WORKSTATION-01"]


def test_match_rationale_starts_with_the_semantic_score():
    retriever, _ = make_retriever(
        catalog=[LAPTOP],
        mapping=SEMANTIC_VECTORS,
        query_vectors={"good laptop for programming": [1.0, 0.0]},
    )

    result = retriever.search([LAPTOP], query="good laptop for programming")

    assert result.products[0]["match_rationale"] == [
        "semantic:1.00",
        "offers:available",
        "rating:4.6",
        "price:discounted",
    ]


def test_unrelated_queries_return_nothing_above_the_threshold():
    retriever, embeddings = make_retriever(
        catalog=CATALOG,
        mapping={sku: [1.0, 0.0] for sku in SEMANTIC_VECTORS},
        query_vectors={"zzzzzz": [0.0, 1.0]},
    )

    result = retriever.search(CATALOG, query="zzzzzz")

    assert result.products == []
    assert result.trace["mode"] == "dense"
    assert result.trace["top_k"] == []
    assert embeddings.query_vectors["zzzzzz"] == [0.0, 1.0]
    assert MIN_SIMILARITY == 0.25


def test_browse_mode_skips_embeddings_and_orders_by_availability_then_rating():
    catalog = [LAPTOP, WORKSTATION, MONITOR, {**CHAIR, "offers": []}]
    retriever, embeddings = make_retriever(
        catalog=catalog,
        mapping={
            "NW-LAPTOP-01": [1.0, 0.0],
            "NW-WORKSTATION-01": [0.95, 0.31],
            "NW-MONITOR-01": [0.1, 0.995],
            "NW-CHAIR-01": [0.05, 0.999],
        },
        query_vectors={},
    )

    result = retriever.search(catalog)

    assert [row["sku"] for row in result.products] == [
        "NW-WORKSTATION-01",
        "NW-MONITOR-01",
        "NW-LAPTOP-01",
        "NW-CHAIR-01",
    ]
    assert result.trace["mode"] == "browse"
    assert result.trace["top_k"] == []
    assert embeddings.queries == []
    assert embeddings.document_calls == []


def test_use_case_and_preferences_are_composed_into_the_query():
    retriever, embeddings = make_retriever(
        catalog=[LAPTOP],
        mapping=SEMANTIC_VECTORS,
        query_vectors={"laptop programming quiet": [1.0, 0.0]},
    )

    retriever.search([LAPTOP], query="laptop", use_case="programming", preferences=["quiet", "  "])

    assert embeddings.queries == ["laptop programming quiet"]


def test_equal_scores_tie_break_by_price_then_sku():
    cheap = product("C-3", "Widget C", price=100)
    first = product("A-1", "Widget A", price=100)
    expensive = product("B-2", "Widget B", price=200)
    catalog = [expensive, cheap, first]
    retriever, _ = make_retriever(
        catalog=catalog,
        mapping={"A-1": [0.9, 0.435], "B-2": [0.9, 0.435], "C-3": [0.9, 0.435]},
        query_vectors={"widget": [1.0, 0.0]},
    )

    result = retriever.search(catalog, query="widget")

    assert [row["sku"] for row in result.products] == ["A-1", "C-3", "B-2"]


def test_results_are_copies_and_inputs_are_not_mutated():
    retriever, _ = make_retriever(
        catalog=CATALOG,
        mapping=SEMANTIC_VECTORS,
        query_vectors={"good laptop for programming": [1.0, 0.0]},
    )
    before = deepcopy(CATALOG)

    result = retriever.search(CATALOG, query="good laptop for programming")

    assert CATALOG == before
    assert result.products[0] is not LAPTOP
    assert result.products[0]["source"] == "marketmesh_registry"
    assert result.products[0]["currency"] == "USD"
    assert result.products[0]["seller"] == "Northwind Audio"


def test_empty_candidates_short_circuit_without_embedding():
    retriever, embeddings = make_retriever(
        catalog=CATALOG,
        mapping=SEMANTIC_VECTORS,
        query_vectors={},
    )

    result = retriever.search(CATALOG, query="anything", max_unit_price_cents=1)

    assert result.products == []
    assert result.trace["candidates"] == 0
    assert embeddings.document_calls == []
    assert embeddings.queries == []


def test_trace_reports_backend_model_and_dimension():
    retriever, _ = make_retriever(
        catalog=[LAPTOP],
        mapping=SEMANTIC_VECTORS,
        query_vectors={"laptop": [1.0, 0.0]},
    )

    trace = retriever.search([LAPTOP], query="laptop").trace

    assert trace["backend"] == "InMemoryVectorStore"
    assert trace["model"] == "Qwen/Qwen3-Embedding-8B"
    assert trace["dimension"] == 2
    assert isinstance(trace["latency_ms"], int)
    assert trace["latency_ms"] >= 0
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run pytest tests/unit/test_retrieval_pure_rag.py -q
```

Expected: `ModuleNotFoundError: No module named 'commerce_core.retrieval.retriever'`.

- [ ] **Step 3: Implement the retriever**

Create `packages/commerce_core/commerce_core/retrieval/retriever.py`:

```python
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

logger = logging.getLogger(__name__)

MIN_SIMILARITY = 0.25
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
    ) -> None:
        self._embeddings = embeddings
        self._model = model
        self._dimensions = dimensions
        self._cache_key = cache_key or f"{model}:{dimensions}"
        self._min_similarity = min_similarity

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
        candidates = [
            product
            for product in rows
            if matches_filters(
                product,
                category=category,
                max_unit_price_cents=max_unit_price_cents,
                in_stock_only=in_stock_only,
            )
        ]
        if not candidates:
            return self._finish("dense", [], 0, started)

        text = compose_query(query, use_case, preferences)
        if not text:
            ranked = sorted(candidates, key=_browse_key)
            return self._finish(
                "browse",
                [self._decorate(product) for product in ranked],
                len(candidates),
                started,
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

        top_k = [
            {"sku": row[2], "score": round(row[0], 4)}
            for row in scored[:MAX_TRACE_HITS]
        ]
        ranked_products = [self._decorate(row[3], score=row[0]) for row in scored]
        return self._finish(
            "dense",
            ranked_products,
            len(candidates),
            started,
            top_k=top_k,
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
    ) -> RetrievalResult:
        trace = {
            "mode": mode,
            "backend": BACKEND,
            "model": self._model,
            "dimension": self._dimensions,
            "candidates": candidates,
            "top_k": list(top_k or []),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
        logger.info(
            "product_retrieval mode=%s candidates=%d returned=%d latency_ms=%d",
            mode,
            candidates,
            len(products),
            trace["latency_ms"],
        )
        return RetrievalResult(products=products, trace=trace)
```

The list comprehension `[... for row in scored for product in [row[3]]]` is clever but ugly. Use a plain loop instead:

```python
        ranked_products = [
            self._decorate(row[3], score=row[0]) for row in scored
        ]
        return self._finish("dense", ranked_products, len(candidates), started, top_k=top_k)
```

Update `packages/commerce_core/commerce_core/retrieval/__init__.py`:

```python
from .documents import product_document
from .embeddings import NebiusEmbeddings
from .filters import matches_filters, offer_available, price_cents, seller_name
from .index import build_store, catalog_hash, clear_cache, get_store
from .retriever import (
    MIN_SIMILARITY,
    ProductRetriever,
    RetrievalResult,
    compose_query,
)

__all__ = [
    "MIN_SIMILARITY",
    "NebiusEmbeddings",
    "ProductRetriever",
    "RetrievalResult",
    "build_store",
    "catalog_hash",
    "clear_cache",
    "compose_query",
    "get_store",
    "matches_filters",
    "offer_available",
    "price_cents",
    "product_document",
    "seller_name",
]
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
uv run pytest tests/unit/test_retrieval_pure_rag.py -q
uv run ruff check packages/commerce_core/commerce_core/retrieval tests/unit/test_retrieval_pure_rag.py
```

Expected: 12 passed; ruff clean.

The cosine scores for the fixture vectors were verified against the installed
`InMemoryVectorStore` + numpy: `[1.0, 0.9507, 0.1, 0.05]` for the four catalog
rows, and a filtered call returned only the filtered documents (proving the
`filter=` callable runs before ranking). If an assertion fails, print
`result.trace["top_k"]` and compare against those numbers.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/retrieval/retriever.py \
  packages/commerce_core/commerce_core/retrieval/__init__.py \
  tests/unit/test_retrieval_pure_rag.py
git commit -m "feat(retrieval): add pure dense product retriever"
```

---

## Task 6: Orchestrator cutover

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/marketplace.py`
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py`
- Modify: `apps/orchestrator_agent/orchestrator_agent/settings.py`
- Test: `tests/unit/test_orchestrator_marketplace.py` (full rewrite)

This task is deliberately atomic: the new tests, the marketplace rewrite, the agent wiring, and the settings land in one commit, because the tool tests cannot pass against a half-switched orchestrator.

**Interfaces:**
- Removes: `TOKEN_SYNONYMS`, `_tokenize`, `_expand`, `_text_fields`, `_contains`, `_first_field`, `_haystack`, `_matches`, `_price`, `_currency`, `_seller`, `_offer_available`, `filter_and_rank_products`.
- Produces: `retrieve_products(products, *, retriever, query=None, category=None, max_unit_price_cents=None, in_stock_only=False, use_case=None, preferences=None) -> tuple[list[dict], dict]`.
- Produces: `shape_search_result(applied_filters, products, limit=12, retrieval=None) -> dict`.
- Produces: `Settings.embedding_model` (default `Qwen/Qwen3-Embedding-8B`) and `Settings.embedding_dimensions` (default `1024`).
- Produces: `_build_marketplace_search_tool(settings, *, retriever=None) -> FunctionTool`; omitting `retriever` builds a real `ProductRetriever` only when `nebius_api_key` is set.
- Unchanged: `fetch_marketplace_products(...)`.

- [ ] **Step 1: Rewrite the test file**

Replace `tests/unit/test_orchestrator_marketplace.py` with:

```python
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
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run pytest tests/unit/test_orchestrator_marketplace.py -q
```

Expected: import error — `retrieve_products` does not exist, and `filter_and_rank_products` tests no longer match.

- [ ] **Step 3: Replace `marketplace.py`, wire the agent, and add settings**

Write `apps/orchestrator_agent/orchestrator_agent/marketplace.py` as:

```python
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
```

> `shape_search_result` copies only the top-level dict. `retrieval["top_k"]` is shared with the caller's trace. That is intentional and matches the previous `applied_filters` behavior; no request-scoped mutation happens after shaping.

Add to `apps/orchestrator_agent/orchestrator_agent/settings.py`, directly after `nebius_model`:

```python
    embedding_model: str = Field(
        default="Qwen/Qwen3-Embedding-8B",
        validation_alias=AliasChoices("NEBIUS_EMBEDDING_MODEL", "EMBEDDING_MODEL"),
    )
    embedding_dimensions: int = Field(
        default=1024,
        validation_alias=AliasChoices("EMBEDDING_DIMENSIONS"),
    )
```

Add to `apps/orchestrator_agent/orchestrator_agent/agent.py` imports, directly after `from ag_ui_adk import AGUIToolset` (same third-party block, alphabetical before `google.adk`):

```python
from commerce_core.retrieval import NebiusEmbeddings, ProductRetriever
```

Replace the whole `_build_marketplace_search_tool` function with:

```python
def _build_marketplace_search_tool(
    settings: Settings,
    *,
    retriever: ProductRetriever | None = None,
) -> FunctionTool:
    if retriever is None and settings.nebius_api_key:
        retriever = ProductRetriever(
            NebiusEmbeddings(
                api_key=settings.nebius_api_key,
                base_url=settings.nebius_base_url,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
            ),
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )

    async def search_marketplace_products(
        # ADK's automatic function parser does not understand PEP 604 unions.
        query: Optional[str] = None,  # noqa: UP045
        category: Optional[str] = None,  # noqa: UP045
        max_unit_price_cents: Optional[int] = None,  # noqa: UP045
        in_stock_only: bool = False,
        use_case: Optional[str] = None,  # noqa: UP045
        preferences: Optional[list[str]] = None,  # noqa: UP045
        limit: int = 12,
    ) -> dict:
        """Find products from MarketMesh sellers for a grounded purchase search."""
        if retriever is None:
            return {
                "error": "retrieval_unavailable",
                "message": "Product search is temporarily unavailable",
            }
        try:
            products = await marketplace.fetch_marketplace_products(
                base_url=settings.buyer_internal_url,
                internal_token=settings.buyer_internal_token,
                timeout=settings.buyer_internal_timeout_seconds,
                category=category or None,
            )
        except Exception:
            logger.exception("marketplace catalog fetch failed")
            return {
                "error": "marketplace_unavailable",
                "message": "Marketplace catalog is unavailable",
            }

        ceiling: int | None
        try:
            ceiling = (
                int(max_unit_price_cents)
                if max_unit_price_cents is not None
                else None
            )
        except (TypeError, ValueError):
            ceiling = None
        try:
            effective_limit = int(limit)
        except (TypeError, ValueError):
            effective_limit = 12
        effective_limit = max(1, min(effective_limit, 24))

        try:
            ranked, trace = marketplace.retrieve_products(
                products,
                retriever=retriever,
                query=query,
                category=category,
                max_unit_price_cents=ceiling,
                in_stock_only=bool(in_stock_only),
                use_case=use_case,
                preferences=preferences,
            )
        except Exception:
            logger.exception("product retrieval failed")
            return {
                "error": "retrieval_unavailable",
                "message": "Product search is temporarily unavailable",
            }

        return marketplace.shape_search_result(
            {
                "query": query,
                "category": category,
                "max_unit_price_cents": ceiling,
                "in_stock_only": bool(in_stock_only),
                "use_case": use_case,
                "preferences": preferences or [],
                "limit": effective_limit,
            },
            ranked,
            effective_limit,
            retrieval=trace,
        )

    return FunctionTool(search_marketplace_products)
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
uv run pytest tests/unit/test_orchestrator_marketplace.py -q
uv run ruff check apps/orchestrator_agent/orchestrator_agent/marketplace.py \
  tests/unit/test_orchestrator_marketplace.py
```

Expected: 14 passed. The full retrieval package suite must still be green:

```bash
uv run pytest tests/unit/test_retrieval_embeddings.py tests/unit/test_retrieval_filters.py \
  tests/unit/test_retrieval_documents.py tests/unit/test_retrieval_index.py \
  tests/unit/test_retrieval_pure_rag.py tests/unit/test_orchestrator_marketplace.py -q
uv run ruff check apps/orchestrator_agent/orchestrator_agent/marketplace.py \
  apps/orchestrator_agent/orchestrator_agent/agent.py \
  apps/orchestrator_agent/orchestrator_agent/settings.py \
  tests/unit/test_orchestrator_marketplace.py
```

Expected: 50 passed (4 + 7 + 5 + 8 + 12 + 14); ruff clean.

- [ ] **Step 5: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/marketplace.py \
  apps/orchestrator_agent/orchestrator_agent/agent.py \
  apps/orchestrator_agent/orchestrator_agent/settings.py \
  tests/unit/test_orchestrator_marketplace.py
git commit -m "refactor(orchestrator): replace lexical ranking with dense retrieval"
```

---

## Task 7: Manual smoke script

**Files:**
- Create: `scripts/rag_smoke.py`

This script is not collected by pytest (`scripts/` is outside test paths) and is the only place that talks to the real Nebius endpoint.

**Interfaces:**
- `build_catalog() -> list[dict]` reads every `docs/templates/*.yaml` through `commerce_core.pricing.load_policy` and emits marketplace-shaped rows.
- `main()` runs three queries with the real embedding model and prints SKUs, prices, semantic reasons, and traces.

- [ ] **Step 1: Write the script**

Create `scripts/rag_smoke.py`:

```python
"""Manual pure-RAG smoke run against the seeded seller templates.

Usage:
    NEBIUS_API_KEY=... uv run python scripts/rag_smoke.py

Requires network access to the Nebius Token Factory embeddings endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path

from commerce_core.pricing import load_policy
from commerce_core.retrieval import NebiusEmbeddings, ProductRetriever

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "docs" / "templates"

MODEL = os.environ.get("NEBIUS_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")
DIMENSIONS = 1024

QUERIES: list[dict] = [
    {"query": "good laptop for programming under $1500", "max_unit_price_cents": 150000},
    {"query": "noise cancelling headphones for travel"},
    {"query": "standing desk for a small home office", "category": "Standing Desk"},
]


def build_catalog() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(TEMPLATES.glob("*.yaml")):
        policy = load_policy(path)
        for item in policy.catalog:
            price = (
                item.initial_unit_price_cents
                or item.list_unit_price_cents
                or policy.list_unit_price_cents
            )
            rows.append(
                {
                    "id": item.sku,
                    "sku": item.sku,
                    "name": item.name,
                    "category": item.category,
                    "description": item.description,
                    "rating": item.rating,
                    "original_unit_price_cents": item.original_unit_price_cents,
                    "unit_price_cents": price,
                    "offers": [
                        {
                            "seller_id": policy.seller_id,
                            "seller_name": policy.name,
                            "unit_price_cents": price,
                            "currency": "USD",
                            "available": bool(item.stock_on_hand),
                            "on_hand": item.stock_on_hand or 0,
                            "incoming": item.incoming_stock or 0,
                        }
                    ],
                }
            )
    return rows


def main() -> None:
    api_key = os.environ.get("NEBIUS_API_KEY")
    if not api_key:
        raise SystemExit("NEBIUS_API_KEY is required for the smoke run")

    catalog = build_catalog()
    retriever = ProductRetriever(
        NebiusEmbeddings(
            api_key=api_key,
            base_url=os.environ.get(
                "NEBIUS_BASE_URL",
                "https://api.tokenfactory.us-central1.nebius.com/v1/",
            ),
            model=MODEL,
            dimensions=DIMENSIONS,
        ),
        model=MODEL,
        dimensions=DIMENSIONS,
    )

    print(f"catalog: {len(catalog)} products")
    for spec in QUERIES:
        result = retriever.search(catalog, **spec)
        print(f"\nquery: {spec}")
        print(f"trace: {result.trace}")
        for product in result.products[:10]:
            reason = (product.get("match_rationale") or ["-"])[0]
            print(
                f"  {product['sku']:<24} "
                f"{product['unit_price_cents']:>8}c  {reason:<16} {product['name']}"
            )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports without a key**

```bash
uv run python -c "import runpy; runpy.run_path('scripts/rag_smoke.py', run_name='not_main')"
uv run ruff check scripts/rag_smoke.py
```

Expected: no output; ruff clean.

- [ ] **Step 3: Run the live smoke test when a key is available**

```bash
set -a; source .env; set +a
uv run python scripts/rag_smoke.py
```

Expected shape (scores vary):

```
catalog: 180 products

query: {'query': 'good laptop for programming under $1500', 'max_unit_price_cents': 150000}
trace: {'mode': 'dense', ..., 'candidates': 71, 'latency_ms': 850}
  NW-LAPTOP-01  99900c  semantic:0.71  MacBook Air M4 13-inch
  ...
```

The price-ceiling query must never print a product above `150000c`. If the first query returns no laptops, lower `MIN_SIMILARITY` in `retriever.py` to `0.15` and re-run; record the observed score distribution in the commit message.

- [ ] **Step 4: Commit**

```bash
git add scripts/rag_smoke.py
git commit -m "test(retrieval): add live pure-RAG smoke script"
```

---

## Task 8: Final verification

- [ ] **Step 1: Prove the lexical path is gone**

```bash
grep -rn "TOKEN_SYNONYMS\|filter_and_rank_products\|_tokenize\|_expand" \
  apps/orchestrator_agent packages/commerce_core || true
```

Expected: no matches. Any match is a leftover.

```bash
grep -rn "semantic:" apps/console/features/chat/product-cards.tsx
```

Expected: no match — the card already renders whatever strings are in `match_rationale`, so no frontend change is needed. Open the file and confirm `match_rationale` is mapped to list items.

- [ ] **Step 2: Run the focused suites**

```bash
uv run pytest tests/unit/test_retrieval_embeddings.py tests/unit/test_retrieval_filters.py \
  tests/unit/test_retrieval_documents.py tests/unit/test_retrieval_index.py \
  tests/unit/test_retrieval_pure_rag.py tests/unit/test_orchestrator_marketplace.py -q
```

Expected: 50 passed.

- [ ] **Step 3: Run adjacent suites that import the orchestrator**

```bash
uv run pytest tests/unit -q -k "orchestrator or negotiation or retrieval"
```

Expected: all pass. If an unrelated pre-existing failure appears (the repo has known verifund/tenancy integration red tests), confirm it fails identically on `git stash` and record that in the PR notes — do not fix it here.

- [ ] **Step 4: Lint everything touched**

```bash
uv run ruff check packages/commerce_core/commerce_core/retrieval \
  apps/orchestrator_agent/orchestrator_agent/marketplace.py \
  apps/orchestrator_agent/orchestrator_agent/agent.py \
  apps/orchestrator_agent/orchestrator_agent/settings.py \
  scripts/rag_smoke.py \
  tests/unit/test_retrieval_embeddings.py tests/unit/test_retrieval_filters.py \
  tests/unit/test_retrieval_documents.py tests/unit/test_retrieval_index.py \
  tests/unit/test_retrieval_pure_rag.py tests/unit/test_orchestrator_marketplace.py
```

Expected: `All checks passed!`

- [ ] **Step 5: Refresh the knowledge graph**

```bash
graphify update .
```

Expected: incremental update completes. If `graphify` is unavailable, note it and continue.

- [ ] **Step 6: Review the final diff**

```bash
git status --short
git log --oneline -6
```

Confirm the five commits exist and that the pre-existing dirty files (`apps/buyer_agent/buyer_agent/settlement_flow.py`, the verifund control-plane files, the verifund tests, `.scratchpad/fix-offer-expiry-plan.md`) are still **unstaged**.

---

## Self-Review

**Spec coverage**

| Spec section | Where implemented |
|---|---|
| 3.1 Failure mode returns `retrieval_unavailable` | Task 6 agent tool + tests |
| 4.1 New package | Tasks 1–5 |
| 4.2 Embeddings adapter (OpenAI SDK, `dimensions=1024`) | Task 1 |
| 4.3 Document text and metadata | Task 3 |
| 4.4 Catalog-hash index, batching | Tasks 1 (`batch_size`), 4 |
| 4.5 Filter → compose query → rank → threshold → rationale → tie-break | Task 5 |
| 4.5 Browse path (`mode: "browse"`) | Task 5 |
| 4.6 Trace + structured log | Task 5 |
| 5.1 `marketplace.py` rewrite | Task 6 |
| 5.2 `agent.py` wiring | Task 6 |
| 5.3 `settings.py` fields | Task 6 |
| 6 Behavior changes | Task 5 rationale tests + Task 7 live run |
| 7 Error handling | Task 6 tests |
| 8 Testing | Tasks 1–7 |
| 10 Acceptance | Task 8 |

**Deliberate deviations from the spec, and why**

1. **Batching lives in `NebiusEmbeddings`, not `index.py`.** The index calls `add_documents` once; the adapter splits into 64-item requests. This keeps one place responsible for provider request limits and makes the batching testable without a vector store.
2. **The retriever embeds the query itself** and calls `similarity_search_with_score_by_vector`. The spec wrote `similarity_search_with_score`, but the cache is process-wide, so a cached store could otherwise hold an embeddings client from a previous construction (stale key/endpoint). Computing the query vector on the live retriever removes that hazard and keeps the trace accurate.
3. **`top_k` is `[]` in browse mode.** There are no semantic scores to report; browse ordering is deterministic and fully described by `mode`. The spec's example only covers the dense case.

**Type consistency**

- `RetrievalResult.products` is `list[dict]`; `marketplace.retrieve_products` returns that plus `trace` — matches every call site.
- `ProductRetriever.search` accepts `preferences: list[str] | None`; the agent passes `preferences` straight through (ADK gives a list or None).
- `shape_search_result(..., retrieval: dict | None)` is backward compatible; existing call sites without `retrieval` keep working.
- Trace keys are stable across the retriever, `marketplace`, and the tests: `mode`, `backend`, `model`, `dimension`, `candidates`, `top_k`, `latency_ms`.

**Verified while writing this plan**

- `InMemoryVectorStore` in `langchain-core` 1.6.13 ships in the installed venv and exposes `similarity_search_with_score_by_vector(embedding, k, filter=...)`.
- Cosine scores for the fixture vectors are `[1.0, 0.9507, 0.1, 0.05]`, confirming the threshold of `0.25` drops the monitor and chair.
- The `filter=` callable is applied before similarity ranking (verified with a filtered call).
- `numpy` is **not** installed in the current venv and is required by the store — hence the dependency added in Task 1.
- Nebius `Qwen/Qwen3-Embedding-8B` accepts `dimensions=1024` (native 4096) against the live endpoint.

**Known follow-ups (out of scope, do not implement here)**

- Tuning `MIN_SIMILARITY` from real score distributions (single constant, one-line change).
- Persisting the index across process restarts (today every cold start re-embeds 180 documents).
- Enhancement #11's `retrieve_candidates` in the buyer planner remains unwired and untouched.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-11-12-pure-rag-product-retrieval.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch one fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batching with checkpoints.






