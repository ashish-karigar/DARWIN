import pytest

from app.ragv2.eval.evaluate import (
    CaseResult,
    _print_pacing_pause,
    _print_progress,
    _print_report_summary,
)
from app.ragv2.eval.report import EvaluationReport
from app.ragv2.eval.pacing import FixedBatchPacer


def test_pauses_after_every_two_cases_except_after_final_case():
    sleeps = []
    notices = []
    pacer = FixedBatchPacer(
        cases_per_batch=2,
        pause_seconds=60,
        sleep_function=sleeps.append,
        on_pause=notices.append,
    )

    pauses = tuple(
        pacer.after_case(completed_cases=index, total_cases=5)
        for index in range(1, 6)
    )

    assert pauses == (0.0, 60, 0.0, 60, 0.0)
    assert sleeps == [60, 60]
    assert [notice.completed_cases for notice in notices] == [2, 4]


def test_does_not_pause_when_the_second_case_is_the_final_case():
    sleeps = []
    pacer = FixedBatchPacer(sleep_function=sleeps.append)

    pacer.after_case(completed_cases=1, total_cases=2)
    pacer.after_case(completed_cases=2, total_cases=2)

    assert sleeps == []


def test_initial_cooldown_creates_a_clean_cloud_window():
    sleeps = []
    notices = []
    pacer = FixedBatchPacer(
        initial_cooldown_seconds=60,
        sleep_function=sleeps.append,
        on_pause=notices.append,
    )

    waited = pacer.before_run(total_cases=23)

    assert waited == 60
    assert sleeps == [60]
    assert notices[0].reason == "initial-cooldown"


@pytest.mark.parametrize(
    ("arguments", "message"),
    (
        ({"cases_per_batch": 0}, "cases_per_batch"),
        ({"pause_seconds": -1}, "pause_seconds"),
        ({"initial_cooldown_seconds": -1}, "initial_cooldown_seconds"),
    ),
)
def test_rejects_invalid_pacing_configuration(arguments, message):
    with pytest.raises(ValueError, match=message):
        FixedBatchPacer(**arguments)


def test_progress_and_pause_callbacks_print_independently(capsys):
    result = CaseResult(
        case_id="case-02",
        should_answer=True,
        retrieval_rank=1,
        retrieval_answerable=True,
        strategy_correct=True,
        answer_correct=True,
        grounded=True,
        citation_precision=100.0,
        verification_passed=True,
        abstention_correct=None,
        latency_seconds=1.25,
    )
    pacer = FixedBatchPacer(
        pause_seconds=60,
        sleep_function=lambda _: None,
        on_pause=_print_pacing_pause,
    )

    _print_progress(2, 23, result)
    pacer.after_case(completed_cases=2, total_cases=23)

    stderr = capsys.readouterr().err
    assert "[2/23] case-02: completed in 1.25s" in stderr
    assert "Groq safety pause: 60s after 2/23 cases." in stderr


def test_progress_labels_provider_failure(capsys):
    result = CaseResult(
        case_id="provider-case",
        should_answer=True,
        retrieval_rank=1,
        retrieval_answerable=True,
        strategy_correct=True,
        answer_correct=False,
        grounded=False,
        citation_precision=0.0,
        verification_passed=False,
        abstention_correct=None,
        latency_seconds=8.0,
        provider_failure_count=1,
    )

    _print_progress(4, 23, result)

    assert "provider-case: provider-failed" in capsys.readouterr().err


def test_saved_report_prints_compact_terminal_summary(capsys, tmp_path):
    report = EvaluationReport(
        dataset="Test",
        retrieval_only=False,
        case_count=23,
        successful_cases=4,
        hit_at_1_percent=100.0,
        hit_at_5_percent=100.0,
        mean_reciprocal_rank=1.0,
        no_answer_rejection_percent=0.0,
        answer_required_term_accuracy_percent=50.0,
        grounded_answer_rate_percent=75.0,
        citation_precision_percent=75.0,
        verification_pass_percent=75.0,
        average_latency_seconds=20.0,
        p95_latency_seconds=40.0,
        cases=(),
        provider_failure_count=1,
        fallback_used_count=1,
        failed_quality_gates=("execution_success",),
        terminated_early=True,
        termination_reason="Provider contamination detected.",
        completed_case_count=4,
    )
    output = tmp_path / "report.json"

    _print_report_summary(report, output)

    stderr = capsys.readouterr().err
    assert "RAG benchmark: STOPPED EARLY" in stderr
    assert "Cases executed" in stderr
    assert "4/23" in stderr
    assert "Summary" in stderr
    assert "Case results" in stderr
    assert "Detailed JSON" in stderr
