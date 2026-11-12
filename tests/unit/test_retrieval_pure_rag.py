from __future__ import annotations

import uuid
from copy import deepcopy

import pytest
from commerce_core.retrieval.documents import product_document
from commerce_core.retrieval.index import clear_cache
from commerce_core.retrieval.retriever import (
    MIN_SIMILARITY,
    RELATIVE_MARGIN,
    ProductRetriever,
    compose_query,
)
from langchain_core.embeddings import Embeddings


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
    assert result.trace["candidates"] == 3

    under_monitor = retriever.search(
        CATALOG, query="good laptop for programming", max_unit_price_cents=40000
    )
    assert under_monitor.products == []
    assert under_monitor.trace["candidates"] == 1


def test_in_stock_filter_excludes_unavailable_products():
    catalog = [
        {**LAPTOP, "offers": [{**LAPTOP["offers"][0], "available": False}]},
        WORKSTATION,
    ]
    retriever, _ = make_retriever(
        catalog=catalog,
        mapping={"NW-LAPTOP-01": [1.0, 0.0], "NW-WORKSTATION-01": [0.95, 0.31]},
        query_vectors={"good laptop for programming": [1.0, 0.0]},
    )

    result = retriever.search(catalog, query="good laptop for programming", in_stock_only=True)

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
    assert MIN_SIMILARITY == 0.60
    assert RELATIVE_MARGIN == 0.10


def test_relative_margin_drops_weak_but_above_floor_hits():
    relevant = product("EX-RELEVANT-1", "Relevant Laptop", price=1000)
    close = product("EX-CLOSE-2", "Almost Laptop", price=1200)
    distant = product("EX-DISTANT-3", "Wireless Mouse", price=300)
    catalog = [distant, close, relevant]
    retriever, _ = make_retriever(
        catalog=catalog,
        mapping={
            "EX-RELEVANT-1": [1.0, 0.0],
            "EX-CLOSE-2": [0.92, 0.392],
            "EX-DISTANT-3": [0.65, 0.76],
        },
        query_vectors={"laptop": [1.0, 0.0]},
    )

    result = retriever.search(catalog, query="laptop")

    assert [row["sku"] for row in result.products] == ["EX-RELEVANT-1", "EX-CLOSE-2"]
    assert result.trace["cutoff"] == 0.9


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

    retriever.search(
        [LAPTOP], query="laptop", use_case="programming", preferences=["quiet", "  "]
    )

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
