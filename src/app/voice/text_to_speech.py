import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import pyttsx3
import sounddevice as sd
from dotenv import load_dotenv
from fishaudio import FishAudio
from fishaudio.types.tts import TTSConfig

from app.system.audio_focus import get_audio_focus_manager
from app.services.ui_activity import publish_ui_state


load_dotenv()

fish_client = FishAudio()


def _tts_config() -> TTSConfig:
    return TTSConfig(
        format="pcm",
        sample_rate=24_000,
        latency="balanced",
        chunk_length=100,
    )


def _fish_stream(text: str):
    return FishAudio().tts.stream(
        text=f"[calm] {text}",
        model=os.getenv("FISH_TTS_MODEL", "s2.1-pro-free"),
        reference_id=os.getenv("FISH_VOICE_ID"),
        speed=float(os.getenv("FISH_TTS_SPEED", "1.25")),
        config=_tts_config(),
    )


def _generate_pcm(text: str) -> bytes:
    return _fish_stream(text).collect()


def clean_for_speech(text: str) -> str:
    text = re.sub(r"(?:\s*[.…]{2,}\s*)+", " ", text)
    text = text.replace("e.g.", "for example")
    text = text.replace("i.e.", "that is")
    text = text.replace(";", ",")

    def speak_decimal(match: re.Match) -> str:
        digits = " ".join(match.group(2))
        return f"{match.group(1)} point {digits}"

    text = re.sub(r"\b(\d+)\.(\d+)\b", speak_decimal, text)

    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"[*_#>|~]", "", text)
    text = re.sub(
        r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]",
        "",
        text,
    )
    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*[°º]\s*F\b",
        r"\1 degrees Fahrenheit",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*[°º]\s*C\b",
        r"\1 degrees Celsius",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\bmph\b",
        "miles per hour",
        text,
        flags=re.IGNORECASE,
    )

    spoken_lines = []

    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        # Remove numbered-list and bullet prefixes.
        line = re.sub(r"^(?:\d+[.)]|[-•])\s*", "", line)

        # Add a natural pause between list items.
        if line[-1] not in ".!?:":
            line += "."

        spoken_lines.append(line)

    return " ".join(spoken_lines)


def speak_locally(text: str) -> None:
    engine = pyttsx3.init()
    engine.setProperty("rate", 165)
    engine.say(text)
    engine.runAndWait()


def _speak_with_focus_held(text: str) -> dict[str, float]:
    cleaned_text = clean_for_speech(text)
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned_text)
        if sentence.strip()
    ] or [cleaned_text]
    request_started = time.monotonic()
    first_audio_at = None

    try:
        remainder = b""
        with ThreadPoolExecutor(max_workers=min(3, len(sentences))) as executor:
            later_audio = [
                executor.submit(_generate_pcm, sentence) for sentence in sentences[1:]
            ]

            with sd.RawOutputStream(
                samplerate=24_000,
                channels=1,
                dtype="int16",
            ) as output:
                audio_sources = [_fish_stream(sentences[0]), *later_audio]

                for source in audio_sources:
                    chunks = (
                        source if not hasattr(source, "result") else [source.result()]
                    )
                    for chunk in chunks:
                        data = remainder + chunk
                        complete_length = len(data) - (len(data) % 2)
                        if complete_length:
                            if first_audio_at is None:
                                first_audio_at = time.monotonic()
                                publish_ui_state("speaking")
                            output.write(data[:complete_length])
                        remainder = data[complete_length:]

        finished_at = time.monotonic()
        return {
            "first_audio": (first_audio_at or finished_at) - request_started,
            "playback": finished_at - (first_audio_at or finished_at),
        }

    except Exception as error:
        print(f"Fish Audio unavailable; using local voice: {error}")
        if first_audio_at is None:
            publish_ui_state("speaking")
            speak_locally(cleaned_text)
        finished_at = time.monotonic()
        return {
            "first_audio": finished_at - request_started,
            "playback": 0.0,
        }


def speak(text: str) -> dict[str, float]:
    try:
        with get_audio_focus_manager().duck():
            return _speak_with_focus_held(text)
    finally:
        publish_ui_state("idle")
