import json
from time import perf_counter

from app.runtime import AssistantRuntime
from app.runtime_events import RuntimeEvent, current_runtime_request, emit_runtime_event
from app.services.performance_log import VoicePerformanceTrace, configured_log_path


def test_stats_log_records_question_operations_and_durations(tmp_path, monkeypatch):
    log_path = tmp_path / "custom-name.jsonl"
    monkeypatch.setenv("DARWIN_STATS_LOG_ENABLED", "true")
    monkeypatch.setenv("DARWIN_STATS_LOG_FILE", str(log_path))

    def supervisor(_message: str, session_id: str) -> str:
        request_id, _ = current_runtime_request()
        emit_runtime_event(
            RuntimeEvent(
                kind="skill",
                request_id=request_id,
                session_id=session_id,
                skill="weather",
                phase="started",
            )
        )
        emit_runtime_event(
            RuntimeEvent(
                kind="skill",
                request_id=request_id,
                session_id=session_id,
                skill="weather",
                phase="completed",
            )
        )
        return "Clear skies."

    AssistantRuntime("desktop", supervisor_runner=supervisor).submit(
        "What is the weather?"
    )

    records = log_path.read_text(encoding="utf-8").splitlines()
    assert len(records) == 1
    record = json.loads(records[0])
    assert record["question"] == "What is the weather?"
    assert record["session_id"] == "desktop"
    assert record["success"] is True
    assert record["total_seconds"] >= 0
    assert [operation["name"] for operation in record["operations"]] == [
        "assistant.orchestration",
        "weather",
    ]
    assert all(operation["duration_seconds"] >= 0 for operation in record["operations"])


def test_stats_log_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DARWIN_STATS_LOG_ENABLED", "false")
    monkeypatch.setenv("DARWIN_STATS_LOG_FILE", str(tmp_path / "disabled.jsonl"))

    assert configured_log_path() is None


def test_voice_latency_log_separates_stt_tts_and_response_latency(
    tmp_path, monkeypatch
):
    log_path = tmp_path / "voice-latency.jsonl"
    monkeypatch.setenv("DARWIN_STATS_LOG_ENABLED", "true")
    monkeypatch.setenv("DARWIN_STATS_LOG_FILE", str(log_path))
    trace = VoicePerformanceTrace(
        "Tell me the weather",
        "request-voice",
        "desktop",
        {"recording_seconds": 1.2, "whisper_seconds": 0.4},
    )
    trace.set_reasoning(0.7)
    trace.add_tts(
        {"network_first_chunk": 0.2, "first_audio": 0.25, "playback": 1.8},
        requested_at=perf_counter(),
    )
    trace.finish()

    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["record_type"] == "voice_latency"
    assert record["question"] == "Tell me the weather"
    assert record["recording_seconds"] == 1.2
    assert record["stt_seconds"] == 0.4
    assert record["reasoning_seconds"] == 0.7
    assert record["tts_first_audio_seconds"] == 0.25
    assert record["tts_network_first_chunk_seconds"] == 0.2
    assert record["playback_seconds"] == 1.8
    assert record["response_latency_after_stt_seconds"] >= 0.25
    assert [operation["category"] for operation in record["operations"]] == [
        "input",
        "stt",
        "reasoning",
        "tts",
    ]
