from collections.abc import Callable
from time import monotonic
from typing import TypeVar
from uuid import uuid4

from app.safety.audit import record_action
from app.safety.confirmation import request_confirmation
from app.safety.context import current_session_id
from app.safety.models import ActionOutcome, ActionRequest, ExecutionResult
from app.safety.policy import get_policy


T = TypeVar("T")


def execute_guarded(
    action_key: str,
    summary: str,
    operation: Callable[[], T],
    metadata: dict[str, str] | None = None,
) -> ExecutionResult[T]:
    """Authorize, execute, and audit one allowlisted action."""
    started = monotonic()
    policy = get_policy(action_key)
    request = ActionRequest(
        action_id=str(uuid4()),
        policy=policy,
        summary=summary.strip(),
        session_id=current_session_id(),
        metadata=metadata or {},
    )

    if not request_confirmation(request):
        record_action(request, ActionOutcome.DENIED, monotonic() - started)
        return ExecutionResult(outcome=ActionOutcome.DENIED)

    try:
        value = operation()
    except Exception as error:
        error_type = type(error).__name__
        record_action(
            request,
            ActionOutcome.FAILED,
            monotonic() - started,
            error_type=error_type,
        )
        return ExecutionResult(
            outcome=ActionOutcome.FAILED,
            error_type=error_type,
        )

    record_action(request, ActionOutcome.SUCCEEDED, monotonic() - started)
    return ExecutionResult(outcome=ActionOutcome.SUCCEEDED, value=value)
