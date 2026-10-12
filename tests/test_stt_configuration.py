import numpy as np

from app.voice import speech_to_text as stt


class Segment:
    text = " hello "


class FakeWhisper:
    def __init__(self) -> None:
        self.source = None
        self.options = None

    def transcribe(self, source, **options):
        self.source = source
        self.options = options
        return [Segment()], object()


def test_stt_uses_in_memory_audio_and_low_latency_options(monkeypatch) -> None:
    model = FakeWhisper()
    monkeypatch.setattr(stt, "whisper_model", model)
    monkeypatch.setenv("DARWIN_WHISPER_BEAM_SIZE", "1")
    monkeypatch.setenv("DARWIN_WHISPER_VAD_FILTER", "false")

    transcript = stt.transcribe_audio(np.array([[0], [32767]], dtype=np.int16))

    assert transcript == "hello"
    assert isinstance(model.source, np.ndarray)
    assert model.source.dtype == np.float32
    assert model.options["beam_size"] == 1
    assert model.options["vad_filter"] is False
    assert model.options["condition_on_previous_text"] is False


def test_endpoint_prefetch_reuses_single_final_transcription(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_transcribe(audio):
        calls.append(np.asarray(audio).copy())
        return "prefetched result"

    def fake_record(**kwargs):
        audio = np.ones((1600, 1), dtype=np.int16)
        monkeypatch.setattr(stt, "_last_recorded_audio", audio)
        kwargs["endpoint_candidate_callback"](audio)
        return tmp_path / "input.wav"

    monkeypatch.setenv("DARWIN_STT_ENDPOINT_PREFETCH", "true")
    monkeypatch.setattr(stt, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(stt, "record_until_silence", fake_record)
    monkeypatch.setattr(stt, "publish_ui_state", lambda _state: True)

    transcript = stt.listen(announce=True, report_timing=False)

    assert transcript == "prefetched result"
    assert len(calls) == 1


def test_resumed_speech_invalidates_prefetched_transcript(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_transcribe(audio):
        calls.append(np.asarray(audio).copy())
        return f"samples-{np.asarray(audio).shape[0]}"

    def fake_record(**kwargs):
        candidate = np.ones((800, 1), dtype=np.int16)
        final = np.ones((1600, 1), dtype=np.int16)
        kwargs["endpoint_candidate_callback"](candidate)
        kwargs["endpoint_candidate_invalidated"]()
        monkeypatch.setattr(stt, "_last_recorded_audio", final)
        return tmp_path / "input.wav"

    monkeypatch.setenv("DARWIN_STT_ENDPOINT_PREFETCH", "true")
    monkeypatch.setattr(stt, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(stt, "record_until_silence", fake_record)
    monkeypatch.setattr(stt, "publish_ui_state", lambda _state: True)

    transcript = stt.listen(announce=True, report_timing=False)

    assert transcript == "samples-1600"
    assert calls[-1].shape == (1600, 1)
