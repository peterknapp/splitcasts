"""Global conversion queue: scan co-published episodes, process one-by-one."""

from __future__ import annotations

from pathlib import Path

from apofika.db import (
    Podcast,
    enqueue_job,
    get_episode_by_guid,
    list_podcasts,
    list_queue_jobs,
    queue_counts,
)
from apofika.fetch import EpisodeMeta, parse_recent
from apofika.formatting import parse_timestamp
from apofika.paths import CO_PUBLISH_WINDOW_SEC, UI_RECENT_EPISODES


def _already_split(podcast_id: int, guid: str) -> bool:
    ep = get_episode_by_guid(podcast_id, guid)
    return bool(
        ep
        and ep.status == "split"
        and ep.processed_path
        and Path(ep.processed_path).exists()
    )


def _within_window(anchor: EpisodeMeta, candidate: EpisodeMeta, window_sec: float) -> bool:
    a = parse_timestamp(anchor.published)
    c = parse_timestamp(candidate.published)
    if a is None or c is None:
        # If we cannot parse dates, only keep the RSS-newest item (index handled by caller).
        return candidate.guid == anchor.guid
    return abs((a - c).total_seconds()) <= window_sec


def select_copublish_batch(
    items: list[EpisodeMeta],
    *,
    window_sec: float = CO_PUBLISH_WINDOW_SEC,
) -> list[EpisodeMeta]:
    """
    From recent RSS items (newest first), keep the newest cluster only.

    Does **not** pull in older unsplit catalog entries that merely appear in
    the "last 5" list.
    """
    if not items:
        return []
    anchor = items[0]
    return [it for it in items if _within_window(anchor, it, window_sec)]


def enqueue_podcast_scan(
    podcast: Podcast,
    *,
    force_guid: str | None = None,
    force_all_in_batch: bool = False,
    window_sec: float = CO_PUBLISH_WINDOW_SEC,
) -> list[str]:
    """
    Fetch recent RSS items and enqueue work.

    - Auto: unsplit episodes in the co-publish window of the newest item.
    - force_guid: enqueue that episode even if already split.
    - force_all_in_batch: enqueue every episode in the co-publish window (force).
    """
    items, _ = parse_recent(podcast.source_rss_url, limit=UI_RECENT_EPISODES)
    if not items:
        return []

    batch = select_copublish_batch(items, window_sec=window_sec)
    enqueued: list[str] = []

    if force_guid:
        match = next((it for it in items if it.guid == force_guid), None)
        if match is None:
            # Still allow queueing by guid/title from UI if RSS briefly fails match
            job = enqueue_job(podcast.id, force_guid, force_guid, force=True)
            if job:
                enqueued.append(force_guid)
            return enqueued
        job = enqueue_job(podcast.id, match.guid, match.title, force=True)
        if job:
            enqueued.append(match.guid)
        return enqueued

    for meta in batch:
        force = force_all_in_batch
        if not force and _already_split(podcast.id, meta.guid):
            continue
        job = enqueue_job(podcast.id, meta.guid, meta.title, force=force)
        if job:
            enqueued.append(meta.guid)
    return enqueued


def enqueue_all_active_scans() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for podcast in list_podcasts(active_only=True):
        try:
            guids = enqueue_podcast_scan(podcast)
        except Exception as exc:  # noqa: BLE001
            result[podcast.slug] = [f"error:{exc}"]
            continue
        if guids:
            result[podcast.slug] = guids
    return result


def pipeline_snapshot(limit: int = 40) -> dict:
    counts = queue_counts()
    jobs = list_queue_jobs(limit=limit)
    return {
        "pending": counts.get("pending", 0),
        "running": counts.get("running", 0),
        "jobs": jobs,
    }
