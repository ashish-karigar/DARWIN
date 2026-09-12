import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from app.protocol.schemas import PROTOCOL_VERSION, server_message_adapter
from app.services import ui_activity
from app.services.ui_state import StateCommand, audio_level_message, state_message


def test_state_message_uses_the_shared_wire_contract() -> None:
    message = state_message("listening")
    parsed = server_message_adapter.validate_python(message)

    assert parsed.type == "assistant.state"
    assert parsed.state == "listening"
    assert parsed.protocol_version == PROTOCOL_VERSION


def test_preview_command_rejects_unknown_fields() -> None:
    command = StateCommand.model_validate(
        {"token": "secret", "type": "assistant.state.preview", "state": "speaking"}
    )

    assert command.state == "speaking"


def test_audio_level_message_uses_the_shared_wire_contract() -> None:
    parsed = server_message_adapter.validate_python(audio_level_message(0.72))

    assert parsed.type == "assistant.audio-level"
    assert parsed.level == 0.72


def short_socket_path() -> Path:
    return Path(tempfile.gettempdir()) / f"darwin-test-{uuid4().hex[:8]}.sock"


def test_voice_activity_reaches_the_local_state_socket(monkeypatch) -> None:
    socket_path = short_socket_path()
    monkeypatch.setattr(ui_activity, "activity_socket_path", lambda: socket_path)

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as listener:
            listener.bind(str(socket_path))
            assert ui_activity.publish_ui_state("listening") is True
            assert json.loads(listener.recv(512)) == {"state": "listening"}
    finally:
        socket_path.unlink(missing_ok=True)


def test_state_service_forwards_real_voice_activity(monkeypatch) -> None:
    socket_path = short_socket_path()
    environment = {
        **os.environ,
        "DARWIN_UI_STATE_TOKEN": "test-token",
        "DARWIN_UI_ACTIVITY_SOCKET": str(socket_path),
    }
    monkeypatch.setenv("DARWIN_UI_ACTIVITY_SOCKET", str(socket_path))
    process = subprocess.Popen(
        [sys.executable, "-m", "app.services.ui_state"],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert json.loads(process.stdout.readline())["state"] == "idle"
        assert ui_activity.publish_ui_state("listening") is True
        assert json.loads(process.stdout.readline())["state"] == "listening"
        assert ui_activity.publish_ui_audio_level(0.64) is True
        assert json.loads(process.stdout.readline())["level"] == 0.64
    finally:
        if process.stdin is not None:
            process.stdin.close()
        process.wait(timeout=2)
