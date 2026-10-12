from langchain_core.tools import tool

from app.agents.knowledge_agent import run_knowledge_agent
from app.agents.productivity_agent import run_productivity_agent
from app.agents.mac_agent import run_mac_agent
from app.agents.weather_agent import run_weather_agent
from app.agents.diagnostics_agent import run_diagnostics_agent
from app.tools.camera import control_camera
from app.tools.apps import APP_TOOLS
from app.tools.capabilities import discover_tools
from app.runtime_events import (
    RuntimeEvent,
    current_runtime_request,
    emit_runtime_event,
    raise_if_cancelled,
)
from app.safety.context import current_session_id


def _run_specialist(name: str, query: str, runner) -> str:
    raise_if_cancelled()
    request_id, runtime_session_id = current_runtime_request()
    session_id = current_session_id()
    if runtime_session_id != "system":
        session_id = runtime_session_id
    emit_runtime_event(
        RuntimeEvent(
            kind="skill",
            request_id=request_id,
            session_id=session_id,
            skill=name,
            phase="started",
        )
    )
    try:
        result = runner(query)
        raise_if_cancelled()
    except Exception:
        emit_runtime_event(
            RuntimeEvent(
                kind="skill",
                request_id=request_id,
                session_id=session_id,
                skill=name,
                phase="failed",
            )
        )
        raise
    emit_runtime_event(
        RuntimeEvent(
            kind="skill",
            request_id=request_id,
            session_id=session_id,
            skill=name,
            phase="completed",
        )
    )
    return result


@tool
def ask_knowledge_specialist(query: str) -> str:
    """Delegate DARWIN/project knowledge questions to the knowledge specialist."""
    return _run_specialist("knowledge", query, run_knowledge_agent)


@tool
def ask_productivity_specialist(query: str) -> str:
    """Delegate live calendar/schedule queries, creating/deleting events, reminders, tasks, and scheduling follow-up answers. The specialist asks for missing dates/times."""
    return _run_specialist("productivity", query, run_productivity_agent)

@tool
def ask_mac_specialist(query: str) -> str:
    """Delegate music playback, camera, and allowlisted Mac-control requests."""
    return _run_specialist("mac", query, run_mac_agent)

@tool
def ask_weather_specialist(query: str) -> str:
    """Delegate weather questions to the weather specialist."""
    return _run_specialist("weather", query, run_weather_agent)


@tool
def ask_diagnostics_specialist(query: str) -> str:
    """Delegate DARWIN health, performance, failure, and latency questions."""
    return _run_specialist("diagnostics", query, run_diagnostics_agent)


SUPERVISOR_TOOLS = [
    discover_tools,
    *APP_TOOLS,
    control_camera,
    ask_knowledge_specialist,
    ask_productivity_specialist,
    ask_mac_specialist,
    ask_weather_specialist,
    ask_diagnostics_specialist,
]
