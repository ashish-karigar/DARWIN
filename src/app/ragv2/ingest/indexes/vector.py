from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import chromadb

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import Chunk, RetrievalHit
from app.ragv2.ingest.indexes.embeddings import (
    EmbeddingModel,
    OllamaEmbeddingModel,
)
from app.ragv2.ingest.indexes.search_text import (
    build_search_text,
)


class VectorIndex(Protocol):
    def upsert(self, chunks: Sequence[Chunk]) -> None:
        ...

    def search(
        self,
        query: str,
        limit: int = 5,
    ) -> tuple[RetrievalHit, ...]:
        ...

    def delete_document(self, document_id: str) -> int:
        ...


class ChromaVectorIndex:
    """Stores and searches child-chunk embeddings in Chroma."""

    def __init__(
        self,
        rag_settings: RagSettings = settings,
        embedding_model: EmbeddingModel | None = None,
        client: Any | None = None,
    ):
        self.settings = rag_settings
        self.embedding_model = (
            embedding_model or OllamaEmbeddingModel()
        )

        self.settings.vector_index_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.client = client or chromadb.PersistentClient(
            path=self.settings.vector_index_directory
        )

        self.collection = self.client.get_or_create_collection(
            name=self.settings.vector_collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, chunks: Sequence[Chunk]) -> None:
        chunks = tuple(chunks)

        if not chunks:
            return

        chunk_ids = [chunk.chunk_id for chunk in chunks]

        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError(
                "Vector upsert received duplicate chunk IDs."
            )

        for batch in self._batches(chunks):
            texts = [
                build_search_text(chunk)
                for chunk in batch
            ]
            embeddings = self.embedding_model.embed_documents(texts)

            self.collection.upsert(
                ids=[chunk.chunk_id for chunk in batch],
                documents=texts,
                embeddings=embeddings,
                metadatas=[
                    {
                        "document_id": chunk.document_id,
                        "content_type": chunk.content_type.value,
                        "chunk_json": chunk.model_dump_json(),
                    }
                    for chunk in batch
                ],
            )

    def search(
            self,
            query: str,
            limit: int = 5,
            where: dict[str, Any] | None = None,
    ) -> tuple[RetrievalHit, ...]:
        ...
        if not query.strip():
            raise ValueError("Vector search query cannot be empty.")

        if limit < 1:
            raise ValueError("Vector search limit must be positive.")

        available = self.collection.count()

        if available == 0:
            return ()

        query_arguments = {
            "query_embeddings": [
                self.embedding_model.embed_query(query)
            ],
            "n_results": min(limit, available),
            "include": ["metadatas", "distances"],
        }

        if where:
            query_arguments["where"] = where

        result = self.collection.query(**query_arguments)

        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        hits = []

        for rank, (metadata, distance) in enumerate(
            zip(metadatas, distances),
            start=1,
        ):
            if metadata is None or "chunk_json" not in metadata:
                raise RuntimeError(
                    "Vector result is missing its chunk payload."
                )

            raw_similarity = 1.0 - float(distance)
            normalized_score = max(
                0.0,
                min(1.0, raw_similarity),
            )

            hits.append(
                RetrievalHit(
                    chunk=Chunk.model_validate_json(
                        metadata["chunk_json"]
                    ),
                    score=normalized_score,
                    raw_score=raw_similarity,
                    rank=rank,
                    retriever="vector",
                )
            )

        return tuple(hits)

    def delete_document(self, document_id: str) -> int:
        result = self.collection.get(
            where={"document_id": document_id},
            include=[],
        )
        chunk_ids = result["ids"]

        if chunk_ids:
            self.collection.delete(ids=chunk_ids)

        return len(chunk_ids)

    def count(self) -> int:
        return self.collection.count()

    def _batches(
        self,
        chunks: tuple[Chunk, ...],
    ) -> list[tuple[Chunk, ...]]:
        batch_size = self.settings.embedding_batch_size

        if batch_size < 1:
            raise ValueError(
                "Embedding batch size must be positive."
            )

        return [
            chunks[start:start + batch_size]
            for start in range(0, len(chunks), batch_size)
        ]