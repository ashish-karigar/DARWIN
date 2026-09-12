"""Streaming speech activity detection for microphone endpointing."""

from dataclasses import dataclass
import os
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[3]
VAD_MODEL_PATH = (
    PROJECT_ROOT / "data" / "models" / "openwakeword" / "silero_vad.onnx"
)


@dataclass(frozen=True)
class SpeechActivity:
    probability: float
    is_speech: bool


class SpeechActivityDetector:
    """Use Silero VAD to distinguish speech from room noise and music."""

    def __init__(self, threshold: float | None = None, runtime=None) -> None:
        self.threshold = (
            float(os.getenv("DARWIN_VAD_THRESHOLD", "0.5"))
            if threshold is None
            else threshold
        )
        if not 0.0 < self.threshold < 1.0:
            raise ValueError("DARWIN_VAD_THRESHOLD must be between 0 and 1.")

        if runtime is None:
            from openwakeword.vad import VAD

            if not VAD_MODEL_PATH.is_file():
                raise FileNotFoundError(f"Missing speech activity model: {VAD_MODEL_PATH}")
            runtime = VAD(model_path=str(VAD_MODEL_PATH))
        self.runtime = runtime

    def reset(self) -> None:
        """Clear recurrent state before capturing a new utterance."""
        self.runtime.reset_states()

    def process(self, samples: np.ndarray) -> SpeechActivity:
        """Classify one 80 ms block of 16 kHz PCM audio."""
        audio = np.asarray(samples).reshape(-1).astype(np.int16, copy=False)
        probability = float(self.runtime.predict(audio, frame_size=640))
        return SpeechActivity(
            probability=probability,
            is_speech=probability >= self.threshold,
        )
