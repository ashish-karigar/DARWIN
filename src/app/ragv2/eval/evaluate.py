import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from app.ragv2.config import PROJECT_ROOT
from app.llm.telemetry import ModelCallEvent, capture_model_calls
from app.ragv2.eval.datasets import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationQualityGates,
    load_dataset,
)
from app.ragv2.eval.fact_judge import FactCoverageJudge, FactCoverageResult
from app.ragv2.eval.metrics import (
    excludes_forbidden_terms,
    fact_recall,
    missing_fact_groups,
    percentage,
    percentile,
    source_coverage,
    source_matches,
)
from app.ragv2.eval.pacing import FixedBatchPacer, PacingPause
from app.ragv2.eval.console_report import render_console_report
from app.ragv2.eval.report import (
    CaseCitation,
    CaseResult,
    EvaluationReport,
)
from app.ragv2.eval.selection import failed_case_ids_from_report
from app.ragv2.retrieve.retrieve import (
    RetrievalPipeline,
    RetrievalResult,
)
from app.ragv2.service import RagResponse, RagService


DEFAULT_DATASET = (
    PROJECT_ROOT / "data" / "ragv2" / "evaluation"
    / "production_cases.json"
)


def _passage_excerpt(text: str, limit: int = 280) -> str:
    normalized = " ".join(text.split())
    return (
        normalized
        if len(normalized) <= limit
        else normalized[: limit - 1].rstrip() + "…"
    )


def _retrieval_stage_details(
    retrieval: RetrievalResult,
) -> tuple[dict[str, object], ...]:
    """Captures readable retrieval artifacts for terminal diagnostics."""

    details = []
    for trace in getattr(retrieval, "traces", ()):
        grade_by_chunk = {
            grade.hit.chunk.chunk_id: grade
            for grade in trace.grades
        }
        hits = []
        for hit in trace.reranked_hits[:5]:
            grade = grade_by_chunk.get(hit.chunk.chunk_id)
            hits.append(
                {
                    "rank": hit.rank,
                    "score": round(hit.score, 3),
                    "document": hit.chunk.document_id,
                    "page": hit.chunk.page_number,
                    "text": _passage_excerpt(hit.chunk.text),
                    "relevant": (
                        grade.is_relevant if grade is not None else None
                    ),
                    "direct": (
                        grade.directly_answers if grade is not None else None
                    ),
                    "grade": (
                        round(grade.relevance_score, 3)
                        if grade is not None
                        else None
                    ),
                    "reason": grade.reason if grade is not None else None,
                }
            )
        details.append(
            {
                "query": trace.query,
                "candidate_count": len(trace.candidates),
                "hits": tuple(hits),
            }
        )
    return tuple(details)


def _timing_fields(timings) -> dict[str, float | None]:
    """Maps a RetrievalTimings span onto the CaseResult's per-stage fields."""

    return {
        "query_analysis_seconds": getattr(
            timings, "query_analysis_seconds", None
        ),
        "hybrid_retrieval_seconds": getattr(
            timings, "hybrid_seconds", None
        ),
        "reranking_seconds": getattr(timings, "reranking_seconds", None),
        "grading_seconds": getattr(timings, "grading_seconds", None),
        "context_build_seconds": getattr(timings, "context_seconds", None),
    }


def _fact_coverage(
    fact_judge: FactCoverageJudge | None,
    answer_text: str,
    fact_groups: tuple[tuple[str, ...], ...],
) -> FactCoverageResult:
    """Scores required facts by meaning when a judge is available.

    Falls back to literal substring matching only when no judge was
    supplied (e.g. unit tests scoring a case in isolation), so the
    semantic grader is what actually runs during a real evaluation.
    """

    if fact_judge is not None:
        return fact_judge.coverage(answer_text, fact_groups)
    return FactCoverageResult(
        percent=fact_recall(answer_text, fact_groups),
        missing_groups=missing_fact_groups(answer_text, fact_groups),
    )


def _context_stage_details(context) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "document": item.document_title,
            "page": item.page_number,
            "direct": item.directly_answers,
            "score": round(item.relevance_score, 3),
            "text": _passage_excerpt(item.text),
        }
        for item in context.items
    )


class RagEvaluator:
    """Runs reproducible retrieval and end-to-end RAG evaluations."""

    def __init__(
        self,
        retrieval_pipeline: RetrievalPipeline | None = None,
        rag_service: RagService | None = None,
        benchmark_pacer: FixedBatchPacer | None = None,
        stop_on_provider_failure: bool = False,
        fact_coverage_judge: FactCoverageJudge | None = None,
    ):
        self.retrieval_pipeline = retrieval_pipeline
        self.rag_service = rag_service
        self.benchmark_pacer = benchmark_pacer
        self.stop_on_provider_failure = stop_on_provider_failure
        self.fact_coverage_judge = fact_coverage_judge

    def evaluate(
        self,
        dataset: EvaluationDataset,
        *,
        retrieval_only: bool = False,
        progress: Callable[[int, int, CaseResult], None] | None = None,
    ) -> EvaluationReport:
        service = None

        if not retrieval_only:
            service = self.rag_service or RagService()

        results = []
        total_cases = len(dataset.cases)
        if self.benchmark_pacer is not None:
            self.benchmark_pacer.before_run(total_cases=total_cases)

        termination_reason = None
        for index, case in enumerate(dataset.cases, start=1):
            result = self._run_case(
                case,
                retrieval_only=retrieval_only,
                service=service,
            )
            results.append(result)
            if progress is not None:
                progress(index, total_cases, result)

            if (
                self.stop_on_provider_failure
                and self._provider_contaminated(result)
            ):
                termination_reason = (
                    "Provider contamination detected in "
                    f"{case.case_id}; remaining cases were not run."
                )
                for remaining in dataset.cases[index:]:
                    results.append(
                        self._skipped_case(
                            remaining,
                            termination_reason,
                        )
                    )
                break

            if self.benchmark_pacer is not None:
                self.benchmark_pacer.after_case(
                    completed_cases=index,
                    total_cases=total_cases,
                )

        return self._report(
            dataset.name,
            retrieval_only,
            tuple(results),
            quality_gates=dataset.quality_gates,
            termination_reason=termination_reason,
        )

    @staticmethod
    def _provider_contaminated(result: CaseResult) -> bool:
        # A rate limit or a circuit-open skip is expected, handled
        # behavior now: StructuredModelRunner already waits out a short
        # provider-quoted window and retries before ever reaching here,
        # so one still showing up in provider_failure_count just means
        # that self-recovery worked (or fallback covered it, counted
        # separately below) -- not that this case's result is degraded.
        # A bare "failure" outcome is different: an error the runner
        # doesn't already know how to recover from (bad model name,
        # auth, network), and is still worth stopping the batch for.
        non_recoverable_failure = any(
            call.get("outcome") == "failure"
            for call in result.model_calls
        )
        return non_recoverable_failure

    @staticmethod
    def _skipped_case(
        case: EvaluationCase,
        reason: str,
    ) -> CaseResult:
        return CaseResult(
            case_id=case.case_id,
            should_answer=case.should_answer,
            retrieval_rank=None,
            retrieval_answerable=False,
            strategy_correct=None,
            answer_correct=None,
            grounded=None,
            citation_precision=None,
            verification_passed=None,
            abstention_correct=None,
            latency_seconds=0.0,
            error="SkippedAfterProviderFailure",
            tags=case.tags,
            question=case.question,
            error_message=reason,
        )

    def _run_case(
        self,
        case: EvaluationCase,
        *,
        retrieval_only: bool,
        service: RagService | None,
    ) -> CaseResult:
        started_at = perf_counter()
        captured_calls: list[ModelCallEvent] = []

        try:
            with capture_model_calls() as captured_calls:
                response = (
                    None
                    if retrieval_only
                    else service.ask(
                        case.question,
                        conversation_context=case.conversation_context,
                    )
                )
                retrieval = (
                    self._get_retrieval_pipeline().retrieve(
                        case.question,
                        conversation_context=case.conversation_context,
                    )
                    if retrieval_only
                    else response.retrieval
                )
            # Response latency stops when the RAG system has produced its
            # answer. Benchmark-only fact judging happens afterward and
            # must not be reported as user-visible DARWIN latency.
            response_latency = perf_counter() - started_at
            evaluation_calls: list[ModelCallEvent] = []
            fact_coverage = None
            evaluation_started_at = perf_counter()
            if not retrieval_only and case.should_answer:
                with capture_model_calls() as evaluation_calls:
                    fact_coverage = self._get_fact_coverage_judge().coverage(
                        response.answer.answer,
                        case.fact_groups,
                    )
            evaluation_seconds = perf_counter() - evaluation_started_at

            return self._score_case(
                case,
                retrieval,
                response,
                response_latency,
                model_calls=(
                    tuple(captured_calls)
                    if retrieval_only
                    else tuple(response.model_calls)
                ),
                fact_coverage=fact_coverage,
                evaluation_seconds=evaluation_seconds,
                evaluation_model_calls=tuple(evaluation_calls),
            )
        except Exception as error:
            model_calls = tuple(captured_calls)
            return CaseResult(
                case_id=case.case_id,
                should_answer=case.should_answer,
                retrieval_rank=None,
                retrieval_answerable=False,
                strategy_correct=None,
                answer_correct=None,
                grounded=None,
                citation_precision=None,
                verification_passed=None,
                abstention_correct=None,
                latency_seconds=round(perf_counter() - started_at, 4),
                error=type(error).__name__,
                tags=case.tags,
                question=case.question,
                provider_failure_count=sum(
                    event.outcome in {
                        "failure",
                        "rate_limited",
                        "circuit_open",
                    }
                    for event in model_calls
                ),
                schema_invalid_count=sum(
                    event.outcome == "schema_invalid"
                    for event in model_calls
                ),
                fallback_used_count=sum(
                    event.outcome == "success"
                    and event.used_fallback
                    for event in model_calls
                ),
                provider_call_counts=tuple(
                    sorted(
                        Counter(
                            event.provider for event in model_calls
                        ).items()
                    )
                ),
                model_outcome_counts=tuple(
                    sorted(
                        Counter(
                            event.outcome for event in model_calls
                        ).items()
                    )
                ),
                model_calls=tuple(
                    event.as_dict() for event in model_calls
                ),
                error_message=" ".join(str(error).split())[:500],
            )

    def _get_retrieval_pipeline(self) -> RetrievalPipeline:
        if self.retrieval_pipeline is None:
            self.retrieval_pipeline = RetrievalPipeline()
        return self.retrieval_pipeline

    def _get_fact_coverage_judge(self) -> FactCoverageJudge:
        if self.fact_coverage_judge is None:
            self.fact_coverage_judge = FactCoverageJudge()
        return self.fact_coverage_judge

    @staticmethod
    def _score_case(
        case: EvaluationCase,
        retrieval: RetrievalResult,
        response: RagResponse | None,
        latency: float,
        model_calls: tuple[ModelCallEvent, ...] = (),
        fact_judge: FactCoverageJudge | None = None,
        fact_coverage: FactCoverageResult | None = None,
        evaluation_seconds: float | None = None,
        evaluation_model_calls: tuple[ModelCallEvent, ...] = (),
    ) -> CaseResult:
        rank = next(
            (
                index
                for index, hit in enumerate(
                    retrieval.reranked_hits,
                    start=1,
                )
                if source_matches(
                    hit.chunk.source_uri,
                    case.expected_source_suffixes,
                )
            ),
            None,
        )
        if rank is None and any(
            source_matches(
                item.source_uri,
                case.expected_source_suffixes,
            )
            for item in retrieval.context.items
        ):
            rank = 1
        strategy_correct = (
            None
            if case.expected_strategy is None
            else retrieval.analysis.strategy
            == case.expected_strategy
        )
        retrieved_source_uris = tuple(
            dict.fromkeys(
                (
                    *(hit.chunk.source_uri for hit in retrieval.reranked_hits),
                    *(item.source_uri for item in retrieval.context.items),
                )
            )
        )
        retrieval_source_recall = source_coverage(
            retrieved_source_uris,
            case.expected_source_suffixes,
        ) if case.should_answer else None

        if response is None:
            return CaseResult(
                case_id=case.case_id,
                should_answer=case.should_answer,
                retrieval_rank=rank,
                retrieval_answerable=retrieval.fully_answerable,
                strategy_correct=strategy_correct,
                answer_correct=None,
                grounded=None,
                citation_precision=None,
                verification_passed=None,
                abstention_correct=(
                    (not retrieval.fully_answerable)
                    if not case.should_answer
                    else None
                ),
                latency_seconds=round(latency, 4),
                retrieval_source_recall=retrieval_source_recall,
                latency_budget_passed=(
                    None
                    if case.maximum_latency_seconds is None
                    else latency <= case.maximum_latency_seconds
                ),
                retrieval_latency_seconds=(
                    retrieval.timings.total_seconds
                ),
                **_timing_fields(retrieval.timings),
                tags=case.tags,
                provider_failure_count=sum(
                    event.outcome in {
                        "failure",
                        "rate_limited",
                        "circuit_open",
                    }
                    for event in model_calls
                ),
                schema_invalid_count=sum(
                    event.outcome == "schema_invalid"
                    for event in model_calls
                ),
                fallback_used_count=sum(
                    event.outcome == "success"
                    and event.used_fallback
                    for event in model_calls
                ),
                provider_call_counts=tuple(
                    sorted(
                        Counter(
                            event.provider for event in model_calls
                        ).items()
                    )
                ),
                model_outcome_counts=tuple(
                    sorted(
                        Counter(
                            event.outcome for event in model_calls
                        ).items()
                    )
                ),
                question=case.question,
                model_calls=tuple(
                    event.as_dict() for event in model_calls
                ),
                query_strategy=getattr(
                    retrieval.analysis.strategy,
                    "value",
                    str(retrieval.analysis.strategy),
                ),
                planned_queries=tuple(
                    getattr(retrieval.analysis, "retrieval_queries", ())
                ),
                unanswered_queries=tuple(
                    getattr(retrieval, "unanswered_queries", ())
                ),
                retrieval_trace_count=len(
                    getattr(retrieval, "traces", ())
                ),
                context_item_count=len(retrieval.context.items),
                context_token_count=getattr(
                    retrieval.context,
                    "total_tokens",
                    0,
                ),
                standalone_query=getattr(
                    retrieval.analysis,
                    "standalone_query",
                    None,
                ),
                step_back_query=getattr(
                    retrieval.analysis,
                    "step_back_query",
                    None,
                ),
                retrieval_details=_retrieval_stage_details(retrieval),
                context_details=_context_stage_details(retrieval.context),
            )

        answer = response.answer
        precision = (
            percentage(
                sum(
                    source_matches(
                        citation.source_uri,
                        case.expected_source_suffixes,
                    )
                    for citation in answer.citations
                ),
                len(answer.citations),
            )
            if answer.citations
            else 0.0
        )
        citation_source_uris = tuple(
            citation.source_uri
            for citation in answer.citations
        )
        citation_recall = (
            source_coverage(
                citation_source_uris,
                case.required_citation_sources,
            )
            if case.should_answer
            else None
        )
        fact_coverage = (
            fact_coverage
            or _fact_coverage(fact_judge, answer.answer, case.fact_groups)
            if case.should_answer
            else None
        )
        completeness = (
            (0.0 if answer.abstained else fact_coverage.percent)
            if case.should_answer
            else None
        )
        forbidden_passed = (
            excludes_forbidden_terms(
                answer.answer,
                case.forbidden_terms,
            )
            if case.should_answer and not answer.abstained
            else (False if case.should_answer else None)
        )
        provider_failure_count = sum(
            event.outcome in {
                "failure",
                "rate_limited",
                "circuit_open",
            }
            for event in model_calls
        )
        schema_invalid_count = sum(
            event.outcome == "schema_invalid"
            for event in model_calls
        )
        fallback_used_count = sum(
            event.outcome == "success" and event.used_fallback
            for event in model_calls
        )
        provider_call_counts = Counter(
            event.provider for event in model_calls
        )
        model_outcome_counts = Counter(
            event.outcome for event in model_calls
        )
        answer_correct = (
            bool(
                not answer.abstained
                and completeness == 100.0
                and forbidden_passed
            )
            if case.should_answer
            else False
        )
        verification = response.verification
        final_context = (
            getattr(response, "final_context", None)
            or retrieval.context
        )
        correction_results = getattr(response, "correction_results", ())
        correction_seconds = (
            sum(
                correction.timings.total_seconds
                for correction in correction_results
            )
            if correction_results
            else None
        )

        return CaseResult(
            case_id=case.case_id,
            should_answer=case.should_answer,
            retrieval_rank=rank,
            retrieval_answerable=retrieval.fully_answerable,
            strategy_correct=strategy_correct,
            answer_correct=answer_correct,
            grounded=answer.is_grounded,
            citation_precision=precision,
            verification_passed=(
                response.verification.is_supported
                if response.verification is not None
                else answer.abstained
            ),
            abstention_correct=(
                answer.abstained
                if not case.should_answer
                else None
            ),
            latency_seconds=round(latency, 4),
            retrieval_source_recall=retrieval_source_recall,
            answer_completeness=completeness,
            forbidden_terms_passed=forbidden_passed,
            citation_recall=citation_recall,
            false_abstention=(
                case.should_answer and answer.abstained
            ),
            false_answer=(
                not case.should_answer and not answer.abstained
            ),
            latency_budget_passed=(
                None
                if case.maximum_latency_seconds is None
                else latency <= case.maximum_latency_seconds
            ),
            retrieval_latency_seconds=(
                retrieval.timings.total_seconds
            ),
            **_timing_fields(retrieval.timings),
            correction_seconds=correction_seconds,
            provider_failure_count=provider_failure_count,
            schema_invalid_count=schema_invalid_count,
            fallback_used_count=fallback_used_count,
            tags=case.tags,
            provider_call_counts=tuple(
                sorted(provider_call_counts.items())
            ),
            model_outcome_counts=tuple(
                sorted(model_outcome_counts.items())
            ),
            question=case.question,
            answer_text=answer.answer,
            answer_abstained=answer.abstained,
            confidence_reason=answer.confidence_reason,
            unsupported_claims=answer.unsupported_claims,
            missing_fact_groups=(
                fact_coverage.missing_groups
                if case.should_answer
                else ()
            ),
            citations=tuple(
                CaseCitation(
                    citation_id=citation.citation_id,
                    document_title=citation.document_title,
                    source_uri=citation.source_uri,
                    page_number=citation.page_number,
                )
                for citation in answer.citations
            ),
            verification_confidence_reason=(
                verification.confidence_reason
                if verification is not None
                else None
            ),
            verification_unsupported_claims=(
                verification.unsupported_claims
                if verification is not None
                else ()
            ),
            verification_contradicted_claims=(
                verification.contradicted_claims
                if verification is not None
                else ()
            ),
            route_history=response.route_history,
            model_calls=tuple(
                event.as_dict() for event in model_calls
            ),
            evaluation_seconds=(
                round(evaluation_seconds, 4)
                if evaluation_seconds is not None
                else None
            ),
            evaluation_model_calls=tuple(
                event.as_dict() for event in evaluation_model_calls
            ),
            query_strategy=getattr(
                retrieval.analysis.strategy,
                "value",
                str(retrieval.analysis.strategy),
            ),
            planned_queries=tuple(
                getattr(retrieval.analysis, "retrieval_queries", ())
            ),
            unanswered_queries=tuple(
                getattr(retrieval, "unanswered_queries", ())
            ),
            retrieval_trace_count=len(
                getattr(retrieval, "traces", ())
            ),
            correction_targets=tuple(
                getattr(response, "correction_targets", ())
            ),
            rewritten_queries=tuple(
                getattr(response, "rewritten_queries", ())
            ),
            context_item_count=len(final_context.items),
            context_token_count=getattr(
                final_context,
                "total_tokens",
                0,
            ),
            context_sources=tuple(
                dict.fromkeys(
                    (
                        f"{item.document_title}"
                        + (
                            f" p.{item.page_number}"
                            if item.page_number is not None
                            else ""
                        )
                    )
                    for item in final_context.items
                )
            ),
            standalone_query=getattr(
                retrieval.analysis,
                "standalone_query",
                None,
            ),
            step_back_query=getattr(
                retrieval.analysis,
                "step_back_query",
                None,
            ),
            retrieval_details=_retrieval_stage_details(retrieval),
            correction_details=tuple(
                detail
                for correction in getattr(
                    response,
                    "correction_results",
                    (),
                )
                for detail in _retrieval_stage_details(correction)
            ),
            context_details=_context_stage_details(final_context),
        )

    @staticmethod
    def _report(
        dataset_name: str,
        retrieval_only: bool,
        cases: tuple[CaseResult, ...],
        quality_gates: EvaluationQualityGates | None = None,
        termination_reason: str | None = None,
    ) -> EvaluationReport:
        successful = tuple(case for case in cases if case.error is None)
        answerable = tuple(case for case in successful if case.should_answer)
        no_answer = tuple(case for case in successful if not case.should_answer)
        ranks = tuple(
            case.retrieval_rank
            for case in answerable
            if case.retrieval_rank is not None
        )
        latencies = tuple(case.latency_seconds for case in successful)

        def optional_percent(values):
            values = tuple(value for value in values if value is not None)
            return (
                percentage(sum(bool(value) for value in values), len(values))
                if values
                else None
            )

        citation_values = tuple(
            case.citation_precision
            for case in answerable
            if case.citation_precision is not None
        )
        retrieval_source_values = tuple(
            case.retrieval_source_recall
            for case in answerable
            if case.retrieval_source_recall is not None
        )
        retrieval_answerability = optional_percent(
            case.retrieval_answerable for case in answerable
        ) or 0.0
        completeness_values = tuple(
            case.answer_completeness
            for case in answerable
            if case.answer_completeness is not None
        )
        citation_recall_values = tuple(
            case.citation_recall
            for case in answerable
            if case.citation_recall is not None
        )
        retrieval_latencies = tuple(
            case.retrieval_latency_seconds
            for case in successful
            if case.retrieval_latency_seconds is not None
        )
        latency_budget_values = tuple(
            case.latency_budget_passed
            for case in successful
            if case.latency_budget_passed is not None
        )
        strategy_values = tuple(
            case.strategy_correct
            for case in successful
            if case.strategy_correct is not None
        )

        def mean(values) -> float:
            return (
                round(sum(values) / len(values), 2)
                if values
                else 0.0
            )

        answer_accuracy = (
            None
            if retrieval_only
            else optional_percent(
                case.answer_correct for case in answerable
            )
        )
        answer_completeness = (
            None if retrieval_only else mean(completeness_values)
        )
        citation_recall_percent = (
            None if retrieval_only else mean(citation_recall_values)
        )
        false_abstention_rate = (
            None
            if retrieval_only
            else percentage(
                sum(case.false_abstention for case in answerable),
                len(answerable),
            )
        )
        false_answer_rate = (
            None
            if retrieval_only
            else percentage(
                sum(case.false_answer for case in no_answer),
                len(no_answer),
            )
        )
        no_answer_rejection = (
            optional_percent(
                case.abstention_correct for case in no_answer
            )
            or 0.0
        )
        p95_latency = percentile(latencies, 0.95)
        gates = quality_gates or EvaluationQualityGates()
        failed_gates = []
        execution_success = percentage(
            len(successful),
            len(cases),
        )

        category_results = {}
        all_tags = sorted(
            {tag for case in successful for tag in case.tags}
        )
        for tag in all_tags:
            tagged = tuple(
                case for case in successful if tag in case.tags
            )
            tagged_answerable = tuple(
                case for case in tagged if case.should_answer
            )
            tagged_no_answer = tuple(
                case for case in tagged if not case.should_answer
            )
            category_results[tag] = {
                "case_count": len(tagged),
                "answer_accuracy_percent": (
                    percentage(
                        sum(
                            bool(case.answer_correct)
                            for case in tagged_answerable
                        ),
                        len(tagged_answerable),
                    )
                    if not retrieval_only and tagged_answerable
                    else None
                ),
                "retrieval_source_recall_percent": mean(
                    tuple(
                        case.retrieval_source_recall
                        for case in tagged_answerable
                        if case.retrieval_source_recall is not None
                    )
                ),
                "strategy_accuracy_percent": (
                    percentage(
                        sum(
                            bool(case.strategy_correct)
                            for case in tagged
                            if case.strategy_correct is not None
                        ),
                        sum(
                            case.strategy_correct is not None
                            for case in tagged
                        ),
                    )
                    if any(
                        case.strategy_correct is not None
                        for case in tagged
                    )
                    else None
                ),
                "no_answer_rejection_percent": (
                    percentage(
                        sum(
                            bool(case.abstention_correct)
                            for case in tagged_no_answer
                        ),
                        len(tagged_no_answer),
                    )
                    if tagged_no_answer
                    else None
                ),
                "average_latency_seconds": round(
                    sum(case.latency_seconds for case in tagged)
                    / len(tagged),
                    4,
                ),
            }

        if execution_success < gates.execution_success_min_percent:
            failed_gates.append("execution_success")

        if answerable and mean(retrieval_source_values) < (
            gates.retrieval_source_recall_min_percent
        ):
            failed_gates.append("retrieval_source_recall")

        if answerable and retrieval_answerability < (
            gates.retrieval_answerability_min_percent
        ):
            failed_gates.append("retrieval_answerability")

        strategy_accuracy = (
            percentage(
                sum(bool(value) for value in strategy_values),
                len(strategy_values),
            )
            if strategy_values
            else None
        )
        if (
            strategy_accuracy is not None
            and strategy_accuracy
            < gates.strategy_accuracy_min_percent
        ):
            failed_gates.append("strategy_accuracy")

        if no_answer and no_answer_rejection < (
            gates.no_answer_rejection_min_percent
        ):
            failed_gates.append("no_answer_rejection")

        if not retrieval_only and answerable:
            if (answer_accuracy or 0.0) < gates.answer_accuracy_min_percent:
                failed_gates.append("answer_accuracy")
            if (answer_completeness or 0.0) < (
                gates.answer_completeness_min_percent
            ):
                failed_gates.append("answer_completeness")
            if (citation_recall_percent or 0.0) < (
                gates.citation_recall_min_percent
            ):
                failed_gates.append("citation_recall")
            if (false_abstention_rate or 0.0) > (
                gates.false_abstention_max_percent
            ):
                failed_gates.append("false_abstention_rate")

        if (
            gates.p95_latency_max_seconds is not None
            and p95_latency > gates.p95_latency_max_seconds
        ):
            failed_gates.append("p95_latency")

        latency_budget_pass = (
            percentage(
                sum(latency_budget_values),
                len(latency_budget_values),
            )
            if latency_budget_values
            else None
        )
        if (
            latency_budget_pass is not None
            and latency_budget_pass
            < gates.latency_budget_pass_min_percent
        ):
            failed_gates.append("latency_budget_pass")

        provider_totals = Counter()
        outcome_totals = Counter()
        for case in successful:
            provider_totals.update(dict(case.provider_call_counts))
            outcome_totals.update(dict(case.model_outcome_counts))

        return EvaluationReport(
            dataset=dataset_name,
            retrieval_only=retrieval_only,
            case_count=len(cases),
            successful_cases=len(successful),
            hit_at_1_percent=percentage(
                sum(rank == 1 for rank in ranks),
                len(answerable),
            ),
            hit_at_5_percent=percentage(
                sum(rank <= 5 for rank in ranks),
                len(answerable),
            ),
            mean_reciprocal_rank=round(
                sum(1 / rank for rank in ranks) / len(answerable),
                4,
            ) if answerable else 0.0,
            no_answer_rejection_percent=no_answer_rejection,
            answer_required_term_accuracy_percent=answer_accuracy,
            grounded_answer_rate_percent=(
                None
                if retrieval_only
                else optional_percent(
                    case.grounded for case in answerable
                )
            ),
            citation_precision_percent=(
                None
                if retrieval_only
                else (
                    round(
                        sum(citation_values) / len(citation_values),
                        2,
                    )
                    if citation_values
                    else 0.0
                )
            ),
            verification_pass_percent=(
                None
                if retrieval_only
                else optional_percent(
                    case.verification_passed
                    for case in answerable
                )
            ),
            average_latency_seconds=round(
                sum(latencies) / len(latencies),
                4,
            ) if latencies else 0.0,
            p95_latency_seconds=p95_latency,
            cases=cases,
            retrieval_source_recall_percent=mean(
                retrieval_source_values
            ),
            retrieval_answerability_percent=retrieval_answerability,
            answer_completeness_percent=answer_completeness,
            citation_recall_percent=citation_recall_percent,
            false_abstention_rate_percent=false_abstention_rate,
            false_answer_rate_percent=false_answer_rate,
            latency_budget_pass_percent=(
                latency_budget_pass
            ),
            average_retrieval_latency_seconds=(
                round(
                    sum(retrieval_latencies)
                    / len(retrieval_latencies),
                    4,
                )
                if retrieval_latencies
                else 0.0
            ),
            provider_failure_count=sum(
                case.provider_failure_count for case in successful
            ),
            schema_invalid_count=sum(
                case.schema_invalid_count for case in successful
            ),
            fallback_used_count=sum(
                case.fallback_used_count for case in successful
            ),
            passed_quality_gates=not failed_gates,
            failed_quality_gates=tuple(failed_gates),
            category_results=category_results,
            execution_success_percent=execution_success,
            model_call_count=sum(outcome_totals.values()),
            provider_call_counts=dict(sorted(provider_totals.items())),
            model_outcome_counts=dict(sorted(outcome_totals.items())),
            strategy_accuracy_percent=strategy_accuracy,
            terminated_early=termination_reason is not None,
            termination_reason=termination_reason,
            completed_case_count=len(successful),
        )


def _print_progress(
    index: int,
    total: int,
    result: CaseResult,
) -> None:
    if result.error:
        status = f"error={result.error}"
    elif result.provider_failure_count:
        status = "provider-failed"
    elif result.fallback_used_count:
        status = "fallback-used"
    else:
        status = "completed"
    print(
        f"[{index}/{total}] {result.case_id}: {status} "
        f"in {result.latency_seconds:.2f}s",
        file=sys.stderr,
        flush=True,
    )


def _print_report_summary(
    report: EvaluationReport,
    output_path: Path,
) -> None:
    print(
        "\n" + render_console_report(report, output_path),
        file=sys.stderr,
        flush=True,
    )


def _print_pacing_pause(pause: PacingPause) -> None:
    if pause.reason == "initial-cooldown":
        message = (
            "Groq preflight cooldown: "
            f"waiting {pause.seconds:.0f}s for a clean rate window."
        )
    else:
        message = (
            "Groq safety pause: "
            f"{pause.seconds:.0f}s after "
            f"{pause.completed_cases}/{pause.total_cases} cases."
        )

    print(
        message,
        file=sys.stderr,
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
    )
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
    )
    parser.add_argument(
        "--local-model",
        action="store_true",
        help="Use local Qwen instead of the configured cloud model.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--enforce-gates",
        action="store_true",
        help="Exit unsuccessfully when a dataset quality gate fails.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Run one case ID. Repeat to select multiple cases.",
    )
    parser.add_argument(
        "--rerun-failed",
        type=Path,
        help="Run only failed or provider-contaminated cases in a report.",
    )
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Run cases containing any selected tag. Repeatable.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Run only the first N selected cases.",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Print one stderr status line after every completed case.",
    )
    parser.add_argument(
        "--no-rate-pacing",
        action="store_true",
        help=(
            "Disable the default Groq free-plan pause after every two "
            "cloud-backed cases."
        ),
    )
    parser.add_argument(
        "--cases-per-batch",
        type=int,
        default=2,
        help="Cloud benchmark cases to run before pausing (default: 2).",
    )
    parser.add_argument(
        "--pacing-pause-seconds",
        type=float,
        default=60.0,
        help="Seconds to pause between cloud case batches (default: 60).",
    )
    parser.add_argument(
        "--initial-cooldown-seconds",
        type=float,
        default=60.0,
        help="Clean-window wait before a cloud benchmark (default: 60).",
    )
    parser.add_argument(
        "--continue-on-provider-failure",
        action="store_true",
        help=(
            "Continue after provider failure or fallback. This makes a "
            "release benchmark provider-contaminated."
        ),
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print full JSON even when --output saves a report file.",
    )
    arguments = parser.parse_args()

    if arguments.limit is not None and arguments.limit < 1:
        parser.error("--limit must be at least 1")
    if arguments.cases_per_batch < 1:
        parser.error("--cases-per-batch must be at least 1")
    if arguments.pacing_pause_seconds < 0:
        parser.error("--pacing-pause-seconds cannot be negative")
    if arguments.initial_cooldown_seconds < 0:
        parser.error("--initial-cooldown-seconds cannot be negative")
    if arguments.rerun_failed and arguments.case_id:
        parser.error("--rerun-failed cannot be combined with --case-id")

    rag_service = None
    if arguments.local_model and not arguments.retrieval_only:
        from app.ragv2.eval.runtime import create_local_rag_service

        rag_service = create_local_rag_service()

    case_ids = (
        failed_case_ids_from_report(arguments.rerun_failed)
        if arguments.rerun_failed
        else tuple(arguments.case_id)
    )
    dataset = load_dataset(arguments.dataset).select(
        case_ids=case_ids,
        tags=tuple(arguments.tag),
        limit=arguments.limit,
    )
    cloud_run = (
        not arguments.retrieval_only
        and not arguments.local_model
    )
    use_rate_pacing = (
        cloud_run
        and not arguments.no_rate_pacing
    )
    benchmark_pacer = (
        FixedBatchPacer(
            cases_per_batch=arguments.cases_per_batch,
            pause_seconds=arguments.pacing_pause_seconds,
            initial_cooldown_seconds=(
                arguments.initial_cooldown_seconds
            ),
            on_pause=_print_pacing_pause,
        )
        if use_rate_pacing
        else None
    )

    report = RagEvaluator(
        rag_service=rag_service,
        benchmark_pacer=benchmark_pacer,
        stop_on_provider_failure=(
            cloud_run
            and not arguments.continue_on_provider_failure
        ),
    ).evaluate(
        dataset,
        retrieval_only=arguments.retrieval_only,
        progress=(
            _print_progress if arguments.progress else None
        ),
    )
    payload = json.dumps(report.to_dict(), indent=2)

    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload + "\n", encoding="utf-8")
        _print_report_summary(report, arguments.output)

    if arguments.print_json or not arguments.output:
        print(payload)

    if arguments.enforce_gates and not report.passed_quality_gates:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
