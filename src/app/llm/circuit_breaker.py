import re
from email.utils import parsedate_to_datetime
from datetime import UTC, datetime
from threading import Lock
from time import monotonic


class ProviderCircuitOpenError(RuntimeError):
    """Raised when a temporarily unavailable provider is skipped."""


class ProviderCircuitBreaker:
    """Stops repeated calls to a provider during a rate-limit window."""

    def __init__(self):
        self._open_until: dict[str, float] = {}
        self._lock = Lock()

    def is_open(self, provider: str) -> bool:
        with self._lock:
            deadline = self._open_until.get(provider, 0.0)

            if deadline <= monotonic():
                self._open_until.pop(provider, None)
                return False

            return True

    def trip_for_rate_limit(
        self,
        provider: str,
        error: Exception,
    ) -> bool:
        if not self.is_rate_limit(error):
            return False

        delay = self.retry_delay_seconds(error)

        with self._lock:
            self._open_until[provider] = max(
                self._open_until.get(provider, 0.0),
                monotonic() + delay,
            )

        return True

    @classmethod
    def retry_delay_seconds(cls, error: Exception) -> float:
        """Reads Groq's retry header before falling back to message text."""

        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)

        if headers is not None:
            retry_milliseconds = headers.get("retry-after-ms")
            if retry_milliseconds is not None:
                try:
                    return max(0.0, float(retry_milliseconds) / 1000) + 1.0
                except (TypeError, ValueError):
                    pass

            retry_after = headers.get("retry-after")
            parsed_header = cls._parse_retry_after_header(retry_after)
            if parsed_header is not None:
                return parsed_header + 1.0

        return cls._retry_delay_seconds(str(error))

    def reset(self) -> None:
        with self._lock:
            self._open_until.clear()

    @staticmethod
    def is_rate_limit(error: Exception) -> bool:
        name = type(error).__name__.casefold()
        message = str(error).casefold()
        return (
            "ratelimit" in name
            or "rate limit" in message
            or "status: 429" in message
            or "error code: 429" in message
        )

    @staticmethod
    def _retry_delay_seconds(message: str) -> float:
        minute_match = re.search(
            r"try again in\s+(\d+)m([\d.]+)s",
            message,
            flags=re.IGNORECASE,
        )

        if minute_match:
            return (
                int(minute_match.group(1)) * 60
                + float(minute_match.group(2))
                + 1.0
            )

        second_match = re.search(
            r"try again in\s+([\d.]+)s",
            message,
            flags=re.IGNORECASE,
        )

        if second_match:
            return float(second_match.group(1)) + 1.0

        # Groq documents retry-after on every 429. If an intermediary strips
        # it, one complete TPM window is safer and less disruptive than the
        # former arbitrary five-minute circuit.
        return 61.0

    @staticmethod
    def _parse_retry_after_header(value) -> float | None:
        if value is None:
            return None

        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            pass

        try:
            deadline = parsedate_to_datetime(str(value))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            return max(
                0.0,
                (deadline - datetime.now(UTC)).total_seconds(),
            )
        except (TypeError, ValueError, OverflowError):
            return None


provider_circuit_breaker = ProviderCircuitBreaker()
