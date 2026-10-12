import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.llm.circuit_breaker import ProviderCircuitBreaker
from app.llm.structured import (
    StructuredModelRunner,
    StructuredModelUnavailableError,
)
from app.llm.telemetry import capture_model_calls


class FakeRunnable:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)

        if self.error is not None:
            raise self.error

        return self.result


class FakeModel:
    def __init__(self, runnable):
        self.runnable = runnable
        self.schemas = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        return self.runnable


class FakeSchema:
    pass


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    confidence: float


class SequenceRunnable:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        result = next(self.results)

        if isinstance(result, Exception):
            raise result

        return result


def test_primary_structured_model_is_used_when_available():
    primary = FakeRunnable(result="primary")
    fallback = FakeRunnable(result="fallback")
    runner = StructuredModelRunner(
        FakeSchema,
        primary_model=FakeModel(primary),
        fallback_model=FakeModel(fallback),
        circuit_breaker=ProviderCircuitBreaker(),
    )

    result = runner.invoke(["message"])

    assert result == "primary"
    assert len(primary.calls) == 1
    assert fallback.calls == []


def test_local_structured_model_handles_primary_failure():
    primary = FakeRunnable(error=RuntimeError("rate limited"))
    fallback = FakeRunnable(result="fallback")
    runner = StructuredModelRunner(
        FakeSchema,
        primary_model=FakeModel(primary),
        fallback_model=FakeModel(fallback),
        circuit_breaker=ProviderCircuitBreaker(),
    )

    result = runner.invoke(["message"])

    assert result == "fallback"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


def test_reports_failure_when_both_models_are_unavailable():
    primary = FakeRunnable(error=RuntimeError("rate limited"))
    fallback = FakeRunnable(error=RuntimeError("offline"))
    runner = StructuredModelRunner(
        FakeSchema,
        primary_model=FakeModel(primary),
        fallback_model=FakeModel(fallback),
        circuit_breaker=ProviderCircuitBreaker(),
    )

    with pytest.raises(
        StructuredModelUnavailableError,
        match="RuntimeError; RuntimeError",
    ):
        runner.invoke(["message"])


def test_repairs_a_groq_server_side_parse_failure():
    """A provider-side output_parse_failed must be treated as

    repairable, not a plain failure. Regression test for a real
    production incident: Groq rejected a tool call server-side (the
    model leaked reasoning text instead of clean JSON) with a
    BadRequestError our own pydantic validation never saw, so it was
    misclassified as a genuine failure -- skipping the repair retry,
    falling back to a slow local model, and tripping the eval
    harness's batch-contamination stop for something a same-provider
    retry can often fix.
    """

    class GroqBadRequestError(Exception):
        pass

    primary = SequenceRunnable(
        [
            GroqBadRequestError(
                "Error code: 400 - {'error': {'message': "
                "\"Parsing failed. The model generated output that "
                "could not be parsed.\", 'type': 'invalid_request_error', "
                "'code': 'output_parse_failed'}}"
            ),
            {"answer": "grounded", "confidence": 0.8},
        ]
    )
    runner = StructuredModelRunner(
        StrictSchema,
        primary_model=FakeModel(primary),
        circuit_breaker=ProviderCircuitBreaker(),
    )

    with capture_model_calls() as events:
        result = runner.invoke([{"role": "user", "content": "Q"}])

    assert result.answer == "grounded"
    assert len(primary.calls) == 2
    assert [event.outcome for event in events] == [
        "schema_invalid",
        "success",
    ]


def test_repairs_an_incomplete_structured_response_once():
    primary = SequenceRunnable(
        [
            {"confidence": 0.8},
            {"answer": "grounded", "confidence": 0.8},
        ]
    )
    runner = StructuredModelRunner(
        StrictSchema,
        primary_model=FakeModel(primary),
        circuit_breaker=ProviderCircuitBreaker(),
    )

    with capture_model_calls() as events:
        result = runner.invoke([{"role": "user", "content": "Q"}])

    assert result.answer == "grounded"
    assert len(primary.calls) == 2
    assert [event.outcome for event in events] == [
        "schema_invalid",
        "success",
    ]


def test_rate_limit_opens_circuit_and_skips_repeated_primary_calls():
    primary = FakeRunnable(
        error=RuntimeError("Error code: 429 rate limit")
    )
    fallback = FakeRunnable(
        result={"answer": "local", "confidence": 0.7}
    )
    breaker = ProviderCircuitBreaker()
    runner = StructuredModelRunner(
        StrictSchema,
        primary_model=FakeModel(primary),
        fallback_model=FakeModel(fallback),
        circuit_breaker=breaker,
    )

    with capture_model_calls() as events:
        first = runner.invoke(["message"])
        second = runner.invoke(["message"])

    assert first.answer == "local"
    assert second.answer == "local"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 2
    assert [event.outcome for event in events] == [
        "rate_limited",
        "success",
        "circuit_open",
        "success",
    ]
    assert events[1].used_fallback is True
    assert events[3].used_fallback is True


def test_short_rate_limit_window_retries_primary_before_falling_back():
    """A brief, provider-quoted wait should beat a slow local fallback.

    Mirrors the real Groq OTPM 429 this guards against: "Please try
    again in 2.82s" is far cheaper to wait out than routing to a local
    model that can take 15-20s on modest hardware.
    """

    primary = SequenceRunnable(
        [
            RuntimeError(
                "Error code: 429 - rate limit. Please try again in 2.82s."
            ),
            {"answer": "retried primary", "confidence": 0.9},
        ]
    )
    fallback = FakeRunnable(result={"answer": "fallback", "confidence": 0.5})
    sleeps = []
    runner = StructuredModelRunner(
        StrictSchema,
        primary_model=FakeModel(primary),
        fallback_model=FakeModel(fallback),
        circuit_breaker=ProviderCircuitBreaker(),
        sleep_function=sleeps.append,
    )

    with capture_model_calls() as events:
        result = runner.invoke(["message"])

    assert result.answer == "retried primary"
    assert len(primary.calls) == 2
    assert fallback.calls == []
    assert sleeps == [3.82]
    assert [event.outcome for event in events] == [
        "rate_limited",
        "success",
    ]
    assert events[1].used_fallback is False


def test_long_rate_limit_window_falls_back_without_waiting():
    primary = FakeRunnable(
        error=RuntimeError("Error code: 429 rate limit")
    )
    fallback = FakeRunnable(result={"answer": "fallback", "confidence": 0.5})
    sleeps = []
    runner = StructuredModelRunner(
        StrictSchema,
        primary_model=FakeModel(primary),
        fallback_model=FakeModel(fallback),
        circuit_breaker=ProviderCircuitBreaker(),
        sleep_function=sleeps.append,
    )

    result = runner.invoke(["message"])

    assert result.answer == "fallback"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1
    assert sleeps == []


def test_retry_after_short_wait_also_fails_then_falls_back():
    primary = SequenceRunnable(
        [
            RuntimeError(
                "Error code: 429 - rate limit. Please try again in 1s."
            ),
            RuntimeError(
                "Error code: 429 - rate limit. Please try again in 1s."
            ),
        ]
    )
    fallback = FakeRunnable(result={"answer": "fallback", "confidence": 0.5})
    sleeps = []
    runner = StructuredModelRunner(
        StrictSchema,
        primary_model=FakeModel(primary),
        fallback_model=FakeModel(fallback),
        circuit_breaker=ProviderCircuitBreaker(),
        sleep_function=sleeps.append,
    )

    result = runner.invoke(["message"])

    assert result.answer == "fallback"
    assert len(primary.calls) == 2
    assert len(fallback.calls) == 1
    assert sleeps == [2.0]


def test_circuit_breaker_uses_provider_retry_after_header():
    class Response:
        headers = {"retry-after": "12.5"}

    error = RuntimeError("Error code: 429 rate limit")
    error.response = Response()

    assert ProviderCircuitBreaker.retry_delay_seconds(error) == 13.5


def test_circuit_breaker_defaults_to_one_minute_without_header():
    error = RuntimeError("Error code: 429 rate limit")

    assert ProviderCircuitBreaker.retry_delay_seconds(error) == 61.0
