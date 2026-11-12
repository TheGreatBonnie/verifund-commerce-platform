# Pure RAG Product Retrieval — Design

**Date:** 2026-11-12
**Status:** Approved design, spec under review
**Branch context:** `development`
**Supersedes:** lexical scoring in `apps/orchestrator_agent/orchestrator_agent/marketplace.py`

## 1. Objective

Replace the deterministic lexical scorer used by the orchestrator's
`search_marketplace_products` tool with **pure dense retrieval**. A shopper
query such as "Find me a good laptop for programming under $1500" must return
semantically relevant products, rendered by the existing CopilotKit
`search_marketplace_products` product cards (`apps/console/features/chat/chat.tsx`,
`features/chat/product-cards.tsx`).

The change is a **direct replacement**: lexical token scoring is removed, not
kept as a fallback or fused with dense scores.

## 2. Non-goals

- No hybrid retrieval, RRF fusion, or reranker.
- No LLM query rewrite or expansion.
- No changes to negotiation, buyer, seller, A2A, or Verifund flows.
- No persistence layer or vector database service. `InMemoryVectorStore` only.
- No metrics-gated rollout; no recall@k evaluation harness.
- No changes to deterministic constraint extraction ("under $1500" is already
  converted to `max_unit_price_cents=150000` by the orchestrator prompt).

## 3. Decisions

| Decision | Value |
|---|---|
| Retrieval mode | Pure dense (cosine), replaces lexical entirely |
| Vector store | `langchain_core.vectorstores.InMemoryVectorStore` (langchain-core 1.6.13, already installed) |
| Embedding provider | Nebius Token Factory, OpenAI-compatible `/embeddings` |
| Embedding model | `Qwen/Qwen3-Embedding-8B` (only embedding model exposed; verified) |
| Dimensions | `1024` via MRL truncation (verified: native 4096, `dimensions=1024` accepted) |
| Query text | `query + use_case + preferences`, no rewrite |
| Code location | `packages/commerce_core/commerce_core/retrieval/` |
| Index lifecycle | Lazy build, module-level cache keyed by catalog content hash |
| Rollout | Direct replacement, no feature flag |
| Card reasons | `match_rationale` gains `semantic:<score>` |
| Trace | `retrieval` block in tool result + structured log |
| Failure mode | Return `retrieval_unavailable` error to the agent (no products) |
| Minimum similarity | `0.25` constant, applied after ranking |

### 3.1 Failure mode rationale

Round 1 initially chose automatic lexical fallback; the later explicit answer
chose surfacing the error, and the lexical scorer no longer exists to fall back
to. Search therefore returns:

```json
{"error": "retrieval_unavailable", "message": "Product search is temporarily unavailable"}
```

The agent's existing `marketplace_unavailable` handling covers the UX. This is
the accepted trade-off: a provider outage degrades product discovery rather
than silently returning unrelated products.

## 4. Architecture

### 4.1 New package

```
packages/commerce_core/commerce_core/retrieval/
├── __init__.py      # ProductRetriever, RetrievalResult, RetrievalTrace, build_embeddings
├── embeddings.py    # OpenAIEmbeddings factory for Nebius
├── documents.py     # product -> Document
├── index.py         # catalog-hash cache + InMemoryVectorStore
└── retriever.py     # filtering, ranking, rationale, trace
```

`packages/commerce_core/pyproject.toml` gains `langchain-core>=1.0,<2` and
`langchain-openai>=0.3,<2` (already present in the root environment).

### 4.2 Embeddings

Use the OpenAI-compatible SDK directly rather than `OpenAIEmbeddings`, so the
request shape matches Nebius exactly and there is no tiktoken preprocessing:

```python
from openai import OpenAI
from langchain_core.embeddings import Embeddings

class NebiusEmbeddings(Embeddings):
    def __init__(self, *, api_key: str, base_url: str, model: str,
                 dimensions: int = 1024, batch_size: int = 64,
                 client: Any | None = None) -> None:
        self._client = client or OpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._dimensions = dimensions
        self._batch_size = batch_size

    def _create(self, inputs: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(
            model=self._model, input=inputs, dimensions=self._dimensions
        )
        return [item.embedding for item in sorted(response.data, key=lambda i: i.index)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            vectors.extend(self._create(texts[start : start + self._batch_size]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._create([text])[0]
```

`base_url` is `settings.nebius_base_url` — the existing env var. The documented
sample uses the `eu-north1` regional endpoint
(`https://api.tokenfactory.eu-north1.nebius.com/v1/`); the repo default is
`us-central1`. Both are OpenAI-compatible; keeping one setting means the same
`NEBIUS_BASE_URL` serves the chat model and embeddings.

`dimensions=1024` is passed explicitly (MRL truncation, verified against the
live endpoint). `client` injection exists for unit tests only.

### 4.3 Documents

Indexed text, in this order, one field per line:

```
{name}
{category}
{sku}
{description}
Seller: {seller}
```

Price and availability are **excluded from the embedded text** because they
change frequently and carry no semantic meaning; they live in metadata for
filtering and rationale. SKU is included so exact model-number queries retain a
chance under pure dense retrieval.

Metadata: `sku`, `name`, `category`, `price_cents`, `available`, `rating`.

### 4.4 Index

- Module-level `_CACHE: dict[str, tuple[str, InMemoryVectorStore]]`.
- Cache key: `f"{model}:{dimensions}"`.
- `catalog_hash(products)` = sha256 over sorted
  `sku|name|description|category|seller|price_cents|available`.
  Price and availability are included so metadata is never stale even though
  they are not embedded.
- On hash mismatch: build `Document`s, embed in batches of 64, create a new
  `InMemoryVectorStore`, replace the cache entry.
- First search pays ~180 embeddings (one batched call per 64 docs); later
  searches pay one query embedding.

### 4.5 Retrieval

`ProductRetriever.search(products, *, query, use_case, preferences, category,
max_unit_price_cents, in_stock_only)`:

1. Apply hard filters (unchanged semantics): category equality,
   `unit_price_cents <= max_unit_price_cents`, `in_stock_only` requires an offer
   with `available is True`. Empty result short-circuits to `[]`.
2. Compose query text: `" ".join(filter(None, [query, use_case, *preferences]))`.
   If the composed text is empty (browse-only request, no query/use_case/
   preferences), skip embedding and return the filtered products ordered by
   availability, rating, price, SKU; the trace reports `mode: "browse"`. This
   preserves the existing "show me products" behavior without a meaningless
   embedding call.
3. Call `similarity_search_with_score(text, k=len(filtered), filter=...)` where
   the filter callable keeps only documents whose `sku` is in the filtered set.
   Filtering **before** ranking avoids the reference implementation's
   retrieve-then-filter truncation bug.
4. Drop results with cosine similarity `< MIN_SIMILARITY` (0.25).
5. Rebuild product dicts in rank order; attach `match_rationale`:
   `semantic:<score:.2f>`, then `offers:available`, `rating:<value>` when
   ≥ 4.5, `price:discounted` when applicable. Non-semantic reasons are
   computed per product as today.
6. Sort ties by `(price_cents, sku)` for determinism.
7. Return `RetrievalResult(products, trace)`.

`InMemoryVectorStore._similarity_search_with_score_by_vector` (verified) uses
`cosine_similarity` and supports a `filter` callable; higher score is better.

### 4.6 Trace

```json
"retrieval": {
  "mode": "dense",
  "backend": "InMemoryVectorStore",
  "model": "Qwen/Qwen3-Embedding-8B",
  "dimension": 1024,
  "candidates": 34,
  "top_k": [{"sku": "NW-LAPTOP-01", "score": 0.82}],
  "latency_ms": 87
}
```

`top_k` is capped at the returned product count (max 24). A structured log line
is emitted at INFO with the same fields minus `top_k`.

## 5. Integration

### 5.1 `marketplace.py`

Remove: `TOKEN_SYNONYMS`, `_expand`, `_first_field`, and the lexical scoring
loop in `filter_and_rank_products`.

Keep: `_matches`, `_price`, `_offer_available`, `_seller`, `_currency`,
`_text_fields` only if still referenced.

Replace `filter_and_rank_products(...)` with:

```python
def retrieve_products(products, *, retriever, query=None, category=None,
                      max_unit_price_cents=None, in_stock_only=False,
                      use_case=None, preferences=None) -> tuple[list[dict], dict]:
```

`shape_search_result(payload, products, limit=12, retrieval=None)` adds the
`retrieval` block when provided; `applied_filters` and `total_candidates` keep
their current meaning.

### 5.2 `agent.py`

`_build_marketplace_search_tool` constructs the retriever once (closure scope)
from `settings.nebius_api_key`, `settings.nebius_base_url`,
`settings.embedding_model`, `settings.embedding_dimensions`. The tool:

- returns `{"error": "retrieval_unavailable", ...}` when the key is missing or
  the retriever raises;
- otherwise calls `retrieve_products` and passes the trace to
  `shape_search_result`.

### 5.3 `settings.py`

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

## 6. Behavior changes

| Query | Before | After |
|---|---|---|
| "good laptop for programming" | Laptops score highest; irrelevant accessories with rating/availability still appear | Semantically nearest laptops first; accessories below threshold disappear |
| "NC-700" | Exact SKU/name match ranks first | SKU is embedded in the doc text; expected to rank first, verified by tests and the live smoke run |
| "zzzzzz" | `[]` | `[]` via `MIN_SIMILARITY` |
| Card reasons | `query:<token>:name`, `offers:available`, `rating:4.8` | `semantic:0.82`, `offers:available`, `rating:4.8` |

Deterministic filters, ordering tie-breaks, payload shape, and the card contract
are unchanged.

## 7. Error handling

| Failure | Behavior |
|---|---|
| Missing API key | `retrieval_unavailable` error object |
| Embedding request fails | `retrieval_unavailable` error object |
| Empty catalog / no filtered candidates | `{"products": [], "total_candidates": 0}` |
| All scores below threshold | `{"products": [], ...}` with `retrieval.mode = "dense"` |
| Invalid `max_unit_price_cents` | Ignored, as today |

## 8. Testing

TDD with a deterministic fake embedder; no network in unit tests.

**New**

1. `tests/unit/test_retrieval_documents.py`
   - embedded text contains name, category, SKU, description, seller;
   - embedded text does **not** contain price;
   - metadata carries `sku`, `price_cents`, `available`, `rating`.
2. `tests/unit/test_retrieval_index.py`
   - same catalog searched twice → embedder called once for the catalog;
   - changed catalog → rebuild;
   - batching respects 64-document batches;
   - cache keyed by model and dimension.
3. `tests/unit/test_retrieval_pure_rag.py`
   - synthetic vectors: laptops near the "programming laptop" query, accessories far;
   - "good laptop for programming under $1500" ranks laptops above accessories;
   - price ceiling and in-stock filters are never violated;
   - `match_rationale` starts with `semantic:`;
   - unrelated query returns `[]` under `MIN_SIMILARITY`.

**Rewritten**

4. `tests/unit/test_orchestrator_marketplace.py`
   - existing filter/`shape_search_result` coverage preserved using a fake retriever;
   - `retrieval` block present with mode/backend/model/dimension/top_k;
   - embedder failure returns `retrieval_unavailable`.

**Manual**

5. `scripts/rag_smoke.py` (optional, not run in CI): three README-style queries
   against the seeded 180-product catalog using the real Nebius embedding
   endpoint; prints top-10 SKUs, scores, and latency.

## 9. Risks

- **Exact-match regression:** pure dense may rank a semantically similar product
  above an exact model-number match. Mitigated by embedding the SKU and by
  deterministic tie-breaks; accepted as part of "pure RAG".
- **Provider dependency on the search path:** one embedding call per search
  (plus 3 batched calls on cold start). Accepted.
- **Threshold sensitivity:** Qwen embeddings are not centered, so unrelated
  cosine scores can be non-trivial. `MIN_SIMILARITY = 0.25` is a constant tuned
  by the live smoke run; changing it is a one-line edit.
- **Cache growth:** one index per (model, dimensions) pair; bounded in practice.

## 10. Acceptance

- Lexical scoring and `TOKEN_SYNONYMS` are gone from `marketplace.py`.
- Unit suite for retrieval and orchestrator marketplace passes; `ruff` clean.
- A real-embedding smoke run over the seeded catalog returns laptops for
  "good laptop for programming under $1500", all at or below $1500.
- Tool result includes a `retrieval` block; cards render `semantic:` reasons.
- Existing buyer/seller/negotiation suites unaffected.
