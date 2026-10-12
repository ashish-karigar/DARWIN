"""Discover actual registered agent tools, not a static prompt inventory."""
import json
from langchain_core.tools import tool
from app.tools.apps import installed_apps


def capability_snapshot() -> dict:
    # Lazy imports avoid the supervisor/agent construction cycle.
    from app.agents.supervisor_tools import SUPERVISOR_TOOLS
    from app.agents.productivity_agent import PRODUCTIVITY_TOOLS
    from app.agents.mac_agent import MAC_TOOLS
    from app.agents.weather_agent import WEATHER_TOOLS
    from app.agents.diagnostics_agent import DIAGNOSTICS_TOOLS
    from app.ragv2.tools import knowledge_search
    knowledge_search.metadata = {"capability": "search stored knowledge"}
    groups = {"supervisor": SUPERVISOR_TOOLS, "productivity": PRODUCTIVITY_TOOLS, "mac": MAC_TOOLS, "weather": WEATHER_TOOLS, "diagnostics": DIAGNOSTICS_TOOLS, "knowledge": [knowledge_search]}
    return {"tools": [{"agent": group, "name": item.name, "description": item.description, "capability": (item.metadata or {}).get("capability", item.name.replace("_", " ")), "parameters": item.args} for group, tools in groups.items() for item in tools], "apps": installed_apps(), "availability_note": "Registered tools are not proof of macOS permission or provider availability. Check actual tool results. UI app installation alone does not imply data access."}


@tool
def discover_tools() -> str:
    """Inspect the current registered tools, their parameters, owning specialists, and installed UI apps. Use for every question about DARWIN's abilities; never recite a remembered prompt inventory."""
    return json.dumps(capability_snapshot())


def capability_summary() -> str:
    snapshot = capability_snapshot()
    # Names are derived from registered tool objects, so additions appear automatically.
    names = list(dict.fromkeys(item["capability"] for item in snapshot["tools"] if not item["name"].startswith("ask_") and item["name"] != "discover_tools"))
    apps = ", ".join(app["name"] for app in snapshot["apps"])
    return "I can " + ", ".join(names[:-1]) + ", and " + names[-1] + f". My installed apps include {apps}. Calendar and reminder access requires macOS permission."
