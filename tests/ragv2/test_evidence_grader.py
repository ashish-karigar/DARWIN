import pytest

from app.ragv2.config import RagSettings
from app.ragv2.contracts import (
    Chunk,
    ContentType,
    RetrievalHit,
)
from app.ragv2.retrieve.retrieval.grader import (
    EvidenceDecision,
    EvidenceGrader,
)


def create_hit(
    chunk_id: str,
    rank: int,
) -> RetrievalHit:
    return RetrievalHit(
        chunk=Chunk(
            chunk_id=chunk_id,
            document_id="document-1",
            parent_id=f"parent-{chunk_id}",
            text=f"Evidence contained in {chunk_id}.",
            content_type=ContentType.TEXT,
            source_uri="/documents/rag.pdf",
            token_count=5,
        ),
        score=0.9,
        rank=rank,
        retriever="reranker",
    )


class FakeGradingProvider:
    def __init__(self, decisions):
        self.decisions = tuple(decisions)
        self.calls = []

    def grade(self, query, hits):
        self.calls.append(
            {
                "query": query,
                "hits": tuple(hits),
            }
        )

        return self.decisions


def test_distinguishes_direct_related_and_weak_evidence():
    hits = (
        create_hit("direct", 1),
        create_hit("related", 2),
        create_hit("weak", 3),
    )

    provider = FakeGradingProvider(
        (
            EvidenceDecision(
                chunk_id="related",
                relevance_score=0.85,
                is_relevant=True,
                directly_answers=False,
                reason="Related background only.",
            ),
            EvidenceDecision(
                chunk_id="direct",
                relevance_score=0.97,
                is_relevant=True,
                directly_answers=True,
                reason="Explicitly states the answer.",
            ),
            EvidenceDecision(
                chunk_id="weak",
                relevance_score=0.40,
                is_relevant=True,
                directly_answers=True,
                reason="Insufficient supporting detail.",
            ),
        )
    )

    grades = EvidenceGrader(
        provider=provider,
        rag_settings=RagSettings(
            evidence_relevance_threshold=0.65
        ),
    ).grade(
        "What memory does RAG use?",
        hits,
    )

    assert [grade.hit.chunk.chunk_id for grade in grades] == [
        "direct",
        "related",
        "weak",
    ]

    assert grades[0].is_relevant
    assert grades[0].directly_answers

    assert grades[1].is_relevant
    assert not grades[1].directly_answers

    assert not grades[2].is_relevant
    assert not grades[2].directly_answers


def test_empty_hits_skip_the_provider():
    provider = FakeGradingProvider(())
    grader = EvidenceGrader(provider=provider)

    assert grader.grade("A valid question", ()) == ()
    assert provider.calls == []


def test_rejects_duplicate_input_chunks():
    hit = create_hit("duplicate", 1)
    grader = EvidenceGrader(
        provider=FakeGradingProvider(())
    )

    with pytest.raises(
        ValueError,
        match="duplicate chunk IDs",
    ):
        grader.grade("Question", (hit, hit))


@pytest.mark.parametrize(
    "decisions",
    [
        (),
        (
            EvidenceDecision(
                chunk_id="unknown",
                relevance_score=0.9,
                is_relevant=True,
                directly_answers=True,
                reason="Unknown result.",
            ),
        ),
        (
            EvidenceDecision(
                chunk_id="expected",
                relevance_score=0.9,
                is_relevant=True,
                directly_answers=True,
                reason="First decision.",
            ),
            EvidenceDecision(
                chunk_id="expected",
                relevance_score=0.8,
                is_relevant=True,
                directly_answers=False,
                reason="Duplicate decision.",
            ),
        ),
    ],
)
def test_rejects_invalid_provider_responses(decisions):
    grader = EvidenceGrader(
        provider=FakeGradingProvider(decisions)
    )

    with pytest.raises(
        RuntimeError,
        match="missing, duplicate, or unknown",
    ):
        grader.grade(
            "Question",
            (create_hit("expected", 1),),
        )


def test_rejects_empty_question():
    grader = EvidenceGrader(
        provider=FakeGradingProvider(())
    )

    with pytest.raises(ValueError, match="cannot be empty"):
        grader.grade("   ", ())