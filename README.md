# DARWIN

DARWIN (Distributed Agentic Reasoning and Workflow Intelligence Network) is a local-first personal assistant. The current backend provides agent routing, voice interaction, safety controls, system tools, memory, and diagnostics. The OS-like desktop UI is tracked in [project-checklist.md](project-checklist.md).

## Backend requirements

- Python 3.11 is the tested development runtime.
- The project metadata currently permits Python 3.11 or newer, but newer Python releases are not considered supported until the full test suite passes on them.
- Audio features may require the host operating system's microphone permission and audio libraries.
- Live responses require either the configured Groq credentials/network access or a compatible local Ollama server and model.

## Development setup

The existing development machine has a Conda environment named `DARWIN`:

```bash
conda activate DARWIN
python --version
python -m pip install -e ".[dev]"
```

The expected Python version is 3.11.x. Do not install project dependencies into an unrelated global or base environment.

## Run the backend

```bash
conda activate DARWIN
python main.py
```

Choose `text` mode to exercise the assistant without initializing the continuous voice loop.

## Run tests

```bash
conda activate DARWIN
python -m pytest -q
```

See [docs/backend-baseline.md](docs/backend-baseline.md) for the first recorded UI-project baseline and known issues.

## Desktop UI setup

The DARWIN desktop requires Node.js 22.12 or newer. The current scaffold is tested with Node.js 26.7 and npm 11.19.

```bash
cd darwin-ui
npm install
npm run install:runtime
```

`install:runtime` downloads the Electron executable for the current platform. It is separate from dependency installation so the runtime download is explicit and failures are easier to diagnose.

Start the Electron development window with hot reload:

```bash
npm run dev
```

Run the UI quality gates:

```bash
npm run typecheck
npm run lint
npm run format:check
npm test
npm run build
```
3a0b36c4d9eacadb18089fc6649f129238039f0602077c1781d6526f2df877ba