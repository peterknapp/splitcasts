"""Detect recurring jingle timestamps via template matching."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve

from apofika.paths import JINGLE_REF_PATH

SAMPLE_RATE = 16_000


@dataclass
class JingleHit:
    time_sec: float
    score: float


@dataclass
class DetectionResult:
    hits: list[JingleHit]
    threshold: float
    min_distance_sec: float

    def times(self) -> list[float]:
        return [h.time_sec for h in self.hits]

    def to_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "min_distance_sec": self.min_distance_sec,
            "hits": [asdict(h) for h in self.hits],
        }


def extract_jingle(
    source_mp3: Path,
    start_sec: float,
    duration_sec: float = 3.0,
    dest: Path = JINGLE_REF_PATH,
) -> Path:
    """Extract a short reference clip from an episode."""
    y, _ = librosa.load(
        str(source_mp3),
        sr=SAMPLE_RATE,
        mono=True,
        offset=max(0.0, start_sec),
        duration=duration_sec,
    )
    if y.size == 0:
        raise ValueError("Extracted jingle is empty — check start/duration")
    dest.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dest), y, SAMPLE_RATE)
    return dest


def _load_mono(path: Path) -> np.ndarray:
    y, _ = librosa.load(str(path), sr=SAMPLE_RATE, mono=True)
    if y.size == 0:
        raise ValueError(f"Empty audio: {path}")
    # zero-mean, unit-ish peak normalize for stabler correlation
    y = y - float(np.mean(y))
    peak = float(np.max(np.abs(y))) or 1.0
    return (y / peak).astype(np.float32)


def _normalized_cross_correlation(signal: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Return NCC scores along the signal (same length as signal - template + 1)."""
    tmpl = template.astype(np.float64) - float(np.mean(template))
    tmpl_norm = float(np.sqrt(np.sum(tmpl * tmpl))) or 1.0
    tmpl = tmpl / tmpl_norm

    sig = signal.astype(np.float64)
    # correlation via FFT convolution with time-reversed template
    corr = fftconvolve(sig, tmpl[::-1], mode="valid")

    window = np.ones(len(tmpl), dtype=np.float64)
    local_energy = np.convolve(sig * sig, window, mode="valid")
    local_norm = np.sqrt(np.maximum(local_energy, 1e-12))
    return (corr / local_norm).astype(np.float64)


def _pick_peaks(
    scores: np.ndarray,
    sr: int,
    threshold: float,
    min_distance_sec: float,
) -> list[JingleHit]:
    min_distance = max(1, int(min_distance_sec * sr))
    candidates = np.where(scores >= threshold)[0]
    if candidates.size == 0:
        # fall back to top absolute peaks above a softer relative threshold
        soft = max(threshold * 0.85, float(np.max(scores)) * 0.55)
        candidates = np.where(scores >= soft)[0]

    hits: list[JingleHit] = []
    # greedily take highest remaining peaks with distance constraint
    ranked = sorted(candidates.tolist(), key=lambda i: float(scores[i]), reverse=True)
    taken: list[int] = []
    for idx in ranked:
        if any(abs(idx - t) < min_distance for t in taken):
            continue
        taken.append(idx)
        hits.append(JingleHit(time_sec=round(idx / sr, 3), score=round(float(scores[idx]), 4)))

    hits.sort(key=lambda h: h.time_sec)
    return hits


def detect_jingles(
    episode_path: Path,
    jingle_path: Path = JINGLE_REF_PATH,
    threshold: float = 0.55,
    min_distance_sec: float = 60.0,
) -> DetectionResult:
    if not jingle_path.exists():
        raise FileNotFoundError(
            f"Jingle reference missing: {jingle_path}. "
            "Run `apofika extract-jingle` first."
        )

    signal = _load_mono(episode_path)
    template = _load_mono(jingle_path)
    if len(template) >= len(signal):
        raise ValueError("Jingle reference is longer than the episode")

    scores = _normalized_cross_correlation(signal, template)
    hits = _pick_peaks(scores, SAMPLE_RATE, threshold=threshold, min_distance_sec=min_distance_sec)
    return DetectionResult(hits=hits, threshold=threshold, min_distance_sec=min_distance_sec)


def parse_timestamp(text: str) -> float:
    """Parse MM:SS or HH:MM:SS or raw seconds into float seconds."""
    text = text.strip()
    if ":" not in text:
        return float(text)
    parts = [float(p) for p in text.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"Invalid timestamp: {text}")
