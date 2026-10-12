from app.runtime import AssistantRuntime
from app.runtime_events import (
    RuntimeEvent,
    current_runtime_request,
    emit_runtime_event,
)
from app.safety.context import current_session_id
from app.safety.confirmation import request_confirmation
from app.safety.models import ActionPolicy, ActionRequest, RiskLevel
from threading import Event, Thread


def test_runtime_submits_with_action_context_and_correlated_events() -> None:
    observed: list[RuntimeEvent] = []
    activity: list[str] = []
    skills: list[tuple[str, str, str]] = []

    def supervisor(message: str, session_id: str) -> str:
        request_id, runtime_session = current_runtime_request()
        assert message == "What is the weather?"
        assert session_id == "desktop"
        assert runtime_session == "desktop"
        assert current_session_id() == "desktop"
        emit_runtime_event(
            RuntimeEvent(
                kind="skill",
                request_id=request_id,
                session_id=runtime_session,
                skill="weather",
                phase="started",
            )
        )
        return "Clear skies."

    runtime = AssistantRuntime(
        "desktop",
        supervisor_runner=supervisor,
        activity_publisher=activity.append,
        skill_publisher=lambda skill, phase, request_id: (
            skills.append((skill, phase, request_id)) or True
        ),
    )
    runtime.subscribe(observed.append)

    result = runtime.submit("  What is the weather?  ")

    assert result.content == "Clear skies."
    assert result.session_id == "desktop"
    assert result.reasoning_seconds >= 0
    assert activity == ["thinking", "idle"]
    assert [event.kind for event in observed] == ["state", "response", "skill", "response", "state"]
    assert observed[1].final is False
    assert {event.request_id for event in observed} == {result.request_id}
    assert observed[0].state == "thinking"
    assert observed[-1].state == "idle"
    assert skills == [("weather", "started", result.request_id)]


def test_runtime_emits_structured_failure_and_preserves_exception() -> None:
    observed: list[RuntimeEvent] = []
    activity: list[str] = []

    def broken_supervisor(_message: str, _session_id: str) -> str:
        raise RuntimeError("model unavailable")

    runtime = AssistantRuntime(
        supervisor_runner=broken_supervisor, activity_publisher=activity.append
    )
    runtime.subscribe(observed.append)

    try:
        runtime.submit("hello")
    except RuntimeError as error:
        assert str(error) == "model unavailable"
    else:
        raise AssertionError("runtime should preserve supervisor failures")

    assert [event.kind for event in observed] == ["state", "error", "state"]
    assert observed[1].error == "model unavailable"
    assert observed[2].state == "error"
    assert activity == ["thinking", "error"]


def test_runtime_rejects_empty_and_oversized_messages() -> None:
    runtime = AssistantRuntime(supervisor_runner=lambda _message, _session: "unused")

    for message in ("   ", "x" * 50_001):
        try:
            runtime.submit(message)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid message should be rejected")


def test_broken_observer_cannot_break_a_submission() -> None:
    runtime = AssistantRuntime(
        supervisor_runner=lambda _message, _session: "done",
        activity_publisher=lambda _state: True,
    )
    runtime.subscribe(lambda _event: (_ for _ in ()).throw(RuntimeError("observer")))

    assert runtime.submit("continue").content == "done"


def test_confirmation_times_out_closed() -> None:
    def supervisor(_message: str, session_id: str) -> str:
        approved = request_confirmation(
            ActionRequest(
                action_id="test.write",
                policy=ActionPolicy(
                    "test.write", RiskLevel.REVERSIBLE_WRITE, "Test write"
                ),
                summary="Change a value",
                session_id=session_id,
            )
        )
        return "approved" if approved else "denied"

    runtime = AssistantRuntime(
        supervisor_runner=supervisor,
        activity_publisher=lambda _state: True,
        confirmation_timeout=0.01,
    )

    assert runtime.submit("change it").content == "denied"


def test_runtime_cancel_returns_to_idle_and_discards_late_model_output() -> None:
    entered = Event()
    release = Event()
    observed: list[RuntimeEvent] = []
    errors: list[Exception] = []

    def slow_supervisor(_message: str, _session_id: str) -> str:
        entered.set()
        release.wait(timeout=2)
        return "This late response must not be delivered."

    runtime = AssistantRuntime(
        "desktop-test",
        supervisor_runner=slow_supervisor,
        activity_publisher=lambda _state: True,
    )
    runtime.subscribe(observed.append)

    def submit() -> None:
        try:
            runtime.submit("wait", "cancel-me")
        except Exception as error:
            errors.append(error)

    worker = Thread(target=submit)
    worker.start()
    assert entered.wait(timeout=1)
    assert runtime.cancel("cancel-me") is True
    release.set()
    worker.join(timeout=2)

    assert errors
    assert not any(event.kind == "response" for event in observed)
    assert observed[-2].error_code == "cancelled"
    assert observed[-1].state == "idle"
