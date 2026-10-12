from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack, nullcontext, redirect_stdout
from dataclasses import dataclass
from io import StringIO
import os
import math
from pathlib import Path
import time
from threading import Event, Lock

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv
from faster_whisper import WhisperModel
from scipy.io.wavfile import write

from app.system.audio_focus import get_audio_focus_manager
from app.services.ui_activity import publish_ui_audio_level, publish_ui_state
from app.voice.speech_activity import SpeechActivityDetector


SAMPLE_RATE = 16_000
BLOCK_DURATION = 0.08
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION)

START_TIMEOUT_SECONDS = 8
MAX_RECORDING_SECONDS = 20
SILENCE_SECONDS = 0.6

AUDIO_PATH = Path("data/input.wav")

load_dotenv()

whisper_model = WhisperModel(
    os.getenv("DARWIN_WHISPER_MODEL", "small.en"),
    device=os.getenv("DARWIN_WHISPER_DEVICE", "cpu"),
    compute_type=os.getenv("DARWIN_WHISPER_COMPUTE_TYPE", "int8"),
)
_whisper_lock = Lock()
_warmup_lock = Lock()
_warmed_up = False
_last_recorded_audio: np.ndarray | None = None

_last_input_timing = {
    "recording_seconds": None,
    "whisper_seconds": None,
}

_speech_activity_detector: SpeechActivityDetector | None = None


def get_speech_activity_detector() -> SpeechActivityDetector:
    """Reuse one lightweight VAD runtime across microphone turns."""
    global _speech_activity_detector
    if _speech_activity_detector is None:
        _speech_activity_detector = SpeechActivityDetector()
    return _speech_activity_detector


@dataclass
class AdaptiveSpeechGate:
    """Detect speech immediately while adapting to quiet ambient noise."""

    noise_floor: float = 80.0
    minimum_threshold: float = 250.0
    noise_multiplier: float = 3.0
    adaptation_rate: float = 0.08

    @property
    def threshold(self) -> float:
        return max(self.minimum_threshold, self.noise_floor * self.noise_multiplier)

    def observe(self, volume: float) -> bool:
        if volume >= self.threshold:
            return True

        self.noise_floor = (
            (1.0 - self.adaptation_rate) * self.noise_floor
            + self.adaptation_rate * volume
        )
        return False


def get_last_input_timing() -> dict[str, float | None]:
    return _last_input_timing.copy()


def warm_stt_model() -> None:
    """Pay lazy model initialization at backend startup, not on the first turn."""
    global _warmed_up
    if _warmed_up or os.getenv("DARWIN_WHISPER_WARMUP", "true").casefold() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    with _warmup_lock:
        if _warmed_up:
            return
        transcribe_audio(np.zeros(SAMPLE_RATE // 10, dtype=np.float32))
        _warmed_up = True


def calculate_rms(audio: np.ndarray) -> float:
    samples = audio.astype(np.float32)
    return float(np.sqrt(np.mean(samples**2)))


def record_until_silence(
    output_path: Path = AUDIO_PATH,
    start_timeout_seconds: float = START_TIMEOUT_SECONDS,
    silence_seconds: float = SILENCE_SECONDS,
    max_recording_seconds: float = MAX_RECORDING_SECONDS,
    announce: bool = True,
    input_stream=None,
    manage_audio_focus: bool = False,
    cancel_event: Event | None = None,
    endpoint_candidate_callback: Callable[[np.ndarray], None] | None = None,
    endpoint_candidate_invalidated: Callable[[], None] | None = None,
) -> Path | None:
    global _last_recorded_audio
    _last_recorded_audio = None
    if announce:
        print("Listening...")

    frames = []
    pre_roll = deque(maxlen=5)
    speech_started = False
    silent_blocks = 0
    speech_detector = get_speech_activity_detector()
    speech_detector.reset()
    displayed_level = 0.0

    required_silent_blocks = int(silence_seconds / BLOCK_DURATION)
    prefetch_silence_seconds = max(
        BLOCK_DURATION,
        float(os.getenv("DARWIN_STT_PREFETCH_SILENCE_SECONDS", "0.24")),
    )
    prefetch_silent_blocks = min(
        required_silent_blocks,
        max(1, math.ceil(prefetch_silence_seconds / BLOCK_DURATION)),
    )
    endpoint_candidate_active = False

    stream_context = (
        nullcontext(input_stream)
        if input_stream is not None
        else sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=BLOCK_SIZE,
        )
    )
    with stream_context as stream, ExitStack() as active_contexts:
        waiting_started = time.monotonic()
        recording_started = None

        while True:
            if cancel_event is not None and cancel_event.is_set():
                publish_ui_audio_level(0.0)
                return None
            block, _ = stream.read(BLOCK_SIZE)
            if cancel_event is not None and cancel_event.is_set():
                publish_ui_audio_level(0.0)
                return None
            activity = speech_detector.process(block)
            raw_level = min(1.0, calculate_rms(block) / 4_000.0)
            weighted_level = raw_level * (0.35 + activity.probability * 0.65)
            smoothing = 0.55 if weighted_level > displayed_level else 0.18
            displayed_level += (weighted_level - displayed_level) * smoothing
            publish_ui_audio_level(displayed_level)

            if not speech_started:
                pre_roll.append(block.copy())

                if activity.is_speech:
                    speech_started = True
                    recording_started = time.monotonic()
                    frames.extend(pre_roll)
                    silent_blocks = 0
                    if manage_audio_focus:
                        active_contexts.enter_context(
                            get_audio_focus_manager().duck()
                        )

                elif time.monotonic() - waiting_started >= start_timeout_seconds:
                    if announce:
                        print("No speech detected.")
                    publish_ui_audio_level(0.0)
                    return None

                continue

            frames.append(block.copy())

            if not activity.is_speech:
                silent_blocks += 1
            else:
                if endpoint_candidate_active:
                    endpoint_candidate_active = False
                    if endpoint_candidate_invalidated is not None:
                        endpoint_candidate_invalidated()
                silent_blocks = 0

            if (
                endpoint_candidate_callback is not None
                and not endpoint_candidate_active
                and silent_blocks == prefetch_silent_blocks
            ):
                endpoint_candidate_active = True
                endpoint_candidate_callback(np.concatenate(frames, axis=0))

            recording_duration = time.monotonic() - recording_started

            if silent_blocks >= required_silent_blocks and recording_duration >= 0.5:
                break

            if recording_duration >= max_recording_seconds:
                break

    publish_ui_audio_level(0.0)

    audio = np.concatenate(frames, axis=0)
    _last_recorded_audio = audio.copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write(output_path, SAMPLE_RATE, audio)

    return output_path


def transcribe_audio(audio: Path | np.ndarray) -> str:
    source: str | np.ndarray
    if isinstance(audio, Path):
        source = str(audio)
    else:
        samples = np.asarray(audio).reshape(-1)
        source = (
            samples.astype(np.float32) / 32768.0
            if np.issubdtype(samples.dtype, np.integer)
            else samples.astype(np.float32)
        )
    with _whisper_lock:
        segments, _ = whisper_model.transcribe(
            source,
            language=os.getenv("DARWIN_WHISPER_LANGUAGE", "en"),
            beam_size=max(1, int(os.getenv("DARWIN_WHISPER_BEAM_SIZE", "1"))),
            vad_filter=os.getenv("DARWIN_WHISPER_VAD_FILTER", "false").casefold()
            in {"1", "true", "yes", "on"},
            condition_on_previous_text=False,
            word_timestamps=False,
        )

    return " ".join(
        segment.text.strip() for segment in segments if segment.text.strip()
    ).strip()


def listen(
    start_timeout_seconds: float = START_TIMEOUT_SECONDS,
    *,
    output_path: Path = AUDIO_PATH,
    silence_seconds: float = SILENCE_SECONDS,
    max_recording_seconds: float = MAX_RECORDING_SECONDS,
    manage_audio_focus: bool = True,
    announce: bool = True,
    report_timing: bool = True,
    input_stream=None,
    cancel_event: Event | None = None,
) -> str:
    global _last_input_timing

    publish_ui_state("listening")
    prefetch_enabled = os.getenv(
        "DARWIN_STT_ENDPOINT_PREFETCH", "true"
    ).casefold() in {"1", "true", "yes", "on"}
    prefetch_executor = (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="darwin-stt-prefetch")
        if prefetch_enabled
        else None
    )
    prefetch_future: Future[str] | None = None
    prefetch_valid = False

    def offer_endpoint_candidate(audio: np.ndarray) -> None:
        nonlocal prefetch_future, prefetch_valid
        if prefetch_executor is None:
            return
        if prefetch_future is not None and not prefetch_future.done():
            return
        prefetch_future = prefetch_executor.submit(transcribe_audio, audio.copy())
        prefetch_valid = True

    def invalidate_endpoint_candidate() -> None:
        nonlocal prefetch_valid
        prefetch_valid = False
        if prefetch_future is not None:
            prefetch_future.cancel()

    recording_started = time.monotonic()
    try:
        if announce:
            audio_path = record_until_silence(
                output_path=output_path,
                start_timeout_seconds=start_timeout_seconds,
                silence_seconds=silence_seconds,
                max_recording_seconds=max_recording_seconds,
                input_stream=input_stream,
                manage_audio_focus=manage_audio_focus,
                cancel_event=cancel_event,
                endpoint_candidate_callback=offer_endpoint_candidate,
                endpoint_candidate_invalidated=invalidate_endpoint_candidate,
            )
        else:
            with redirect_stdout(StringIO()):
                audio_path = record_until_silence(
                    output_path=output_path,
                    start_timeout_seconds=start_timeout_seconds,
                    silence_seconds=silence_seconds,
                    max_recording_seconds=max_recording_seconds,
                    input_stream=input_stream,
                    manage_audio_focus=manage_audio_focus,
                    cancel_event=cancel_event,
                    endpoint_candidate_callback=offer_endpoint_candidate,
                    endpoint_candidate_invalidated=invalidate_endpoint_candidate,
                )
    except Exception:
        if prefetch_executor is not None:
            prefetch_executor.shutdown(wait=False, cancel_futures=True)
        raise
    recording_finished = time.monotonic()

    if audio_path is None:
        _last_input_timing = {
            "recording_seconds": recording_finished - recording_started,
            "whisper_seconds": None,
        }
        publish_ui_state("idle")
        if prefetch_executor is not None:
            prefetch_executor.shutdown(wait=False, cancel_futures=True)
        return ""

    publish_ui_state("transcribing")
    try:
        if prefetch_valid and prefetch_future is not None:
            transcript = prefetch_future.result()
        else:
            transcript = transcribe_audio(
                _last_recorded_audio if _last_recorded_audio is not None else audio_path
            )
    except Exception:
        publish_ui_state("error")
        raise
    finally:
        if prefetch_executor is not None:
            prefetch_executor.shutdown(wait=False, cancel_futures=True)
    transcription_finished = time.monotonic()
    _last_input_timing = {
        "recording_seconds": recording_finished - recording_started,
        "whisper_seconds": transcription_finished - recording_finished,
    }
    if report_timing:
        print(
            "Input timing: "
            f"recording {recording_finished - recording_started:.1f}s, "
            f"Whisper {transcription_finished - recording_finished:.1f}s"
        )
    publish_ui_state("idle")
    return transcript
