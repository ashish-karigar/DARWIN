import json

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

DIAGNOSTICS_TOOLS = [inspect_interaction_performance, run_live_diagnostics]
for registered_tool in DIAGNOSTICS_TOOLS:
    registered_tool.metadata = {"capability": "run diagnostics"}

diagnostics_agent = build_agent(
    system_prompt=DIAGNOSTICS_PROMPT,
    tools=DIAGNOSTICS_TOOLS,
)


def run_diagnostics_agent(query: str) -> str:
    normalized = query.casefold()
    if "diagnostic" in normalized or "health check" in normalized:
        raw = run_live_diagnostics.invoke({})
        return summarize_diagnostics(raw)
    result = diagnostics_agent.invoke(
        {"messages": [{"role": "user", "content": query}]}
    )
    return result["messages"][-1].content


def summarize_diagnostics(raw: str) -> str:
    """Convert diagnostic JSON into a brief speech-safe status report."""
    try:
        report = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return "Diagnostics could not produce a readable report."
    if report.get("error"):
        return "Diagnostics could not complete the health checks."

    checks = report.get("checks")
    if not isinstance(checks, dict):
        return "Diagnostics returned an incomplete report."

    healthy = []
    attention = []
    for name, result in checks.items():
        if not isinstance(result, dict):
            continue
        status = result.get("status")
        if status == "healthy":
            healthy.append(name)
        elif status in {"degraded", "unavailable"}:
            attention.append((name, str(result.get("detail", "needs attention"))))

    if not attention:
        return f"Diagnostics complete. All {len(healthy)} checked systems are healthy."

    labels = ", ".join(name.replace("_", " ") for name, _detail in attention[:4])
    remaining = len(attention) - 4
    suffix = f", plus {remaining} more" if remaining > 0 else ""
    healthy_label = "check is" if len(healthy) == 1 else "checks are"
    attention_label = "needs" if len(attention) == 1 else "need"
    return (
        f"Diagnostics complete. {len(healthy)} {healthy_label} healthy. "
        f"{len(attention)} {attention_label} attention: {labels}{suffix}."
    )
