from pathlib import Path

from app.ragv2.eval.console_report import render_console_report
from app.ragv2.eval.report import CaseResult, EvaluationReport


def _report(*cases: CaseResult, retrieval_only: bool = False):
    return EvaluationReport(
        dataset="Test dataset",
        retrieval_only=retrieval_only,
        case_count=len(cases),
        successful_cases=len(cases),
        hit_at_1_percent=100.0,
        hit_at_5_percent=100.0,
        mean_reciprocal_rank=1.0,
        no_answer_rejection_percent=100.0,
        answer_required_term_accuracy_percent=(
            None if retrieval_only else 100.0
        ),
        grounded_answer_rate_percent=None,
        citation_precision_percent=None,
        verification_pass_percent=None,
        average_latency_seconds=1.0,
        p95_latency_seconds=1.0,
        cases=cases,
        passed_quality_gates=True,
        completed_case_count=len(cases),
    )


def test_renders_case_and_failure_tables():
    failed = CaseResult(
        case_id="paper-memory",
        should_answer=True,
        retrieval_rank=1,
        retrieval_answerable=True,
        strategy_correct=True,
        answer_correct=False,
        grounded=True,
        citation_precision=100.0,
        verification_passed=True,
        abstention_correct=None,
        latency_seconds=24.65,
        answer_completeness=50.0,
        citation_recall=100.0,
        missing_fact_groups=(("Wikipedia",),),
        provider_call_counts=(("groq", 1), ("ollama", 1)),
        query_analysis_seconds=0.05,
        hybrid_retrieval_seconds=0.9,
        reranking_seconds=0.4,
        grading_seconds=0.3,
        context_build_seconds=0.02,
        correction_seconds=1.1,
        query_strategy="decompose",
        planned_queries=(
            "How does RAG-Token select documents?",
            "How does RAG-Sequence select documents?",
        ),
        retrieval_trace_count=2,
        route_history=(
            "retrieve",
            "rewrite",
            "retrieve_correction",
            "generate",
            "verify",
            "finalize",
        ),
        answer_text="A grounded comparison.",
        model_calls=(
            {"schema": "QueryDecision", "provider": "ollama"},
            {
                "schema": "RewriteDraft",
                "provider": "ollama",
                "elapsed_seconds": 0.8,
            },
            {
                "schema": "AnswerDraft",
                "provider": "groq",
                "elapsed_seconds": 1.2,
            },
            {
                "schema": "VerificationDraft",
                "provider": "ollama",
                "elapsed_seconds": 19.5,
            },
        ),
        correction_targets=("Missing comparison evidence",),
        rewritten_queries=("Compare both variants by document usage",),
        context_item_count=2,
        context_token_count=451,
        context_sources=("RAG Paper p.3", "RAG Paper p.4"),
        standalone_query="Compare RAG-Token and RAG-Sequence.",
        retrieval_details=(
            {
                "query": "How does RAG-Token select documents?",
                "candidate_count": 20,
                "hits": (
                    {
                        "rank": 1,
                        "score": 0.97,
                        "document": "rag-paper",
                        "page": 3,
                        "text": "RAG-Token may draw a document per token.",
                        "relevant": True,
                        "direct": True,
                        "grade": 0.95,
                        "reason": "Directly defines RAG-Token.",
                    },
                ),
            },
        ),
        context_details=(
            {
                "document": "RAG Paper",
                "page": 3,
                "direct": True,
                "score": 0.95,
                "text": "RAG-Token may draw a document per token.",
            },
        ),
    )

    rendered = render_console_report(
        _report(failed),
        Path("report.json"),
    )

    assert "Summary" in rendered
    assert "Case results" in rendered
    assert "paper-memory" in rendered
    assert "groq:1, ollama:1" in rendered

    # The failure reason now lives as a column on Case results itself,
    # rather than a separate table -- same underlying text either way.
    assert "Reason for failure" in rendered
    assert "missing required facts: Wikipedia" in rendered

    # Query plans, Pipeline routes, Stage results, Needs attention and
    # Category results are commented out in render_console_report (not
    # deleted -- the underlying renderers and their data are untouched,
    # this table set is just off by default for now).
    assert "Needs attention" not in rendered
    assert "Query plans" not in rendered
    assert "Pipeline routes" not in rendered
    assert "Analyze[decompose:ollama]" not in rendered
    assert "Stage results: paper-memory" not in rendered
    assert "Routing & strategy" not in rendered
    assert "Time taken" not in rendered
    assert "Overhead" not in rendered
    assert "Category results" not in rendered

    # Per-hit and per-context-item text dumps add noise, not signal --
    # they stay out of this table (still in the JSON output for anyone
    # who needs to dig in).
    assert "Reranked hit" not in rendered
    assert "Evidence grade" not in rendered
    assert "Context item" not in rendered
    assert "RAG-Token may draw a document per token" not in rendered
    assert "Directly defines RAG-Token" not in rendered


def test_retrieval_only_case_can_pass_without_generated_answer():
    retrieved = CaseResult(
        case_id="retrieval-case",
        should_answer=True,
        retrieval_rank=1,
        retrieval_answerable=True,
        strategy_correct=True,
        answer_correct=None,
        grounded=None,
        citation_precision=None,
        verification_passed=None,
        abstention_correct=None,
        latency_seconds=0.2,
        retrieval_source_recall=100.0,
    )

    rendered = render_console_report(
        _report(retrieved, retrieval_only=True),
        Path("retrieval.json"),
    )

    assert "retrieval-case" in rendered
    assert "PASS" in rendered
    assert "Needs attention" not in rendered


def test_slow_correct_abstention_is_not_labeled_false_answer():
    case = CaseResult(
        case_id="slow-abstention",
        should_answer=False,
        retrieval_rank=None,
        retrieval_answerable=False,
        strategy_correct=True,
        answer_correct=False,
        grounded=False,
        citation_precision=0.0,
        verification_passed=True,
        abstention_correct=True,
        latency_seconds=12.0,
        latency_budget_passed=False,
        false_answer=False,
        answer_abstained=True,
        unsupported_claims=("The requested fact is absent.",),
    )

    rendered = render_console_report(
        _report(case),
        Path("report.json"),
    )

    assert "FALSE ANSWER" not in rendered
    assert "FAIL" in rendered
    assert "unsupported:" not in rendered
