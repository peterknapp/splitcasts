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
) -> tuple[list[Chapter], list[str]]:
    """
    Mapping:
      Intro @ 0
      topics[0] @ 0 as well? No — Intro covers opening; first topic starts at first jingle
        OR first topic at 0 and subsequent topics at jingels.

    Plan says: Intro @ 0; then Thema[i] @ jingle[i].
    So topics are assigned starting at jingle hits. Extra topics after last jingle
    get folded into a warning; if more jingels than topics, leftover hits get
    generic titles.
    """
    warnings: list[str] = []
    chapters: list[Chapter] = [Chapter(start=0.0, title="Intro")]

    if not topics and not jingle_times:
        warnings.append("No topics and no jingles detected")
        return chapters, warnings

    # Assign topic i to jingle i (topic 0 starts after first jingle = first theme block)
    # If we have N topics and N-1 expected separators between them after intro:
    #   jingle[0] -> topics[0], jingle[1] -> topics[1], ...
    for i, t in enumerate(jingle_times):
        if i < len(topics):
            title = topics[i]
        else:
            title = f"Segment {i + 1}"
            warnings.append(f"No topic for jingle at {t:.1f}s — using '{title}'")
        chapters.append(Chapter(start=float(t), title=title))

    unused = topics[len(jingle_times) :]
    if unused:
        warnings.append(
            f"{len(unused)} topic(s) without jingle timestamps: {unused}"
        )
        # Attach remaining topics as a combined last chapter title hint
        if include_outro and chapters:
            pass
        # Append leftover topics starting at last chapter end marker is unknown;
        # keep them only in warnings for MVP unless include_outro with last topic names
        if unused and jingle_times:
            # extend last chapter title with leftover themes for discoverability
            extra = " / ".join(unused)
            chapters[-1] = Chapter(
                start=chapters[-1].start,
                title=f"{chapters[-1].title} (+ {extra})",
            )
        elif unused and not jingle_times:
            # no jingels: put first topic at 0 replacing Intro subtitle style
            chapters = [Chapter(start=0.0, title=topics[0])]
            for idx, topic in enumerate(topics[1:], start=1):
                warnings.append(f"Topic without timestamp skipped/merged: {topic}")
            if len(topics) > 1:
                chapters[0] = Chapter(
                    start=0.0,
                    title=" / ".join(topics),
                )

    expected = max(len(topics) - 0, 0)
    if topics and jingle_times and abs(len(jingle_times) - len(topics)) > 1:
        warnings.append(
            f"Jingle count ({len(jingle_times)}) differs from topic count ({len(topics)}); "
            f"expected roughly {expected} separators"
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
