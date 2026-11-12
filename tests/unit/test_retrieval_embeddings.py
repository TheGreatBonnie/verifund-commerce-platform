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
