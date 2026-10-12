"""Assistant controls for DARWIN's private in-shell Camera app."""

from __future__ import annotations

import json
from typing import Literal

from langchain_core.tools import tool

from app.runtime_events import RuntimeEvent, current_runtime_request, emit_runtime_event

CameraAction = Literal[
    "open",
    "close",
    "capture",
    "next_camera",
    "previous_camera",
    "start_detection",
    "stop_detection",
    "mirror_on",
    "mirror_off",
    "toggle_mirror",
]

_WIRE_ACTIONS: dict[CameraAction, str] = {
    "open": "open",
    "close": "close",
    "capture": "capture",
    "next_camera": "camera.next",
    "previous_camera": "camera.previous",
    "start_detection": "detection.start",
    "stop_detection": "detection.stop",
    "mirror_on": "mirror.on",
    "mirror_off": "mirror.off",
    "toggle_mirror": "mirror.toggle",
}


@tool
def control_camera(action: CameraAction) -> str:
    """Control the Camera app: open/close it, take a picture, switch cameras, start/stop object detection, or set/toggle mirroring."""
    request_id, session_id = current_runtime_request()
    emit_runtime_event(
        RuntimeEvent(
            kind="ui_command",
            request_id=request_id,
            session_id=session_id,
            command="camera.command",
            payload={"action": _WIRE_ACTIONS[action]},
        )
    )
    return json.dumps({"success": True, "action": action})


CAMERA_TOOLS = [control_camera]
