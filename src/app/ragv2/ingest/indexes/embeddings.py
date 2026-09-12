from collections.abc import Sequence
from typing import Protocol

import ollama

from app.ragv2.config import settings


class EmbeddingModel(Protocol):
    model_name: str

    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class OllamaEmbeddingModel:
    """Generates local embeddings through Ollama."""

    def __init__(
        self,
        model_name: str = settings.embedding_model,
        client: ollama.Client | None = None,
    ):
        self.model_name = model_name
        self.client = client or ollama.Client()

    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        if not texts:
            return []

        return self._embed(list(texts))

    def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise ValueError("Embedding query cannot be empty.")

        return self._embed([text])[0]

    def _embed(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        if any(not text.strip() for text in texts):
            raise ValueError(
                "Embedding input cannot contain empty text."
            )

        response = self.client.embed(
            model=self.model_name,
            input=texts,
        )

        embeddings = [
            [float(value) for value in vector]
            for vector in response.embeddings
        ]

        if len(embeddings) != len(texts):
            raise RuntimeError(
                "Embedding model returned an unexpected vector count."
            )

        dimensions = {len(vector) for vector in embeddings}

        if not dimensions or 0 in dimensions:
            raise RuntimeError("Embedding model returned an empty vector.")

        if len(dimensions) != 1:
            raise RuntimeError(
                "Embedding vectors have inconsistent dimensions."
            )

        return embeddings