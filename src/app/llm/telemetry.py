from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ModelCallEvent:
    schema: str
    provider: str
    outcome: str
    attempt: int
    elapsed_seconds: float
    used_fallback: bool
    error_type: str | None = None
    error_message: str | None = None
    retry_after_seconds: float | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


_active_events: ContextVar[list[ModelCallEvent] | None] = (
    ContextVar("darwin_model_call_events", default=None)
)


def record_model_call(event: ModelCallEvent) -> None:
    events = _active_events.get()

    if events is not None:
        events.append(event)


@contextmanager
def capture_model_calls() -> Iterator[list[ModelCallEvent]]:
    events: list[ModelCallEvent] = []
    token = _active_events.set(events)

    try:
        yield events
    finally:
        _active_events.reset(token)
