"""Runtime configuration from environment."""

from __future__ import annotations

import os
from pathlib import Path

from apofika.paths import DEFAULT_HOST, DEFAULT_PORT, ROOT


def public_base() -> str:
    return (
        os.environ.get("SPLITCASTS_PUBLIC_BASE")
        or os.environ.get("APOFIKA_PUBLIC_BASE")
        or f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
    ).rstrip("/")


def session_secret() -> str:
    secret = os.environ.get("SPLITCASTS_SESSION_SECRET") or os.environ.get(
        "APOFIKA_SESSION_SECRET"
    )
    if secret:
        return secret
    # Stable fallback for single-user Pi installs; override in production env.
    return f"splitcasts-dev-{ROOT}"


def password_hash() -> str | None:
    return os.environ.get("SPLITCASTS_PASSWORD_HASH") or os.environ.get(
        "APOFIKA_PASSWORD_HASH"
    )


def password_plain() -> str | None:
    """Optional plaintext password for first-time setup (prefer hash)."""
    return os.environ.get("SPLITCASTS_PASSWORD") or os.environ.get("APOFIKA_PASSWORD")


def db_path() -> Path:
    raw = os.environ.get("SPLITCASTS_DB")
    if raw:
        return Path(raw)
    from apofika.paths import DATA_DIR

    return DATA_DIR / "splitcasts.db"
