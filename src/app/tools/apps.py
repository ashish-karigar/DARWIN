"""Manifest-backed shell app discovery and launch commands."""
import json
from pathlib import Path
from typing import Literal
from langchain_core.tools import tool
from app.runtime_events import RuntimeEvent, current_runtime_request, emit_runtime_event

MANIFESTS = Path(__file__).resolve().parents[3] / "darwin-ui/apps"


def installed_apps() -> list[dict]:
    apps = []
    for path in sorted(MANIFESTS.glob("*/manifest.json")):
        try:
            app = json.loads(path.read_text())
            if all(isinstance(app.get(key), str) for key in ("id", "name", "type")):
                apps.append({key: app.get(key) for key in ("id", "name", "type", "description", "permissions")})
        except (OSError, ValueError):
            continue
    return apps


@tool
def control_app(app_name: str, action: Literal["open", "close"] = "open") -> str:
    """Open or close an installed DARWIN UI app by name or ID, including YouTube, Calendar and Reminders. This only controls the app window, not its data or video selection."""
    matches = [app for app in installed_apps() if app_name.casefold() in {app['name'].casefold(), app['id'].casefold()}]
    if len(matches) != 1:
        return json.dumps({"ok": False, "error": "unknown_app", "apps": installed_apps()})
    request_id, session_id = current_runtime_request()
    if session_id != "desktop":
        return json.dumps({"ok": False, "error": "desktop_session_required"})
    emit_runtime_event(RuntimeEvent(kind="ui_command", request_id=request_id, session_id=session_id, command="app.command", payload={"appId": matches[0]['id'], "action": action}))
    return json.dumps({"ok": True, "status": "requested", "app": matches[0]['name'], "action": action})


APP_TOOLS = [control_app]
