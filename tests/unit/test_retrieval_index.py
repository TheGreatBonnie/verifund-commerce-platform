from __future__ import annotations

import pytest
from commerce_core.retrieval.index import (
    build_store,
    catalog_hash,
    clear_cache,
    get_store,
)
from langchain_core.embeddings import Embeddings


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

    get_store(
        (row for row in [product("A"), product("B")]),
        embeddings=embeddings,
        cache_key="gen",
    )

    assert [len(call) for call in embeddings.document_calls] == [2]


def test_clear_cache_can_drop_a_single_key():
    embeddings = CountingEmbeddings()

    get_store([product("A")], embeddings=embeddings, cache_key="one")
    get_store([product("B")], embeddings=embeddings, cache_key="two")
    clear_cache("one")
    get_store([product("A")], embeddings=embeddings, cache_key="one")

    assert len(embeddings.document_calls) == 3
