"""Embed chapter markers into MP3 ID3 tags."""

from __future__ import annotations

import shutil
from pathlib import Path

from mutagen.id3 import CHAP, CTOC, ID3, TIT2, ID3NoHeaderError
from mutagen.mp3 import MP3

from apofika.chapters import Chapter


def _ms(seconds: float) -> int:
    return max(0, int(round(seconds * 1000)))


def embed_chapters(
    source_mp3: Path,
    dest_mp3: Path,
    chapters: list[Chapter],
    duration_sec: float | None = None,
) -> Path:
    """
    Copy source to dest and write ID3v2 CHAP/CTOC frames.
    Does not re-encode audio.
    """
    dest_mp3.parent.mkdir(parents=True, exist_ok=True)
    if source_mp3.resolve() != dest_mp3.resolve():
        shutil.copy2(source_mp3, dest_mp3)

    if duration_sec is None:
        audio = MP3(dest_mp3)
        duration_sec = float(audio.info.length)

    end_ms = _ms(duration_sec)
    sorted_chapters = sorted(chapters, key=lambda c: c.start)
    if not sorted_chapters:
        sorted_chapters = [Chapter(start=0.0, title="Intro")]

    try:
        tags = ID3(dest_mp3)
    except ID3NoHeaderError:
        tags = ID3()

    # Remove previous chapter frames
    for key in list(tags.keys()):
        if key.startswith("CHAP") or key.startswith("CTOC"):
            del tags[key]

    child_ids: list[str] = []
    for i, chapter in enumerate(sorted_chapters):
        element_id = f"ch{i}"
        child_ids.append(element_id)
        start_ms = _ms(chapter.start)
        if i + 1 < len(sorted_chapters):
            chapter_end = _ms(sorted_chapters[i + 1].start)
        else:
            chapter_end = end_ms
        if chapter_end <= start_ms:
            chapter_end = start_ms + 1000

        tags.add(
            CHAP(
                element_id=element_id,
                start_time=start_ms,
                end_time=chapter_end,
                start_offset=0xFFFFFFFF,
                end_offset=0xFFFFFFFF,
                sub_frames=[TIT2(encoding=3, text=[chapter.title])],
            )
        )

    tags.add(
        CTOC(
            element_id="toc",
            flags=3,  # top-level + ordered
            child_element_ids=child_ids,
            sub_frames=[TIT2(encoding=3, text=["Table of Contents"])],
        )
    )
    tags.save(dest_mp3, v2_version=3)
    return dest_mp3
