from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
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
from app.ragv2.input_validation import (
    validate_conversation_context,
    validate_query,
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
from app.ragv2.retrieve.retrieval.structured import (
    StructuredQueryEngine,
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
    structured_seconds: float = 0.0


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
        structured_query_engine: StructuredQueryEngine | None = None,
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
        self._structured_query_engine = structured_query_engine

    def retrieve(
        self,
        query: str,
        conversation_context: Sequence[str] = (),
        *,
        _analysis_override: QueryAnalysis | None = None,
    ) -> RetrievalResult:
        query = validate_query(
            query,
            rag_settings=self.settings,
        )
        conversation_context = validate_conversation_context(
            conversation_context,
            rag_settings=self.settings,
        )

        started_at = perf_counter()

        if _analysis_override is None:
            stage_started = perf_counter()
            analysis = self.query_analyzer.analyze(
                query,
                conversation_context=conversation_context,
            )
            query_analysis_seconds = perf_counter() - stage_started
        else:
            analysis = _analysis_override
            query_analysis_seconds = 0.0

        required_queries = self._required_queries(analysis)
        stage_started = perf_counter()
        structured_contexts = {
            planned_query: self._structured_context(planned_query)
            for planned_query in required_queries
        }
        structured_seconds = perf_counter() - stage_started
        structured_answers = {
            planned_query
            for planned_query, context in structured_contexts.items()
            if context.has_direct_evidence
        }

        if structured_answers == set(required_queries):
            semantic_queries = ()
        else:
            semantic_queries = tuple(
                planned_query
                for planned_query in analysis.retrieval_queries
                if planned_query not in structured_answers
            )

        traces = self._retrieve_queries(
            analysis,
            semantic_queries,
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
        if (
            analysis.strategy == QueryStrategy.DECOMPOSE
            and hasattr(self.context_builder, "build_requirements")
        ):
            semantic_context = self.context_builder.build_requirements(
                analysis.standalone_query,
                tuple((trace.query, trace.grades) for trace in traces),
            )
        else:
            semantic_context = self.context_builder.build(
                analysis.standalone_query,
                grades,
            )
        context = (
            self.context_builder.merge(
                analysis.standalone_query,
                (
                    semantic_context,
                    *structured_contexts.values(),
                ),
            )
            if any(
                bundle.items
                for bundle in structured_contexts.values()
            )
            else semantic_context
        )
        context_seconds = perf_counter() - stage_started

        unanswered_queries = self._find_unanswered_queries(
            analysis,
            traces,
            structured_contexts,
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
                structured_seconds=round(
                    structured_seconds,
                    4,
                ),
            ),
        )

    def retrieve_direct(self, query: str) -> RetrievalResult:
        """Retrieves an already-planned corrective query without replanning."""

        query = validate_query(query, rag_settings=self.settings)
        analysis = QueryAnalysis(
            original_query=query,
            standalone_query=query,
            strategy=QueryStrategy.DIRECT,
        )
        return self.retrieve(query, _analysis_override=analysis)

    def _structured_context(
        self,
        query: str,
    ) -> ContextBundle:
        if not StructuredQueryEngine.supports(query):
            return self._empty_context(query)

        if self._structured_query_engine is None:
            self._structured_query_engine = StructuredQueryEngine(
                rag_settings=self.settings
            )

        try:
            return self._structured_query_engine.retrieve(query)
        except Exception:
            return self._empty_context(query)

    def _retrieve_query(
        self,
        query: str,
    ) -> QueryRetrievalTrace:
        candidates, hybrid_seconds = self._search_query(query)
        return self._complete_query(
            query,
            candidates,
            hybrid_seconds,
        )

    def _search_query(
        self,
        query: str,
    ) -> tuple[tuple[RetrievalHit, ...], float]:
        """Runs only hybrid candidate search for safe parallel execution."""

        started_at = perf_counter()
        candidates = self.hybrid_retriever.search(
            query,
            limit=self.settings.retrieval_candidate_limit,
        )
        return tuple(candidates), perf_counter() - started_at

    def _complete_query(
        self,
        query: str,
        candidates: tuple[RetrievalHit, ...],
        hybrid_seconds: float,
    ) -> QueryRetrievalTrace:
        """Reranks and grades one candidate set on the shared models."""

        stage_started = perf_counter()
        reranked_hits = self.reranker.rerank(query, candidates)
        reranking_seconds = perf_counter() - stage_started

        stage_started = perf_counter()
        grades = self.evidence_grader.grade(query, reranked_hits)
        grading_seconds = perf_counter() - stage_started

        return QueryRetrievalTrace(
            query=query,
            candidates=candidates,
            reranked_hits=tuple(reranked_hits),
            grades=tuple(grades),
            hybrid_seconds=hybrid_seconds,
            reranking_seconds=reranking_seconds,
            grading_seconds=grading_seconds,
        )

    def _retrieve_queries(
        self,
        analysis: QueryAnalysis,
        queries: tuple[str, ...],
    ) -> tuple[QueryRetrievalTrace, ...]:
        """Runs step-back retrieval only when the direct search fails."""

        if not queries:
            return ()

        if analysis.strategy != QueryStrategy.STEP_BACK:
            if len(queries) == 1:
                return (self._retrieve_query(queries[0]),)

            workers = max(
                1,
                min(self.settings.retrieval_parallel_workers, len(queries)),
            )
            with ThreadPoolExecutor(max_workers=workers) as executor:
                searches = tuple(executor.map(self._search_query, queries))

            # Cross-encoder and grading models are shared and may not be
            # thread-safe, so only retrieval I/O is concurrent.
            return tuple(
                self._complete_query(query, candidates, elapsed)
                for query, (candidates, elapsed) in zip(
                    queries,
                    searches,
                    strict=True,
                )
            )

        primary = self._retrieve_query(queries[0])
        direct_count = sum(
            grade.directly_answers
            for grade in primary.grades
        )

        if direct_count >= self.settings.minimum_direct_evidence:
            return (primary,)

        return (
            primary,
            *(
                self._retrieve_query(query)
                for query in queries[1:]
            ),
        )

    def _find_unanswered_queries(
        self,
        analysis: QueryAnalysis,
        traces: tuple[QueryRetrievalTrace, ...],
        structured_contexts: dict[str, ContextBundle],
    ) -> tuple[str, ...]:
        required_queries = self._required_queries(analysis)

        if analysis.strategy == QueryStrategy.STEP_BACK:
            direct_evidence_count = sum(
                grade.directly_answers
                for trace in traces
                for grade in trace.grades
            )

            return (
                ()
                if direct_evidence_count
                >= self.settings.minimum_direct_evidence
                else required_queries
            )

        trace_by_query = {
            trace.query: trace
            for trace in traces
        }

        unanswered = []

        for required_query in required_queries:
            if structured_contexts[
                required_query
            ].has_direct_evidence:
                continue

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
    def _required_queries(
        analysis: QueryAnalysis,
    ) -> tuple[str, ...]:
        return (
            analysis.subqueries
            if analysis.strategy == QueryStrategy.DECOMPOSE
            else (analysis.standalone_query,)
        )

    @staticmethod
    def _empty_context(query: str) -> ContextBundle:
        return ContextBundle(
            query=query,
            items=(),
            total_tokens=0,
            has_direct_evidence=False,
        )

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
