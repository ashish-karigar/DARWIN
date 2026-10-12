from app.ragv2.contracts import (
    Chunk,
    ContentType,
    RetrievalHit,
)
from app.ragv2.eval.datasets import (
    EvaluationCase,
    EvaluationDataset,
)
from app.ragv2.eval.offline import CandidateEvaluator


class FakeHybrid:
    def search(self, query):
        return (
            RetrievalHit(
                chunk=Chunk(
                    chunk_id="chunk",
                    document_id="document",
                    parent_id="parent",
                    text="Evidence",
                    content_type=ContentType.TEXT,
                    source_uri="/documents/source.pdf",
                    token_count=1,
                ),
                score=0.8,
                rank=1,
                retriever="hybrid",
            ),
        )


class FakeReranker:
    def rerank(self, query, candidates):
        return tuple(candidates)


def test_offline_evaluator_measures_candidate_ranking():
    dataset = EvaluationDataset(
        name="Offline test",
        cases=(
            EvaluationCase(
                case_id="hit",
                question="Question",
                should_answer=True,
                expected_source_suffixes=("source.pdf",),
            ),
            EvaluationCase(
                case_id="ignored-negative",
                question="Unknown",
                should_answer=False,
            ),
        ),
    )

    report = CandidateEvaluator(
        hybrid_retriever=FakeHybrid(),
        reranker=FakeReranker(),
    ).evaluate(dataset)

    assert report.answerable_case_count == 1
    assert report.hit_at_1_percent == 100.0
    assert report.mean_reciprocal_rank == 1.0
