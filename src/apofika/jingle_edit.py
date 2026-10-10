"""Extract short jingle clips from episode audio for snippet slots."""

from __future__ import annotations

import io
from pathlib import Path

import librosa
import soundfile as sf

from apofika.db import Podcast, delete_snippet, upsert_snippet
from apofika.detect import SAMPLE_RATE, extract_jingle, parse_timestamp
from apofika.fetch import EpisodeMeta, download_episode, parse_recent, safe_filename
from apofika.paths import (
    UI_RECENT_EPISODES,
    ensure_feed_dirs,
    feed_raw_dir,
    feed_snippets_dir,
)

MAX_CLIP_SEC = 10.0
MIN_CLIP_SEC = 0.5


def resolve_episode_meta(podcast: Podcast, guid: str) -> EpisodeMeta:
    items, _ = parse_recent(podcast.source_rss_url, limit=UI_RECENT_EPISODES)
    for meta in items:
        if meta.guid == guid:
            return meta
    # Also allow already-downloaded raw files beyond the UI window
    raw = feed_raw_dir(podcast.slug) / f"{safe_filename(guid)}.mp3"
    if raw.exists():
        return EpisodeMeta(
            guid=guid,
            title=raw.stem,
            description="",
            summary="",
            link="",
            published="",
            enclosure_url="",
            enclosure_type="audio/mpeg",
            enclosure_length=raw.stat().st_size,
            duration=None,
            image_url=None,
            author=None,
            episode_number=None,
        )
    raise ValueError("Episode nicht in den letzten Folgen gefunden.")


def ensure_episode_audio(podcast: Podcast, guid: str) -> Path:
    ensure_feed_dirs(podcast.slug)
    raw_dir = feed_raw_dir(podcast.slug)
    existing = raw_dir / f"{safe_filename(guid)}.mp3"
    if existing.exists() and existing.stat().st_size > 0:
        return existing
    meta = resolve_episode_meta(podcast, guid)
    if not meta.enclosure_url:
        raise ValueError("Keine Audio-URL für diese Episode.")
    return download_episode(meta, dest_dir=raw_dir)


def _clip_params(start: str, duration: float) -> tuple[float, float]:
    start_sec = parse_timestamp(start)
    if start_sec < 0:
        raise ValueError("Startzeit darf nicht negativ sein.")
    dur = float(duration)
    if dur < MIN_CLIP_SEC or dur > MAX_CLIP_SEC:
        raise ValueError(f"Dauer muss zwischen {MIN_CLIP_SEC} und {MAX_CLIP_SEC} Sekunden liegen.")
    return start_sec, dur


def render_clip_wav_bytes(source_mp3: Path, start: str, duration: float) -> bytes:
    start_sec, dur = _clip_params(start, duration)
    y, _ = librosa.load(
        str(source_mp3),
        sr=SAMPLE_RATE,
        mono=True,
        offset=start_sec,
        duration=dur,
    )
    if y.size == 0:
        raise ValueError("Ausschnitt ist leer — Startzeit prüfen.")
    buf = io.BytesIO()
    sf.write(buf, y, SAMPLE_RATE, format="WAV")
    return buf.getvalue()


def save_clip_to_slot(
    podcast: Podcast,
    guid: str,
    start: str,
    duration: float,
    position: int,
) -> Path:
    if position < 1 or position > 3:
        raise ValueError("Slot muss 1–3 sein.")
    start_sec, dur = _clip_params(start, duration)
    source = ensure_episode_audio(podcast, guid)
    ensure_feed_dirs(podcast.slug)
    dest_name = f"snippet{position}.wav"
    dest = feed_snippets_dir(podcast.slug) / dest_name

    old = delete_snippet(podcast.id, position)
    if old:
        old_path = feed_snippets_dir(podcast.slug) / old
        if old_path.exists() and old_path != dest:
            old_path.unlink()

    extract_jingle(source, start_sec=start_sec, duration_sec=dur, dest=dest)
    upsert_snippet(podcast.id, position, dest_name)
    return dest
