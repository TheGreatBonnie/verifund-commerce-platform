"""Nebius Token Factory embedding adapter.

The Nebius endpoint is OpenAI-compatible, so we call the `openai` SDK directly
instead of `OpenAIEmbeddings`: that keeps the request shape identical to the
documented sample and avoids tiktoken preprocessing that does not match the
Qwen tokenizer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

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
