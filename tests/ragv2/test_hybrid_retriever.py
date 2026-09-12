from threading import Barrier

import pytest

from app.ragv2.config import RagSettings
from app.ragv2.contracts import (
    Chunk,
    ContentType,
    RetrievalHit,
)
from app.ragv2.retrieve.retrieval.hybrid import (
    HybridRetriever,
)


def create_hit(
    chunk_id: str,
    rank: int,
    retriever: str,
) -> RetrievalHit:
    return RetrievalHit(
        chunk=Chunk(
            chunk_id=chunk_id,
            document_id="document-1",
            parent_id=f"parent-{chunk_id}",
            text=f"Evidence from {chunk_id}.",
            content_type=ContentType.TEXT,
            source_uri="/documents/source.txt",
            token_count=4,
        ),
        score=0.8,
        rank=rank,
        retriever=retriever,
    )


class FakeVectorIndex:
    def __init__(self, hits=(), barrier=None):
        self.hits = hits
        self.barrier = barrier
        self.calls = []

    def search(self, query, limit=5, where=None):
        self.calls.append(
            {
                "query": query,
                "limit": limit,
                "where": where,
            }
        )

        if self.barrier:
            self.barrier.wait(timeout=2)

        return self.hits


class FakeLexicalIndex:
    def __init__(self, hits=(), barrier=None):
        self.hits = hits
        self.barrier = barrier
        self.calls = []

    def search(
        self,
        query,
        limit=5,
        document_id=None,
        content_type=None,
    ):
        self.calls.append(
            {
                "query": query,
                "limit": limit,
                "document_id": document_id,
                "content_type": content_type,
            }
        )

        if self.barrier:
            self.barrier.wait(timeout=2)

        return self.hits


def test_retrieves_and_fuses_both_indexes():
    vector = FakeVectorIndex(
        hits=(
            create_hit("vector-only", 1, "vector"),
            create_hit("shared", 2, "vector"),
        )
    )
    lexical = FakeLexicalIndex(
        hits=(
            create_hit("shared", 1, "lexical"),
            create_hit("lexical-only", 2, "lexical"),
        )
    )

    retriever = HybridRetriever(
        vector_index=vector,
        lexical_index=lexical,
        rag_settings=RagSettings(
            retrieval_candidate_limit=10,
            retrieval_result_limit=2,
        ),
    )

    hits = retriever.search("hybrid retrieval")

    assert len(hits) == 2
    assert hits[0].chunk.chunk_id == "shared"
    assert hits[0].retriever == "hybrid"

    assert vector.calls[0]["limit"] == 10
    assert lexical.calls[0]["limit"] == 10


def test_passes_filters_to_both_indexes():
    vector = FakeVectorIndex()
    lexical = FakeLexicalIndex()

    retriever = HybridRetriever(
        vector_index=vector,
        lexical_index=lexical,
    )

    retriever.search(
        "invoice total",
        limit=3,
        document_id="document-1",
        content_type=ContentType.TABLE,
    )

    assert vector.calls[0]["where"] == {
        "$and": [
            {"document_id": "document-1"},
            {"content_type": "table"},
        ]
    }

    assert lexical.calls[0]["document_id"] == "document-1"
    assert lexical.calls[0]["content_type"] == ContentType.TABLE


def test_runs_retrievers_concurrently():
    barrier = Barrier(2)

    retriever = HybridRetriever(
        vector_index=FakeVectorIndex(barrier=barrier),
        lexical_index=FakeLexicalIndex(barrier=barrier),
    )

    assert retriever.search("parallel retrieval") == ()


def test_rejects_invalid_queries():
    retriever = HybridRetriever(
        vector_index=FakeVectorIndex(),
        lexical_index=FakeLexicalIndex(),
    )

    with pytest.raises(ValueError, match="cannot be empty"):
        retriever.search("   ")

    with pytest.raises(ValueError, match="must be positive"):
        retriever.search("retrieval", limit=0)