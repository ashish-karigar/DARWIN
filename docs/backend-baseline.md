# Backend Baseline

## Baseline identity

- Date: 2026-09-09
- Checklist task: UI-001
- Project version: 0.1.0
- Tested interpreter: Python 3.11.16 from the `DARWIN` Conda environment
- Test command: `python -m pytest -q`

## Test result

The intended DARWIN environment completed the suite successfully:

```text
25 passed, 3 subtests passed in 10.38s
```

The active base Python 3.14.7 environment could not collect the suite because declared project dependencies were not installed there. Missing imports included `sounddevice`, `fishaudio`, `soundfile`, `langchain_core`, `tiktoken`, and `langgraph`. This is an environment/setup failure, not a recorded backend test failure.

## Supervisor entry-path check

`app.agents.supervisor.run_supervisor` was invoked with a deterministic stubbed supervisor response. The method accepted the message and thread ID, extracted and cleaned the returned content, and produced:

```text
DARWIN baseline response.
```

This verifies the local callable boundary that the future UI service will use without transmitting project prompts or credentials to an external provider.

## Known live-model issue

A live invocation reached the model-provider boundary but was not completed as part of this baseline. Without external network access, the primary Groq request fails and the Ollama fallback raises:

```text
TypeError: Client.chat() got an unexpected keyword argument 'parallel_tool_calls'
```

This indicates an incompatibility between the installed Ollama Python client and the LangChain Ollama integration. It is a pre-existing runtime issue to resolve when live/offline model execution is brought into the UI service; it does not affect the passing unit-test baseline.

## Repository hygiene

The existing `.gitignore` excludes:

- `.env`
- Python bytecode and `__pycache__`
- generated package metadata
- IDE configuration
- SQLite data
- downloaded models
- voice profiles
- authentication data

No secret values were copied into this report.

## Supported setup for current work

Use Python 3.11.x in the `DARWIN` Conda environment and install the project in editable mode with development dependencies:

```bash
conda activate DARWIN
python -m pip install -e ".[dev]"
python -m pytest -q
```

The test baseline should remain green while the desktop UI is introduced.
