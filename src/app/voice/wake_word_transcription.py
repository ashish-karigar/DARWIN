from functools import lru_cache
from pathlib import Path

from faster_whisper import WhisperModel


@lru_cache(maxsize=1)
def _wake_transcriber() -> WhisperModel:
    return WhisperModel("base.en", device="cpu", compute_type="int8")


def transcribe_wake_word(audio_path: Path) -> str:
    segments, _ = _wake_transcriber().transcribe(
        str(audio_path),
        language="en",
        beam_size=3,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    return " ".join(
        segment.text.strip() for segment in segments if segment.text.strip()
    ).strip()
