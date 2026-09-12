"""Minimal process boundary for DARWIN shell activity state.

This deliberately does not run the assistant, microphone, or speech pipeline yet.
It gives the desktop a Python-owned state stream that those systems can publish to
later without coupling the renderer to terminal output.
"""

from __future__ import annotations

import json
import os
import select
import socket
import sys
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError

from app.protocol.schemas import PROTOCOL_VERSION
from app.services.ui_activity import activity_socket_path


AssistantStateName = Literal[
    "idle", "listening", "transcribing", "thinking", "speaking", "error"
]


class StateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    type: Literal["assistant.state.preview"]
    state: AssistantStateName


def state_message(state: AssistantStateName) -> dict[str, object]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "type": "assistant.state",
        "requestId": None,
        "state": state,
    }


def audio_level_message(level: float) -> dict[str, object]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "type": "assistant.audio-level",
        "level": max(0.0, min(1.0, level)),
    }


def run_state_service(token: str) -> None:
    def publish(state: AssistantStateName) -> None:
        print(json.dumps(state_message(state), separators=(",", ":")), flush=True)

    def publish_level(level: float) -> None:
        print(json.dumps(audio_level_message(level), separators=(",", ":")), flush=True)

    socket_path = activity_socket_path()
    socket_path.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as activity_socket:
        activity_socket.bind(str(socket_path))
        socket_path.chmod(0o600)
        publish("idle")
        try:
            while True:
                readable, _, _ = select.select([sys.stdin, activity_socket], [], [])
                if activity_socket in readable:
                    try:
                        payload = json.loads(activity_socket.recv(512))
                        state = payload.get("state") if isinstance(payload, dict) else None
                        if (
                            isinstance(payload, dict)
                            and payload.get("type") == "audio.level"
                            and isinstance(payload.get("level"), (int, float))
                        ):
                            publish_level(float(payload["level"]))
                            continue
                        if state in {
                            "idle",
                            "listening",
                            "transcribing",
                            "thinking",
                            "speaking",
                            "error",
                        }:
                            publish(state)
                    except (OSError, ValueError):
                        pass
                if sys.stdin in readable:
                    raw_line = sys.stdin.readline()
                    if not raw_line:
                        break
                    try:
                        command = StateCommand.model_validate_json(raw_line)
                        if command.token == token:
                            publish(command.state)
                    except (ValidationError, ValueError):
                        continue
        finally:
            socket_path.unlink(missing_ok=True)


def main() -> None:
    token = os.environ.get("DARWIN_UI_STATE_TOKEN", "")
    if not token:
        raise SystemExit("DARWIN_UI_STATE_TOKEN is required")
    run_state_service(token)


if __name__ == "__main__":
    main()
