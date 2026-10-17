"""Build numbered chapter cut marks from jingle timestamps."""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

TOPIC_HEADER_RE = re.compile(
    r"Die\s+Themen\s*:\s*(.+?)(?=(?:\n\s*\n|\n?Hosts\b|\s*Du möchtest|$))",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
PROMO_CUT_RE = re.compile(r"\s+Du möchtest\b.*$", re.IGNORECASE)


@dataclass
class Chapter:
    start: float
    title: str

    def start_psc(self) -> str:
        total = int(round(self.start))
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"


def strip_html(text: str) -> str:
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_topics(description: str) -> list[str]:
    """Extract show-note topics (kept for metadata / debugging only)."""
    plain = strip_html(description)
    match = TOPIC_HEADER_RE.search(plain) or TOPIC_HEADER_RE.search(description)
    if not match:
        return []
    blob = strip_html(match.group(1)).strip()
    blob = PROMO_CUT_RE.sub("", blob).strip()
    if not blob:
        return []

    if ";" in blob:
        parts = blob.split(";")
    else:
        parts = blob.split(",")

    topics: list[str] = []
    for part in parts:
        cleaned = re.sub(r"\s+", " ", part).strip(" \t\r\n.;")
        cleaned = PROMO_CUT_RE.sub("", cleaned).strip(" \t\r\n.;")
        if cleaned.lower().startswith("du möchtest"):
            continue
        if cleaned:
            topics.append(cleaned)
    return topics


def build_chapters(
    topics: list[str],
    jingle_times: list[float],
    include_outro: bool = False,
    **_kwargs,
) -> tuple[list[Chapter], list[str]]:
    """
    Cut marks only — numbered 1..n at each jingle hit. No Intro chapter.
    ``topics`` is ignored for titles (call-site compatibility).
    """
    warnings: list[str] = []
    times = sorted({float(t) for t in jingle_times if float(t) >= 0.0})

    if not times:
        warnings.append("No jingles detected — no chapter marks")
        if topics:
            warnings.append(
                f"{len(topics)} show-note topic(s) ignored (numbered cuts only)"
            )
        return [], warnings

    chapters = [Chapter(start=t, title=str(i)) for i, t in enumerate(times, start=1)]

    if topics:
        warnings.append(
            f"{len(topics)} show-note topic(s) ignored (numbered cuts only)"
        )

    deduped: list[Chapter] = []
    for ch in chapters:
        if deduped and abs(deduped[-1].start - ch.start) < 0.5:
            deduped[-1] = ch
        else:
            deduped.append(ch)

    return deduped, warnings


def save_chapters_json(chapters: list[Chapter], path: Path, extra: dict | None = None) -> None:
    payload = {
        "chapters": [asdict(c) for c in chapters],
        **(extra or {}),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
