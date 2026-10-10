"""Fetch latest episode from the source RSS feed."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
import feedparser
import httpx

from apofika.paths import RAW_DIR, SOURCE_FEED_URL, ensure_dirs


@dataclass
class EpisodeMeta:
    guid: str
    title: str
    description: str
    summary: str
    link: str
    published: str
    enclosure_url: str
    enclosure_type: str
    enclosure_length: int | None
    duration: int | None
    image_url: str | None
    author: str | None
    episode_number: int | None


def _entry_guid(entry: feedparser.FeedParserDict) -> str:
    guid = getattr(entry, "id", None) or getattr(entry, "guid", None)
    if guid:
        return str(guid)
    if entry.get("link"):
        return str(entry.link)
    raise ValueError("Feed entry has no guid/id/link")


def _enclosure(entry: feedparser.FeedParserDict) -> tuple[str, str, int | None]:
    enclosures = entry.get("enclosures") or []
    if not enclosures:
        raise ValueError(f"No enclosure for episode: {entry.get('title')}")
    enc = enclosures[0]
    url = enc.get("href") or enc.get("url")
    if not url:
        raise ValueError("Enclosure missing URL")
    length_raw = enc.get("length")
    length = int(length_raw) if length_raw and str(length_raw).isdigit() else None
    return str(url), str(enc.get("type") or "audio/mpeg"), length


def _duration(entry: feedparser.FeedParserDict) -> int | None:
    raw = entry.get("itunes_duration")
    if raw is None:
        return None
    text = str(raw).strip()
    if text.isdigit():
        return int(text)
    parts = text.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    return None


def _image_url(entry: feedparser.FeedParserDict, feed: feedparser.FeedParserDict) -> str | None:
    image = entry.get("image")
    if isinstance(image, dict) and image.get("href"):
        return str(image["href"])
    itunes_image = entry.get("itunes_image")
    if isinstance(itunes_image, dict) and itunes_image.get("href"):
        return str(itunes_image["href"])
    feed_image = feed.feed.get("image")
    if isinstance(feed_image, dict) and feed_image.get("href"):
        return str(feed_image["href"])
    return None


def fetch_parsed(feed_url: str) -> feedparser.FeedParserDict:
    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        response = client.get(feed_url)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"Failed to parse feed: {parsed.bozo_exception}")
    if not parsed.entries:
        raise RuntimeError("Feed has no entries")
    return parsed


def entry_to_meta(
    entry: feedparser.FeedParserDict,
    parsed: feedparser.FeedParserDict,
) -> EpisodeMeta:
    url, enc_type, length = _enclosure(entry)
    description = entry.get("summary") or entry.get("description") or ""
    if entry.get("content"):
        content0 = entry.content[0]
        if content0.get("value"):
            description = content0["value"]
    return EpisodeMeta(
        guid=_entry_guid(entry),
        title=str(entry.get("title") or "Untitled"),
        description=str(description),
        summary=str(entry.get("summary") or description),
        link=str(entry.get("link") or ""),
        published=str(entry.get("published") or entry.get("updated") or ""),
        enclosure_url=url,
        enclosure_type=enc_type,
        enclosure_length=length,
        duration=_duration(entry),
        image_url=_image_url(entry, parsed),
        author=str(entry.get("author") or entry.get("itunes_author") or "") or None,
        episode_number=_parse_episode_number(entry),
    )


def parse_latest(feed_url: str = SOURCE_FEED_URL) -> tuple[EpisodeMeta, feedparser.FeedParserDict]:
    parsed = fetch_parsed(feed_url)
    return entry_to_meta(parsed.entries[0], parsed), parsed


def parse_recent(
    feed_url: str,
    limit: int = 5,
) -> tuple[list[EpisodeMeta], feedparser.FeedParserDict]:
    parsed = fetch_parsed(feed_url)
    items: list[EpisodeMeta] = []
    for entry in parsed.entries[:limit]:
        try:
            items.append(entry_to_meta(entry, parsed))
        except ValueError:
            continue
    return items, parsed


def _parse_episode_number(entry: feedparser.FeedParserDict) -> int | None:
    raw = entry.get("itunes_episode")
    if raw is None:
        return None
    try:
        return int(str(raw))
    except ValueError:
        return None


def safe_filename(guid: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", guid).strip("_")
    return cleaned or "episode"


def download_episode(meta: EpisodeMeta, dest_dir: Path = RAW_DIR) -> Path:
    ensure_dirs()
    dest = dest_dir / f"{safe_filename(meta.guid)}.mp3"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    with httpx.stream("GET", meta.enclosure_url, follow_redirects=True, timeout=120.0) as resp:
        resp.raise_for_status()
        tmp = dest.with_suffix(".mp3.part")
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=1024 * 256):
                fh.write(chunk)
        tmp.replace(dest)
    return dest


def channel_meta(parsed: feedparser.FeedParserDict) -> dict:
    feed = parsed.feed
    image = None
    if isinstance(feed.get("image"), dict):
        image = feed["image"].get("href")
    itunes_image = feed.get("itunes_image")
    if isinstance(itunes_image, dict) and itunes_image.get("href"):
        image = itunes_image["href"]
    return {
        "title": feed.get("title") or "ApoFiKa Chapters",
        "link": feed.get("link") or "",
        "description": feed.get("description") or feed.get("subtitle") or "",
        "language": feed.get("language") or "de",
        "author": feed.get("author") or feed.get("itunes_author") or "",
        "image": image,
        "copyright": feed.get("rights") or "",
    }
