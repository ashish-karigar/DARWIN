import pytest

from app.ragv2.contracts import (
    Chunk,
    ContentType,
    RetrievalHit,
)
from app.ragv2.retrieve.retrieval.fusion import (
    ReciprocalRankFusion,
)


def create_chunk(chunk_id: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="document-1",
        parent_id=f"parent-{chunk_id}",
        text=f"Evidence from {chunk_id}.",
        content_type=ContentType.TEXT,
        source_uri="/documents/source.txt",
        token_count=4,
    )


def create_hit(
    chunk_id: str,
    rank: int,
    retriever: str,
    score: float = 0.8,
) -> RetrievalHit:
    return RetrievalHit(
        chunk=create_chunk(chunk_id),
        score=score,
        rank=rank,
        retriever=retriever,
    )


def test_rewards_chunks_found_by_multiple_retrievers():
    fused = ReciprocalRankFusion().fuse(
        {
            "vector": (
                create_hit("vector-only", 1, "vector"),
                create_hit("shared", 2, "vector"),
            ),
            "lexical": (
                create_hit("shared", 1, "lexical"),
                create_hit("lexical-only", 2, "lexical"),
            ),
        }
    )

    assert fused[0].chunk.chunk_id == "shared"
    assert fused[0].score == 1.0
    assert fused[0].retriever == "hybrid"
    assert fused[0].metadata["matched_retrievers"] == (
        "vector",
        "lexical",
    )
    assert fused[0].metadata["component_ranks"] == {
        "vector": 2,
        "lexical": 1,
    }


def test_ignores_duplicate_chunks_within_one_retriever():
    fused = ReciprocalRankFusion(
        rank_constant=60
    ).fuse(
        {
            "vector": (
                create_hit("shared", 1, "vector"),
                create_hit("shared", 2, "vector"),
            ),
        }
    )

    assert len(fused) == 1
    assert fused[0].raw_score == pytest.approx(1 / 61)


def test_applies_weights_and_result_limit():
    fused = ReciprocalRankFusion(
        retriever_weights={
            "vector": 0.5,
            "lexical": 2.0,
        }
    ).fuse(
        {
            "vector": (
                create_hit("vector-result", 1, "vector"),
            ),
            "lexical": (
                create_hit("lexical-result", 1, "lexical"),
            ),
        },
        limit=1,
    )

    assert len(fused) == 1
    assert fused[0].chunk.chunk_id == "lexical-result"


def test_handles_empty_and_invalid_configuration():
    fusion = ReciprocalRankFusion()

    assert fusion.fuse({}) == ()

    with pytest.raises(ValueError, match="limit must be positive"):
        fusion.fuse({}, limit=0)

    with pytest.raises(
        ValueError,
        match="constant must be positive",
    ):
        ReciprocalRankFusion(rank_constant=0)

    with pytest.raises(
        ValueError,
        match="weights cannot be negative",
    ):
        ReciprocalRankFusion(
            retriever_weights={"vector": -1.0}
        )