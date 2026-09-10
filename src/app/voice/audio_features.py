from pathlib import Path

import numpy as np
from scipy.fft import dct
from scipy.io.wavfile import read
from scipy.signal import resample_poly, stft
from scipy.spatial.distance import cdist


TARGET_SAMPLE_RATE = 16_000


def load_mono_audio(path: Path) -> np.ndarray:
    sample_rate, audio = read(path)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    if np.issubdtype(audio.dtype, np.integer):
        scale = max(abs(np.iinfo(audio.dtype).min), np.iinfo(audio.dtype).max)
        audio = audio.astype(np.float32) / float(scale)
    else:
        audio = audio.astype(np.float32)

    if sample_rate != TARGET_SAMPLE_RATE:
        audio = resample_poly(audio, TARGET_SAMPLE_RATE, sample_rate).astype(np.float32)
    return audio


def _trim_silence(audio: np.ndarray) -> np.ndarray:
    frame_size = int(0.025 * TARGET_SAMPLE_RATE)
    hop_size = int(0.010 * TARGET_SAMPLE_RATE)
    if len(audio) < frame_size:
        return audio

    starts = range(0, len(audio) - frame_size + 1, hop_size)
    rms = np.array(
        [np.sqrt(np.mean(audio[start : start + frame_size] ** 2)) for start in starts]
    )
    threshold = max(0.004, float(np.percentile(rms, 20)) * 2.5, float(rms.max()) * 0.06)
    active = np.flatnonzero(rms >= threshold)
    if active.size == 0:
        return audio

    padding = int(0.12 * TARGET_SAMPLE_RATE)
    start = max(0, int(active[0] * hop_size) - padding)
    end = min(
        len(audio),
        int(active[-1] * hop_size) + frame_size + padding,
    )
    return audio[start:end]


def _mel_frequency(value: np.ndarray | float) -> np.ndarray | float:
    return 2595.0 * np.log10(1.0 + np.asarray(value) / 700.0)


def _hertz_frequency(value: np.ndarray | float) -> np.ndarray | float:
    return 700.0 * (10 ** (np.asarray(value) / 2595.0) - 1.0)


def _mel_filterbank(fft_size: int, filter_count: int = 26) -> np.ndarray:
    minimum_mel = _mel_frequency(80.0)
    maximum_mel = _mel_frequency(TARGET_SAMPLE_RATE / 2)
    mel_points = np.linspace(minimum_mel, maximum_mel, filter_count + 2)
    hertz_points = _hertz_frequency(mel_points)
    bins = np.floor((fft_size + 1) * hertz_points / TARGET_SAMPLE_RATE).astype(int)
    maximum_bin = fft_size // 2
    bins = np.clip(bins, 0, maximum_bin)

    filters = np.zeros((filter_count, maximum_bin + 1), dtype=np.float32)
    for index in range(1, filter_count + 1):
        left, center, right = bins[index - 1 : index + 2]
        if center > left:
            filters[index - 1, left:center] = np.linspace(
                0.0, 1.0, center - left, endpoint=False
            )
        if right > center:
            filters[index - 1, center:right] = np.linspace(
                1.0, 0.0, right - center, endpoint=False
            )
    return filters


def extract_mfcc(path: Path) -> np.ndarray:
    """Return normalized MFCC and delta features for template matching."""
    audio = _trim_silence(load_mono_audio(path))
    if len(audio) < int(0.25 * TARGET_SAMPLE_RATE):
        raise ValueError(f"Wake-word sample is too short: {path}")

    emphasized = np.append(audio[0], audio[1:] - 0.97 * audio[:-1])
    _, _, spectrum = stft(
        emphasized,
        fs=TARGET_SAMPLE_RATE,
        window="hann",
        nperseg=400,
        noverlap=240,
        nfft=512,
        boundary=None,
        padded=False,
    )
    power = np.abs(spectrum) ** 2
    mel_energy = _mel_filterbank(512) @ power
    log_mel = np.log(np.maximum(mel_energy, 1e-10))
    coefficients = dct(log_mel, type=2, axis=0, norm="ortho")[:13].T
    delta = np.gradient(coefficients, axis=0)
    features = np.concatenate([coefficients, delta], axis=1).astype(np.float32)
    return (features - features.mean(axis=0)) / (features.std(axis=0) + 1e-6)


def dtw_distance(first: np.ndarray, second: np.ndarray) -> float:
    """Return length-normalized dynamic-time-warping distance."""
    local_cost = cdist(first, second, metric="euclidean") / np.sqrt(first.shape[1])
    rows, columns = local_cost.shape
    costs = np.full((rows + 1, columns + 1), np.inf, dtype=np.float32)
    steps = np.zeros((rows + 1, columns + 1), dtype=np.int32)
    costs[0, 0] = 0.0

    for row in range(1, rows + 1):
        for column in range(1, columns + 1):
            choices = (
                (costs[row - 1, column], steps[row - 1, column]),
                (costs[row, column - 1], steps[row, column - 1]),
                (costs[row - 1, column - 1], steps[row - 1, column - 1]),
            )
            previous_cost, previous_steps = min(choices, key=lambda item: item[0])
            costs[row, column] = local_cost[row - 1, column - 1] + previous_cost
            steps[row, column] = previous_steps + 1

    return float(costs[rows, columns] / max(1, steps[rows, columns]))
