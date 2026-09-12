import pytest

from app.ragv2.config import RagSettings
from app.ragv2.contracts import (
    Chunk,
    ContentType,
    ContextBundle,
    EvidenceGrade,
    RetrievalHit,
    QueryAnalysis,
    QueryStrategy
)
from app.ragv2.retrieve.retrieve import RetrievalPipeline


def create_hit() -> RetrievalHit:
    return RetrievalHit(
        chunk=Chunk(
            chunk_id="chunk-1",
            document_id="document-1",
            parent_id="parent-1",
            text="The direct answer is contained here.",
            content_type=ContentType.TEXT,
            source_uri="/documents/source.pdf",
            token_count=7,
        ),
        score=0.9,
        rank=1,
        retriever="hybrid",
    )


def create_grade(hit: RetrievalHit) -> EvidenceGrade:
    return EvidenceGrade(
        hit=hit,
        relevance_score=0.95,
        is_relevant=True,
        directly_answers=True,
        reason="The passage explicitly answers the question.",
    )


class FakeHybridRetriever:
    def __init__(self, hit, events):
        self.hit = hit
        self.events = events
        self.calls = []

    def search(self, query, limit):
        self.events.append("hybrid")
        self.calls.append(
            {
                "query": query,
                "limit": limit,
            }
        )
        return (self.hit,)


class FakeReranker:
    def __init__(self, events):
        self.events = events

    def rerank(self, query, hits):
        self.events.append("rerank")
        return tuple(hits)


class FakeEvidenceGrader:
    def __init__(self, grade, events):
        self.grade_result = grade
        self.events = events

    def grade(self, query, hits):
        self.events.append("grade")
        return (self.grade_result,)


class FakeContextBuilder:
    def __init__(self, events):
        self.events = events

    def build(self, query, grades):
        self.events.append("context")

        return ContextBundle(
            query=query,
            items=(),
            total_tokens=0,
            has_direct_evidence=True,
        )


def create_pipeline(events):
    hit = create_hit()
    grade = create_grade(hit)
    hybrid = FakeHybridRetriever(hit, events)

    pipeline = RetrievalPipeline(
        hybrid_retriever=hybrid,
        reranker=FakeReranker(events),
        evidence_grader=FakeEvidenceGrader(
            grade,
            events,
        ),
        context_builder=FakeContextBuilder(events),
        rag_settings=RagSettings(
            retrieval_candidate_limit=12,
        ),
    )

    return pipeline, hybrid


def test_runs_every_retrieval_stage_in_order():
    events = []
    pipeline, hybrid = create_pipeline(events)

    result = pipeline.retrieve(
        "What does the passage say?"
    )

    assert events == [
        "hybrid",
        "rerank",
        "grade",
        "context",
    ]

    assert hybrid.calls == [
        {
            "query": "What does the passage say?",
            "limit": 12,
        }
    ]

    assert len(result.candidates) == 1
    assert len(result.reranked_hits) == 1
    assert len(result.grades) == 1
    assert result.context.has_direct_evidence


def test_returns_non_negative_stage_timings():
    result = create_pipeline([])[0].retrieve(
        "Question"
    )

    assert result.timings.hybrid_seconds >= 0
    assert result.timings.reranking_seconds >= 0
    assert result.timings.grading_seconds >= 0
    assert result.timings.context_seconds >= 0
    assert result.timings.total_seconds >= 0


def test_rejects_empty_query_before_running_stages():
    events = []
    pipeline, _ = create_pipeline(events)

    with pytest.raises(ValueError, match="cannot be empty"):
        pipeline.retrieve("   ")

    assert events == []

class FixedQueryAnalyzer:
    def __init__(self, analysis):
        self.analysis = analysis
        self.calls = []

    def analyze(self, query, conversation_context=()):
        self.calls.append(
            {
                "query": query,
                "conversation_context": tuple(
                    conversation_context
                ),
            }
        )
        return self.analysis


class QueryAwareHybridRetriever:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def search(self, query, limit):
        self.queries.append(query)
        return self.results.get(query, ())


class QueryAwareEvidenceGrader:
    def __init__(self, direct_queries):
        self.direct_queries = set(direct_queries)

    def grade(self, query, hits):
        directly_answers = query in self.direct_queries

        return tuple(
            EvidenceGrade(
                hit=hit,
                relevance_score=(
                    0.95 if directly_answers else 0.75
                ),
                is_relevant=True,
                directly_answers=directly_answers,
                reason=(
                    "Direct evidence."
                    if directly_answers
                    else "Supporting evidence only."
                ),
            )
            for hit in hits
        )


def create_named_hit(chunk_id):
    original = create_hit()

    return original.model_copy(
        update={
            "chunk": original.chunk.model_copy(
                update={
                    "chunk_id": chunk_id,
                    "parent_id": f"parent-{chunk_id}",
                }
            )
        }
    )


def test_reports_unanswered_decomposed_subquery():
    first_query = "Who created RAG?"
    second_query = "What memory does RAG use?"

    analysis = QueryAnalysis(
        original_query=(
            "Who created RAG and what memory does it use?"
        ),
        standalone_query=(
            "Who created RAG and what memory does it use?"
        ),
        strategy=QueryStrategy.DECOMPOSE,
        subqueries=(first_query, second_query),
    )

    hybrid = QueryAwareHybridRetriever(
        {
            first_query: (create_named_hit("creator"),),
            second_query: (create_named_hit("memory"),),
        }
    )

    pipeline = RetrievalPipeline(
        query_analyzer=FixedQueryAnalyzer(analysis),
        hybrid_retriever=hybrid,
        reranker=FakeReranker([]),
        evidence_grader=QueryAwareEvidenceGrader(
            direct_queries={first_query}
        ),
        context_builder=FakeContextBuilder([]),
    )

    result = pipeline.retrieve(
        analysis.original_query
    )

    assert [trace.query for trace in result.traces] == [
        first_query,
        second_query,
    ]
    assert len(result.candidates) == 2
    assert result.unanswered_queries == (second_query,)
    assert not result.fully_answerable


def test_step_back_support_is_not_required_direct_evidence():
    specific_query = (
        "Why does RAG reduce hallucination?"
    )
    background_query = (
        "How does external evidence improve factual accuracy?"
    )
    shared_hit = create_named_hit("shared-evidence")

    analysis = QueryAnalysis(
        original_query=specific_query,
        standalone_query=specific_query,
        strategy=QueryStrategy.STEP_BACK,
        step_back_query=background_query,
    )

    hybrid = QueryAwareHybridRetriever(
        {
            specific_query: (shared_hit,),
            background_query: (shared_hit,),
        }
    )

    pipeline = RetrievalPipeline(
        query_analyzer=FixedQueryAnalyzer(analysis),
        hybrid_retriever=hybrid,
        reranker=FakeReranker([]),
        evidence_grader=QueryAwareEvidenceGrader(
            direct_queries={specific_query}
        ),
        context_builder=FakeContextBuilder([]),
    )

    result = pipeline.retrieve(specific_query)

    assert len(result.traces) == 2
    assert len(result.candidates) == 1
    assert len(result.grades) == 1
    assert result.fully_answerable
    assert result.unanswered_queries == ()