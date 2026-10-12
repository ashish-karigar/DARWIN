from types import SimpleNamespace
from unittest.mock import Mock, patch

import main as darwin_main
from app.safety import set_confirmation_handler
from app.services.status import set_status_handler


def test_speech_prioritizes_darwin_audio_over_capture() -> None:
    continuous = Mock()
    events = []
    continuous.response_started.side_effect = lambda: events.append("capture stopped")
    continuous.response_completed.side_effect = lambda: events.append("capture resumed")

    with patch.object(
        darwin_main,
        "speak",
        side_effect=lambda _message: events.append("speech")
        or {"first_audio": 0.1, "playback": 0.2},
    ):
        timing = darwin_main.speak_with_audio_priority("hello", continuous)

    assert events == ["capture stopped", "speech", "capture resumed"]
    assert timing == {"first_audio": 0.1, "playback": 0.2}


def test_capture_resumes_when_speech_fails() -> None:
    continuous = Mock()
    with patch.object(darwin_main, "speak", side_effect=RuntimeError("audio failed")):
        try:
            darwin_main.speak_with_audio_priority("hello", continuous)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Expected speech failure")

    continuous.response_started.assert_called_once_with()
    continuous.response_completed.assert_called_once_with()


def test_text_terminal_uses_reusable_runtime() -> None:
    runtime = Mock()
    runtime.submit.return_value = SimpleNamespace(
        content="Runtime response", reasoning_seconds=0.25
    )

    try:
        with (
            patch.object(darwin_main, "AssistantRuntime", return_value=runtime) as factory,
            patch.object(darwin_main, "initialize_location", return_value=None),
            patch.object(darwin_main, "available_capability_names", return_value=[]),
            patch.object(darwin_main, "record_interaction") as record_interaction,
            patch("builtins.input", side_effect=["desktop", "text", "hello", "exit"]),
            patch("builtins.print") as output,
        ):
            darwin_main.main()
    finally:
        set_confirmation_handler(None)
        set_status_handler(None)

    factory.assert_called_once_with(session_id="desktop")
    runtime.submit.assert_called_once_with("hello")
    record_interaction.assert_called_once()
    assert record_interaction.call_args.kwargs["reasoning_seconds"] == 0.25
    output.assert_any_call("\nDARWIN: Runtime response")
    output.assert_any_call("DARWIN offline.")
