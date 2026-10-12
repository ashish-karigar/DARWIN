import json
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.protocol.schemas import PROTOCOL_VERSION
from app.runtime import AssistantRuntime
from app.safety.confirmation import request_confirmation
from app.safety.models import ActionPolicy, ActionRequest, RiskLevel
from app.services.assistant_api import BACKEND_VERSION, create_app


def wire_message(message_type: str, **payload: object) -> dict[str, object]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "type": message_type,
        **payload,
    }


def test_health_reports_backend_and_protocol_versions() -> None:
    client = TestClient(create_app())

    assert client.get("/health").json() == {
        "status": "ok",
        "backendVersion": BACKEND_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
    }


def test_authenticated_service_rejects_missing_credentials() -> None:
    client = TestClient(create_app(auth_token="secret"))

    assert client.get("/health").status_code == 401
    assert (
        client.get("/health", headers={"x-darwin-token": "secret"}).status_code
        == 200
    )


def test_groq_usage_is_exposed_only_to_authenticated_ui() -> None:
    usage = {
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
        "used_tokens": 73_420,
        "input_tokens": 70_000,
        "output_tokens": 3_420,
        "daily_limit_tokens": 200_000,
        "remaining_tokens": 126_580,
        "request_count": 12,
        "usage_day": "2026-09-12",
        "reset_at": "2026-09-13T00:00:00+00:00",
        "tracked_since": "2026-09-12T12:00:00+00:00",
        "scope": "darwin-local",
    }

    with patch(
        "app.services.assistant_api.get_groq_daily_usage"
    ) as get_usage:
        get_usage.return_value.as_dict.return_value = usage
        client = TestClient(create_app(auth_token="secret"))

        assert client.get("/usage/groq").status_code == 401
        response = client.get(
            "/usage/groq",
            headers={"x-darwin-token": "secret"},
        )

    assert response.status_code == 200
    assert response.json() == usage


def test_websocket_submits_to_one_session_and_correlates_events() -> None:
    created_sessions: list[str] = []

    def runtime_factory(session_id: str) -> AssistantRuntime:
        created_sessions.append(session_id)
        return AssistantRuntime(
            session_id,
            supervisor_runner=lambda message, _session: f"Received: {message}",
            activity_publisher=lambda _state: True,
            skill_publisher=lambda _skill, _phase, _request: True,
        )

    client = TestClient(create_app(runtime_factory))
    request = wire_message(
        "assistant.request", sessionId="desktop", content="status"
    )

    with client.websocket_connect("/ws") as socket:
        socket.send_json(wire_message("session.hello", clientName="DARWIN UI"))
        assert socket.receive_json()["type"] == "session.ready"
        socket.send_json(request)
        messages = [socket.receive_json() for _ in range(3)]

        socket.send_json(
            wire_message("assistant.request", sessionId="desktop", content="again")
        )
        second_messages = [socket.receive_json() for _ in range(3)]

    assert [message["type"] for message in messages] == [
        "assistant.state",
        "assistant.response",
        "assistant.state",
    ]
    assert messages[0]["state"] == "thinking"
    assert messages[1]["content"] == "Received: status"
    assert messages[1]["final"] is True
    assert messages[2]["state"] == "idle"
    assert {message["requestId"] for message in messages} == {request["messageId"]}
    assert len(second_messages) == 3
    assert created_sessions == ["desktop"]


def test_websocket_streams_weather_acknowledgement_before_final_answer() -> None:
    def runtime_factory(session_id: str) -> AssistantRuntime:
        return AssistantRuntime(
            session_id,
            supervisor_runner=lambda _message, _session: "should not run",
            enable_fast_paths=True,
            activity_publisher=lambda _state: True,
            skill_publisher=lambda _skill, _phase, _request: True,
        )

    client = TestClient(create_app(runtime_factory))
    request = wire_message(
        "assistant.request", sessionId="desktop", content="Weather in Harrisburg?"
    )

    with patch(
        "app.runtime.fetch_weather_response", return_value="It is 72 degrees."
    ):
        with client.websocket_connect("/ws") as socket:
            socket.send_json(wire_message("session.hello", clientName="DARWIN UI"))
            socket.receive_json()
            socket.send_json(request)
            messages = [socket.receive_json() for _ in range(8)]

    responses = [
        message for message in messages if message["type"] == "assistant.response"
    ]
    assert [(message["content"], message["final"]) for message in responses] == [
        ("Checking Harrisburg now.", False),
        ("It is 72 degrees.", True),
    ]


def test_websocket_requires_hello_and_returns_structured_validation_errors() -> None:
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as socket:
        socket.send_json(
            wire_message("assistant.request", sessionId="desktop", content="hello")
        )
        not_ready = socket.receive_json()
        assert not_ready["type"] == "error"
        assert not_ready["code"] == "session_not_ready"

        socket.send_text("not json")
        invalid = socket.receive_json()
        assert invalid["type"] == "error"
        assert invalid["code"] == "invalid_message"
        assert invalid["recoverable"] is True


def test_websocket_rejects_oversized_messages() -> None:
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps({"padding": "x" * (64 * 1024)}))
        error = socket.receive_json()
        assert error["code"] == "message_too_large"


def test_websocket_returns_safe_error_without_a_traceback() -> None:
    def runtime_factory(session_id: str) -> AssistantRuntime:
        def fail(_message: str, _session: str) -> str:
            raise RuntimeError("private backend detail")

        return AssistantRuntime(
            session_id,
            supervisor_runner=fail,
            activity_publisher=lambda _state: True,
        )

    client = TestClient(create_app(runtime_factory))
    request = wire_message("assistant.request", sessionId="desktop", content="fail")

    with client.websocket_connect("/ws") as socket:
        socket.send_json(wire_message("session.hello", clientName="DARWIN UI"))
        socket.receive_json()
        socket.send_json(request)
        messages = [socket.receive_json() for _ in range(3)]

    error = next(message for message in messages if message["type"] == "error")
    assert error["code"] == "assistant_failed"
    assert error["message"] == "The assistant request failed."
    assert "private backend detail" not in json.dumps(messages)


def test_websocket_resolves_a_structured_confirmation() -> None:
    def runtime_factory(session_id: str) -> AssistantRuntime:
        def confirm(_message: str, _session: str) -> str:
            approved = request_confirmation(
                ActionRequest(
                    action_id="test.write",
                    policy=ActionPolicy(
                        "test.write", RiskLevel.REVERSIBLE_WRITE, "Test write"
                    ),
                    summary="Change the test value",
                    session_id=session_id,
                )
            )
            return "Approved" if approved else "Denied"

        return AssistantRuntime(
            session_id,
            supervisor_runner=confirm,
            activity_publisher=lambda _state: True,
        )

    client = TestClient(create_app(runtime_factory))
    request = wire_message("assistant.request", sessionId="desktop", content="change it")

    with client.websocket_connect("/ws") as socket:
        socket.send_json(wire_message("session.hello", clientName="DARWIN UI"))
        socket.receive_json()
        socket.send_json(request)
        assert socket.receive_json()["state"] == "thinking"
        confirmation = socket.receive_json()
        assert confirmation["type"] == "confirmation.required"
        assert confirmation["summary"] == "Change the test value"
        socket.send_json(
            wire_message(
                "confirmation.response",
                requestId=request["messageId"],
                approved=True,
            )
        )
        response = socket.receive_json()
        assert response["type"] == "assistant.response"
        assert response["content"] == "Approved"
        assert socket.receive_json()["state"] == "idle"


def test_websocket_cancels_response_delivery() -> None:
    def runtime_factory(session_id: str) -> AssistantRuntime:
        import time

        return AssistantRuntime(
            session_id,
            supervisor_runner=lambda _message, _session: (time.sleep(0.05) or "late"),
            activity_publisher=lambda _state: True,
        )

    client = TestClient(create_app(runtime_factory))
    request = wire_message("assistant.request", sessionId="desktop", content="wait")

    with client.websocket_connect("/ws") as socket:
        socket.send_json(wire_message("session.hello", clientName="DARWIN UI"))
        socket.receive_json()
        socket.send_json(request)
        assert socket.receive_json()["state"] == "thinking"
        socket.send_json(
            wire_message("assistant.cancel", requestId=request["messageId"])
        )
        error = socket.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "cancelled"
        assert socket.receive_json()["state"] == "idle"


def test_voice_entry_transcribes_and_uses_the_same_session() -> None:
    def runtime_factory(session_id: str) -> AssistantRuntime:
        return AssistantRuntime(
            session_id,
            supervisor_runner=lambda message, _session: f"Heard: {message}",
            activity_publisher=lambda _state: True,
        )

    client = TestClient(create_app(runtime_factory))
    request = wire_message("assistant.listen", sessionId="desktop")

    with patch("app.voice.speech_to_text.listen", return_value="camera status"):
        with client.websocket_connect("/ws") as socket:
            socket.send_json(wire_message("session.hello", clientName="DARWIN UI"))
            socket.receive_json()
            socket.send_json(request)
            messages = [socket.receive_json() for _ in range(4)]

    assert [message["type"] for message in messages] == [
        "assistant.transcription",
        "assistant.state",
        "assistant.response",
        "assistant.state",
    ]
    assert messages[0]["content"] == "camera status"
    assert messages[2]["content"] == "Heard: camera status"
    assert {message["requestId"] for message in messages} == {request["messageId"]}
