from app.agents.base import build_agent
from app.tools.diagnostics import inspect_interaction_performance, run_live_diagnostics


DIAGNOSTICS_PROMPT = """
You are DARWIN's internal diagnostics specialist.

For "run diagnostics" or current system health, call run_live_diagnostics.
For historical latency or reliability, call inspect_interaction_performance.
Call both only when the user explicitly requests a comprehensive report.
Use only measured values returned by the tool.
Clearly distinguish processing latency from recording and playback duration.
Report sample size and mention when it is too small for strong conclusions.
Never invent accuracy or health measurements that were not evaluated.
Keep the result concise and write in the third person for DARWIN to summarize.
"""

diagnostics_agent = build_agent(
    system_prompt=DIAGNOSTICS_PROMPT,
    tools=[inspect_interaction_performance, run_live_diagnostics],
)


def run_diagnostics_agent(query: str) -> str:
    result = diagnostics_agent.invoke(
        {"messages": [{"role": "user", "content": query}]}
    )
    return result["messages"][-1].content
