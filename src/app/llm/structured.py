from collections.abc import Callable
from time import perf_counter, sleep
from typing import Any

from pydantic import ValidationError

from langchain_core.exceptions import OutputParserException

from app.llm.circuit_breaker import (
    ProviderCircuitBreaker,
    ProviderCircuitOpenError,
    provider_circuit_breaker,
)
from app.llm.models import (
    create_fallback_model,
    create_primary_model,
)
from app.llm.telemetry import ModelCallEvent, record_model_call


class StructuredModelUnavailableError(RuntimeError):
    """Raised when both structured-output providers fail."""


class StructuredModelRunner:
    """Runs strict structured output with repair, fallback, and telemetry."""

    def __init__(
        self,
        schema: type,
        *,
        primary_model: Any | None = None,
        fallback_model: Any | None = None,
        reasoning_effort: str = "low",
        primary_provider: str = "groq",
        fallback_provider: str = "ollama",
        repair_attempts: int = 1,
        circuit_breaker: ProviderCircuitBreaker = (
            provider_circuit_breaker
        ),
        rate_limit_retry_max_seconds: float = 10.0,
        sleep_function: Callable[[float], None] = sleep,
    ):
        use_default_fallback = primary_model is None
        primary = primary_model or create_primary_model(
            reasoning_effort=reasoning_effort
        )
        fallback = fallback_model

        if fallback is None and use_default_fallback:
            fallback = create_fallback_model()

        self.primary = primary.with_structured_output(schema)
        self.fallback = (
            fallback.with_structured_output(schema)
            if fallback is not None
            else None
        )
        self.schema = schema
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider
        self.repair_attempts = max(0, repair_attempts)
        self.circuit_breaker = circuit_breaker
        self.rate_limit_retry_max_seconds = rate_limit_retry_max_seconds
        self.sleep_function = sleep_function

    @classmethod
    def local(
        cls,
        schema: type,
        *,
        model: Any | None = None,
        repair_attempts: int = 1,
    ) -> "StructuredModelRunner":
        return cls(
            schema,
            primary_model=model or create_fallback_model(),
            fallback_model=None,
            primary_provider="ollama",
            fallback_provider="",
            repair_attempts=repair_attempts,
        )

    def invoke(self, messages):
        primary_error: Exception

        if self.circuit_breaker.is_open(self.primary_provider):
            primary_error = ProviderCircuitOpenError(
                f"{self.primary_provider} circuit is open."
            )
            self._record(
                provider=self.primary_provider,
                outcome="circuit_open",
                attempt=0,
                elapsed_seconds=0.0,
                used_fallback=False,
                error=primary_error,
            )
        else:
            try:
                return self._invoke_provider(
                    self.primary,
                    messages,
                    provider=self.primary_provider,
                    used_fallback=False,
                )
            except Exception as error:
                primary_error = error
                tripped = self.circuit_breaker.trip_for_rate_limit(
                    self.primary_provider,
                    error,
                )

                # A short, provider-quoted rate-limit window is usually
                # faster to wait out than a slow local fallback model --
                # and it keeps this call off the fallback provider
                # entirely, rather than trading one problem (rate limit)
                # for another (fallback's own latency or quality). Only
                # worth it when the wait is short; a long or unspecified
                # window (the circuit breaker's minute-long default when
                # a provider doesn't say) still falls straight through.
                if tripped:
                    delay = self.circuit_breaker.retry_delay_seconds(
                        error
                    )

                    if delay <= self.rate_limit_retry_max_seconds:
                        self.sleep_function(delay)

                        try:
                            return self._invoke_provider(
                                self.primary,
                                messages,
                                provider=self.primary_provider,
                                used_fallback=False,
                            )
                        except Exception as retry_error:
                            primary_error = retry_error
                            self.circuit_breaker.trip_for_rate_limit(
                                self.primary_provider,
                                retry_error,
                            )

        if self.fallback is None:
            raise primary_error

        try:
            return self._invoke_provider(
                self.fallback,
                messages,
                provider=self.fallback_provider,
                used_fallback=True,
            )
        except Exception as fallback_error:
            raise StructuredModelUnavailableError(
                "Primary and fallback structured models failed: "
                f"{type(primary_error).__name__}; "
                f"{type(fallback_error).__name__}."
            ) from fallback_error

    def _invoke_provider(
        self,
        runnable,
        messages,
        *,
        provider: str,
        used_fallback: bool,
    ):
        current_messages = list(messages)
        last_error: Exception | None = None

        for attempt in range(1, self.repair_attempts + 2):
            started_at = perf_counter()

            try:
                result = self._validate_result(
                    runnable.invoke(current_messages)
                )
                self._record(
                    provider=provider,
                    outcome="success",
                    attempt=attempt,
                    elapsed_seconds=perf_counter() - started_at,
                    used_fallback=used_fallback,
                )
                return result
            except Exception as error:
                last_error = error
                rate_limited = self.circuit_breaker.is_rate_limit(
                    error
                )
                structured_error = self._is_structured_error(error)
                self._record(
                    provider=provider,
                    outcome=(
                        "rate_limited"
                        if rate_limited
                        else (
                            "schema_invalid"
                            if structured_error
                            else "failure"
                        )
                    ),
                    attempt=attempt,
                    elapsed_seconds=perf_counter() - started_at,
                    used_fallback=used_fallback,
                    error=error,
                )

                if (
                    rate_limited
                    or not structured_error
                    or attempt > self.repair_attempts
                ):
                    raise

                current_messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": self._repair_instruction(),
                    },
                ]

        assert last_error is not None
        raise last_error

    def _validate_result(self, result):
        validator = getattr(self.schema, "model_validate", None)

        if validator is None:
            return result

        if isinstance(result, self.schema):
            return result

        return validator(result)

    def _repair_instruction(self) -> str:
        schema = self.schema.model_json_schema()
        required = schema.get("required", [])
        return (
            "Your previous structured response was invalid. Return "
            "a complete object and include every required field: "
            f"{required}. Do not omit a field; use null or an empty "
            "list only when the schema permits it."
        )

    @staticmethod
    def _is_structured_error(error: Exception) -> bool:
        if isinstance(
            error,
            (ValidationError, OutputParserException),
        ) or "validation" in type(error).__name__.casefold():
            return True

        # Groq (and other OpenAI-compatible APIs) can reject a tool
        # call server-side with a 400 before it ever reaches our own
        # pydantic validation -- e.g. the model leaks reasoning text
        # instead of clean JSON. Same repairable condition, just
        # caught one layer earlier; without this it was misclassified
        # as a plain failure, skipping the repair retry and going
        # straight to fallback/contamination for something a retry
        # can often fix on the same provider.
        return "output_parse_failed" in str(error).casefold()

    def _record(
        self,
        *,
        provider: str,
        outcome: str,
        attempt: int,
        elapsed_seconds: float,
        used_fallback: bool,
        error: Exception | None = None,
    ) -> None:
        record_model_call(
            ModelCallEvent(
                schema=self.schema.__name__,
                provider=provider,
                outcome=outcome,
                attempt=attempt,
                elapsed_seconds=round(elapsed_seconds, 4),
                used_fallback=used_fallback,
                error_type=(
                    type(error).__name__ if error else None
                ),
                error_message=(
                    self._safe_error_message(error)
                    if error is not None
                    else None
                ),
                retry_after_seconds=(
                    round(
                        self.circuit_breaker.retry_delay_seconds(error),
                        3,
                    )
                    if error is not None
                    and self.circuit_breaker.is_rate_limit(error)
                    else None
                ),
            )
        )

    @staticmethod
    def _safe_error_message(error: Exception) -> str:
        """Keeps provider diagnostics useful without dumping huge payloads."""

        normalized = " ".join(str(error).split())
        return normalized[:500]
