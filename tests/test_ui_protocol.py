import pytest
from pydantic import ValidationError

from app.protocol.schemas import (
    AppManifest,
    PROTOCOL_VERSION,
    client_message_adapter,
    darwin_input_event_adapter,
    server_message_adapter,
)


MESSAGE_BASE = {
    "protocolVersion": PROTOCOL_VERSION,
    "messageId": "6f6bbfd0-dde9-4c27-9234-7f8156631d7a",
    "timestamp": "2026-09-10T02:00:00Z",
}


def test_native_manifest_requires_entry() -> None:
    with pytest.raises(ValidationError):
        AppManifest.model_validate(
            {
                "id": "darwin.settings",
                "name": "Settings",
                "version": "1.0.0",
                "type": "native",
            }
        )


def test_web_manifest_requires_an_approved_https_origin_and_session() -> None:
    with pytest.raises(ValidationError, match="approved HTTPS origin"):
        AppManifest.model_validate(
            {
                "id": "darwin.video",
                "name": "Video",
                "version": "1.0.0",
                "type": "web",
                "url": "https://video.example",
                "allowedOrigins": ["https://evil.example"],
                "session": "darwin.video",
            }
        )


def test_input_event_discriminator_accepts_pointer_move() -> None:
    event = darwin_input_event_adapter.validate_python(
        {
            "type": "pointer.move",
            "source": "gesture",
            "timestamp": 1_789_000_000_000,
            "confidence": 0.95,
            "x": 320,
            "y": 180,
        }
    )

    assert event.type == "pointer.move"


def test_assistant_request_rejects_empty_content() -> None:
    with pytest.raises(ValidationError):
        client_message_adapter.validate_python(
            {
                **MESSAGE_BASE,
                "type": "assistant.request",
                "sessionId": "default",
                "content": "",
            }
        )


def test_assistant_request_rejects_unsupported_version() -> None:
    with pytest.raises(ValidationError, match="Unsupported protocol version"):
        client_message_adapter.validate_python(
            {
                **MESSAGE_BASE,
                "protocolVersion": "2.0",
                "type": "assistant.request",
                "sessionId": "default",
                "content": "Status report.",
            }
        )


def test_server_error_message_is_versioned_and_validated() -> None:
    message = server_message_adapter.validate_python(
        {
            **MESSAGE_BASE,
            "type": "error",
            "requestId": None,
            "code": "invalid_message",
            "message": "The message could not be validated.",
            "recoverable": True,
        }
    )

    assert message.type == "error"
