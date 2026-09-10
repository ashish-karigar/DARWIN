import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.voice.audio_features import dtw_distance, extract_mfcc
from app.voice.speaker_identity import VerificationResult, speaker_embedding


SUPPORTED_WAKE_PHRASES = (
    "DARWIN",
    "Hey DARWIN",
    "Hello DARWIN",
    "Hi DARWIN",
    "What's up DARWIN",
    "Good morning DARWIN",
    "Good afternoon DARWIN",
    "Good evening DARWIN",
)
SPOKEN_NAME_ALIASES = (
    "darwin",
    "darwen",
    "darvin",
)
WAKE_PROFILE_DIRECTORY = Path("data/voice_profiles/ashish/darwin_wake_word")
WAKE_SAMPLES_DIRECTORY = WAKE_PROFILE_DIRECTORY / "samples"
WAKE_PROFILE_PATH = WAKE_PROFILE_DIRECTORY / "profile.json"
WAKE_TEMPLATES_PATH = WAKE_PROFILE_DIRECTORY / "templates.npz"
WAKE_VOICEPRINT_PATH = WAKE_PROFILE_DIRECTORY / "voiceprint.npy"


@dataclass(frozen=True)
class WakeWordResult:
    accepted: bool
    phrase_accepted: bool
    phrase_distance: float
    phrase_threshold: float
    speaker: VerificationResult


def is_personalized_wake_word_enrolled() -> bool:
    return all(
        path.is_file()
        for path in (WAKE_PROFILE_PATH, WAKE_TEMPLATES_PATH, WAKE_VOICEPRINT_PATH)
    )


def transcript_contains_darwin(transcript: str) -> bool:
    """Validate that local transcription contains DARWIN or a known rendering."""
    aliases = "|".join(re.escape(alias) for alias in SPOKEN_NAME_ALIASES)
    return re.search(rf"\b(?:{aliases})\b", transcript, re.IGNORECASE) is not None


@lru_cache(maxsize=1)
def _load_profile() -> tuple[dict, list[np.ndarray]]:
    if not is_personalized_wake_word_enrolled():
        raise RuntimeError(
            "Personalized wake word missing. Run: python -m app.voice.enroll_wake_word"
        )
    profile = json.loads(WAKE_PROFILE_PATH.read_text(encoding="utf-8"))
    stored = np.load(WAKE_TEMPLATES_PATH)
    templates = [stored[key] for key in sorted(stored.files)]
    return profile, templates


def enroll_personalized_wake_word(
    sample_paths: list[Path],
    sample_phrases: list[str],
) -> dict:
    if len(sample_paths) < 5:
        raise ValueError("At least five wake-word samples are required.")
    if len(sample_paths) != len(sample_phrases):
        raise ValueError("Every wake-word sample must have a phrase label.")

    templates = [extract_mfcc(path) for path in sample_paths]
    speaker_embeddings = np.stack(
        [speaker_embedding(path) for path in sample_paths]
    )
    nearest_distances = []
    for index, template in enumerate(templates):
        alternatives = [
            dtw_distance(template, other)
            for other_index, other in enumerate(templates)
            if other_index != index
        ]
        nearest_distances.append(min(alternatives))

    threshold = float(np.percentile(nearest_distances, 90)) * 1.10
    threshold = round(threshold, 4)

    wake_voiceprint = speaker_embeddings.mean(axis=0)
    wake_voiceprint /= np.linalg.norm(wake_voiceprint)
    wake_similarities = speaker_embeddings @ wake_voiceprint
    leave_one_out_similarities = []
    for index, embedding in enumerate(speaker_embeddings):
        comparison = np.delete(speaker_embeddings, index, axis=0).mean(axis=0)
        comparison /= np.linalg.norm(comparison)
        leave_one_out_similarities.append(float(embedding @ comparison))
    speaker_threshold = min(leave_one_out_similarities) - 0.05
    speaker_threshold = round(float(np.clip(speaker_threshold, 0.40, 0.60)), 4)

    WAKE_PROFILE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        WAKE_TEMPLATES_PATH,
        **{f"template_{index:02d}": value for index, value in enumerate(templates)},
    )
    np.save(WAKE_VOICEPRINT_PATH, wake_voiceprint.astype(np.float32))
    profile = {
        "phrases": list(SUPPORTED_WAKE_PHRASES),
        "sample_phrases": sample_phrases,
        "sample_count": len(templates),
        "distance_threshold": threshold,
        "average_nearest_distance": round(float(np.mean(nearest_distances)), 4),
        "maximum_nearest_distance": round(float(max(nearest_distances)), 4),
        "wake_speaker_threshold": speaker_threshold,
        "average_wake_speaker_similarity": round(
            float(np.mean(wake_similarities)), 4
        ),
        "minimum_wake_speaker_similarity": round(float(wake_similarities.min()), 4),
        "speaker_verification_required": True,
        "feature_type": "MFCC plus delta with DTW",
    }
    WAKE_PROFILE_PATH.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    _load_profile.cache_clear()
    return profile


def evaluate_wake_word(audio_path: Path) -> WakeWordResult:
    profile, templates = _load_profile()
    candidate = extract_mfcc(audio_path)
    distance = min(dtw_distance(candidate, template) for template in templates)
    threshold = float(profile["distance_threshold"])
    phrase_accepted = distance <= threshold
    wake_voiceprint = np.load(WAKE_VOICEPRINT_PATH)
    candidate_embedding = speaker_embedding(audio_path)
    speaker_similarity = float(candidate_embedding @ wake_voiceprint)
    speaker_threshold = float(profile["wake_speaker_threshold"])
    speaker_result = VerificationResult(
        accepted=speaker_similarity >= speaker_threshold,
        similarity=round(speaker_similarity, 4),
        threshold=speaker_threshold,
    )
    return WakeWordResult(
        accepted=phrase_accepted and speaker_result.accepted,
        phrase_accepted=phrase_accepted,
        phrase_distance=round(distance, 4),
        phrase_threshold=threshold,
        speaker=speaker_result,
    )
