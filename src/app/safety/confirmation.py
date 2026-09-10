from collections.abc import Callable

from app.safety.models import ActionRequest


ConfirmationHandler = Callable[[ActionRequest], bool]
_handler: ConfirmationHandler | None = None


def set_confirmation_handler(handler: ConfirmationHandler | None) -> None:
    global _handler
    _handler = handler


def request_confirmation(request: ActionRequest) -> bool:
    """Request confirmation, denying safely when no UI handler is installed."""
    if not request.policy.requires_confirmation:
        return True
    if _handler is None:
        return False
    try:
        return bool(_handler(request))
    except Exception:
        return False
