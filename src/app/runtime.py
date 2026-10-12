"""Reusable single-session orchestration for terminal and future OS clients."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, RLock, Timer
from time import perf_counter
from uuid import uuid4

from app.agents.supervisor import run_supervisor
from app.runtime_events import (
    EventSink,
    RuntimeEvent,
    RuntimeRequestCancelled,
    runtime_event_context,
)
from app.safety import action_context, confirmation_context
from app.safety.models import ActionRequest
from app.services.performance_log import RequestPerformanceTrace
from app.services.conversational_weather import (
    correction_location,
    fetch_weather_response,
    is_weather_request,
    resolve_weather_intent,
)
from app.services.conversational_context import ambient_intent, ambient_response
from app.services.ui_activity import publish_ui_skill, publish_ui_state
from app.services.request_acknowledgement import acknowledgement_for

SupervisorRunner = Callable[[str, str], str]
ActivityPublisher = Callable[[str], bool]
SkillPublisher = Callable[[str, str, str], bool]


@dataclass(frozen=True)
class AssistantResult:
    request_id: str
    session_id: str
    content: str
    reasoning_seconds: float


class AssistantCancelledError(RuntimeError):
    pass


@dataclass
class _ActiveRequest:
    cancelled: Event
    confirmation: Event
    approved: bool = False
    intent: str | None = None
    acknowledged: bool = False


class AssistantRuntime:
    """Submit messages to one DARWIN session and observe structured lifecycle events."""

    def __init__(
        self,
        session_id: str = "default",
        *,
        supervisor_runner: SupervisorRunner = run_supervisor,
        activity_publisher: ActivityPublisher = publish_ui_state,
        skill_publisher: SkillPublisher = publish_ui_skill,
        confirmation_timeout: float = 30.0,
        enable_fast_paths: bool | None = None,
        enable_acknowledgements: bool = True,
        acknowledgement_delay: float = 1.0,
    ) -> None:
        normalized_session = session_id.strip()
        if not normalized_session:
            raise ValueError("session_id must not be empty")
        self.session_id = normalized_session
        self._supervisor_runner = supervisor_runner
        self._activity_publisher = activity_publisher
        self._skill_publisher = skill_publisher
        self._confirmation_timeout = max(0.01, confirmation_timeout)
        self._enable_acknowledgements = enable_acknowledgements
        self._acknowledgement_delay = max(0.01, acknowledgement_delay)
        self._enable_fast_paths = (
            supervisor_runner is run_supervisor
            if enable_fast_paths is None
            else enable_fast_paths
        )
        self._execution_lock = Lock()
        self._listener_lock = RLock()
        self._listeners: list[EventSink] = []
        self._active_lock = RLock()
        self._active: dict[str, _ActiveRequest] = {}
        self._awaiting_weather_location = False
        self._default_weather_location: str | None = None

    def subscribe(self, listener: EventSink) -> Callable[[], None]:
        with self._listener_lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._listener_lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def submit(self, message: str, request_id: str | None = None) -> AssistantResult:
        content = message.strip()
        if not content:
            raise ValueError("message must not be empty")
        if len(content) > 50_000:
            raise ValueError("message exceeds 50,000 characters")

        request_id = request_id or str(uuid4())
        active = _ActiveRequest(cancelled=Event(), confirmation=Event())
        corrected_location: str | None = None
        with self._active_lock:
            if request_id in self._active:
                raise ValueError("request_id is already active")
            previous = tuple(self._active.values())
            if self._enable_fast_paths and len(previous) == 1:
                previous_turn = previous[0]
                if previous_turn.intent == "weather":
                    corrected_location = correction_location(content)
            if (
                self._enable_fast_paths
                and corrected_location is None
                and self._awaiting_weather_location
            ):
                corrected_location = correction_location(content)
            if corrected_location:
                for previous_turn in previous:
                    previous_turn.cancelled.set()
                    previous_turn.confirmation.set()
                active.intent = "weather"
            elif self._enable_fast_paths and is_weather_request(content):
                active.intent = "weather"
            elif self._enable_fast_paths:
                active.intent = ambient_intent(content)
            self._active[request_id] = active
        performance_trace = RequestPerformanceTrace(
            content, request_id, self.session_id
        )
        unsubscribe_performance = self.subscribe(performance_trace.observe)
        if active.intent == "weather":
            return self._submit_weather(
                content,
                request_id,
                active,
                performance_trace,
                unsubscribe_performance,
                corrected_location=corrected_location,
            )
        if active.intent in {"time", "location"}:
            return self._submit_immediate(
                request_id,
                active,
                performance_trace,
                unsubscribe_performance,
                content=ambient_response(active.intent),
                operation=f"context.{active.intent}",
            )

        with self._execution_lock:
            self._publish(
                RuntimeEvent(
                    kind="state",
                    request_id=request_id,
                    session_id=self.session_id,
                    state="thinking",
                )
            )
            self._publish_activity("thinking")
            started = perf_counter()
            acknowledgement_timer: Timer | None = None
            try:
                if active.cancelled.is_set():
                    raise AssistantCancelledError("Request cancelled")
                acknowledgement = acknowledgement_for(content)
                if acknowledgement:
                    self._acknowledge_once(request_id, active, acknowledgement)
                elif self._enable_acknowledgements:
                    acknowledgement_timer = Timer(
                        self._acknowledgement_delay, self._acknowledge_once,
                        args=(request_id, active, "I'm on it."),
                    )
                    acknowledgement_timer.daemon = True
                    acknowledgement_timer.start()
                with runtime_event_context(
                    self._publish,
                    request_id,
                    self.session_id,
                    active.cancelled,
                ), action_context(self.session_id), confirmation_context(
                    lambda request: self._confirm(request_id, active, request)
                ):
                    response = self._supervisor_runner(content, self.session_id)
                if acknowledgement_timer:
                    acknowledgement_timer.cancel()
                with self._active_lock:
                    active.acknowledged = True
                if active.cancelled.is_set():
                    raise AssistantCancelledError("Request cancelled")
                if not isinstance(response, str) or not response.strip():
                    raise RuntimeError("The supervisor returned an empty response.")
                elapsed = perf_counter() - started
                self._publish(
                    RuntimeEvent(
                        kind="response",
                        request_id=request_id,
                        session_id=self.session_id,
                        content=response,
                    )
                )
                self._publish(
                    RuntimeEvent(
                        kind="state",
                        request_id=request_id,
                        session_id=self.session_id,
                        state="idle",
                    )
                )
                self._publish_activity("idle")
                performance_trace.finish(
                    success=True, response_characters=len(response)
                )
                return AssistantResult(request_id, self.session_id, response, elapsed)
            except Exception as error:
                if acknowledgement_timer:
                    acknowledgement_timer.cancel()
                with self._active_lock:
                    active.acknowledged = True
                cancelled = isinstance(
                    error, (AssistantCancelledError, RuntimeRequestCancelled)
                )
                safe_error = str(error).strip()[:500] or type(error).__name__
                self._publish(
                    RuntimeEvent(
                        kind="error",
                        request_id=request_id,
                        session_id=self.session_id,
                        error=safe_error,
                        error_code=(
                            "cancelled"
                            if cancelled
                            else "assistant_failed"
                        ),
                    )
                )
                self._publish(
                    RuntimeEvent(
                        kind="state",
                        request_id=request_id,
                        session_id=self.session_id,
                        state="idle" if cancelled else "error",
                    )
                )
                self._publish_activity("idle" if cancelled else "error")
                performance_trace.finish(
                    success=False, error_type=type(error).__name__
                )
                raise
            finally:
                if acknowledgement_timer:
                    acknowledgement_timer.cancel()
                unsubscribe_performance()
                with self._active_lock:
                    self._active.pop(request_id, None)

    def _submit_immediate(
        self,
        request_id: str,
        active: _ActiveRequest,
        performance_trace: RequestPerformanceTrace,
        unsubscribe_performance: Callable[[], None],
        *,
        content: str,
        operation: str,
    ) -> AssistantResult:
        started = perf_counter()
        try:
            self._publish(
                RuntimeEvent(
                    kind="skill",
                    request_id=request_id,
                    session_id=self.session_id,
                    skill=operation,
                    phase="started",
                )
            )
            if active.cancelled.is_set():
                raise AssistantCancelledError("Request cancelled")
            self._publish(
                RuntimeEvent(
                    kind="skill",
                    request_id=request_id,
                    session_id=self.session_id,
                    skill=operation,
                    phase="completed",
                )
            )
            self._publish(
                RuntimeEvent(
                    kind="response",
                    request_id=request_id,
                    session_id=self.session_id,
                    content=content,
                    final=True,
                )
            )
            self._publish(
                RuntimeEvent(
                    kind="state",
                    request_id=request_id,
                    session_id=self.session_id,
                    state="idle",
                )
            )
            elapsed = perf_counter() - started
            performance_trace.finish(success=True, response_characters=len(content))
            return AssistantResult(request_id, self.session_id, content, elapsed)
        finally:
            unsubscribe_performance()
            with self._active_lock:
                self._active.pop(request_id, None)

    def _submit_weather(
        self,
        content: str,
        request_id: str,
        active: _ActiveRequest,
        performance_trace: RequestPerformanceTrace,
        unsubscribe_performance: Callable[[], None],
        *,
        corrected_location: str | None,
    ) -> AssistantResult:
        """Run weather outside the serialized agent path so corrections can supersede it."""
        started = perf_counter()
        self._publish(
            RuntimeEvent(
                kind="state",
                request_id=request_id,
                session_id=self.session_id,
                state="thinking",
            )
        )
        self._publish_activity("thinking")
        try:
            self._publish(
                RuntimeEvent(
                    kind="skill",
                    request_id=request_id,
                    session_id=self.session_id,
                    skill="intent.weather",
                    phase="started",
                )
            )
            intent = resolve_weather_intent(
                content,
                corrected_location=corrected_location,
                default_location=self._default_weather_location,
            )
            if corrected_location:
                with self._active_lock:
                    self._default_weather_location = corrected_location
                    self._awaiting_weather_location = False
            self._publish(
                RuntimeEvent(
                    kind="skill",
                    request_id=request_id,
                    session_id=self.session_id,
                    skill="intent.weather",
                    phase="completed",
                )
            )
            self._acknowledge_once(request_id, active, intent.acknowledgement)
            self._publish(
                RuntimeEvent(
                    kind="skill",
                    request_id=request_id,
                    session_id=self.session_id,
                    skill="weather",
                    phase="started",
                )
            )
            response = fetch_weather_response(intent)
            with self._active_lock:
                self._awaiting_weather_location = response == "Which town should I use?"
            self._publish(
                RuntimeEvent(
                    kind="skill",
                    request_id=request_id,
                    session_id=self.session_id,
                    skill="weather",
                    phase="completed",
                )
            )
            if active.cancelled.is_set():
                raise AssistantCancelledError("Request superseded")
            elapsed = perf_counter() - started
            self._publish(
                RuntimeEvent(
                    kind="response",
                    request_id=request_id,
                    session_id=self.session_id,
                    content=response,
                    final=True,
                )
            )
            self._publish(
                RuntimeEvent(
                    kind="state",
                    request_id=request_id,
                    session_id=self.session_id,
                    state="idle",
                )
            )
            self._publish_activity("idle")
            performance_trace.finish(success=True, response_characters=len(response))
            return AssistantResult(request_id, self.session_id, response, elapsed)
        except Exception as error:
            error_code = (
                "superseded"
                if isinstance(error, AssistantCancelledError)
                and str(error) == "Request superseded"
                else "cancelled"
                if isinstance(error, AssistantCancelledError)
                else "assistant_failed"
            )
            self._publish(
                RuntimeEvent(
                    kind="error",
                    request_id=request_id,
                    session_id=self.session_id,
                    error=str(error).strip()[:500] or type(error).__name__,
                    error_code=error_code,
                )
            )
            performance_trace.finish(success=False, error_type=type(error).__name__)
            raise
        finally:
            unsubscribe_performance()
            with self._active_lock:
                self._active.pop(request_id, None)

    def cancel(self, request_id: str) -> bool:
        with self._active_lock:
            active = self._active.get(request_id)
        if active is None:
            return False
        active.cancelled.set()
        active.confirmation.set()
        return True

    def respond_confirmation(self, request_id: str, approved: bool) -> bool:
        with self._active_lock:
            active = self._active.get(request_id)
        if active is None:
            return False
        active.approved = approved
        active.confirmation.set()
        return True

    def _confirm(
        self, request_id: str, active: _ActiveRequest, request: ActionRequest
    ) -> bool:
        expires = datetime.now(UTC) + timedelta(seconds=self._confirmation_timeout)
        self._publish(
            RuntimeEvent(
                kind="confirmation",
                request_id=request_id,
                session_id=self.session_id,
                summary=request.summary,
                risk=request.policy.risk.value,
                expires_at=expires.isoformat().replace("+00:00", "Z"),
            )
        )
        answered = active.confirmation.wait(timeout=self._confirmation_timeout)
        return answered and not active.cancelled.is_set() and active.approved

    def _acknowledge_once(self, request_id: str, active: _ActiveRequest, content: str) -> None:
        if not self._enable_acknowledgements:
            return
        with self._active_lock:
            if active.cancelled.is_set() or active.acknowledged or self._active.get(request_id) is not active:
                return
            active.acknowledged = True
            self._publish(RuntimeEvent(
                kind="response", request_id=request_id, session_id=self.session_id,
                content=content, final=False,
            ))

    def _publish(self, event: RuntimeEvent) -> None:
        if event.kind == 'skill' and event.phase == 'started' and event.skill and not event.skill.startswith(('model.', 'intent.', 'context.')):
            with self._active_lock:
                active = self._active.get(event.request_id)
                if active:
                    self._acknowledge_once(event.request_id, active, "I'm on it.")
        if event.kind == "skill" and event.skill and event.phase:
            try:
                self._skill_publisher(event.skill, event.phase, event.request_id)
            except Exception:
                pass
        with self._listener_lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                # Observers cannot break assistant execution.
                continue

    def _publish_activity(self, state: str) -> None:
        try:
            self._activity_publisher(state)
        except Exception:
            # Desktop visualization is observational and cannot break reasoning.
            pass
