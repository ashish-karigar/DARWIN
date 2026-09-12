import numpy as np
import pytest

from app.ragv2.config import RagSettings
from app.ragv2.contracts import (
    Chunk,
    ContentType,
    RetrievalHit,
)
from app.ragv2.retrieve.retrieval.reranker import (
    CrossEncoderReranker,
    CrossEncoderScorer,
)


def create_hit(
    chunk_id: str,
    text: str,
    rank: int,
    heading: tuple[str, ...] = (),
) -> RetrievalHit:
    return RetrievalHit(
        chunk=Chunk(
            chunk_id=chunk_id,
            document_id="document-1",
            parent_id=f"parent-{chunk_id}",
            text=text,
            content_type=ContentType.TEXT,
            heading_path=heading,
            source_uri="/documents/rag.pdf",
            token_count=8,
        ),
        score=1.0 / rank,
        rank=rank,
        retriever="hybrid",
        metadata={"matched_retrievers": ("vector",)},
    )


class FakePassageScorer:
    def __init__(self, scores):
        self.scores = scores
        self.received_pairs = []

    def score(self, pairs):
        self.received_pairs = list(pairs)
        return self.scores


class FakeCrossEncoderModel:
    def __init__(self):
        self.calls = []

    def predict(
        self,
        pairs,
        batch_size,
        show_progress_bar,
    ):
        self.calls.append(
            {
                "pairs": pairs,
                "batch_size": batch_size,
                "show_progress_bar": show_progress_bar,
            }
        )

        return np.array([[2.0], [-1.0]])


def test_promotes_the_most_relevant_passage():
    hits = (
        create_hit(
            "keyword-match",
            "RAG has several trainable model parameters.",
            rank=1,
        ),
        create_hit(
            "direct-answer",
            (
                "The non-parametric memory is a dense "
                "vector index of Wikipedia."
            ),
            rank=2,
            heading=("Introduction",),
        ),
        create_hit(
            "weak-match",
            "Memory can be updated at test time.",
            rank=3,
        ),
    )

    scorer = FakePassageScorer(
        scores=[0.2, 4.0, -1.0]
    )

    reranked = CrossEncoderReranker(
        scorer=scorer,
        rag_settings=RagSettings(
            reranker_result_limit=2
        ),
    ).rerank(
        "What non-parametric memory does RAG use?",
        hits,
    )

    assert len(reranked) == 2
    assert reranked[0].chunk.chunk_id == "direct-answer"
    assert reranked[0].rank == 1
    assert reranked[0].retriever == "reranker"
    assert reranked[0].score > 0.98

    assert reranked[0].metadata["previous_rank"] == 2
    assert reranked[0].metadata["previous_retriever"] == "hybrid"

    assert scorer.received_pairs[1][1].startswith(
        "Heading: Introduction"
    )


def test_cross_encoder_adapter_flattens_predictions():
    model = FakeCrossEncoderModel()

    scorer = CrossEncoderScorer(
        model_name="fake-model",
        batch_size=8,
        model=model,
    )

    scores = scorer.score(
        (
            ("question", "first passage"),
            ("question", "second passage"),
        )
    )

    assert scores == [2.0, -1.0]
    assert model.calls[0]["batch_size"] == 8
    assert not model.calls[0]["show_progress_bar"]


def test_handles_empty_results_and_invalid_input():
    scorer = FakePassageScorer(scores=[])
    reranker = CrossEncoderReranker(scorer=scorer)

    assert reranker.rerank("valid question", ()) == ()
    assert scorer.received_pairs == []

    with pytest.raises(ValueError, match="cannot be empty"):
        reranker.rerank("   ", ())

    with pytest.raises(ValueError, match="must be positive"):
        reranker.rerank("question", (), limit=0)


def test_rejects_incomplete_model_output():
    hits = (
        create_hit("first", "First passage.", rank=1),
        create_hit("second", "Second passage.", rank=2),
    )

    reranker = CrossEncoderReranker(
        scorer=FakePassageScorer(scores=[1.0])
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected score count",
    ):
        reranker.rerank("question", hits)