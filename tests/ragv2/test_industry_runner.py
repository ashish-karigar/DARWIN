from types import SimpleNamespace

from app.ragv2.eval.industry.checkpoint import BenchmarkCheckpoint
from app.ragv2.eval.industry.contracts import (
    BenchmarkCase,
    BenchmarkSample,
)
from app.ragv2.eval.industry.runner import IndustryBenchmarkRunner


def _sample(case):
    return BenchmarkSample(
        dataset=case.dataset,
        query_id=case.query_id,
        query=case.query,
        reference_answer=case.reference_answer,
        response="Answer",
        retrieved_contexts=(),
        grounded=False,
        abstained=True,
        latency_seconds=0.1,
    )


def test_checkpoint_resume_skips_completed_cases(tmp_path, monkeypatch):
    cases = tuple(
        BenchmarkCase(
            dataset="sample",
            query_id=f"q{number}",
            query=f"Question {number}",
            reference_answer=f"Answer {number}",
        )
        for number in range(3)
    )
    checkpoint = BenchmarkCheckpoint(tmp_path / "samples.jsonl")
    checkpoint.append(_sample(cases[0]))
    calls = []

    service = SimpleNamespace(
        ask=lambda question, **kwargs: calls.append(question) or object()
    )
    usage = SimpleNamespace(
        today=lambda: SimpleNamespace(remaining_tokens=200_000)
    )
    monkeypatch.setattr(
        "app.ragv2.eval.industry.runner.sample_from_response",
        lambda case, response: _sample(case),
    )

    report = IndustryBenchmarkRunner(
        service,
        checkpoint,
        usage_store=usage,
    ).run("sample", cases)

    assert calls == ["Question 1", "Question 2"]
    assert report.executed_cases == 2
    assert report.completed_cases == 3
    assert len(checkpoint.load()) == 3


def test_daily_reserve_stops_before_provider_call(tmp_path):
    case = BenchmarkCase(
        dataset="sample",
        query_id="q1",
        query="Question",
        reference_answer="Answer",
    )
    checkpoint = BenchmarkCheckpoint(tmp_path / "samples.jsonl")
    usage = SimpleNamespace(
        today=lambda: SimpleNamespace(remaining_tokens=10_000)
    )
    service = SimpleNamespace(
        ask=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("provider should not be called")
        )
    )

    report = IndustryBenchmarkRunner(
        service,
        checkpoint,
        usage_store=usage,
        daily_token_reserve=10_000,
    ).run("sample", (case,))

    assert report.stopped_for_daily_budget is True
    assert report.executed_cases == 0
