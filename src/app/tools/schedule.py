"""Validated assistant tools for the same Apple calendars/reminders as the UI."""
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Literal

from langchain_core.tools import tool
from app.safety import execute_guarded
from app.services.native_apps import invoke_native

_READ_CAPTURE: ContextVar[dict | None] = ContextVar('schedule_read_capture', default=None)


@contextmanager
def capture_schedule_reads():
    # Mutable request-local capture survives copied ToolNode worker contexts.
    captured = {}
    token = _READ_CAPTURE.set(captured)
    try:
        yield captured
    finally:
        _READ_CAPTURE.reset(token)


def local_zone():
    configured = os.environ.get("DARWIN_TIMEZONE") or os.environ.get("TZ")
    if not configured:
        try:
            configured = os.readlink("/etc/localtime").split("zoneinfo/")[-1]
        except OSError:
            configured = "America/New_York"
    return ZoneInfo(configured)


def resolve_day(day: str) -> date:
    today = datetime.now(local_zone()).date()
    text = day.strip().casefold()
    if text in {"today", "tomorrow", "yesterday"}:
        return today + timedelta(days={"today": 0, "tomorrow": 1, "yesterday": -1}[text])
    return date.fromisoformat(text)


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Include an explicit timezone offset")
    return parsed


def execute(app: str, action: str, request: dict) -> str:
    outcome = execute_guarded(
        f"{app.casefold()}.{action}",
        f"{action.title()} {app.casefold()} item: {request.get('title', request.get('id', ''))}",
        lambda: invoke_native(app, {"action": action, **request}),
    )
    return json.dumps(outcome.value if outcome.succeeded else {"ok": False, "error": "action_denied_or_failed"})


@tool
def list_schedule(day: str) -> str:
    """Read actual Apple Calendar events for today, tomorrow, or an ISO YYYY-MM-DD date. Never use memory for live schedule questions."""
    try:
        selected = resolve_day(day)
        start = datetime.combine(selected, time.min, local_zone())
        end = datetime.combine(selected + timedelta(days=1), time.min, local_zone())
    except ValueError:
        return json.dumps({"ok": False, "question": "Which date should I check?"})
    result = execute("Calendar", "list", {"rangeStart": start.isoformat(), "rangeEnd": end.isoformat()})
    captured = _READ_CAPTURE.get()
    if captured is not None:
        captured.update(day=selected.isoformat(), payload=json.loads(result))
    return result


@tool
def create_calendar_event(title: str, start_at: str | None = None, end_at: str | None = None, calendar_id: str | None = None, notes: str = "", all_day: bool = False) -> str:
    """Add an Apple Calendar event. Require user-provided date, time and duration/end time; ask for missing information, never guess. ISO timestamps must include timezone offsets. Explicit all-day requests use midnight boundaries."""
    if not title.strip() or len(title) > 500 or len(notes) > 5000:
        return json.dumps({"ok": False, "error": "invalid_title_or_notes"})
    if not start_at:
        return json.dumps({"ok": False, "question": "What day and time should I schedule it?"})
    if not end_at:
        return json.dumps({"ok": False, "question": "How long should I block out?"})
    try:
        start, end = timestamp(start_at), timestamp(end_at)
        if end <= start:
            raise ValueError("End must be after start")
    except ValueError as error:
        return json.dumps({"ok": False, "error": str(error), "question": "What date, start time, and duration should I use?"})
    payload = {"title": title.strip(), "startDate": start.isoformat(), "endDate": end.isoformat(), "notes": notes, "allDay": all_day}
    if calendar_id:
        payload["calendarId"] = calendar_id
    return execute("Calendar", "create", payload)


@tool
def delete_calendar_event(event_id: str, title: str) -> str:
    """Remove one calendar occurrence by the exact ID returned by list_schedule. Resolve ambiguous matches with the user first. Requires confirmation; do not retry a denial."""
    if not event_id or not title.strip():
        return json.dumps({"ok": False, "error": "event_identity_required"})
    # The native delete request needs only the ID; title is used for the confirmation.
    return execute("Calendar", "delete", {"id": event_id, "title": title})


@tool
def list_reminders() -> str:
    """Read actual Apple Reminders and reminder lists, including due dates and completion status."""
    return execute("Reminders", "list", {})


@tool
def create_reminder(title: str, due_at: str | None = None, notes: str = "", without_due_date: bool = False) -> str:
    """Create an Apple reminder. Ask for date/time unless the user explicitly wants no due date. Due timestamp must include timezone offset."""
    if not title.strip() or len(title) > 500 or len(notes) > 5000:
        return json.dumps({"ok": False, "error": "invalid_title_or_notes"})
    if not due_at and not without_due_date:
        return json.dumps({"ok": False, "question": "When should I remind you?"})
    try:
        due = timestamp(due_at).isoformat() if due_at else None
    except ValueError:
        return json.dumps({"ok": False, "question": "What date and time should I use?"})
    return execute("Reminders", "create", {"title": title.strip(), "notes": notes, "dueDate": due})


@tool
def change_reminder(action: Literal["complete", "delete"], reminder_id: str, title: str) -> str:
    """Complete or delete an exact Apple reminder ID from list_reminders. Ask which reminder if ambiguous. Deletion requires confirmation."""
    if not reminder_id or not title.strip():
        return json.dumps({"ok": False, "error": "reminder_identity_required"})
    return execute("Reminders", action, {"id": reminder_id, "title": title, "completed": True})


SCHEDULE_TOOLS = [list_schedule, create_calendar_event, delete_calendar_event, list_reminders, create_reminder, change_reminder]
for registered_tool in SCHEDULE_TOOLS:
    registered_tool.metadata = {"capability": "manage your calendar and reminders"}
