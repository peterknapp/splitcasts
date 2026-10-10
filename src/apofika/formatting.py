"""Display helpers."""

from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime


def format_published(value: str | None) -> str:
    """Format RSS pubDate / ISO timestamps for German UI display."""
    if not value:
        return "—"
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
            return text
    # Show local wall time without forcing a specific zone conversion if naive
    return dt.strftime("%d.%m.%Y, %H:%M Uhr")
