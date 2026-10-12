from app.voice import text_to_speech as tts
import time


class FakeTtsService:
    def __init__(self, *, websocket_error: Exception | None = None) -> None:
        self.websocket_error = websocket_error
        self.websocket_calls = 0
        self.http_calls = 0

    def stream_websocket(self, text_stream, **_kwargs):
        self.websocket_calls += 1
        assert list(text_stream) == ["[calm] Hello."]
        if self.websocket_error:
            raise self.websocket_error
        return iter((b"ws-audio",))

    def stream(self, *, text, **_kwargs):
        self.http_calls += 1
        assert text == "[calm] Hello."
        return iter((b"http-audio",))


class FakeClient:
    def __init__(self, service: FakeTtsService) -> None:
        self.tts = service


def test_websocket_transport_reuses_module_client(monkeypatch) -> None:
    service = FakeTtsService()
    monkeypatch.setattr(tts, "fish_client", FakeClient(service))
    monkeypatch.setenv("FISH_TTS_TRANSPORT", "websocket")

    assert b"".join(tts._fish_stream("Hello.")) == b"ws-audio"
    assert service.websocket_calls == 1
    assert service.http_calls == 0


def test_websocket_setup_failure_falls_back_before_audio(monkeypatch) -> None:
    service = FakeTtsService(websocket_error=RuntimeError("unavailable"))
    monkeypatch.setattr(tts, "fish_client", FakeClient(service))
    monkeypatch.setenv("FISH_TTS_TRANSPORT", "websocket")

    assert b"".join(tts._fish_stream("Hello.")) == b"http-audio"
    assert service.websocket_calls == 1
    assert service.http_calls == 1


def test_partial_remote_speech_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("DARWIN_SPEAK_PARTIAL_RESPONSES", raising=False)

    assert tts.partial_speech_enabled() is False


def test_finalized_text_is_split_at_natural_clause_boundaries(monkeypatch) -> None:
    monkeypatch.setenv("FISH_TTS_CLAUSE_MAX_CHARS", "55")
    monkeypatch.setenv("FISH_TTS_CLAUSE_MIN_CHARS", "25")

    clauses = tts._split_tts_clauses(
        "Clear and warm, around seventy six degrees Fahrenheit, with a light breeze."
    )

    assert clauses == [
        "Clear and warm, around seventy six degrees Fahrenheit,",
        "with a light breeze.",
    ]


def test_clause_prefetch_preserves_order_and_is_bounded(monkeypatch) -> None:
    active = 0
    maximum_active = 0

    def generate(clause: str) -> bytes:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        time.sleep({"first": 0.03, "second": 0.01, "third": 0.01}[clause])
        active -= 1
        return clause.encode()

    monkeypatch.setattr(tts, "_generate_pcm", generate)
    monkeypatch.setenv("FISH_TTS_PREFETCH_CLAUSES", "2")

    assert list(tts._prefetched_pcm(["first", "second", "third"])) == [
        b"first",
        b"second",
        b"third",
    ]
    assert maximum_active == 2
