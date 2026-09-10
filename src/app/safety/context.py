from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator


_session_id: ContextVar[str] = ContextVar("darwin_action_session_id", default="system")


def current_session_id() -> str:
    return _session_id.get()


@contextmanager
def action_context(session_id: str) -> Iterator[None]:
    token = _session_id.set(session_id)
    try:
        yield
    finally:
        _session_id.reset(token)
