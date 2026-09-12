from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    ContextBundle,
    EvidenceGrade,
    QueryAnalysis,
    QueryStrategy,
    RetrievalHit,
)
from app.ragv2.retrieve.retrieval.context_builder import (
    ContextBuilder,
)
from app.ragv2.retrieve.retrieval.grader import (
    EvidenceGrader,
)
from app.ragv2.retrieve.retrieval.hybrid import (
    HybridRetriever,
)
from app.ragv2.retrieve.retrieval.query_analyzer import (
    QueryAnalyzer,
)
from app.ragv2.retrieve.retrieval.reranker import (
    CrossEncoderReranker,
)


@dataclass(frozen=True, slots=True)
class QueryRetrievalTrace:
    query: str
    candidates: tuple[RetrievalHit, ...]
    reranked_hits: tuple[RetrievalHit, ...]
    grades: tuple[EvidenceGrade, ...]
    hybrid_seconds: float
    reranking_seconds: float
    grading_seconds: float


@dataclass(frozen=True, slots=True)
class RetrievalTimings:
    query_analysis_seconds: float
    hybrid_seconds: float
    reranking_seconds: float
    grading_seconds: float
    context_seconds: float
    total_seconds: float


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    query: str
    analysis: QueryAnalysis
    traces: tuple[QueryRetrievalTrace, ...]
    candidates: tuple[RetrievalHit, ...]
    reranked_hits: tuple[RetrievalHit, ...]
    grades: tuple[EvidenceGrade, ...]
    context: ContextBundle
    unanswered_queries: tuple[str, ...]
    timings: RetrievalTimings

    @property
    def fully_answerable(self) -> bool:
        return not self.unanswered_queries


class RetrievalPipeline:
    """Plans and executes DARWIN's complete retrieval workflow."""

    def __init__(
        self,
        query_analyzer: QueryAnalyzer | None = None,
        hybrid_retriever: HybridRetriever | None = None,
        reranker: CrossEncoderReranker | None = None,
        evidence_grader: EvidenceGrader | None = None,
        context_builder: ContextBuilder | None = None,
        rag_settings: RagSettings = settings,
    ):
        self.settings = rag_settings
        self.query_analyzer = (
            query_analyzer
            or QueryAnalyzer(rag_settings=rag_settings)
        )
        self.hybrid_retriever = (
            hybrid_retriever
            or HybridRetriever(rag_settings=rag_settings)
        )
        self.reranker = (
            reranker
            or CrossEncoderReranker(
                rag_settings=rag_settings
            )
        )
        self.evidence_grader = (
            evidence_grader
            or EvidenceGrader(
                rag_settings=rag_settings
            )
        )
        self.context_builder = (
            context_builder
            or ContextBuilder(
                rag_settings=rag_settings
            )
        )

    def retrieve(
        self,
        query: str,
        conversation_context: Sequence[str] = (),
    ) -> RetrievalResult:
        query = query.strip()

        if not query:
            raise ValueError(
                "Retrieval query cannot be empty."
            )

        started_at = perf_counter()

        stage_started = perf_counter()
        analysis = self.query_analyzer.analyze(
            query,
            conversation_context=conversation_context,
        )
        query_analysis_seconds = (
            perf_counter() - stage_started
        )

        traces = tuple(
            self._retrieve_query(planned_query)
            for planned_query in analysis.retrieval_queries
        )

        candidates = self._merge_hits(
            trace.candidates
            for trace in traces
        )
        reranked_hits = self._merge_hits(
            trace.reranked_hits
            for trace in traces
        )
        grades = self._merge_grades(
            trace.grades
            for trace in traces
        )

        stage_started = perf_counter()
        context = self.context_builder.build(
            analysis.standalone_query,
            grades,
        )
        context_seconds = perf_counter() - stage_started

        unanswered_queries = self._find_unanswered_queries(
            analysis,
            traces,
        )

        return RetrievalResult(
            query=query,
            analysis=analysis,
            traces=traces,
            candidates=candidates,
            reranked_hits=reranked_hits,
            grades=grades,
            context=context,
            unanswered_queries=unanswered_queries,
            timings=RetrievalTimings(
                query_analysis_seconds=round(
                    query_analysis_seconds,
                    4,
                ),
                hybrid_seconds=round(
                    sum(
                        trace.hybrid_seconds
                        for trace in traces
                    ),
                    4,
                ),
                reranking_seconds=round(
                    sum(
                        trace.reranking_seconds
                        for trace in traces
                    ),
                    4,
                ),
                grading_seconds=round(
                    sum(
                        trace.grading_seconds
                        for trace in traces
                    ),
                    4,
                ),
                context_seconds=round(
                    context_seconds,
                    4,
                ),
                total_seconds=round(
                    perf_counter() - started_at,
                    4,
                ),
            ),
        )

    def _retrieve_query(
        self,
        query: str,
    ) -> QueryRetrievalTrace:
        stage_started = perf_counter()
        candidates = self.hybrid_retriever.search(
            query,
            limit=self.settings.retrieval_candidate_limit,
        )
        hybrid_seconds = perf_counter() - stage_started

        stage_started = perf_counter()
        reranked_hits = self.reranker.rerank(
            query,
            candidates,
        )
        reranking_seconds = perf_counter() - stage_started

        stage_started = perf_counter()
        grades = self.evidence_grader.grade(
            query,
            reranked_hits,
        )
        grading_seconds = perf_counter() - stage_started

        return QueryRetrievalTrace(
            query=query,
            candidates=candidates,
            reranked_hits=reranked_hits,
            grades=grades,
            hybrid_seconds=hybrid_seconds,
            reranking_seconds=reranking_seconds,
            grading_seconds=grading_seconds,
        )

    def _find_unanswered_queries(
        self,
        analysis: QueryAnalysis,
        traces: tuple[QueryRetrievalTrace, ...],
    ) -> tuple[str, ...]:
        required_queries = (
            analysis.subqueries
            if analysis.strategy == QueryStrategy.DECOMPOSE
            else (analysis.standalone_query,)
        )

        trace_by_query = {
            trace.query: trace
            for trace in traces
        }

        unanswered = []

        for required_query in required_queries:
            trace = trace_by_query.get(required_query)

            direct_evidence_count = (
                sum(
                    grade.directly_answers
                    for grade in trace.grades
                )
                if trace is not None
                else 0
            )

            if (
                direct_evidence_count
                < self.settings.minimum_direct_evidence
            ):
                unanswered.append(required_query)

        return tuple(unanswered)

    @staticmethod
    def _merge_hits(
        result_groups,
    ) -> tuple[RetrievalHit, ...]:
        merged = {}

        for results in result_groups:
            for hit in results:
                merged.setdefault(
                    hit.chunk.chunk_id,
                    hit,
                )

        return tuple(merged.values())

    @staticmethod
    def _merge_grades(
        grade_groups,
    ) -> tuple[EvidenceGrade, ...]:
        merged = {}

        for grades in grade_groups:
            for grade in grades:
                chunk_id = grade.hit.chunk.chunk_id
                existing = merged.get(chunk_id)

                if (
                    existing is None
                    or RetrievalPipeline._grade_priority(
                        grade
                    )
                    > RetrievalPipeline._grade_priority(
                        existing
                    )
                ):
                    merged[chunk_id] = grade

        return tuple(merged.values())

    @staticmethod
    def _grade_priority(
        grade: EvidenceGrade,
    ) -> tuple[bool, bool, float, int]:
        return (
            grade.directly_answers,
            grade.is_relevant,
            grade.relevance_score,
            -grade.hit.rank,
        )