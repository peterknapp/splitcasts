"""Build a local RSS feed with Podlove Simple Chapters."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from apofika.chapters import Chapter
from apofika.fetch import EpisodeMeta
from apofika.paths import FEED_PATH, DEFAULT_HOST, DEFAULT_PORT


def _esc(text: str) -> str:
    return escape(text or "", {"'": "&apos;", '"': "&quot;"})


def _cdata(text: str) -> str:
    safe = (text or "").replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{safe}]]>"


def format_rfc2822(published: str | None = None) -> str:
    if published:
        return published
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def psc_chapters_xml(chapters: list[Chapter]) -> str:
    lines = ['        <psc:chapters version="1.2">']
    for ch in chapters:
        lines.append(
            f'          <psc:chapter start="{ch.start_psc()}" title="{_esc(ch.title)}" />'
        )
    lines.append("        </psc:chapters>")
    return "\n".join(lines)


def build_item_xml(
    meta: EpisodeMeta,
    media_url: str,
    media_length: int,
    chapters: list[Chapter],
) -> str:
    duration = meta.duration if meta.duration is not None else ""
    image_line = ""
    if meta.image_url:
        image_line = f'        <itunes:image href="{_esc(meta.image_url)}"/>\n'
    episode_line = ""
    if meta.episode_number is not None:
        episode_line = f"        <itunes:episode>{meta.episode_number}</itunes:episode>\n"

    summary = strip_for_summary(meta.summary or meta.description)
    return f"""    <item>
        <title>{_esc(meta.title)}</title>
        <itunes:title>{_esc(meta.title)}</itunes:title>
        <description>{_cdata(summary)}</description>
        <pubDate>{_esc(format_rfc2822(meta.published))}</pubDate>
        <link>{_esc(meta.link)}</link>
        <guid isPermaLink="false">{_esc(meta.guid)}</guid>
{image_line}{episode_line}        <itunes:summary>{_cdata(summary)}</itunes:summary>
        <itunes:explicit>no</itunes:explicit>
        <itunes:author>{_esc(meta.author or "")}</itunes:author>
        <enclosure url="{_esc(media_url)}" type="{_esc(meta.enclosure_type or "audio/mpeg")}" length="{media_length}"/>
        <itunes:duration>{duration}</itunes:duration>
{psc_chapters_xml(chapters)}
    </item>"""


def strip_for_summary(text: str) -> str:
    # keep readable text; RSS description can be HTML but summary is fine as text
    from apofika.chapters import strip_html

    return strip_html(text)


def build_feed_xml(
    channel: dict,
    items_xml: list[str],
    self_url: str,
) -> str:
    image_block = ""
    if channel.get("image"):
        image_block = f"""    <image>
      <url>{_esc(channel["image"])}</url>
      <title>{_esc(channel.get("title") or "")}</title>
      <link>{_esc(channel.get("link") or "")}</link>
    </image>
    <itunes:image href="{_esc(channel["image"])}"/>"""

    items = "\n".join(items_xml)
    now = format_rfc2822()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:psc="http://podlove.org/simple-chapters"
     version="2.0">
  <channel>
    <atom:link href="{_esc(self_url)}" rel="self" type="application/rss+xml"/>
    <title>{_esc(channel.get("title") or "ApoFiKa Chapters")}</title>
    <language>{_esc(channel.get("language") or "de")}</language>
    <lastBuildDate>{_esc(now)}</lastBuildDate>
    <description>{_cdata((channel.get("description") or "") + " (lokale Kapitel-Version)")}</description>
    <link>{_esc(channel.get("link") or self_url)}</link>
    <itunes:author>{_esc(channel.get("author") or "")}</itunes:author>
    <itunes:summary>{_cdata(channel.get("description") or "")}</itunes:summary>
    <itunes:explicit>no</itunes:explicit>
{image_block}
{items}
  </channel>
</rss>
"""


def write_feed(
    channel: dict,
    episodes: list[tuple[EpisodeMeta, Path, list[Chapter]]],
    public_base: str | None = None,
    feed_path: Path = FEED_PATH,
) -> Path:
    """
    episodes: list of (meta, processed_mp3_path, chapters), newest first.
    """
    base = (public_base or f"http://{DEFAULT_HOST}:{DEFAULT_PORT}").rstrip("/")
    self_url = f"{base}/feed.xml"
    items: list[str] = []
    for meta, mp3_path, chapters in episodes:
        length = mp3_path.stat().st_size
        media_url = f"{base}/media/{mp3_path.name}"
        items.append(build_item_xml(meta, media_url, length, chapters))

    xml = build_feed_xml(channel, items, self_url)
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text(xml, encoding="utf-8")
    return feed_path
