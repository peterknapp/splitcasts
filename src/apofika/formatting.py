"""Display helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse RSS pubDate or ISO timestamps into aware UTC datetimes."""
    if not value:
        return None
    text = value.strip()
    dt: datetime | None = None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def episode_recency_key(published_at: str | None, processed_at: str | None, episode_id: int = 0) -> tuple:
    """Sort key for newest-first (never lexicographically on RFC822 day names)."""
    for raw in (published_at, processed_at):
        dt = parse_timestamp(raw)
        if dt is not None:
            return (dt.timestamp(), episode_id)
    return (0.0, episode_id)


def format_published(value: str | None) -> str:
    """Format RSS pubDate / ISO timestamps for German UI display."""
    dt = parse_timestamp(value)
    if dt is None:
        return value.strip() if value and value.strip() else "—"
    # Show local wall time without forcing a specific zone conversion if naive
    return dt.strftime("%d.%m.%Y, %H:%M Uhr")
