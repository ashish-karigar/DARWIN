import json
from unittest.mock import patch

from app.agents.diagnostics_agent import run_diagnostics_agent, summarize_diagnostics


def test_diagnostics_summary_never_exposes_raw_json() -> None:
    raw = json.dumps(
        {
            "status": "degraded",
            "checks": {
                "sqlite": {"status": "healthy", "detail": "responded"},
                "fish_audio": {
                    "status": "unavailable",
                    "detail": "secret terminal detail",
                },
                "location": {"status": "degraded", "detail": "not cached"},
            },
        }
    )

    summary = summarize_diagnostics(raw)

    assert summary == (
        "Diagnostics complete. 1 check is healthy. 2 need attention: "
        "fish audio, location."
    )
    assert "{" not in summary
    assert "secret terminal detail" not in summary


def test_explicit_diagnostics_uses_deterministic_summary() -> None:
    raw = json.dumps(
        {"status": "healthy", "checks": {"sqlite": {"status": "healthy"}}}
    )
    with patch("app.agents.diagnostics_agent.run_live_diagnostics") as tool:
        tool.invoke.return_value = raw
        response = run_diagnostics_agent("Run diagnostics")

    assert response == "Diagnostics complete. All 1 checked systems are healthy."
