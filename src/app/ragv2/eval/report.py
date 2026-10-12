"""Serializable contracts produced by the RAG benchmark."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class CaseCitation:
    citation_id: str
    document_title: str
    source_uri: str
    page_number: int | None


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    should_answer: bool
    retrieval_rank: int | None
    retrieval_answerable: bool
    strategy_correct: bool | None
    answer_correct: bool | None
    grounded: bool | None
    citation_precision: float | None
    verification_passed: bool | None
    abstention_correct: bool | None
    latency_seconds: float
    error: str | None = None
    retrieval_source_recall: float | None = None
    answer_completeness: float | None = None
    forbidden_terms_passed: bool | None = None
    citation_recall: float | None = None
    false_abstention: bool = False
    false_answer: bool = False
    latency_budget_passed: bool | None = None
    retrieval_latency_seconds: float | None = None
    query_analysis_seconds: float | None = None
    hybrid_retrieval_seconds: float | None = None
    reranking_seconds: float | None = None
    grading_seconds: float | None = None
    context_build_seconds: float | None = None
    correction_seconds: float | None = None
    provider_failure_count: int = 0
    schema_invalid_count: int = 0
    fallback_used_count: int = 0
    tags: tuple[str, ...] = ()
    provider_call_counts: tuple[tuple[str, int], ...] = ()
    model_outcome_counts: tuple[tuple[str, int], ...] = ()
    question: str = ""
    answer_text: str | None = None
    answer_abstained: bool | None = None
    confidence_reason: str | None = None
    unsupported_claims: tuple[str, ...] = ()
    missing_fact_groups: tuple[tuple[str, ...], ...] = ()
    citations: tuple[CaseCitation, ...] = ()
    verification_confidence_reason: str | None = None
    verification_unsupported_claims: tuple[str, ...] = ()
    verification_contradicted_claims: tuple[str, ...] = ()
    route_history: tuple[str, ...] = ()
    model_calls: tuple[dict[str, object], ...] = ()
    evaluation_seconds: float | None = None
    evaluation_model_calls: tuple[dict[str, object], ...] = ()
    error_message: str | None = None
    query_strategy: str | None = None
    planned_queries: tuple[str, ...] = ()
    unanswered_queries: tuple[str, ...] = ()
    retrieval_trace_count: int = 0
    correction_targets: tuple[str, ...] = ()
    rewritten_queries: tuple[str, ...] = ()
    context_item_count: int = 0
    context_token_count: int = 0
    context_sources: tuple[str, ...] = ()
    standalone_query: str | None = None
    step_back_query: str | None = None
    retrieval_details: tuple[dict[str, object], ...] = ()
    correction_details: tuple[dict[str, object], ...] = ()
    context_details: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    dataset: str
    retrieval_only: bool
    case_count: int
    successful_cases: int
    hit_at_1_percent: float
    hit_at_5_percent: float
    mean_reciprocal_rank: float
    no_answer_rejection_percent: float
    answer_required_term_accuracy_percent: float | None
    grounded_answer_rate_percent: float | None
    citation_precision_percent: float | None
    verification_pass_percent: float | None
    average_latency_seconds: float
    p95_latency_seconds: float
    cases: tuple[CaseResult, ...]
    retrieval_source_recall_percent: float = 0.0
    retrieval_answerability_percent: float = 0.0
    answer_completeness_percent: float | None = None
    citation_recall_percent: float | None = None
    false_abstention_rate_percent: float | None = None
    false_answer_rate_percent: float | None = None
    latency_budget_pass_percent: float | None = None
    average_retrieval_latency_seconds: float = 0.0
    provider_failure_count: int = 0
    schema_invalid_count: int = 0
    fallback_used_count: int = 0
    passed_quality_gates: bool = True
    failed_quality_gates: tuple[str, ...] = ()
    category_results: (
        dict[str, dict[str, float | int | None]] | None
    ) = None
    execution_success_percent: float = 0.0
    model_call_count: int = 0
    provider_call_counts: dict[str, int] | None = None
    model_outcome_counts: dict[str, int] | None = None
    strategy_accuracy_percent: float | None = None
    terminated_early: bool = False
    termination_reason: str | None = None
    completed_case_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)
