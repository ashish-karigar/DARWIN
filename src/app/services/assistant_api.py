"""Loopback-only FastAPI boundary for the reusable DARWIN assistant runtime."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from threading import Lock
from threading import Event
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.llm.usage import get_groq_daily_usage
from app.protocol.schemas import (
    PROTOCOL_VERSION,
    AssistantCancel,
    AssistantListen,
    AssistantRequest,
    AssistantWake,
    MediaControl,
    ConfirmationResponse,
    SessionHello,
    client_message_adapter,
    server_message_adapter,
)
from app.runtime import AssistantRuntime
from app.runtime import AssistantResult
from app.runtime_events import RuntimeEvent

BACKEND_VERSION = "0.1.0"
MAX_MESSAGE_BYTES = 64 * 1024
RuntimeFactory = Callable[[str], AssistantRuntime]
SendJson = Callable[[dict[str, Any]], Awaitable[None]]
PartialResponseHandler = Callable[[str], Awaitable[None]]


class RuntimeRegistry:
    """Return one serialized runtime per explicit OS session ID."""

    def __init__(self, factory: RuntimeFactory) -> None:
        self._factory = factory
        self._lock = Lock()
        self._runtimes: dict[str, AssistantRuntime] = {}

    def get(self, session_id: str) -> AssistantRuntime:
        with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                runtime = self._factory(session_id)
                self._runtimes[session_id] = runtime
            return runtime


def _base(message_type: str) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "type": message_type,
    }


def _validated_message(payload: dict[str, Any]) -> dict[str, Any]:
    message = server_message_adapter.validate_python(payload)
    return message.model_dump(by_alias=True, mode="json", exclude_none=False)


def _error_message(
    code: str,
    message: str,
    *,
    request_id: UUID | str | None = None,
    recoverable: bool = True,
) -> dict[str, Any]:
    return _validated_message(
        {
            **_base("error"),
            "requestId": str(request_id) if request_id else None,
            "code": code,
            "message": message,
            "recoverable": recoverable,
        }
    )


def _runtime_message(event: RuntimeEvent, request_id: UUID) -> dict[str, Any] | None:
    if event.kind == "state" and event.state:
        return _validated_message(
            {
                **_base("assistant.state"),
                "requestId": str(request_id),
                "state": event.state,
            }
        )
    if event.kind == "skill" and event.skill and event.phase:
        return _validated_message(
            {
                **_base("assistant.activity"),
                "requestId": str(request_id),
                "skill": event.skill,
                "phase": event.phase,
            }
        )
    if event.kind == "response" and event.content is not None:
        return _validated_message(
            {
                **_base("assistant.response"),
                "requestId": str(request_id),
                "content": event.content,
                "final": event.final is not False,
            }
        )
    if event.kind == "ui_command" and event.command:
        payload = event.payload or {}
        return _validated_message(
            {
                **_base(event.command),
                "requestId": str(request_id),
                **payload,
            }
        )
    if event.kind == "confirmation" and event.summary and event.expires_at:
        risk = "low" if event.risk == "low_impact" else event.risk
        return _validated_message(
            {
                **_base("confirmation.required"),
                "requestId": str(request_id),
                "summary": event.summary,
                "risk": risk,
                "expiresAt": event.expires_at,
            }
        )
    if event.kind == "error":
        return _error_message(
            event.error_code or "assistant_failed",
            "Request cancelled."
            if event.error_code in {"cancelled", "superseded"}
            else "The assistant request failed.",
            request_id=request_id,
        )
    return None


async def _run_request(
    send_json: SendJson,
    runtime: AssistantRuntime,
    request: AssistantRequest,
    on_partial_response: PartialResponseHandler | None = None,
) -> AssistantResult | None:
    loop = asyncio.get_running_loop()
    events: asyncio.Queue[RuntimeEvent] = asyncio.Queue()

    def observe(event: RuntimeEvent) -> None:
        if event.request_id == str(request.message_id):
            loop.call_soon_threadsafe(events.put_nowait, event)

    unsubscribe = runtime.subscribe(observe)
    task = asyncio.create_task(
        asyncio.to_thread(runtime.submit, request.content, str(request.message_id))
    )
    error_sent = False

    async def deliver(event: RuntimeEvent) -> None:
        nonlocal error_sent
        message = _runtime_message(event, request.message_id)
        if message is None:
            return
        await send_json(message)
        if (
            event.kind == "response"
            and event.content is not None
            and event.final is False
            and on_partial_response is not None
        ):
            await on_partial_response(event.content)
        error_sent = error_sent or event.kind == "error"

    try:
        while not task.done() or not events.empty():
            try:
                event = await asyncio.wait_for(events.get(), timeout=0.05)
            except TimeoutError:
                continue
            await deliver(event)
        await asyncio.sleep(0)
        while not events.empty():
            await deliver(events.get_nowait())
        return await task
    except Exception:
        if not task.done():
            task.cancel()
        if not error_sent:
            await send_json(
                _error_message(
                    "assistant_failed",
                    "The assistant request failed.",
                    request_id=request.message_id,
                )
            )
    finally:
        unsubscribe()
    return None


def create_app(
    runtime_factory: RuntimeFactory = AssistantRuntime,
    *,
    auth_token: str | None = None,
) -> FastAPI:
    app = FastAPI(title="DARWIN Local API", version=BACKEND_VERSION)
    registry = RuntimeRegistry(runtime_factory)

    @app.get("/health")
    async def health(x_darwin_token: str | None = Header(default=None)) -> dict[str, str]:
        if auth_token and x_darwin_token != auth_token:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {
            "status": "ok",
            "backendVersion": BACKEND_VERSION,
            "protocolVersion": PROTOCOL_VERSION,
        }

    @app.get("/usage/groq")
    async def groq_usage(
        x_darwin_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        if auth_token and x_darwin_token != auth_token:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return get_groq_daily_usage().as_dict()

    @app.websocket("/ws")
    async def assistant_socket(websocket: WebSocket) -> None:
        client_host = websocket.client.host if websocket.client else ""
        if client_host not in {"127.0.0.1", "::1", "testclient"}:
            await websocket.close(code=1008, reason="Loopback clients only")
            return
        if auth_token and websocket.query_params.get("token") != auth_token:
            await websocket.close(code=1008, reason="Unauthorized")
            return
        await websocket.accept()
        ready = False
        send_lock = asyncio.Lock()
        active: dict[str, tuple[AssistantRuntime, asyncio.Task[None]]] = {}
        wake_task: asyncio.Task[None] | None = None
        wake_conversation: Any | None = None
        wake_enabled = False
        voice_cancellations: dict[str, Event] = {}
        loop = asyncio.get_running_loop()
        from app.services.media_state import subscribe_now_playing

        def on_media(payload: dict[str, Any]) -> None:
            message = _validated_message({**_base("media.now-playing"), **payload})
            loop.call_soon_threadsafe(asyncio.create_task, send(message))

        unsubscribe_media = subscribe_now_playing(on_media)

        async def send(payload: dict[str, Any]) -> None:
            async with send_lock:
                await websocket.send_json(payload)

        async def run_request(runtime: AssistantRuntime, request: AssistantRequest) -> None:
            try:
                await _run_request(send, runtime, request)
            finally:
                active.pop(str(request.message_id), None)

        async def run_voice(
            runtime: AssistantRuntime,
            request: AssistantListen,
            cancel_event: Event,
        ) -> None:
            request_id = str(request.message_id)
            voice_trace = None
            try:
                from app.services.performance_log import VoicePerformanceTrace
                from app.voice.speech_to_text import get_last_input_timing, listen

                transcription = await asyncio.to_thread(
                    listen, cancel_event=cancel_event
                )
                if cancel_event.is_set():
                    return
                if not transcription.strip():
                    await send(
                        _error_message(
                            "no_speech",
                            "No speech was detected.",
                            request_id=request.message_id,
                        )
                    )
                    return
                voice_trace = VoicePerformanceTrace(
                    transcription,
                    request_id,
                    request.session_id,
                    get_last_input_timing(),
                )
                await send(
                    _validated_message(
                        {
                            **_base("assistant.transcription"),
                            "requestId": request_id,
                            "content": transcription,
                            "final": True,
                        }
                    )
                )
                assistant_request = AssistantRequest.model_validate(
                    {
                        "protocolVersion": request.protocol_version,
                        "messageId": request_id,
                        "timestamp": request.timestamp,
                        "type": "assistant.request",
                        "sessionId": request.session_id,
                        "content": transcription,
                    }
                )
                async def speak_partial(content: str) -> None:
                    if not cancel_event.is_set():
                        from app.voice.text_to_speech import speak
                        requested_at = perf_counter()
                        timing = await asyncio.to_thread(
                            speak, content, cancel_event=cancel_event
                        )
                        if voice_trace is not None:
                            voice_trace.add_tts(
                                timing,
                                requested_at=requested_at,
                                label="text_to_speech.partial",
                            )

                from app.voice.text_to_speech import partial_speech_enabled

                result = await _run_request(
                    send,
                    runtime,
                    assistant_request,
                    on_partial_response=(
                        speak_partial if partial_speech_enabled() else None
                    ),
                )
                if result is not None and voice_trace is not None:
                    voice_trace.set_reasoning(result.reasoning_seconds)
                    voice_trace.finish(success=not cancel_event.is_set())
            except Exception:
                if voice_trace is not None:
                    voice_trace.finish(
                        success=False, error_type="voice_request_failed"
                    )
                await send(
                    _error_message(
                        "transcription_failed",
                        "Speech could not be transcribed.",
                        request_id=request.message_id,
                    )
                )
            finally:
                voice_cancellations.pop(request_id, None)
                active.pop(request_id, None)

        async def run_manual_voice(
            runtime: AssistantRuntime,
            request: AssistantListen,
            cancel_event: Event,
        ) -> None:
            nonlocal wake_task, wake_conversation
            from app.voice.text_to_speech import interrupt_speech

            interrupt_speech()
            current_request_id = str(request.message_id)
            for active_id, active_cancel in tuple(voice_cancellations.items()):
                if active_id != current_request_id:
                    active_cancel.set()
            if wake_task is not None and not wake_task.done():
                if wake_conversation is not None:
                    wake_conversation.close()
                wake_task.cancel()
                with suppress(asyncio.CancelledError):
                    await wake_task
                wake_task = None
            try:
                await run_voice(runtime, request, cancel_event)
            finally:
                if wake_enabled and wake_task is None:
                    wake_task = asyncio.create_task(run_wake(runtime))

        async def run_wake(runtime: AssistantRuntime) -> None:
            nonlocal wake_conversation
            from app.services.performance_log import VoicePerformanceTrace
            from app.voice.conversation import ContinuousConversation
            from app.voice.speech_to_text import get_last_input_timing
            from app.voice.text_to_speech import partial_speech_enabled, speak

            loop = asyncio.get_running_loop()
            state_events: asyncio.Queue[str] = asyncio.Queue()

            def on_state(state: str) -> None:
                loop.call_soon_threadsafe(state_events.put_nowait, state)

            try:
                wake_conversation = await asyncio.to_thread(
                    ContinuousConversation, on_state
                )
                while True:
                    capture = asyncio.create_task(
                        asyncio.to_thread(wake_conversation.next_message)
                    )
                    while not capture.done():
                        try:
                            state = await asyncio.wait_for(state_events.get(), 0.1)
                            await send(
                                _validated_message(
                                    {
                                        **_base("assistant.state"),
                                        "requestId": None,
                                        "state": state,
                                    }
                                )
                            )
                        except TimeoutError:
                            continue
                    transcription = await capture
                    request_id = uuid4()
                    voice_trace = VoicePerformanceTrace(
                        transcription,
                        str(request_id),
                        runtime.session_id,
                        get_last_input_timing(),
                    )
                    await send(
                        _validated_message(
                            {
                                **_base("assistant.transcription"),
                                "requestId": str(request_id),
                                "content": transcription,
                                "final": True,
                            }
                        )
                    )
                    request = AssistantRequest.model_validate(
                        {
                            **_base("assistant.request"),
                            "messageId": str(request_id),
                            "sessionId": runtime.session_id,
                            "content": transcription,
                        }
                    )
                    turn_cancel = Event()

                    async def process_turn() -> None:
                        async def speak_partial(content: str) -> None:
                            if wake_conversation is None or turn_cancel.is_set():
                                return
                            wake_conversation.response_started()
                            await send(
                                _validated_message(
                                    {
                                        **_base("assistant.state"),
                                        "requestId": str(request_id),
                                        "state": "speaking",
                                    }
                                )
                            )
                            try:
                                requested_at = perf_counter()
                                timing = await asyncio.to_thread(
                                    speak, content, cancel_event=turn_cancel
                                )
                                voice_trace.add_tts(
                                    timing,
                                    requested_at=requested_at,
                                    label="text_to_speech.partial",
                                )
                            finally:
                                wake_conversation.response_completed()

                        result = await _run_request(
                            send,
                            runtime,
                            request,
                            on_partial_response=(
                                speak_partial if partial_speech_enabled() else None
                            ),
                        )
                        if result is not None:
                            voice_trace.set_reasoning(result.reasoning_seconds)
                        if result is not None and not turn_cancel.is_set():
                            wake_conversation.response_started()
                            await send(
                                _validated_message(
                                    {
                                        **_base("assistant.state"),
                                        "requestId": str(request_id),
                                        "state": "speaking",
                                    }
                                )
                            )
                            try:
                                requested_at = perf_counter()
                                timing = await asyncio.to_thread(
                                    speak, result.content, cancel_event=turn_cancel
                                )
                                voice_trace.add_tts(
                                    timing,
                                    requested_at=requested_at,
                                    label="text_to_speech.final",
                                )
                            finally:
                                wake_conversation.response_completed()
                            if not turn_cancel.is_set():
                                await send(
                                    _validated_message(
                                        {
                                            **_base("assistant.state"),
                                            "requestId": str(request_id),
                                            "state": "idle",
                                        }
                                    )
                                )
                        voice_trace.finish(
                            success=result is not None and not turn_cancel.is_set()
                        )

                    request_key = str(request_id)
                    turn_task = asyncio.create_task(process_turn())
                    voice_cancellations[request_key] = turn_cancel
                    active[request_key] = (runtime, turn_task)
                    try:
                        await turn_task
                    except asyncio.CancelledError:
                        if asyncio.current_task() and asyncio.current_task().cancelling():
                            raise
                    finally:
                        voice_cancellations.pop(request_key, None)
                        active.pop(request_key, None)
            except asyncio.CancelledError:
                raise
            except Exception:
                await send(
                    _error_message(
                        "wake_listener_failed",
                        "Wake-word listening is unavailable.",
                    )
                )
            finally:
                if wake_conversation is not None:
                    wake_conversation.close()
                    wake_conversation = None

        try:
            while True:
                raw_message = await websocket.receive_text()
                if len(raw_message.encode("utf-8")) > MAX_MESSAGE_BYTES:
                    await send(
                        _error_message("message_too_large", "Message exceeds 64 KiB.")
                    )
                    await websocket.close(code=1009)
                    return
                try:
                    message = client_message_adapter.validate_python(
                        json.loads(raw_message)
                    )
                except (json.JSONDecodeError, ValidationError):
                    await send(
                        _error_message("invalid_message", "Message validation failed.")
                    )
                    continue

                if isinstance(message, SessionHello):
                    ready = True
                    await send(
                        _validated_message(
                            {
                                **_base("session.ready"),
                                "backendVersion": BACKEND_VERSION,
                                "acceptedProtocolVersion": PROTOCOL_VERSION,
                            }
                        )
                    )
                elif not ready:
                    await send(
                        _error_message(
                            "session_not_ready",
                            "Send session.hello before assistant requests.",
                        )
                    )
                elif isinstance(message, AssistantRequest):
                    request_id = str(message.message_id)
                    if request_id in active:
                        await send(
                            _error_message(
                                "duplicate_request",
                                "Request ID is already active.",
                                request_id=message.message_id,
                            )
                        )
                        continue
                    runtime = registry.get(message.session_id)
                    from app.voice.text_to_speech import interrupt_speech

                    interrupt_speech()
                    for active_cancel in tuple(voice_cancellations.values()):
                        active_cancel.set()
                    task = asyncio.create_task(run_request(runtime, message))
                    active[request_id] = (runtime, task)
                elif isinstance(message, AssistantListen):
                    request_id = str(message.message_id)
                    if request_id in active:
                        await send(
                            _error_message(
                                "duplicate_request",
                                "Request ID is already active.",
                                request_id=message.message_id,
                            )
                        )
                        continue
                    runtime = registry.get(message.session_id)
                    cancel_event = Event()
                    voice_cancellations[request_id] = cancel_event
                    task = asyncio.create_task(
                        run_manual_voice(runtime, message, cancel_event)
                    )
                    active[request_id] = (runtime, task)
                elif isinstance(message, AssistantWake):
                    wake_enabled = message.enabled
                    if message.enabled and (wake_task is None or wake_task.done()):
                        wake_task = asyncio.create_task(
                            run_wake(registry.get(message.session_id))
                        )
                    elif not message.enabled and wake_task is not None:
                        if wake_conversation is not None:
                            wake_conversation.close()
                        wake_task.cancel()
                        wake_task = None
                elif isinstance(message, MediaControl):
                    from app.tools.music import _control_with_fallback

                    try:
                        await asyncio.to_thread(
                            _control_with_fallback, message.action, "auto"
                        )
                    except Exception:
                        await send(
                            _error_message(
                                "media_control_failed",
                                "Music playback could not be controlled.",
                            )
                        )
                elif isinstance(message, AssistantCancel):
                    request_id = str(message.request_id)
                    entry = active.pop(request_id, None)
                    if entry is None:
                        await send(
                            _error_message(
                                "request_not_active",
                                "The request is no longer active.",
                                request_id=message.request_id,
                            )
                        )
                    else:
                        from app.voice.text_to_speech import interrupt_speech

                        cancel_event = voice_cancellations.pop(request_id, None)
                        if cancel_event is not None:
                            cancel_event.set()
                        interrupt_speech()
                        entry[0].cancel(request_id)
                        entry[1].cancel()
                        await send(
                            _error_message(
                                "cancelled",
                                "Request cancelled.",
                                request_id=message.request_id,
                            )
                        )
                        await send(
                            _validated_message(
                                {
                                    **_base("assistant.state"),
                                    "requestId": request_id,
                                    "state": "idle",
                                }
                            )
                        )
                elif isinstance(message, ConfirmationResponse):
                    entry = active.get(str(message.request_id))
                    if entry is None or not entry[0].respond_confirmation(
                        str(message.request_id), message.approved
                    ):
                        await send(
                            _error_message(
                                "confirmation_expired",
                                "The confirmation is no longer active.",
                                request_id=message.request_id,
                            )
                        )
                else:
                    await send(
                        _error_message(
                            "unsupported_message",
                            "This message type is not supported yet.",
                            request_id=getattr(message, "request_id", None),
                        )
                    )
        except WebSocketDisconnect:
            unsubscribe_media()
            for request_id, (runtime, task) in tuple(active.items()):
                runtime.cancel(request_id)
                task.cancel()
            if wake_conversation is not None:
                wake_conversation.close()
            if wake_task is not None:
                wake_task.cancel()
            return

    return app


app = create_app(auth_token=os.environ.get("DARWIN_API_TOKEN"))


def main() -> None:
    import uvicorn
    from app.services.ambient_context import start_background_refresh

    port = int(os.environ.get("DARWIN_API_PORT", "8765"))
    if not os.environ.get("DARWIN_API_TOKEN"):
        raise SystemExit("DARWIN_API_TOKEN is required")
    start_background_refresh()
    uvicorn.run(app, host="127.0.0.1", port=port, ws_max_size=MAX_MESSAGE_BYTES)


if __name__ == "__main__":
    main()
