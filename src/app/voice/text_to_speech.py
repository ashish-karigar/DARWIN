import os
import re
import threading
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor

import pyttsx3
import sounddevice as sd
from dotenv import load_dotenv
from fishaudio import FishAudio
from fishaudio.types.tts import TTSConfig

from app.system.audio_focus import get_audio_focus_manager
from app.services.ui_activity import publish_ui_state, publish_ui_voice_playback


load_dotenv()

fish_client = FishAudio()
_PLAYBACK_SERIAL_LOCK = threading.Lock()
_PLAYBACK_STATE_LOCK = threading.Lock()
_ACTIVE_PLAYBACK_CANCEL: threading.Event | None = None
_PCM_FRAME_BYTES = 960  # 20 ms of mono 24 kHz int16 audio.


def partial_speech_enabled() -> bool:
    """Remote acknowledgements are opt-in because they serialize with final TTS."""
    return os.getenv("DARWIN_SPEAK_PARTIAL_RESPONSES", "false").casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def interrupt_speech() -> None:
    """Signal the active playback stream to stop at the next audio frame."""
    with _PLAYBACK_STATE_LOCK:
        active = _ACTIVE_PLAYBACK_CANCEL
    if active is not None:
        active.set()


def _write_cancellable(
    output,
    data: bytes,
    cancel_event: threading.Event,
) -> bool:
    for offset in range(0, len(data), _PCM_FRAME_BYTES):
        if cancel_event.is_set():
            return False
        output.write(data[offset : offset + _PCM_FRAME_BYTES])
    return not cancel_event.is_set()


def _tts_config() -> TTSConfig:
    return TTSConfig(
        format="pcm",
        sample_rate=24_000,
        latency=os.getenv("FISH_TTS_LATENCY", "balanced"),
        chunk_length=max(
            100, min(300, int(os.getenv("FISH_TTS_CHUNK_LENGTH", "100")))
        ),
        min_chunk_length=max(
            0, min(100, int(os.getenv("FISH_TTS_MIN_CHUNK_LENGTH", "30")))
        ),
        normalize=os.getenv("FISH_TTS_NORMALIZE", "true").casefold()
        in {"1", "true", "yes", "on"},
        condition_on_previous_chunks=os.getenv(
            "FISH_TTS_CONDITION_PREVIOUS", "true"
        ).casefold()
        in {"1", "true", "yes", "on"},
    )


def _http_fish_stream(text: str):
    return fish_client.tts.stream(
        text=text,
        model=os.getenv("FISH_TTS_MODEL", "s2.1-pro-free"),
        reference_id=os.getenv("FISH_VOICE_ID"),
        speed=float(os.getenv("FISH_TTS_SPEED", "1.25")),
        config=_tts_config(),
    )


def _fish_stream(text: str) -> Iterator[bytes]:
    """Use one low-latency stream and fall back before playback if WS setup fails."""
    prompted = f"[calm] {text}"
    transport = os.getenv("FISH_TTS_TRANSPORT", "http").strip().casefold()
    if transport == "http":
        yield from _http_fish_stream(prompted)
        return

    emitted_audio = False
    try:
        stream = fish_client.tts.stream_websocket(
            iter((prompted,)),
            model=os.getenv("FISH_TTS_MODEL", "s2.1-pro-free"),
            reference_id=os.getenv("FISH_VOICE_ID"),
            speed=float(os.getenv("FISH_TTS_SPEED", "1.25")),
            config=_tts_config(),
        )
        for chunk in stream:
            emitted_audio = True
            yield chunk
    except Exception:
        if emitted_audio:
            raise
        yield from _http_fish_stream(prompted)


def _generate_pcm(text: str) -> bytes:
    return b"".join(_fish_stream(text))


def _split_tts_clauses(text: str) -> list[str]:
    """Split finalized speech into short, natural TTS requests.

    Fish's free HTTP endpoint delays its first PCM for long inputs. Keeping the
    first clause short reduces time to first audio, while a bounded prefetch
    queue prepares later clauses during playback.
    """
    maximum = max(40, min(180, int(os.getenv("FISH_TTS_CLAUSE_MAX_CHARS", "80"))))
    minimum = max(15, min(maximum, int(os.getenv("FISH_TTS_CLAUSE_MIN_CHARS", "35"))))
    segments = re.findall(r".+?(?:[.!?;:,]+(?:\s+|$)|$)", text.strip())
    clauses: list[str] = []
    current = ""

    def append_words(value: str) -> None:
        nonlocal current
        words = value.split()
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > maximum:
                clauses.append(current)
                current = word
            else:
                current = candidate

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        candidate = f"{current} {segment}".strip()
        if current and len(candidate) > maximum:
            if len(current) >= minimum:
                clauses.append(current)
                current = ""
            else:
                append_words(segment)
                continue
        if len(segment) > maximum:
            append_words(segment)
        else:
            current = f"{current} {segment}".strip()
        if len(current) >= minimum and re.search(r"[.!?;:,]+$", current):
            clauses.append(current)
            current = ""

    if current:
        clauses.append(current)
    return clauses or [text]


def _prefetched_pcm(clauses: list[str]) -> Iterator[bytes]:
    """Generate clauses in order with a strictly bounded request window."""
    prefetch = max(1, min(2, int(os.getenv("FISH_TTS_PREFETCH_CLAUSES", "2"))))
    with ThreadPoolExecutor(max_workers=prefetch, thread_name_prefix="darwin-tts") as pool:
        pending: dict[int, Future[bytes]] = {}
        next_to_submit = 0

        while next_to_submit < min(prefetch, len(clauses)):
            pending[next_to_submit] = pool.submit(
                _generate_pcm, clauses[next_to_submit]
            )
            next_to_submit += 1

        for index in range(len(clauses)):
            yield pending.pop(index).result()
            if next_to_submit < len(clauses):
                pending[next_to_submit] = pool.submit(
                    _generate_pcm, clauses[next_to_submit]
                )
                next_to_submit += 1


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


def _speak_with_focus_held(
    text: str, cancel_event: threading.Event | None = None
) -> dict[str, float]:
    cleaned_text = clean_for_speech(text)
    request_started = time.monotonic()
    first_network_chunk_at = None
    first_audio_at = None
    focus_stop = threading.Event()
    focus_thread: threading.Thread | None = None

    def start_audio_focus() -> None:
        nonlocal focus_thread

        def hold_focus() -> None:
            with get_audio_focus_manager().duck():
                focus_stop.wait()

        focus_thread = threading.Thread(target=hold_focus, daemon=True)
        focus_thread.start()

    def release_focus() -> None:
        focus_stop.set()
        if focus_thread is not None:
            focus_thread.join(timeout=5)

    try:
        remainder = b""
        clauses = _split_tts_clauses(cleaned_text)
        with sd.RawOutputStream(
            samplerate=24_000,
            channels=1,
            dtype="int16",
            latency="low",
        ) as output:
            for chunk in _prefetched_pcm(clauses):
                if first_network_chunk_at is None:
                    first_network_chunk_at = time.monotonic()
                if cancel_event is not None and cancel_event.is_set():
                    break
                data = remainder + chunk
                complete_length = len(data) - (len(data) % 2)
                if complete_length:
                    complete = data[:complete_length]
                    if first_audio_at is None:
                        # First write is the audible-playback boundary used by
                        # UI media ducking and latency instrumentation.
                        first_frame_length = min(len(complete), _PCM_FRAME_BYTES)
                        if not _write_cancellable(
                            output,
                            complete[:first_frame_length],
                            cancel_event or threading.Event(),
                        ):
                            break
                        first_audio_at = time.monotonic()
                        publish_ui_state("speaking")
                        publish_ui_voice_playback(True)
                        start_audio_focus()
                        complete = complete[first_frame_length:]
                    if complete:
                        if cancel_event is not None:
                            if not _write_cancellable(output, complete, cancel_event):
                                break
                        else:
                            output.write(complete)
                remainder = data[complete_length:]

        finished_at = time.monotonic()
        publish_ui_voice_playback(False)
        release_focus()
        return {
            "network_first_chunk": (first_network_chunk_at or finished_at)
            - request_started,
            "first_audio": (first_audio_at or finished_at) - request_started,
            "playback": finished_at - (first_audio_at or finished_at),
        }

    except Exception as error:
        release_focus()
        print(f"Fish Audio unavailable; using local voice: {error}")
        if first_audio_at is None and not (
            cancel_event is not None and cancel_event.is_set()
        ):
            publish_ui_state("speaking")
            publish_ui_voice_playback(True)
            with get_audio_focus_manager().duck():
                speak_locally(cleaned_text)
                publish_ui_voice_playback(False)
        finished_at = time.monotonic()
        return {
            "network_first_chunk": (first_network_chunk_at or finished_at)
            - request_started,
            "first_audio": finished_at - request_started,
            "playback": 0.0,
        }


def speak(
    text: str, *, cancel_event: threading.Event | None = None
) -> dict[str, float]:
    global _ACTIVE_PLAYBACK_CANCEL
    playback_cancel = cancel_event or threading.Event()
    interrupt_speech()
    with _PLAYBACK_SERIAL_LOCK:
        if playback_cancel.is_set():
            return {"first_audio": 0.0, "playback": 0.0}
        with _PLAYBACK_STATE_LOCK:
            _ACTIVE_PLAYBACK_CANCEL = playback_cancel
        try:
            return _speak_with_focus_held(text, cancel_event=playback_cancel)
        finally:
            with _PLAYBACK_STATE_LOCK:
                if _ACTIVE_PLAYBACK_CANCEL is playback_cancel:
                    _ACTIVE_PLAYBACK_CANCEL = None
            publish_ui_voice_playback(False)
            publish_ui_state("idle")
