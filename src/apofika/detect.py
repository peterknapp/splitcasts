"""Detect recurring jingle timestamps via template matching."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from mutagen.mp3 import MP3
from scipy.signal import fftconvolve, find_peaks

from apofika.paths import JINGLE_REF_PATH

SAMPLE_RATE = 16_000
# ~5 minutes per chunk — keeps peak RAM low on Raspberry Pi 3B
CHUNK_SEC = 300.0
# Floor while scanning so soft-fallback still has candidates without storing every sample
SCAN_FLOOR = 0.35


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


def _normalize_audio(y: np.ndarray) -> np.ndarray:
    y = y.astype(np.float32, copy=False)
    y = y - float(np.mean(y))
    peak = float(np.max(np.abs(y))) or 1.0
    return (y / peak).astype(np.float32)


def _load_mono(path: Path) -> np.ndarray:
    y, _ = librosa.load(str(path), sr=SAMPLE_RATE, mono=True)
    if y.size == 0:
        raise ValueError(f"Empty audio: {path}")
    return _normalize_audio(y)


def _prepare_template(template: np.ndarray) -> np.ndarray:
    tmpl = template.astype(np.float32, copy=False)
    tmpl = tmpl - float(np.mean(tmpl))
    tmpl_norm = float(np.sqrt(np.sum(tmpl * tmpl))) or 1.0
    return (tmpl / tmpl_norm).astype(np.float32)


def _normalized_cross_correlation(signal: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Return NCC scores along the signal (same length as signal - template + 1)."""
    tmpl = _prepare_template(template)
    sig = signal.astype(np.float32, copy=False)
    corr = fftconvolve(sig, tmpl[::-1], mode="valid").astype(np.float32, copy=False)
    window = np.ones(len(tmpl), dtype=np.float32)
    local_energy = np.convolve(sig * sig, window, mode="valid").astype(np.float32, copy=False)
    local_norm = np.sqrt(np.maximum(local_energy, 1e-12))
    return (corr / local_norm).astype(np.float32)


def _audio_duration_sec(path: Path) -> float:
    try:
        return float(MP3(path).info.length)
    except Exception:
        return float(librosa.get_duration(path=str(path)))


def _scan_chunk_candidates(
    episode_path: Path,
    template: np.ndarray,
    threshold: float,
) -> list[JingleHit]:
    """
    Stream the episode in overlapping chunks and collect threshold candidates.
    Avoids holding the full episode + full score array in RAM (Pi 3B friendly).
    """
    tmpl_len = len(template)
    overlap_sec = tmpl_len / SAMPLE_RATE
    hop_sec = max(60.0, CHUNK_SEC - overlap_sec)
    duration = _audio_duration_sec(episode_path)
    floor = min(threshold, SCAN_FLOOR)
    # local peak spacing inside a chunk (~5s) — final min_distance applied later
    local_distance = max(1, int(5.0 * SAMPLE_RATE))
    candidates: list[JingleHit] = []

    offset = 0.0
    while offset < duration:
        load_dur = min(CHUNK_SEC, max(0.0, duration - offset) + overlap_sec)
        if load_dur <= 0:
            break
        y, _ = librosa.load(
            str(episode_path),
            sr=SAMPLE_RATE,
            mono=True,
            offset=offset,
            duration=load_dur,
        )
        if y.size < tmpl_len:
            break
        y = _normalize_audio(y)
        scores = _normalized_cross_correlation(y, template)

        next_offset = offset + hop_sec
        if next_offset < duration:
            keep_samples = int(hop_sec * SAMPLE_RATE)
            scores = scores[: max(1, keep_samples)]

        peak_idxs, _ = find_peaks(scores, height=floor, distance=local_distance)
        if peak_idxs.size == 0 and scores.size:
            peak_idxs = np.array([int(np.argmax(scores))], dtype=int)

        for idx in peak_idxs.tolist():
            candidates.append(
                JingleHit(
                    time_sec=round(offset + idx / SAMPLE_RATE, 3),
                    score=round(float(scores[idx]), 4),
                )
            )

        del y, scores
        offset = next_offset

    return candidates


def _pick_peaks_from_candidates(
    candidates: list[JingleHit],
    threshold: float,
    min_distance_sec: float,
) -> list[JingleHit]:
    if not candidates:
        return []

    above = [c for c in candidates if c.score >= threshold]
    if not above:
        max_score = max(c.score for c in candidates)
        soft = max(threshold * 0.85, max_score * 0.55)
        above = [c for c in candidates if c.score >= soft]

    ranked = sorted(above, key=lambda c: c.score, reverse=True)
    hits: list[JingleHit] = []
    for cand in ranked:
        if any(abs(cand.time_sec - h.time_sec) < min_distance_sec for h in hits):
            continue
        hits.append(cand)
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

    template = _load_mono(jingle_path)
    candidates = _scan_chunk_candidates(episode_path, template, threshold=threshold)
    hits = _pick_peaks_from_candidates(
        candidates,
        threshold=threshold,
        min_distance_sec=min_distance_sec,
    )
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
