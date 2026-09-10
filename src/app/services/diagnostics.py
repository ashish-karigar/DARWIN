import importlib.util
import json
import math
import os
import shutil
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path
from statistics import mean

import chromadb
import httpx
import sounddevice as sd
from dotenv import load_dotenv
from fishaudio import FishAudio

from app.rag.ingest import DATABASE_PATH as RAG_DATABASE_PATH, DOCUMENTS
from app.services.location import get_current_location
from app.services.telemetry import DATABASE_PATH
from app.safety.audit import audit_health
from app.safety.policy import POLICIES, validate_policies
from app.system.discovery import discover_capabilities
from app.voice.speaker_identity import is_enrolled
from app.voice.wake_word import ACTIVATION_NAME, activation_backend_ready


load_dotenv()
RAG_REPORT_PATH = Path("data/evaluation/rag_latest.json")
ROUTING_REPORT_PATH = Path("data/evaluation/routing_latest.json")


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def _summary(values: list[float]) -> dict[str, float | None]:
    return {
        "average_seconds": round(mean(values), 3) if values else None,
        "p95_seconds": _percentile(values, 0.95),
    }


def get_performance_report(limit: int = 50) -> dict:
    """Return measured interaction and retrieval performance."""
    if not DATABASE_PATH.exists():
        return {"status": "unknown", "samples": 0, "message": "No telemetry exists."}

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM interaction_metrics ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
        retrieval_rows = connection.execute(
            "SELECT * FROM retrieval_metrics ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()

    if not rows:
        return {"status": "unknown", "samples": 0, "message": "No telemetry exists."}

    failures = [
        row for row in rows if not row["success"] or row["response_characters"] == 0
    ]

    def values(column: str) -> list[float]:
        return [float(row[column]) for row in rows if row[column] is not None]

    failure_rate = len(failures) / len(rows)
    retrieval_latencies = [float(row["latency_seconds"]) for row in retrieval_rows]
    return {
        "status": "degraded" if failure_rate > 0.10 else "healthy",
        "samples": len(rows),
        "successful_responses": len(rows) - len(failures),
        "failed_responses": len(failures),
        "success_rate_percent": round((1.0 - failure_rate) * 100, 1),
        "recording": _summary(values("recording_seconds")),
        "whisper": _summary(values("whisper_seconds")),
        "reasoning": _summary(values("reasoning_seconds")),
        "time_to_first_audio": _summary(values("first_audio_seconds")),
        "playback": _summary(values("playback_seconds")),
        "retrieval": {
            "samples": len(retrieval_rows),
            **_summary(retrieval_latencies),
        },
        "note": "Recording and playback include actual speaking time.",
    }


def _timed_check(function) -> dict:
    started = time.monotonic()
    try:
        result = function()
        status, detail = result
    except Exception as error:
        status, detail = "unavailable", f"{type(error).__name__}: {error}"
    return {
        "status": status,
        "latency_seconds": round(time.monotonic() - started, 3),
        "detail": detail,
    }


def _check_sqlite() -> tuple[str, str]:
    for path in ("data/conversation_memory.sqlite", str(DATABASE_PATH)):
        with sqlite3.connect(path) as connection:
            connection.execute("SELECT 1").fetchone()
    return "healthy", "Conversation memory and telemetry respond."


def _check_rag() -> tuple[str, str]:
    client = chromadb.PersistentClient(path=RAG_DATABASE_PATH)
    collections = {item.name: item for item in client.list_collections()}
    counts = {name: collection.count() for name, collection in collections.items()}
    stale_sources = []
    for source, collection_name in DOCUMENTS.items():
        collection = collections.get(collection_name)
        if collection is None or not source.exists():
            stale_sources.append(str(source))
            continue
        source_text = source.read_text(encoding="utf-8").strip()
        expected_hash = sha256(source_text.encode("utf-8")).hexdigest()
        stored = collection.get(where={"source": str(source)}, include=["metadatas"])
        hashes = {item.get("document_hash") for item in stored["metadatas"]}
        if hashes != {expected_hash}:
            stale_sources.append(str(source))
    healthy = (
        all(counts.get(name, 0) > 0 for name in DOCUMENTS.values())
        and not stale_sources
    )
    detail = f"Chunk counts: {counts}."
    if stale_sources:
        detail += f" Stale or missing sources: {stale_sources}."
    return ("healthy" if healthy else "degraded"), detail


def _check_ollama() -> tuple[str, str]:
    response = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3.0)
    response.raise_for_status()
    models = [item["name"] for item in response.json().get("models", [])]
    required = {"qwen3:14b", "nomic-embed-text:latest"}
    missing = sorted(required - set(models))
    return (
        ("degraded", f"Missing models: {missing}")
        if missing
        else ("healthy", "Fallback and embedding models are available.")
    )


def _check_groq() -> tuple[str, str]:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return "unavailable", "GROQ_API_KEY is missing."
    response = httpx.get(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=5.0,
    )
    response.raise_for_status()
    models = {item["id"] for item in response.json().get("data", [])}
    model = "openai/gpt-oss-120b"
    return (
        ("healthy", f"Groq is reachable and {model} is available.")
        if model in models
        else ("degraded", f"Groq is reachable but {model} was not listed.")
    )


def _check_fish_audio() -> tuple[str, str]:
    voice_id = os.getenv("FISH_VOICE_ID")
    if not os.getenv("FISH_API_KEY") or not voice_id:
        return "unavailable", "Fish Audio API key or voice ID is missing."
    client = FishAudio()
    try:
        voice = client.voices.get(voice_id)
        return "healthy", f"Fish Audio is reachable; voice {voice.title} is available."
    finally:
        client.close()


def _check_weather() -> tuple[str, str]:
    response = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": 0.0, "longitude": 0.0, "current": "temperature_2m"},
        timeout=5.0,
    )
    response.raise_for_status()
    response.json()["current"]["temperature_2m"]
    return "healthy", "Open-Meteo responded to a neutral-coordinate probe."


def _check_location() -> tuple[str, str]:
    location = get_current_location()
    if location is None:
        return "degraded", "No startup location is cached."
    return (
        "healthy",
        f"A startup location is cached for {location.label}; coordinates were not transmitted.",
    )


def _check_audio_devices() -> tuple[str, str]:
    input_device = sd.query_devices(kind="input")
    output_device = sd.query_devices(kind="output")
    if (
        input_device["max_input_channels"] < 1
        or output_device["max_output_channels"] < 1
    ):
        return "degraded", "A usable input or output audio device was not found."
    return "healthy", f"Input: {input_device['name']}; output: {output_device['name']}."


def _check_apple_music() -> tuple[str, str]:
    if not shutil.which("shortcuts"):
        return "unavailable", "Shortcuts CLI was not found."
    result = subprocess.run(
        ["shortcuts", "list"], capture_output=True, text=True, timeout=3, check=True
    )
    if "DARWIN Play Music" not in result.stdout:
        return "degraded", "DARWIN Play Music shortcut was not found."
    return (
        "healthy",
        "Shortcuts CLI and DARWIN Play Music are available; playback was not triggered.",
    )


def _check_agents() -> tuple[str, str]:
    modules = [
        "app.agents.knowledge_agent",
        "app.agents.productivity_agent",
        "app.agents.mac_agent",
        "app.agents.weather_agent",
        "app.agents.diagnostics_agent",
    ]
    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    return (
        ("degraded", f"Missing agent modules: {missing}")
        if missing
        else ("healthy", f"All {len(modules)} specialist modules are importable.")
    )


def _check_safety() -> tuple[str, str]:
    errors = validate_policies()
    audit_ready, audit_entries = audit_health()
    if errors or not audit_ready:
        return "degraded", f"Policy errors: {errors}; audit available: {audit_ready}."
    return (
        "healthy",
        f"{len(POLICIES)} actions are allowlisted; {audit_entries} actions audited.",
    )


def _check_system_controls() -> tuple[str, str]:
    capabilities = discover_capabilities()
    available = [item.key for item in capabilities if item.available]
    unavailable = [item.key for item in capabilities if not item.available]
    status = "healthy" if available else "degraded"
    return status, f"Available: {available}. Unavailable: {unavailable}."


def _check_conversational_voice() -> tuple[str, str]:
    wake_ready = activation_backend_ready()
    speaker_ready = is_enrolled()
    status = "healthy" if wake_ready and speaker_ready else "degraded"
    return status, (
        f"Local {ACTIVATION_NAME} activation ready: {wake_ready}; "
        f"local speaker profile enrolled: {speaker_ready}."
    )


def _check_rag_evaluation() -> tuple[str, str]:
    if not RAG_REPORT_PATH.exists():
        return "degraded", "No RAG evaluation report exists."
    report = json.loads(RAG_REPORT_PATH.read_text(encoding="utf-8"))
    retrieval = report.get("retrieval_accuracy_percent")
    answer = report.get("answer_required_term_accuracy_percent")
    status = (
        "healthy"
        if retrieval is not None
        and retrieval >= 90
        and answer is not None
        and answer >= 90
        else "degraded"
    )
    return status, (
        f"Retrieval accuracy {retrieval} percent across {report.get('case_count')} cases; "
        f"answer accuracy {answer if answer is not None else 'not evaluated'}."
    )


def _check_routing_evaluation() -> tuple[str, str]:
    if not ROUTING_REPORT_PATH.exists():
        return "degraded", "No agent-routing evaluation report exists."
    report = json.loads(ROUTING_REPORT_PATH.read_text(encoding="utf-8"))
    accuracy = report.get("routing_accuracy_percent")
    status = "healthy" if accuracy is not None and accuracy >= 90 else "degraded"
    return (
        status,
        f"Routing accuracy {accuracy} percent across {report.get('case_count')} cases.",
    )


def run_live_health_checks() -> dict:
    """Run fresh, non-destructive health checks in parallel."""
    started = time.monotonic()
    checks = {
        "sqlite": _check_sqlite,
        "rag_index": _check_rag,
        "rag_evaluation": _check_rag_evaluation,
        "routing_evaluation": _check_routing_evaluation,
        "ollama": _check_ollama,
        "groq": _check_groq,
        "fish_audio": _check_fish_audio,
        "weather": _check_weather,
        "location": _check_location,
        "audio_devices": _check_audio_devices,
        "apple_music": _check_apple_music,
        "agents": _check_agents,
        "safety": _check_safety,
        "system_controls": _check_system_controls,
        "conversational_voice": _check_conversational_voice,
    }
    results = {}
    with ThreadPoolExecutor(max_workers=len(checks)) as executor:
        futures = {
            executor.submit(_timed_check, check): name for name, check in checks.items()
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()

    overall = "healthy"
    if any(item["status"] in {"degraded", "unavailable"} for item in results.values()):
        overall = "degraded"
    return {
        "status": overall,
        "duration_seconds": round(time.monotonic() - started, 3),
        "checks": results,
    }
