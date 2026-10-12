import json
from types import SimpleNamespace

from app.llm.telemetry import ModelCallEvent
from app.ragv2.eval.datasets import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationQualityGates,
)
from app.ragv2.eval.evaluate import (
    CaseResult,
    RagEvaluator,
    failed_case_ids_from_report,
)
from app.ragv2.eval.fact_judge import FactCoverageJudge
from app.ragv2.eval.metrics import (
    contains_required_terms,
    excludes_forbidden_terms,
    fact_recall,
    missing_fact_groups,
    percentile,
    source_coverage,
    source_matches,
)


def test_metric_helpers_are_normalized_and_deterministic():
    assert contains_required_terms(
        "A Dense   Vector Index of WIKIPEDIA.",
        ("dense vector index", "Wikipedia"),
    )
    assert source_matches(
        "/tmp/data/RAG-PAPER.PDF",
        ("rag-paper.pdf",),
    )
    assert percentile((1.0, 2.0, 10.0), 0.95) == 10.0
    assert fact_recall(
        "RAG-Token can change documents for each token.",
        (
            ("RAG-Token",),
            ("each token", "per token"),
        ),
    ) == 100.0
    assert excludes_forbidden_terms(
        "Grounded answer",
        ("administrator password",),
    )
    assert source_coverage(
        ("/docs/paper.pdf", "/docs/invoice.png"),
        ("paper.pdf", "invoice.png"),
    ) == 100.0
    assert missing_fact_groups(
        "The memory is a dense vector index.",
        (("dense vector index",), ("Wikipedia", "wiki")),
    ) == (("Wikipedia", "wiki"),)


def test_report_computes_retrieval_and_safety_metrics():
    dataset = EvaluationDataset(
        name="Test dataset",
        cases=(
            EvaluationCase(
                case_id="answerable",
                question="Question",
                should_answer=True,
                expected_source_suffixes=("source.pdf",),
            ),
            EvaluationCase(
                case_id="negative",
                question="Unknown",
                should_answer=False,
            ),
        ),
    )
    cases = (
        CaseResult(
            case_id="answerable",
            should_answer=True,
            retrieval_rank=1,
            retrieval_answerable=True,
            strategy_correct=True,
            answer_correct=True,
            grounded=True,
            citation_precision=100.0,
            verification_passed=True,
            abstention_correct=None,
            latency_seconds=1.0,
        ),
        CaseResult(
            case_id="negative",
            should_answer=False,
            retrieval_rank=None,
            retrieval_answerable=False,
            strategy_correct=True,
            answer_correct=False,
            grounded=False,
            citation_precision=0.0,
            verification_passed=True,
            abstention_correct=True,
            latency_seconds=2.0,
        ),
    )

    report = RagEvaluator._report(
        dataset.name,
        False,
        cases,
    )

    assert report.hit_at_1_percent == 100.0
    assert report.mean_reciprocal_rank == 1.0
    assert report.no_answer_rejection_percent == 100.0
    assert report.answer_required_term_accuracy_percent == 100.0
    assert report.citation_precision_percent == 100.0


def test_quality_gates_report_specific_failures():
    cases = (
        CaseResult(
            case_id="false-abstention",
            should_answer=True,
            retrieval_rank=1,
            retrieval_answerable=True,
            strategy_correct=True,
            answer_correct=False,
            grounded=False,
            citation_precision=0.0,
            verification_passed=None,
            abstention_correct=None,
            latency_seconds=12.0,
            retrieval_source_recall=100.0,
            answer_completeness=0.0,
            citation_recall=0.0,
            false_abstention=True,
            latency_budget_passed=False,
            tags=("pdf", "attribution"),
        ),
    )

    report = RagEvaluator._report(
        "Gated dataset",
        False,
        cases,
        quality_gates=EvaluationQualityGates(
            answer_accuracy_min_percent=90.0,
            answer_completeness_min_percent=90.0,
            citation_recall_min_percent=90.0,
            false_abstention_max_percent=5.0,
            latency_budget_pass_min_percent=100.0,
            p95_latency_max_seconds=5.0,
        ),
    )

    assert report.passed_quality_gates is False
    assert set(report.failed_quality_gates) == {
        "answer_accuracy",
        "answer_completeness",
        "citation_recall",
        "false_abstention_rate",
        "latency_budget_pass",
        "p95_latency",
    }
    assert report.category_results["pdf"]["case_count"] == 1
    assert (
        report.category_results["attribution"][
            "answer_accuracy_percent"
        ]
        == 0.0
    )


def test_dataset_can_select_cases_by_id_tag_and_limit():
    dataset = EvaluationDataset(
        name="Filterable",
        cases=(
            EvaluationCase(
                case_id="pdf-case",
                question="PDF question",
                should_answer=True,
                expected_source_suffixes=("paper.pdf",),
                tags=("pdf",),
            ),
            EvaluationCase(
                case_id="table-case",
                question="Table question",
                should_answer=True,
                expected_source_suffixes=("sales.md",),
                tags=("table",),
            ),
        ),
    )

    assert dataset.select(tags=("pdf",)).cases[0].case_id == "pdf-case"
    assert dataset.select(case_ids=("table-case",)).cases[0].case_id == (
        "table-case"
    )
    assert len(dataset.select(limit=1).cases) == 1


def test_retrieval_only_enforces_no_answer_gate():
    cases = (
        CaseResult(
            case_id="near-miss",
            should_answer=False,
            retrieval_rank=None,
            retrieval_answerable=True,
            strategy_correct=True,
            answer_correct=None,
            grounded=None,
            citation_precision=None,
            verification_passed=None,
            abstention_correct=False,
            latency_seconds=0.1,
            tags=("no-answer",),
        ),
    )

    report = RagEvaluator._report(
        "Retrieval safety",
        True,
        cases,
        quality_gates=EvaluationQualityGates(
            no_answer_rejection_min_percent=100.0,
        ),
    )

    assert report.passed_quality_gates is False
    assert report.failed_quality_gates == (
        "no_answer_rejection",
    )
    assert (
        report.category_results["no-answer"][
            "no_answer_rejection_percent"
        ]
        == 0.0
    )


def test_execution_errors_fail_the_configured_gate():
    report = RagEvaluator._report(
        "Execution safety",
        True,
        (
            CaseResult(
                case_id="crashed",
                should_answer=False,
                retrieval_rank=None,
                retrieval_answerable=False,
                strategy_correct=None,
                answer_correct=None,
                grounded=None,
                citation_precision=None,
                verification_passed=None,
                abstention_correct=None,
                latency_seconds=0.1,
                error="RuntimeError",
            ),
        ),
        quality_gates=EvaluationQualityGates(
            execution_success_min_percent=100.0,
        ),
    )

    assert report.execution_success_percent == 0.0
    assert report.failed_quality_gates == ("execution_success",)


def test_successful_fallback_does_not_stop_remaining_cases():
    class ProviderFailureEvaluator(RagEvaluator):
        def _run_case(self, case, **kwargs):
            return CaseResult(
                case_id=case.case_id,
                should_answer=case.should_answer,
                retrieval_rank=1,
                retrieval_answerable=True,
                strategy_correct=True,
                answer_correct=True,
                grounded=True,
                citation_precision=100.0,
                verification_passed=True,
                abstention_correct=None,
                latency_seconds=1.0,
                provider_failure_count=1,
                fallback_used_count=1,
                question=case.question,
            )

    dataset = EvaluationDataset(
        name="Fail-fast",
        cases=tuple(
            EvaluationCase(
                case_id=f"case-{index}",
                question=f"Question {index}",
                should_answer=True,
                expected_source_suffixes=("source.pdf",),
            )
            for index in range(1, 4)
        ),
        quality_gates=EvaluationQualityGates(
            execution_success_min_percent=100.0,
        ),
    )
    evaluator = ProviderFailureEvaluator(
        rag_service=object(),
        stop_on_provider_failure=True,
    )

    report = evaluator.evaluate(dataset)

    assert report.terminated_early is False
    assert report.completed_case_count == 3
    assert report.execution_success_percent == 100.0
    assert all(case.error is None for case in report.cases)
    assert "execution_success" not in report.failed_quality_gates


def _dataset_of(count: int, name: str) -> EvaluationDataset:
    return EvaluationDataset(
        name=name,
        cases=tuple(
            EvaluationCase(
                case_id=f"case-{index}",
                question=f"Question {index}",
                should_answer=True,
                expected_source_suffixes=("source.pdf",),
            )
            for index in range(1, count + 1)
        ),
    )


def test_rate_limited_recovery_does_not_stop_the_run():
    """A rate limit StructuredModelRunner already retried past must not

    halt a batch. It now waits out a short provider-quoted window and
    retries the same provider before ever touching a fallback -- that
    self-recovery is not degraded output and shouldn't be treated as
    contamination, even though provider_failure_count still records
    that the first attempt was rate-limited.
    """

    class RecoveredEvaluator(RagEvaluator):
        def _run_case(self, case, **kwargs):
            return CaseResult(
                case_id=case.case_id,
                should_answer=case.should_answer,
                retrieval_rank=1,
                retrieval_answerable=True,
                strategy_correct=True,
                answer_correct=True,
                grounded=True,
                citation_precision=100.0,
                verification_passed=True,
                abstention_correct=None,
                latency_seconds=1.0,
                provider_failure_count=1,
                fallback_used_count=0,
                model_calls=(
                    {
                        "schema": "VerificationDraft",
                        "provider": "groq",
                        "outcome": "rate_limited",
                    },
                    {
                        "schema": "VerificationDraft",
                        "provider": "groq",
                        "outcome": "success",
                    },
                ),
                question=case.question,
            )

    evaluator = RecoveredEvaluator(
        rag_service=object(),
        stop_on_provider_failure=True,
    )

    report = evaluator.evaluate(_dataset_of(3, "Rate-limited-but-fine"))

    assert report.terminated_early is False
    assert report.completed_case_count == 3


def test_non_recoverable_provider_failure_still_stops_the_run():
    """A genuine failure (bad model name, auth, network) is different

    from a rate limit -- StructuredModelRunner has no built-in recovery
    for it, so it's still worth halting the batch to investigate.
    """

    class GenuineFailureEvaluator(RagEvaluator):
        def _run_case(self, case, **kwargs):
            return CaseResult(
                case_id=case.case_id,
                should_answer=case.should_answer,
                retrieval_rank=1,
                retrieval_answerable=True,
                strategy_correct=True,
                answer_correct=True,
                grounded=True,
                citation_precision=100.0,
                verification_passed=True,
                abstention_correct=None,
                latency_seconds=1.0,
                provider_failure_count=1,
                fallback_used_count=0,
                model_calls=(
                    {
                        "schema": "VerificationDraft",
                        "provider": "groq",
                        "outcome": "failure",
                    },
                ),
                question=case.question,
            )

    evaluator = GenuineFailureEvaluator(
        rag_service=object(),
        stop_on_provider_failure=True,
    )

    report = evaluator.evaluate(_dataset_of(3, "Genuine-failure"))

    assert report.terminated_early is True
    assert report.completed_case_count == 1


def test_selects_only_failed_or_provider_contaminated_cases(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "passed",
                        "should_answer": True,
                        "answer_correct": True,
                        "grounded": True,
                        "verification_passed": True,
                        "citation_recall": 100.0,
                        "strategy_correct": True,
                        "latency_budget_passed": True,
                    },
                    {
                        "case_id": "rate-limited",
                        "should_answer": True,
                        "provider_failure_count": 1,
                    },
                    {
                        "case_id": "incomplete",
                        "should_answer": True,
                        "answer_correct": False,
                    },
                    {
                        "case_id": "skipped",
                        "should_answer": False,
                        "error": "SkippedAfterProviderFailure",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    assert failed_case_ids_from_report(report_path) == (
        "rate-limited",
        "incomplete",
        "skipped",
    )


def test_case_report_preserves_answer_and_failure_diagnostics():
    case = EvaluationCase(
        case_id="diagnostic",
        question="What memory does RAG use and where does it come from?",
        should_answer=True,
        expected_source_suffixes=("paper.pdf",),
        required_terms=("dense vector index", "Wikipedia"),
    )
    citation = SimpleNamespace(
        citation_id="S1",
        document_title="RAG paper",
        source_uri="/docs/paper.pdf",
        page_number=2,
    )
    answer = SimpleNamespace(
        answer="RAG uses a dense vector index [S1].",
        citations=(citation,),
        is_grounded=True,
        abstained=False,
        confidence_reason="The cited passage directly supports the answer.",
        unsupported_claims=(),
    )
    verification = SimpleNamespace(
        is_supported=True,
        confidence_reason="All claims are supported.",
        unsupported_claims=(),
        contradicted_claims=(),
    )
    hit = SimpleNamespace(
        chunk=SimpleNamespace(source_uri="/docs/paper.pdf")
    )
    retrieval = SimpleNamespace(
        reranked_hits=(hit,),
        context=SimpleNamespace(items=()),
        analysis=SimpleNamespace(strategy="direct"),
        fully_answerable=True,
        timings=SimpleNamespace(total_seconds=0.2),
    )
    response = SimpleNamespace(
        answer=answer,
        verification=verification,
        route_history=("retrieve", "generate", "verify"),
    )
    model_call = ModelCallEvent(
        schema="AnswerDraft",
        provider="groq",
        outcome="success",
        attempt=1,
        elapsed_seconds=0.4,
        used_fallback=False,
    )

    result = RagEvaluator._score_case(
        case,
        retrieval,
        response,
        1.0,
        model_calls=(model_call,),
    )

    assert result.answer_text == answer.answer
    assert result.missing_fact_groups == (("Wikipedia",),)
    assert result.citations[0].source_uri == "/docs/paper.pdf"
    assert result.verification_confidence_reason == (
        "All claims are supported."
    )
    assert result.route_history == ("retrieve", "generate", "verify")
    assert result.model_calls[0]["provider"] == "groq"


def test_fact_judge_accepts_paraphrases_that_substring_matching_rejects():
    """A correct paraphrase must score as covered, not as a miss.

    Mirrors the real paper-rag-variants failure: the answer describes
    RAG-Token/RAG-Sequence correctly in different words than the
    accepted-phrase list, and should be graded on meaning.
    """

    case = EvaluationCase(
        case_id="paper-rag-variants",
        question="Compare RAG-Token and RAG-Sequence.",
        should_answer=True,
        expected_source_suffixes=("paper.pdf",),
        required_term_groups=(
            ("RAG-Token",),
            ("different document for each target token",),
            ("RAG-Sequence",),
            ("same document to predict each target token",),
        ),
    )
    citation = SimpleNamespace(
        citation_id="S1",
        document_title="RAG paper",
        source_uri="/docs/paper.pdf",
        page_number=3,
    )
    answer = SimpleNamespace(
        answer=(
            "RAG-Token draws a separate latent document for each "
            "target token, while RAG-Sequence treats the retrieved "
            "document as a single latent variable for the whole "
            "sequence."
        ),
        citations=(citation,),
        is_grounded=True,
        abstained=False,
        confidence_reason="Directly supported by the cited passage.",
        unsupported_claims=(),
    )
    verification = SimpleNamespace(
        is_supported=True,
        confidence_reason="All claims are supported.",
        unsupported_claims=(),
        contradicted_claims=(),
    )
    hit = SimpleNamespace(
        chunk=SimpleNamespace(source_uri="/docs/paper.pdf")
    )
    retrieval = SimpleNamespace(
        reranked_hits=(hit,),
        context=SimpleNamespace(items=()),
        analysis=SimpleNamespace(strategy="decompose"),
        fully_answerable=True,
        timings=SimpleNamespace(total_seconds=0.3),
    )
    response = SimpleNamespace(
        answer=answer,
        verification=verification,
        route_history=("retrieve", "generate", "verify"),
    )

    class StubFactCoverageProvider:
        """Fake judge: covered whenever the paraphrase carries the meaning."""

        def judge(self, answer, facts):
            paraphrase_covers = {
                "RAG-Token": "rag-token" in answer.lower(),
                "different document for each target token": (
                    "separate latent document for each" in answer.lower()
                ),
                "RAG-Sequence": "rag-sequence" in answer.lower(),
                "same document to predict each target token": (
                    "single latent variable" in answer.lower()
                ),
            }
            return tuple(paraphrase_covers[fact] for fact in facts)

    fact_judge = FactCoverageJudge(provider=StubFactCoverageProvider())

    result = RagEvaluator._score_case(
        case,
        retrieval,
        response,
        2.0,
        fact_judge=fact_judge,
    )

    assert result.missing_fact_groups == ()
    assert result.answer_completeness == 100.0
    assert result.answer_correct is True
