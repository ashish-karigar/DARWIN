import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from app.voice.openwakeword_detector import (
    OpenWakeWordDetector,
    trained_wake_word_assets_ready,
)
from app.voice.personalized_wake_word import (
    evaluate_wake_word,
    is_personalized_wake_word_enrolled,
    transcript_contains_darwin,
)
from app.voice.speech_to_text import record_until_silence
from app.voice.wake_word_transcription import transcribe_wake_word


ACTIVATION_NAME = "DARWIN"
WAKE_CANDIDATE_PATH = Path(
    "data/voice_profiles/ashish/darwin_wake_word/candidate.wav"
)


def activation_backend_ready() -> bool:
    backend = os.getenv("DARWIN_WAKE_BACKEND", "openwakeword").casefold()
    if backend == "personalized":
        return is_personalized_wake_word_enrolled()
    return backend == "openwakeword" and trained_wake_word_assets_ready()


@lru_cache(maxsize=1)
def _trained_detector() -> OpenWakeWordDetector:
    return OpenWakeWordDetector()


@contextmanager
def wake_listening_session():
    """Keep one microphone stream open across activation and command capture."""
    backend = os.getenv("DARWIN_WAKE_BACKEND", "openwakeword").casefold()
    if backend == "openwakeword":
        with _trained_detector().microphone() as microphone:
            yield microphone
        return

    yield None


def wait_for_wake_word(input_stream=None) -> str:
    """Wait until the selected backend detects DARWIN."""
    if not activation_backend_ready():
        raise RuntimeError(
            "DARWIN wake-word model is unavailable. Expected assets under "
            "data/models/openwakeword."
        )

    backend = os.getenv("DARWIN_WAKE_BACKEND", "openwakeword").casefold()
    if backend == "openwakeword":
        _trained_detector().wait(microphone=input_stream)
        return ACTIVATION_NAME

    return _wait_for_personalized_wake_word()


def _wait_for_personalized_wake_word() -> str:
    """Retain the enrolled MFCC/voiceprint detector as an explicit fallback."""

    debug = os.getenv("DARWIN_WAKE_WORD_DEBUG", "0") == "1"
    while True:
        recording = record_until_silence(
            WAKE_CANDIDATE_PATH,
            start_timeout_seconds=30,
            silence_seconds=0.8,
            max_recording_seconds=5,
            announce=False,
        )
        if recording is None:
            continue

        try:
            result = evaluate_wake_word(recording)
        except ValueError:
            continue

        if debug:
            print(
                "Wake candidate: "
                f"phrase {result.phrase_distance:.3f}/{result.phrase_threshold:.3f}, "
                f"voice {result.speaker.similarity:.3f}/{result.speaker.threshold:.3f}"
            )
        if not result.accepted:
            continue

        transcript = transcribe_wake_word(recording)
        if debug:
            print(f"Wake transcript: {transcript!r}")
        if transcript_contains_darwin(transcript):
            return ACTIVATION_NAME
