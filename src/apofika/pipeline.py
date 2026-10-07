"""End-to-end process pipeline for the latest episode."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from apofika.chapters import build_chapters, parse_topics, save_chapters_json
from apofika.detect import detect_jingles
from apofika.embed import embed_chapters
from apofika.fetch import (
    EpisodeMeta,
    channel_meta,
    download_episode,
    parse_latest,
    safe_filename,
)
from apofika.paths import (
    FEED_PATH,
    JINGLE_REF_PATH,
    PROCESSED_DIR,
    SOURCE_FEED_URL,
    ensure_dirs,
)
from apofika.rss import write_feed
from apofika.state import AppState, EpisodeRecord, load_state, save_state


@dataclass
class ProcessResult:
    skipped: bool
    guid: str
    title: str
    raw_path: Path | None = None
    processed_path: Path | None = None
    chapters_path: Path | None = None
    jingle_times: list[float] | None = None
    warnings: list[str] | None = None
    message: str = ""


def rebuild_feed_from_state(
    state: AppState,
    channel: dict,
    public_base: str | None,
    meta_by_guid: dict[str, EpisodeMeta] | None = None,
) -> Path:
    episodes: list[tuple[EpisodeMeta, Path, list]] = []
    meta_by_guid = meta_by_guid or {}
    for rec in state.episodes:
        processed = PROCESSED_DIR / Path(rec["processed_file"]).name
        chapters_file = Path(rec["chapters_file"])
        if not processed.exists() or not chapters_file.exists():
            continue
        data = json.loads(chapters_file.read_text(encoding="utf-8"))
        from apofika.chapters import Chapter

        chapters = [Chapter(start=c["start"], title=c["title"]) for c in data["chapters"]]
        meta = meta_by_guid.get(rec["guid"])
        if meta is None:
            meta = EpisodeMeta(
                guid=rec["guid"],
                title=rec.get("title") or processed.stem,
                description=data.get("description") or "",
                summary=data.get("description") or "",
                link=data.get("link") or "",
                published=rec.get("published") or data.get("published") or "",
                enclosure_url="",
                enclosure_type="audio/mpeg",
                enclosure_length=processed.stat().st_size,
                duration=data.get("duration"),
                image_url=data.get("image_url"),
                author=data.get("author"),
                episode_number=data.get("episode_number"),
            )
        episodes.append((meta, processed, chapters))
    return write_feed(channel, episodes, public_base=public_base, feed_path=FEED_PATH)


def process_latest(
    feed_url: str = SOURCE_FEED_URL,
    force: bool = False,
    threshold: float = 0.55,
    min_distance_sec: float = 60.0,
    public_base: str | None = None,
    jingle_path: Path = JINGLE_REF_PATH,
) -> ProcessResult:
    ensure_dirs()
    state = load_state()
    meta, parsed = parse_latest(feed_url)
    channel = channel_meta(parsed)

    if state.has_guid(meta.guid) and not force:
        rebuild_feed_from_state(state, channel, public_base, {meta.guid: meta})
        return ProcessResult(
            skipped=True,
            guid=meta.guid,
            title=meta.title,
            message=f"Already processed guid={meta.guid}. Use --force to reprocess.",
        )

    raw_path = download_episode(meta)
    detection = detect_jingles(
        raw_path,
        jingle_path=jingle_path,
        threshold=threshold,
        min_distance_sec=min_distance_sec,
    )
    topics = parse_topics(meta.description or meta.summary)
    chapters, warnings = build_chapters(topics, detection.times())

    stem = safe_filename(meta.guid)
    processed_path = PROCESSED_DIR / f"{stem}.mp3"
    chapters_path = PROCESSED_DIR / f"{stem}.chapters.json"

    embed_chapters(raw_path, processed_path, chapters, duration_sec=meta.duration)
    save_chapters_json(
        chapters,
        chapters_path,
        extra={
            "guid": meta.guid,
            "title": meta.title,
            "topics": topics,
            "detection": detection.to_dict(),
            "warnings": warnings,
            "description": meta.description,
            "summary": meta.summary,
            "link": meta.link,
            "published": meta.published,
            "duration": meta.duration,
            "image_url": meta.image_url,
            "author": meta.author,
            "episode_number": meta.episode_number,
        },
    )

    record = EpisodeRecord(
        guid=meta.guid,
        title=meta.title,
        processed_file=str(processed_path.name),
        chapters_file=str(chapters_path),
        published=meta.published or None,
    )
    state.add_episode(record)
    save_state(state)
    rebuild_feed_from_state(state, channel, public_base, {meta.guid: meta})

    return ProcessResult(
        skipped=False,
        guid=meta.guid,
        title=meta.title,
        raw_path=raw_path,
        processed_path=processed_path,
        chapters_path=chapters_path,
        jingle_times=detection.times(),
        warnings=warnings,
        message=f"Processed '{meta.title}' with {len(chapters)} chapters "
        f"({len(detection.hits)} jingle hits).",
    )
