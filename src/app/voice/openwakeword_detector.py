"""Streaming inference for DARWIN's trained openWakeWord model."""

from dataclasses import dataclass
from contextlib import nullcontext
import os
from pathlib import Path
import time
from typing import Protocol

import numpy as np
import sounddevice as sd


SAMPLE_RATE = 16_000
FRAME_DURATION_SECONDS = 0.08
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_SECONDS)
DEFAULT_THRESHOLD = 0.35

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIRECTORY = PROJECT_ROOT / "data" / "models" / "openwakeword"
DEFAULT_MODEL_PATH = MODEL_DIRECTORY / "darwin_v1.onnx"
MELSPECTROGRAM_PATH = MODEL_DIRECTORY / "melspectrogram.onnx"
EMBEDDING_PATH = MODEL_DIRECTORY / "embedding_model.onnx"


class WakeWordRuntime(Protocol):
    """Minimal interface used from the openWakeWord runtime."""

    def predict(self, samples: np.ndarray) -> dict[str, float]: ...

    def reset(self) -> None: ...


@dataclass(frozen=True)
class WakeDetection:
    triggered: bool
    score: float
    threshold: float


def _configured_model_path() -> Path:
    configured = os.getenv("DARWIN_WAKE_MODEL")
    if not configured:
        return DEFAULT_MODEL_PATH

    path = Path(configured).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def trained_wake_word_assets_ready() -> bool:
    """Return whether every model needed for streaming inference is present."""
    return all(
        path.is_file()
        for path in (
            _configured_model_path(),
            MELSPECTROGRAM_PATH,
            EMBEDDING_PATH,
        )
    )


class OpenWakeWordDetector:
    """Continuously score 80 ms microphone frames for the DARWIN wake word."""

    def __init__(
        self,
        *,
        model_path: Path | None = None,
        threshold: float | None = None,
        runtime: WakeWordRuntime | None = None,
    ) -> None:
        self.model_path = model_path or _configured_model_path()
        self.model_name = self.model_path.stem
        self.threshold = (
            float(os.getenv("DARWIN_WAKE_THRESHOLD", str(DEFAULT_THRESHOLD)))
            if threshold is None
            else threshold
        )

        if not 0.0 < self.threshold < 1.0:
            raise ValueError("DARWIN_WAKE_THRESHOLD must be between 0 and 1.")

        if runtime is None:
            self._validate_assets()
            from openwakeword.model import Model

            runtime = Model(
                wakeword_models=[str(self.model_path)],
                inference_framework="onnx",
                melspec_model_path=str(MELSPECTROGRAM_PATH),
                embedding_model_path=str(EMBEDDING_PATH),
            )

        self.runtime = runtime

    def _validate_assets(self) -> None:
        missing = [
            str(path)
            for path in (
                self.model_path,
                MELSPECTROGRAM_PATH,
                EMBEDDING_PATH,
            )
            if not path.is_file()
        ]
        if missing:
            raise FileNotFoundError(f"Missing openWakeWord model assets: {missing}")

    def process(self, samples: np.ndarray) -> WakeDetection:
        """Score one microphone frame and return its detection state."""
        audio = np.asarray(samples).reshape(-1)
        if np.issubdtype(audio.dtype, np.floating):
            audio = (np.clip(audio, -1.0, 1.0) * 32_767).astype(np.int16)
        else:
            audio = audio.astype(np.int16, copy=False)

        scores = self.runtime.predict(audio)
        score = float(scores.get(self.model_name, 0.0))
        return WakeDetection(
            triggered=score >= self.threshold,
            score=score,
            threshold=self.threshold,
        )

    def reset(self) -> None:
        """Clear streaming feature and prediction buffers."""
        self.runtime.reset()

    def microphone(self) -> sd.InputStream:
        """Create the microphone stream used by wake and command capture."""
        return sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SIZE,
        )

    def wait(self, microphone=None) -> WakeDetection:
        """Listen continuously until the trained model detects DARWIN."""
        debug = os.getenv("DARWIN_WAKE_WORD_DEBUG", "0") == "1"
        debug_started = time.monotonic()
        highest_debug_score = 0.0

        stream_context = (
            nullcontext(microphone) if microphone is not None else self.microphone()
        )
        with stream_context as active_microphone:
            while True:
                samples, overflowed = active_microphone.read(FRAME_SIZE)
                detection = self.process(samples)
                highest_debug_score = max(highest_debug_score, detection.score)

                if debug and time.monotonic() - debug_started >= 1.0:
                    overflow_note = " (audio overflow)" if overflowed else ""
                    print(
                        "Wake score: "
                        f"{highest_debug_score:.3f}/{self.threshold:.3f}"
                        f"{overflow_note}"
                    )
                    debug_started = time.monotonic()
                    highest_debug_score = 0.0

                if detection.triggered:
                    self.reset()
                    return detection
