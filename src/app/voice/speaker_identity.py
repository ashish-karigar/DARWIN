import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np


PROFILE_DIRECTORY = Path("data/voice_profiles/ashish")
VOICEPRINT_PATH = PROFILE_DIRECTORY / "voiceprint.npy"
PROFILE_PATH = PROFILE_DIRECTORY / "profile.json"
MODEL_DIRECTORY = Path("data/models/speechbrain/spkrec-ecapa-voxceleb")
MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"


@dataclass(frozen=True)
class VerificationResult:
    accepted: bool
    similarity: float
    threshold: float


@lru_cache(maxsize=1)
def _speaker_model():
    from speechbrain.inference.speaker import SpeakerRecognition

    return SpeakerRecognition.from_hparams(
        source=MODEL_SOURCE,
        savedir=str(MODEL_DIRECTORY),
        run_opts={"device": "cpu"},
    )


def speaker_embedding(audio_path: Path) -> np.ndarray:
    import torch
    from scipy.io.wavfile import read
    from scipy.signal import resample_poly

    sample_rate, audio = read(audio_path)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if np.issubdtype(audio.dtype, np.integer):
        limit = max(abs(np.iinfo(audio.dtype).min), np.iinfo(audio.dtype).max)
        audio = audio.astype(np.float32) / float(limit)
    else:
        audio = audio.astype(np.float32)
    if sample_rate != 16_000:
        audio = resample_poly(audio, 16_000, sample_rate).astype(np.float32)
    waveform = torch.from_numpy(audio).unsqueeze(0)

    with torch.no_grad():
        encoded = _speaker_model().encode_batch(waveform, normalize=True)
    vector = encoded.squeeze().cpu().numpy().astype(np.float32)
    norm = np.linalg.norm(vector)
    if norm == 0:
        raise ValueError("Speaker embedding was empty")
    return vector / norm


def is_enrolled() -> bool:
    return VOICEPRINT_PATH.exists() and PROFILE_PATH.exists()


def enroll(samples: list[Path]) -> dict:
    if len(samples) < 3:
        raise ValueError("At least three voice samples are required")

    embeddings = np.stack([speaker_embedding(sample) for sample in samples])
    voiceprint = embeddings.mean(axis=0)
    voiceprint /= np.linalg.norm(voiceprint)

    similarities = embeddings @ voiceprint
    configured_threshold = float(os.getenv("SPEAKER_VERIFY_THRESHOLD", "0.30"))
    threshold = min(configured_threshold, float(similarities.min()) - 0.05)
    threshold = round(max(0.25, threshold), 4)

    PROFILE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    np.save(VOICEPRINT_PATH, voiceprint.astype(np.float32))
    profile = {
        "name": "Ashish",
        "sample_count": len(samples),
        "threshold": threshold,
        "minimum_enrollment_similarity": round(float(similarities.min()), 4),
        "average_enrollment_similarity": round(float(similarities.mean()), 4),
        "model": MODEL_SOURCE,
    }
    PROFILE_PATH.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return profile


def verify(audio_path: Path) -> VerificationResult:
    if not is_enrolled():
        raise RuntimeError("No speaker profile is enrolled")

    voiceprint = np.load(VOICEPRINT_PATH)
    candidate = speaker_embedding(audio_path)
    similarity = float(candidate @ voiceprint)
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    threshold = float(
        os.getenv(
            "SPEAKER_VERIFY_THRESHOLD",
            min(float(profile["threshold"]), 0.30),
        )
    )
    return VerificationResult(
        accepted=similarity >= threshold,
        similarity=round(similarity, 4),
        threshold=threshold,
    )
