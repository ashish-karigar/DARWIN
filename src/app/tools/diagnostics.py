import json

from langchain_core.tools import tool

from app.services.diagnostics import get_performance_report, run_live_health_checks
from app.services.status import announce_status
from app.safety import execute_guarded


@tool
def inspect_interaction_performance(sample_limit: int = 50) -> str:
    """Inspect measured DARWIN interaction latency, success rate, and failures."""
    execution = execute_guarded(
        "diagnostics.performance",
        "Read DARWIN performance telemetry",
        lambda: get_performance_report(limit=sample_limit),
    )
    return json.dumps(
        execution.value if execution.succeeded else {"error": "Diagnostics failed."}
    )


@tool
def run_live_diagnostics() -> str:
    """Run fresh health checks against DARWIN services, storage, and local tools."""
    announce_status("Initiating diagnostics. Please stand by.")
    execution = execute_guarded(
        "diagnostics.live",
        "Run non-destructive live diagnostics",
        run_live_health_checks,
    )
    return json.dumps(
        execution.value if execution.succeeded else {"error": "Diagnostics failed."}
    )
