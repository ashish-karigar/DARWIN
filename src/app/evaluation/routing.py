import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from time import monotonic

from app.agents.supervisor import SUPERVISOR_PROMPT
from app.agents.supervisor_tools import SUPERVISOR_TOOLS
from app.llm.models import create_primary_model


CASES_PATH = Path("data/evaluation/routing_cases.json")
REPORT_PATH = Path("data/evaluation/routing_latest.json")


def evaluate_routing() -> dict:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    model = create_primary_model(SUPERVISOR_TOOLS)
    results = []

    for case in cases:
        started = monotonic()
        reply = model.invoke(
            [
                {"role": "system", "content": SUPERVISOR_PROMPT},
                {"role": "user", "content": case["query"]},
            ]
        )
        latency = monotonic() - started
        selected_tools = [call["name"] for call in reply.tool_calls]
        selected_tool = selected_tools[0] if selected_tools else None
        results.append(
            {
                "id": case["id"],
                "expected_tool": case["expected_tool"],
                "selected_tool": selected_tool,
                "pass": selected_tool == case["expected_tool"],
                "latency_seconds": round(latency, 3),
            }
        )

    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(CASES_PATH),
        "case_count": len(results),
        "routing_accuracy_percent": round(100 * mean(item["pass"] for item in results), 1),
        "average_routing_seconds": round(mean(item["latency_seconds"] for item in results), 3),
        "results": results,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    report = evaluate_routing()
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))


if __name__ == "__main__":
    main()
