"""Structured, request-scoped activity events emitted by the DARWIN runtime."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Event
from typing import Literal

RuntimeEventKind = Literal[
    "state", "skill", "response", "confirmation", "ui_command", "error"
]
RuntimeState = Literal["idle", "thinking", "error"]
SkillPhase = Literal["started", "completed", "failed"]


@dataclass(frozen=True)
class RuntimeEvent:
    kind: RuntimeEventKind
    request_id: str
    session_id: str
    state: RuntimeState | None = None
    skill: str | None = None
    phase: SkillPhase | None = None
    content: str | None = None
    final: bool | None = None
    error: str | None = None
    error_code: str | None = None
    summary: str | None = None
    risk: str | None = None
    expires_at: str | None = None
    command: str | None = None
    payload: dict[str, object] | None = None


EventSink = Callable[[RuntimeEvent], None]
_event_sink: ContextVar[EventSink | None] = ContextVar(
    "darwin_runtime_event_sink", default=None
)
_request_id: ContextVar[str] = ContextVar("darwin_runtime_request_id", default="system")
_session_id: ContextVar[str] = ContextVar("darwin_runtime_session_id", default="system")
_cancel_event: ContextVar[Event | None] = ContextVar(
    "darwin_runtime_cancel_event", default=None
)


class RuntimeRequestCancelled(RuntimeError):
    """Raised at cooperative boundaries after the user stops a request."""


def raise_if_cancelled() -> None:
    event = _cancel_event.get()
    if event is not None and event.is_set():
        raise RuntimeRequestCancelled("Request cancelled")


def emit_runtime_event(event: RuntimeEvent) -> None:
    sink = _event_sink.get()
    if sink is not None:
        sink(event)


def current_runtime_request() -> tuple[str, str]:
    return _request_id.get(), _session_id.get()


@contextmanager
def runtime_event_context(
    sink: EventSink,
    request_id: str,
    session_id: str,
    cancel_event: Event | None = None,
) -> Iterator[None]:
    sink_token = _event_sink.set(sink)
    request_token = _request_id.set(request_id)
    session_token = _session_id.set(session_id)
    cancel_token = _cancel_event.set(cancel_event)
    try:
        yield
    finally:
        _cancel_event.reset(cancel_token)
        _session_id.reset(session_token)
        _request_id.reset(request_token)
        _event_sink.reset(sink_token)
