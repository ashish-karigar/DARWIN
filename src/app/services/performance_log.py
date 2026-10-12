"""Opt-in, question-level performance traces for DARWIN requests."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from time import perf_counter

from dotenv import load_dotenv

from app.runtime_events import RuntimeEvent


PROJECT_ROOT = Path(__file__).resolve().parents[3]
_WRITE_LOCK = Lock()


def _enabled(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"1", "true", "yes", "on"}


def configured_log_path() -> Path | None:
    """Return the configured path, or None when local stats logging is disabled."""
    load_dotenv()
    if not _enabled(os.getenv("DARWIN_STATS_LOG_ENABLED")):
        return None
    configured = os.getenv(
        "DARWIN_STATS_LOG_FILE", "data/logs/darwin-performance.jsonl"
    ).strip()
    if not configured:
        return None
    path = Path(configured).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _write_record(record: dict[str, object]) -> None:
    path = configured_log_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with _WRITE_LOCK, path.open("a", encoding="utf-8") as stream:
            stream.write(f"{encoded}\n")
    except OSError:
        # Performance instrumentation must never break an assistant request.
        return


class VoicePerformanceTrace:
    """Measure one spoken turn from recording through audible TTS output."""

    def __init__(
        self,
        question: str,
        request_id: str,
        session_id: str,
        input_timing: dict[str, float | None],
    ) -> None:
        self.question = question
        self.request_id = request_id
        self.session_id = session_id
        self.recording_seconds = input_timing.get("recording_seconds") or 0.0
        self.stt_seconds = input_timing.get("whisper_seconds") or 0.0
        input_seconds = self.recording_seconds + self.stt_seconds
        self.started_at = perf_counter() - input_seconds
        self.transcription_finished_at = perf_counter()
        self.reasoning_seconds = 0.0
        self._tts_operations: list[dict[str, object]] = []
        self._first_audio_at: float | None = None
        self._playback_seconds = 0.0

    def set_reasoning(self, seconds: float) -> None:
        self.reasoning_seconds = max(0.0, seconds)

    def add_tts(
        self,
        timing: dict[str, float],
        *,
        requested_at: float,
        label: str = "text_to_speech",
    ) -> None:
        first_audio_seconds = max(0.0, timing.get("first_audio", 0.0))
        network_first_chunk_seconds = max(
            0.0, timing.get("network_first_chunk", first_audio_seconds)
        )
        playback_seconds = max(0.0, timing.get("playback", 0.0))
        first_audio_at = requested_at + first_audio_seconds
        if self._first_audio_at is None or first_audio_at < self._first_audio_at:
            self._first_audio_at = first_audio_at
        self._playback_seconds += playback_seconds
        self._tts_operations.append(
            {
                "name": label,
                "category": "tts",
                "status": "completed",
                "start_seconds": round(max(0.0, requested_at - self.started_at), 6),
                "duration_seconds": round(first_audio_seconds, 6),
                "first_audio_seconds": round(first_audio_seconds, 6),
                "network_first_chunk_seconds": round(
                    network_first_chunk_seconds, 6
                ),
                "playback_seconds": round(playback_seconds, 6),
            }
        )

    def finish(self, *, success: bool = True, error_type: str | None = None) -> None:
        finished_at = perf_counter()
        first_audio_from_start = (
            max(0.0, self._first_audio_at - self.started_at)
            if self._first_audio_at is not None
            else None
        )
        response_latency = (
            max(0.0, self._first_audio_at - self.transcription_finished_at)
            if self._first_audio_at is not None
            else None
        )
        first_tts_latency = (
            float(self._tts_operations[0]["first_audio_seconds"])
            if self._tts_operations
            else None
        )
        first_network_chunk_latency = (
            float(self._tts_operations[0]["network_first_chunk_seconds"])
            if self._tts_operations
            else None
        )
        input_seconds = self.recording_seconds + self.stt_seconds
        operations: list[dict[str, object]] = [
            {
                "name": "recording_and_vad",
                "category": "input",
                "status": "completed",
                "start_seconds": 0.0,
                "duration_seconds": round(self.recording_seconds, 6),
            },
            {
                "name": "speech_to_text",
                "category": "stt",
                "status": "completed",
                "start_seconds": round(self.recording_seconds, 6),
                "duration_seconds": round(self.stt_seconds, 6),
            },
            {
                "name": "assistant.reasoning",
                "category": "reasoning",
                "status": "completed" if success else "failed",
                "start_seconds": round(input_seconds, 6),
                "duration_seconds": round(self.reasoning_seconds, 6),
            },
            *self._tts_operations,
        ]
        record: dict[str, object] = {
            "record_type": "voice_latency",
            "timestamp": datetime.now(UTC).isoformat(),
            "request_id": self.request_id,
            "session_id": self.session_id,
            "question": self.question,
            "success": success,
            "recording_seconds": round(self.recording_seconds, 6),
            "stt_seconds": round(self.stt_seconds, 6),
            "reasoning_seconds": round(self.reasoning_seconds, 6),
            "tts_first_audio_seconds": (
                round(first_tts_latency, 6) if first_tts_latency is not None else None
            ),
            "tts_network_first_chunk_seconds": (
                round(first_network_chunk_latency, 6)
                if first_network_chunk_latency is not None
                else None
            ),
            "time_to_first_audio_seconds": (
                round(first_audio_from_start, 6) if first_audio_from_start is not None else None
            ),
            "response_latency_after_stt_seconds": (
                round(response_latency, 6) if response_latency is not None else None
            ),
            "playback_seconds": round(self._playback_seconds, 6),
            "total_turn_seconds": round(max(0.0, finished_at - self.started_at), 6),
            "operations": operations,
        }
        if error_type:
            record["error_type"] = error_type
        _write_record(record)


@dataclass
class _OpenOperation:
    name: str
    category: str
    started_at: float


class RequestPerformanceTrace:
    """Collect nested runtime operation timings and write one JSONL record."""

    def __init__(self, question: str, request_id: str, session_id: str) -> None:
        self.question = question
        self.request_id = request_id
        self.session_id = session_id
        self.started_at = perf_counter()
        self._open: dict[tuple[str, str], _OpenOperation] = {}
        self._operations: list[dict[str, object]] = []

    def observe(self, event: RuntimeEvent) -> None:
        if event.request_id != self.request_id:
            return
        now = perf_counter()
        if event.kind == "skill" and event.skill and event.phase:
            key = ("skill", event.skill)
            if event.phase == "started":
                self._open[key] = _OpenOperation(event.skill, "skill", now)
            else:
                opened = self._open.pop(key, None)
                started_at = opened.started_at if opened else now
                self._operations.append(
                    self._operation(
                        event.skill,
                        "skill",
                        event.phase,
                        started_at,
                        now,
                    )
                )
        elif event.kind == "confirmation":
            self._operations.append(
                self._operation(
                    "confirmation",
                    "safety",
                    "requested",
                    now,
                    now,
                    detail=event.summary,
                )
            )
        elif event.kind == "ui_command" and event.command:
            self._operations.append(
                self._operation(
                    event.command,
                    "ui_command",
                    "issued",
                    now,
                    now,
                    detail=event.payload,
                )
            )

    def finish(
        self,
        *,
        success: bool,
        response_characters: int = 0,
        error_type: str | None = None,
    ) -> None:
        path = configured_log_path()
        if path is None:
            return
        finished_at = perf_counter()
        for key, opened in tuple(self._open.items()):
            self._operations.append(
                self._operation(
                    opened.name,
                    opened.category,
                    "incomplete",
                    opened.started_at,
                    finished_at,
                )
            )
            self._open.pop(key, None)

        total_seconds = finished_at - self.started_at
        operations = sorted(
            self._operations, key=lambda operation: float(operation["start_seconds"])
        )
        operations.insert(
            0,
            {
                "name": "assistant.orchestration",
                "category": "orchestration",
                "status": "completed" if success else "failed",
                "start_seconds": 0.0,
                "duration_seconds": round(total_seconds, 6),
            },
        )
        record = {
            "record_type": "request_performance",
            "timestamp": datetime.now(UTC).isoformat(),
            "request_id": self.request_id,
            "session_id": self.session_id,
            "question": self.question,
            "success": success,
            "total_seconds": round(total_seconds, 6),
            "response_characters": response_characters,
            "operations": operations,
        }
        if error_type:
            record["error_type"] = error_type
        _write_record(record)

    def _operation(
        self,
        name: str,
        category: str,
        status: str,
        started_at: float,
        finished_at: float,
        *,
        detail: object | None = None,
    ) -> dict[str, object]:
        operation: dict[str, object] = {
            "name": name,
            "category": category,
            "status": status,
            "start_seconds": round(max(0.0, started_at - self.started_at), 6),
            "duration_seconds": round(max(0.0, finished_at - started_at), 6),
        }
        if detail is not None:
            operation["detail"] = detail
        return operation
