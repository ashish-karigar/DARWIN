from pathlib import Path

import chromadb
import pytest

from app.ragv2.config import RagSettings
from app.ragv2.contracts import Chunk, ContentType
from app.ragv2.ingest.indexes.vector import (
    ChromaVectorIndex,
)


class FakeEmbeddingModel:
    model_name = "fake-embeddings"

    def __init__(self):
        self.batch_sizes = []

    @staticmethod
    def _embed(text: str) -> list[float]:
        normalized = text.casefold()

        return [
            float("retrieval" in normalized),
            float("invoice" in normalized),
            float("music" in normalized),
        ]

    def embed_documents(
        self,
        texts,
    ) -> list[list[float]]:
        self.batch_sizes.append(len(texts))
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def create_chunks() -> tuple[Chunk, ...]:
    return (
        Chunk(
            chunk_id="chunk-retrieval",
            document_id="document-a",
            parent_id="section-retrieval",
            text="Semantic retrieval finds related concepts.",
            content_type=ContentType.TEXT,
            source_uri="/documents/rag.txt",
            token_count=6,
        ),
        Chunk(
            chunk_id="chunk-invoice",
            document_id="document-a",
            parent_id="table-invoice",
            text="Invoice totals and payment amounts.",
            content_type=ContentType.TABLE,
            source_uri="/documents/invoice.pdf",
            token_count=6,
        ),
        Chunk(
            chunk_id="chunk-music",
            document_id="document-b",
            parent_id="section-music",
            text="Music playback controls.",
            content_type=ContentType.TEXT,
            source_uri="/documents/music.txt",
            token_count=4,
        ),
    )


def create_index(
    tmp_path: Path,
) -> tuple[ChromaVectorIndex, FakeEmbeddingModel]:
    embedding_model = FakeEmbeddingModel()

    index = ChromaVectorIndex(
        rag_settings=RagSettings(
            vector_index_directory=tmp_path / "chroma",
            vector_collection_name="test_chunks",
            embedding_batch_size=2,
        ),
        embedding_model=embedding_model,
        client=chromadb.EphemeralClient(),
    )

    return index, embedding_model


def test_batches_and_ranks_semantic_results(tmp_path: Path):
    index, embedding_model = create_index(tmp_path)

    index.upsert(create_chunks())
    hits = index.search("How does retrieval work?", limit=3)

    assert index.count() == 3
    assert embedding_model.batch_sizes == [2, 1]
    assert hits[0].chunk.chunk_id == "chunk-retrieval"
    assert hits[0].retriever == "vector"
    assert hits[0].rank == 1
    assert hits[0].score > 0.99


def test_supports_filters_upserts_and_document_deletion(
    tmp_path: Path,
):
    index, _ = create_index(tmp_path)
    chunks = create_chunks()

    index.upsert(chunks)
    index.upsert(chunks)

    assert index.count() == 3

    hits = index.search(
        "music controls",
        limit=3,
        where={"document_id": "document-b"},
    )

    assert len(hits) == 1
    assert hits[0].chunk.document_id == "document-b"

    assert index.delete_document("document-a") == 2
    assert index.count() == 1
    assert index.delete_document("missing") == 0


def test_rejects_duplicate_chunk_ids(tmp_path: Path):
    index, _ = create_index(tmp_path)
    chunk = create_chunks()[0]

    with pytest.raises(ValueError, match="duplicate chunk IDs"):
        index.upsert((chunk, chunk))