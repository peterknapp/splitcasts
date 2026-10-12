"""Parse show-note topics and map them onto jingle timestamps."""

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
    plain = strip_html(description)
    match = TOPIC_HEADER_RE.search(plain) or TOPIC_HEADER_RE.search(description)
    if not match:
        return []
    blob = strip_html(match.group(1)).strip()
    blob = PROMO_CUT_RE.sub("", blob).strip()
    if not blob:
        return []

    # Prefer semicolon-separated topics (ApoFiKa style)
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
    *,
    intro_grace_sec: float = 60.0,
) -> tuple[list[Chapter], list[str]]:
    """
    Mapping:
      Intro @ 0
      Thema[i] @ topic-jingle[i]

    Many shows play the same jingle once as an opening sting (still inside the
    intro). If the first hit falls within ``intro_grace_sec``, it is treated as
    that intro bumper and *not* paired with topics[0] — otherwise every title
    shifts forward by one ("current chapter shows the next topic").
    """
    warnings: list[str] = []
    chapters: list[Chapter] = [Chapter(start=0.0, title="Intro")]

    if not topics and not jingle_times:
        warnings.append("No topics and no jingles detected")
        return chapters, warnings

    times = [float(t) for t in jingle_times]
    topic_times = times
    if times and times[0] < intro_grace_sec:
        warnings.append(
            f"Leading jingle at {times[0]:.1f}s treated as intro bumper "
            f"(<{intro_grace_sec:.0f}s); topics start at later hits."
        )
        topic_times = times[1:]

    for i, t in enumerate(topic_times):
        if i < len(topics):
            title = topics[i]
        else:
            title = f"Segment {i + 1}"
            warnings.append(f"No topic for jingle at {t:.1f}s — using '{title}'")
        chapters.append(Chapter(start=t, title=title))

    unused = topics[len(topic_times) :]
    if unused:
        warnings.append(
            f"{len(unused)} topic(s) without jingle timestamps: {unused}"
        )
        if unused and topic_times:
            # extend last chapter title with leftover themes for discoverability
            extra = " / ".join(unused)
            chapters[-1] = Chapter(
                start=chapters[-1].start,
                title=f"{chapters[-1].title} (+ {extra})",
            )
        elif unused and not topic_times:
            chapters = [Chapter(start=0.0, title=topics[0])]
            for topic in topics[1:]:
                warnings.append(f"Topic without timestamp skipped/merged: {topic}")
            if len(topics) > 1:
                chapters[0] = Chapter(
                    start=0.0,
                    title=" / ".join(topics),
                )

    if topics and topic_times and abs(len(topic_times) - len(topics)) > 1:
        warnings.append(
            f"Jingle count ({len(topic_times)}) differs from topic count ({len(topics)})"
        )

    # Deduplicate identical consecutive starts
    deduped: list[Chapter] = []
    for ch in chapters:
        if deduped and abs(deduped[-1].start - ch.start) < 0.5:
            deduped[-1] = ch
        else:
            deduped.append(ch)

    if include_outro and deduped:
        # Outro only if last jingle isn't already near end — placeholder title
        # without knowing duration we skip automatic outro unless explicitly wanted
        # with a synthetic +1s mark which players dislike; so no-op unless times allow.
        pass

    return deduped, warnings


def save_chapters_json(chapters: list[Chapter], path: Path, extra: dict | None = None) -> None:
    payload = {
        "chapters": [asdict(c) for c in chapters],
        **(extra or {}),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
