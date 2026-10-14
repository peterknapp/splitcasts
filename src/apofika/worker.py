"""Process podcasts: detect chapters, write output feed, prune old files."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from apofika.chapters import Chapter, build_chapters, parse_topics, save_chapters_json
from apofika.config import public_base
from apofika.db import (
    Podcast,
    get_episode_by_guid,
    list_podcasts,
    list_snippets,
    list_split_episodes,
    mark_episode_purged,
    upsert_episode,
)
from apofika.detect import detect_jingles_multi
from apofika.embed import embed_chapters
from apofika.fetch import (
    EpisodeMeta,
    channel_meta,
    download_episode,
    parse_latest,
    safe_filename,
)
from apofika.paths import (
    MAX_KEEP_EPISODES,
    ensure_feed_dirs,
    feed_processed_dir,
    feed_raw_dir,
    feed_snippets_dir,
    feed_xml_path,
)
from apofika.rss import write_feed


@dataclass
class ProcessResult:
    skipped: bool
    guid: str
    title: str
    slug: str
    jingle_times: list[float] | None = None
    warnings: list[str] | None = None
    message: str = ""
    error: str | None = None


def _snippet_paths(podcast: Podcast) -> list[Path]:
    base = feed_snippets_dir(podcast.slug)
    return [base / s.filename for s in list_snippets(podcast.id)]


def rebuild_podcast_feed(podcast: Podcast, base_url: str | None = None) -> Path:
    from apofika.cover import placeholder_mp3_path, refresh_badged_cover

    ensure_feed_dirs(podcast.slug)
    base = (base_url or public_base()).rstrip("/")
    episodes_out: list[tuple[EpisodeMeta, Path, list[Chapter]]] = []
    source_image = podcast.image_url
    channel = {
        "title": f"{podcast.title} (Splitcasts)",
        "link": f"{base}/feeds/{podcast.slug}",
        "description": f"Kapitel-Version von {podcast.title}",
        "language": "de",
        "author": "Splitcasts",
        "image": None,
        "copyright": "",
    }

    for ep in list_split_episodes(podcast.id, limit=MAX_KEEP_EPISODES):
        if not ep.processed_path or not ep.chapters_json_path:
            continue
        mp3 = Path(ep.processed_path)
        chapters_file = Path(ep.chapters_json_path)
        if not mp3.exists() or not chapters_file.exists():
            continue
        data = json.loads(chapters_file.read_text(encoding="utf-8"))
        chapters = [Chapter(start=c["start"], title=c["title"]) for c in data["chapters"]]
        if data.get("image_url") and not source_image:
            source_image = data["image_url"]
        if data.get("author"):
            channel["author"] = data["author"]
        meta = EpisodeMeta(
            guid=ep.guid,
            title=ep.title,
            description=data.get("description") or "",
            summary=data.get("summary") or data.get("description") or "",
            link=data.get("link") or "",
            published=ep.published_at or data.get("published") or "",
            enclosure_url="",
            enclosure_type="audio/mpeg",
            enclosure_length=mp3.stat().st_size,
            duration=data.get("duration"),
            image_url=data.get("image_url"),
            author=data.get("author"),
            episode_number=data.get("episode_number"),
        )
        episodes_out.append((meta, mp3, chapters))

    # Overcast (and others) often reject feeds with zero <item>s — keep a silent stub.
    if not episodes_out:
        stub = placeholder_mp3_path(podcast.slug)
        if stub.exists():
            now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
            meta = EpisodeMeta(
                guid=f"splitcasts-placeholder-{podcast.slug}",
                title="Noch keine Folge — Splitcasts ist bereit",
                description=(
                    "Dieser Feed hat noch keine konvertierte Episode. "
                    "Sobald Splitcasts die erste Folge verarbeitet hat, erscheint sie hier."
                ),
                summary="Platzhalter, damit der Feed in Podcast-Apps abonnierbar ist.",
                link=channel["link"],
                published=now,
                enclosure_url="",
                enclosure_type="audio/mpeg",
                enclosure_length=stub.stat().st_size,
                duration=2,
                image_url=None,
                author="Splitcasts",
                episode_number=None,
            )
            episodes_out.append((meta, stub, [Chapter(start=0.0, title="Intro")]))

    cover = refresh_badged_cover(podcast.slug, source_image)
    if cover and cover.exists():
        channel["image"] = f"{base}/covers/{podcast.slug}.jpg"
    elif source_image:
        channel["image"] = source_image

    return _write_slug_feed(podcast.slug, channel, episodes_out, base)


def _write_slug_feed(
    slug: str,
    channel: dict,
    episodes: list[tuple[EpisodeMeta, Path, list[Chapter]]],
    base: str,
) -> Path:
    from apofika.rss import build_feed_xml, build_item_xml

    items: list[str] = []
    for meta, mp3_path, chapters in episodes:
        media_url = f"{base}/media/{slug}/{mp3_path.name}"
        items.append(build_item_xml(meta, media_url, mp3_path.stat().st_size, chapters))
    xml = build_feed_xml(channel, items, self_url=f"{base}/feeds/{slug}.xml")
    out = feed_xml_path(slug)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")
    return out


def prune_podcast(podcast: Podcast, keep: int = MAX_KEEP_EPISODES) -> int:
    """Keep newest `keep` split files; purge older files from disk."""
    kept = 0
    removed = 0
    for ep in list_split_episodes(podcast.id):
        if kept < keep:
            # verify files still exist
            ok = True
            if ep.processed_path and not Path(ep.processed_path).exists():
                ok = False
            if ok:
                kept += 1
                continue
        # remove files
        for path_str in (ep.processed_path, ep.chapters_json_path, ep.source_path):
            if not path_str:
                continue
            path = Path(path_str)
            if path.exists():
                path.unlink()
        mark_episode_purged(ep.id)
        removed += 1
    return removed


def process_podcast(
    podcast: Podcast,
    *,
    force: bool = False,
    threshold: float = 0.55,
    min_distance_sec: float = 60.0,
    base_url: str | None = None,
) -> ProcessResult:
    ensure_feed_dirs(podcast.slug)
    snippets = _snippet_paths(podcast)
    if not snippets:
        return ProcessResult(
            skipped=True,
            guid="",
            title="",
            slug=podcast.slug,
            message=f"No snippets for {podcast.slug}; upload jingle references first.",
            error="no_snippets",
        )

    try:
        meta, parsed = parse_latest(podcast.source_rss_url)
    except Exception as exc:
        return ProcessResult(
            skipped=True,
            guid="",
            title="",
            slug=podcast.slug,
            message=f"Failed to fetch source feed: {exc}",
            error=str(exc),
        )

    existing = get_episode_by_guid(podcast.id, meta.guid)
    if (
        existing
        and existing.status == "split"
        and not force
        and existing.processed_path
        and Path(existing.processed_path).exists()
    ):
        rebuild_podcast_feed(podcast, base_url=base_url)
        return ProcessResult(
            skipped=True,
            guid=meta.guid,
            title=meta.title,
            slug=podcast.slug,
            message=f"Already split: {meta.title}",
        )

    upsert_episode(
        podcast.id,
        meta.guid,
        meta.title,
        meta.published or None,
        status="processing",
    )

    try:
        raw_dir = feed_raw_dir(podcast.slug)
        processed_dir = feed_processed_dir(podcast.slug)
        raw_path = download_episode(meta, dest_dir=raw_dir)
        detection = detect_jingles_multi(
            raw_path,
            snippets,
            threshold=threshold,
            min_distance_sec=min_distance_sec,
        )
        topics = parse_topics(meta.description or meta.summary)
        chapters, warnings = build_chapters(topics, detection.times())

        stem = safe_filename(meta.guid)
        processed_path = processed_dir / f"{stem}.mp3"
        chapters_path = processed_dir / f"{stem}.chapters.json"
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
                "channel": channel_meta(parsed),
            },
        )

        now = datetime.now(timezone.utc).isoformat()
        upsert_episode(
            podcast.id,
            meta.guid,
            meta.title,
            meta.published or None,
            status="split",
            source_path=str(raw_path),
            processed_path=str(processed_path),
            chapters_json_path=str(chapters_path),
            processed_at=now,
        )
        prune_podcast(podcast)
        rebuild_podcast_feed(podcast, base_url=base_url)
        return ProcessResult(
            skipped=False,
            guid=meta.guid,
            title=meta.title,
            slug=podcast.slug,
            jingle_times=detection.times(),
            warnings=warnings,
            message=(
                f"Processed '{meta.title}' with {len(chapters)} chapters "
                f"({len(detection.hits)} jingle hits)."
            ),
        )
    except Exception as exc:
        upsert_episode(
            podcast.id,
            meta.guid,
            meta.title,
            meta.published or None,
            status="error",
            error_message=str(exc),
        )
        return ProcessResult(
            skipped=False,
            guid=meta.guid,
            title=meta.title,
            slug=podcast.slug,
            message=f"Error processing '{meta.title}': {exc}",
            error=str(exc),
        )


def process_all(*, force: bool = False, base_url: str | None = None) -> list[ProcessResult]:
    results: list[ProcessResult] = []
    for podcast in list_podcasts(active_only=True):
        results.append(process_podcast(podcast, force=force, base_url=base_url))
    return results


def migrate_apofika_legacy() -> Podcast | None:
    """Create ApoFiKa podcast and move legacy files if present."""
    from apofika.db import create_podcast, get_podcast_by_slug, init_db, update_podcast_image
    from apofika.fetch import channel_meta, fetch_parsed
    from apofika.paths import (
        JINGLE_REF_PATH,
        PROCESSED_DIR,
        RAW_DIR,
        SOURCE_FEED_URL,
    )

    init_db()
    image_url = None
    try:
        image_url = channel_meta(fetch_parsed(SOURCE_FEED_URL)).get("image")
    except Exception:
        image_url = None

    existing = get_podcast_by_slug("apofika")
    if existing is None:
        podcast = create_podcast(
            slug="apofika",
            title="Apokalypse & Filterkaffee",
            source_rss_url=SOURCE_FEED_URL,
            image_url=image_url,
        )
    else:
        podcast = existing
        if image_url and not podcast.image_url:
            update_podcast_image(podcast.id, image_url)
            podcast.image_url = image_url

    ensure_feed_dirs(podcast.slug)
    snippets_dir = feed_snippets_dir(podcast.slug)
    if JINGLE_REF_PATH.exists() and not list(snippets_dir.glob("*")):
        dest = snippets_dir / "snippet1.wav"
        shutil.copy2(JINGLE_REF_PATH, dest)
        from apofika.db import upsert_snippet

        upsert_snippet(podcast.id, 1, dest.name)

    # Import already processed files
    for chapters_file in PROCESSED_DIR.glob("*.chapters.json"):
        data = json.loads(chapters_file.read_text(encoding="utf-8"))
        stem = chapters_file.name.removesuffix(".chapters.json")
        guid = data.get("guid") or stem
        mp3 = PROCESSED_DIR / f"{stem}.mp3"
        if not mp3.exists():
            continue
        target_mp3 = feed_processed_dir(podcast.slug) / mp3.name
        target_json = feed_processed_dir(podcast.slug) / chapters_file.name
        if not target_mp3.exists():
            shutil.copy2(mp3, target_mp3)
        if not target_json.exists():
            shutil.copy2(chapters_file, target_json)
        raw = RAW_DIR / f"{stem}.mp3"
        raw_target = None
        if raw.exists():
            raw_target = feed_raw_dir(podcast.slug) / raw.name
            if not raw_target.exists():
                shutil.copy2(raw, raw_target)
        upsert_episode(
            podcast.id,
            guid,
            data.get("title") or stem,
            data.get("published"),
            status="split",
            source_path=str(raw_target) if raw_target else None,
            processed_path=str(target_mp3),
            chapters_json_path=str(target_json),
            processed_at=datetime.now(timezone.utc).isoformat(),
        )

    prune_podcast(podcast)
    rebuild_podcast_feed(podcast)
    return podcast
