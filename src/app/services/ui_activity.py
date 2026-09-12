"""Low-cost local activity notifications for the DARWIN desktop shell."""

from __future__ import annotations

import json
import os
import socket
import tempfile
from pathlib import Path
from typing import Literal


AssistantStateName = Literal[
    "idle", "listening", "transcribing", "thinking", "speaking", "error"
]


def activity_socket_path() -> Path:
    configured = os.environ.get("DARWIN_UI_ACTIVITY_SOCKET")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / f"darwin-ui-activity-{os.getuid()}.sock"


def publish_ui_state(state: AssistantStateName) -> bool:
    """Publish without delaying voice work when the shell is not running."""
    message = json.dumps({"state": state}, separators=(",", ":")).encode()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            client.sendto(message, str(activity_socket_path()))
        return True
    except OSError:
        return False


def publish_ui_audio_level(level: float) -> bool:
    message = json.dumps(
        {"type": "audio.level", "level": max(0.0, min(1.0, level))},
        separators=(",", ":"),
    ).encode()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            client.sendto(message, str(activity_socket_path()))
        return True
    except OSError:
        return False
