import json

from app.runtime_events import RuntimeEvent, runtime_event_context
from app.tools.camera import control_camera
from app.agents.supervisor_tools import SUPERVISOR_TOOLS, ask_mac_specialist
from app.agents.supervisor import _camera_action


def test_camera_tool_emits_validated_ui_command() -> None:
    observed: list[RuntimeEvent] = []

    with runtime_event_context(observed.append, "request-1", "desktop"):
        result = control_camera.invoke({"action": "start_detection"})

    assert json.loads(result) == {"success": True, "action": "start_detection"}
    assert observed == [
        RuntimeEvent(
            kind="ui_command",
            request_id="request-1",
            session_id="desktop",
            command="camera.command",
            payload={"action": "detection.start"},
        )
    ]


def test_camera_tool_rejects_unknown_actions() -> None:
    try:
        control_camera.invoke({"action": "delete_photos"})
    except Exception:
        pass
    else:
        raise AssertionError("unknown camera actions must be rejected")


def test_camera_tool_is_visible_at_the_supervisor_boundary() -> None:
    assert control_camera in SUPERVISOR_TOOLS
    assert "camera" in ask_mac_specialist.description.casefold()


def test_camera_commands_have_deterministic_routes() -> None:
    assert _camera_action("Open the camera") == "open"
    assert _camera_action("take a picture") == "capture"
    assert _camera_action("switch camera") == "next_camera"
    assert _camera_action("start object detection") == "start_detection"
    assert _camera_action("stop detection") == "stop_detection"
    assert _camera_action("turn mirroring off") == "mirror_off"
    assert _camera_action("close the camera") == "close"
    assert _camera_action("explain how cameras work") is None
