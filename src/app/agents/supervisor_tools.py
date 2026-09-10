from langchain_core.tools import tool

from app.agents.knowledge_agent import run_knowledge_agent
from app.agents.productivity_agent import run_productivity_agent
from app.agents.mac_agent import run_mac_agent
from app.agents.weather_agent import run_weather_agent
from app.agents.diagnostics_agent import run_diagnostics_agent


@tool
def ask_knowledge_specialist(query: str) -> str:
    """Delegate DARWIN/project knowledge questions to the knowledge specialist."""
    return run_knowledge_agent(query)


@tool
def ask_productivity_specialist(query: str) -> str:
    """Delegate task and productivity questions to the productivity specialist."""
    return run_productivity_agent(query)

@tool
def ask_mac_specialist(query: str) -> str:
    """Delegate music playback and allowlisted Mac-control requests."""
    return run_mac_agent(query)

@tool
def ask_weather_specialist(query: str) -> str:
    """Delegate weather questions to the weather specialist."""
    return run_weather_agent(query)


@tool
def ask_diagnostics_specialist(query: str) -> str:
    """Delegate DARWIN health, performance, failure, and latency questions."""
    return run_diagnostics_agent(query)


SUPERVISOR_TOOLS = [
    ask_knowledge_specialist,
    ask_productivity_specialist,
    ask_mac_specialist,
    ask_weather_specialist,
    ask_diagnostics_specialist,
]
