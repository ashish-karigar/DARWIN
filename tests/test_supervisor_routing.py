from unittest.mock import patch

from app.agents.supervisor import run_supervisor


def test_explicit_diagnostics_request_bypasses_supervisor_model() -> None:
    with patch("app.agents.supervisor.ask_diagnostics_specialist") as diagnostics:
        diagnostics.invoke.return_value = "The live checks found one unavailable service."

        response = run_supervisor(
            "some diagnostics and check why is that unavailable", "desktop"
        )

    diagnostics.invoke.assert_called_once_with(
        {"query": "some diagnostics and check why is that unavailable"}
    )
    assert response == "The live checks found one unavailable service."
