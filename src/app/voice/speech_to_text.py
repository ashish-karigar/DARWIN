from collections import deque
from contextlib import ExitStack, nullcontext, redirect_stdout
from dataclasses import dataclass
from io import StringIO
import os
from pathlib import Path
import time

import numpy as np
import sounddevice as sd
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

whisper_model = WhisperModel(
    os.getenv("DARWIN_WHISPER_MODEL", "small.en"),
    device="cpu",
    compute_type="int8",
)

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
) -> Path | None:
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
            block, _ = stream.read(BLOCK_SIZE)
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
                silent_blocks = 0

            recording_duration = time.monotonic() - recording_started

            if silent_blocks >= required_silent_blocks and recording_duration >= 0.5:
                break

            if recording_duration >= max_recording_seconds:
                break

    publish_ui_audio_level(0.0)

    audio = np.concatenate(frames, axis=0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write(output_path, SAMPLE_RATE, audio)

    return output_path


def transcribe_audio(audio_path: Path) -> str:
    segments, _ = whisper_model.transcribe(
        str(audio_path),
        language="en",
        beam_size=3,
        vad_filter=True,
        condition_on_previous_text=False,
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
) -> str:
    global _last_input_timing

    publish_ui_state("listening")
    recording_started = time.monotonic()
    if announce:
        audio_path = record_until_silence(
            output_path=output_path,
            start_timeout_seconds=start_timeout_seconds,
            silence_seconds=silence_seconds,
            max_recording_seconds=max_recording_seconds,
            input_stream=input_stream,
            manage_audio_focus=manage_audio_focus,
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
            )
    recording_finished = time.monotonic()

    if audio_path is None:
        _last_input_timing = {
            "recording_seconds": recording_finished - recording_started,
            "whisper_seconds": None,
        }
        publish_ui_state("idle")
        return ""

    publish_ui_state("transcribing")
    try:
        transcript = transcribe_audio(audio_path)
    except Exception:
        publish_ui_state("error")
        raise
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
