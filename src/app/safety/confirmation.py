from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.safety.models import ActionRequest


ConfirmationHandler = Callable[[ActionRequest], bool]
_handler: ConfirmationHandler | None = None
_context_handler: ContextVar[ConfirmationHandler | None] = ContextVar(
    "darwin_confirmation_handler", default=None
)


def set_confirmation_handler(handler: ConfirmationHandler | None) -> None:
    global _handler
    _handler = handler


@contextmanager
def confirmation_context(handler: ConfirmationHandler) -> Iterator[None]:
    token = _context_handler.set(handler)
    try:
        yield
    finally:
        _context_handler.reset(token)


def request_confirmation(request: ActionRequest) -> bool:
    """Request confirmation, denying safely when no UI handler is installed."""
    if not request.policy.requires_confirmation:
        return True
    handler = _context_handler.get() or _handler
    if handler is None:
        return False
    try:
        return bool(handler(request))
    except Exception:
        return False
