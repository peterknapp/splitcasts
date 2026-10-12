"""SQLite persistence for Splitcasts."""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from apofika.config import db_path
from apofika.paths import ensure_dirs

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass
class Podcast:
    id: int
    slug: str
    title: str
    source_rss_url: str
    active: bool
    created_at: str
    image_url: str | None = None


@dataclass
class Snippet:
    id: int
    podcast_id: int
    position: int
    filename: str
    created_at: str


@dataclass
class Episode:
    id: int
    podcast_id: int
    guid: str
    title: str
    published_at: str | None
    status: str
    error_message: str | None
    source_path: str | None
    processed_path: str | None
    chapters_json_path: str | None
    processed_at: str | None


@dataclass
class ProcessRun:
    podcast_id: int
    status: str  # idle | running | done | error
    message: str | None
    started_at: str | None
    finished_at: str | None


def _connect(path: Path | None = None) -> sqlite3.Connection:
    ensure_dirs()
    db = path or db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    with get_conn(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS podcasts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              slug TEXT NOT NULL UNIQUE,
              title TEXT NOT NULL,
              source_rss_url TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              image_url TEXT
            );
            CREATE TABLE IF NOT EXISTS snippets (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              podcast_id INTEGER NOT NULL REFERENCES podcasts(id) ON DELETE CASCADE,
              position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 3),
              filename TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE(podcast_id, position)
            );
            CREATE TABLE IF NOT EXISTS episodes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              podcast_id INTEGER NOT NULL REFERENCES podcasts(id) ON DELETE CASCADE,
              guid TEXT NOT NULL,
              title TEXT NOT NULL,
              published_at TEXT,
              status TEXT NOT NULL,
              error_message TEXT,
              source_path TEXT,
              processed_path TEXT,
              chapters_json_path TEXT,
              processed_at TEXT,
              UNIQUE(podcast_id, guid)
            );
            CREATE INDEX IF NOT EXISTS idx_episodes_podcast_status
              ON episodes(podcast_id, status);
            CREATE TABLE IF NOT EXISTS process_runs (
              podcast_id INTEGER PRIMARY KEY REFERENCES podcasts(id) ON DELETE CASCADE,
              status TEXT NOT NULL DEFAULT 'idle',
              message TEXT,
              started_at TEXT,
              finished_at TEXT
            );
            """
        )
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(podcasts)").fetchall()
        }
        if "image_url" not in cols:
            conn.execute("ALTER TABLE podcasts ADD COLUMN image_url TEXT")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not SLUG_RE.match(slug):
        raise ValueError("Slug must be lowercase letters, numbers, hyphens")
    return slug


def suggest_slug(title: str, source_rss_url: str = "") -> str:
    """Build a URL slug from a podcast title (fallback: host from URL)."""
    import unicodedata
    from urllib.parse import urlparse

    text = (title or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    if text and SLUG_RE.match(text):
        return text[:60].strip("-")

    host = urlparse(source_rss_url).netloc.lower()
    host = host.removeprefix("www.")
    host = re.sub(r"[^a-z0-9]+", "-", host).strip("-")
    if host and SLUG_RE.match(host):
        return host[:60].strip("-")
    return "podcast"



def list_podcasts(active_only: bool = False) -> list[Podcast]:
    with get_conn() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM podcasts WHERE active = 1 ORDER BY title COLLATE NOCASE"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM podcasts ORDER BY title COLLATE NOCASE"
            ).fetchall()
    return [_podcast(r) for r in rows]


def get_podcast_by_slug(slug: str) -> Podcast | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM podcasts WHERE slug = ?", (slug,)
        ).fetchone()
    return _podcast(row) if row else None


def get_podcast(podcast_id: int) -> Podcast | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM podcasts WHERE id = ?", (podcast_id,)
        ).fetchone()
    return _podcast(row) if row else None


def create_podcast(
    slug: str,
    title: str,
    source_rss_url: str,
    image_url: str | None = None,
) -> Podcast:
    slug = validate_slug(slug)
    title = title.strip()
    source_rss_url = source_rss_url.strip()
    if not title or not source_rss_url:
        raise ValueError("Title and source RSS URL are required")
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO podcasts (slug, title, source_rss_url, active, created_at, image_url)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (slug, title, source_rss_url, _now(), image_url),
        )
        pid = int(cur.lastrowid)
    podcast = get_podcast(pid)
    assert podcast is not None
    return podcast


def update_podcast_image(podcast_id: int, image_url: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE podcasts SET image_url = ? WHERE id = ?",
            (image_url, podcast_id),
        )


def _podcast(row: sqlite3.Row) -> Podcast:
    keys = row.keys()
    return Podcast(
        id=row["id"],
        slug=row["slug"],
        title=row["title"],
        source_rss_url=row["source_rss_url"],
        active=bool(row["active"]),
        created_at=row["created_at"],
        image_url=row["image_url"] if "image_url" in keys else None,
    )


def list_snippets(podcast_id: int) -> list[Snippet]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM snippets WHERE podcast_id = ? ORDER BY position",
            (podcast_id,),
        ).fetchall()
    return [
        Snippet(
            id=r["id"],
            podcast_id=r["podcast_id"],
            position=r["position"],
            filename=r["filename"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def upsert_snippet(podcast_id: int, position: int, filename: str) -> Snippet:
    if position < 1 or position > 3:
        raise ValueError("Snippet position must be 1..3")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO snippets (podcast_id, position, filename, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(podcast_id, position) DO UPDATE SET
              filename = excluded.filename,
              created_at = excluded.created_at
            """,
            (podcast_id, position, filename, _now()),
        )
        row = conn.execute(
            "SELECT * FROM snippets WHERE podcast_id = ? AND position = ?",
            (podcast_id, position),
        ).fetchone()
    return Snippet(
        id=row["id"],
        podcast_id=row["podcast_id"],
        position=row["position"],
        filename=row["filename"],
        created_at=row["created_at"],
    )


def delete_snippet(podcast_id: int, position: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT filename FROM snippets WHERE podcast_id = ? AND position = ?",
            (podcast_id, position),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "DELETE FROM snippets WHERE podcast_id = ? AND position = ?",
            (podcast_id, position),
        )
        return row["filename"]


def get_episode_by_guid(podcast_id: int, guid: str) -> Episode | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM episodes WHERE podcast_id = ? AND guid = ?",
            (podcast_id, guid),
        ).fetchone()
    return _episode(row) if row else None


def upsert_episode(
    podcast_id: int,
    guid: str,
    title: str,
    published_at: str | None,
    status: str,
    error_message: str | None = None,
    source_path: str | None = None,
    processed_path: str | None = None,
    chapters_json_path: str | None = None,
    processed_at: str | None = None,
) -> Episode:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO episodes (
              podcast_id, guid, title, published_at, status, error_message,
              source_path, processed_path, chapters_json_path, processed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(podcast_id, guid) DO UPDATE SET
              title = excluded.title,
              published_at = excluded.published_at,
              status = excluded.status,
              error_message = excluded.error_message,
              source_path = excluded.source_path,
              processed_path = excluded.processed_path,
              chapters_json_path = excluded.chapters_json_path,
              processed_at = excluded.processed_at
            """,
            (
                podcast_id,
                guid,
                title,
                published_at,
                status,
                error_message,
                source_path,
                processed_path,
                chapters_json_path,
                processed_at,
            ),
        )
        row = conn.execute(
            "SELECT * FROM episodes WHERE podcast_id = ? AND guid = ?",
            (podcast_id, guid),
        ).fetchone()
    return _episode(row)


def list_split_episodes(podcast_id: int, limit: int | None = None) -> list[Episode]:
    """Newest-first split episodes.

    Important: do not ORDER BY published_at as text — RFC822 day names
    (Mon/Thu/…) sort lexicographically and can purge the newest episode.
    """
    from apofika.formatting import episode_recency_key

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM episodes
            WHERE podcast_id = ? AND status = 'split' AND processed_path IS NOT NULL
            """,
            (podcast_id,),
        ).fetchall()
    episodes = [_episode(r) for r in rows]
    episodes.sort(
        key=lambda ep: episode_recency_key(ep.published_at, ep.processed_at, ep.id),
        reverse=True,
    )
    if limit is not None:
        return episodes[: int(limit)]
    return episodes


def mark_episode_purged(episode_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE episodes
            SET status = 'purged',
                source_path = NULL,
                processed_path = NULL,
                chapters_json_path = NULL
            WHERE id = ?
            """,
            (episode_id,),
        )


def get_process_run(podcast_id: int) -> ProcessRun:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM process_runs WHERE podcast_id = ?",
            (podcast_id,),
        ).fetchone()
    if not row:
        return ProcessRun(
            podcast_id=podcast_id,
            status="idle",
            message=None,
            started_at=None,
            finished_at=None,
        )
    return ProcessRun(
        podcast_id=row["podcast_id"],
        status=row["status"],
        message=row["message"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def set_process_run(
    podcast_id: int,
    *,
    status: str,
    message: str | None = None,
    started: bool = False,
    finished: bool = False,
) -> ProcessRun:
    now = _now()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM process_runs WHERE podcast_id = ?",
            (podcast_id,),
        ).fetchone()
        started_at = now if started else (existing["started_at"] if existing else None)
        finished_at = now if finished else (None if started else (existing["finished_at"] if existing else None))
        if existing:
            conn.execute(
                """
                UPDATE process_runs
                SET status = ?, message = ?, started_at = ?, finished_at = ?
                WHERE podcast_id = ?
                """,
                (status, message, started_at, finished_at, podcast_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO process_runs (podcast_id, status, message, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (podcast_id, status, message, started_at, finished_at),
            )
    return get_process_run(podcast_id)


def _episode(row: sqlite3.Row) -> Episode:
    return Episode(
        id=row["id"],
        podcast_id=row["podcast_id"],
        guid=row["guid"],
        title=row["title"],
        published_at=row["published_at"],
        status=row["status"],
        error_message=row["error_message"],
        source_path=row["source_path"],
        processed_path=row["processed_path"],
        chapters_json_path=row["chapters_json_path"],
        processed_at=row["processed_at"],
    )
