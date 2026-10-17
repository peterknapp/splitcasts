"""Project path helpers."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = ROOT / "assets"
DATA_DIR = ROOT / "data"
FEEDS_DIR = DATA_DIR / "feeds"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
STATE_PATH = DATA_DIR / "state.json"
FEED_PATH = DATA_DIR / "feed.xml"
JINGLE_REF_PATH = ASSETS_DIR / "jingle_ref.wav"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

SOURCE_FEED_URL = "https://apokalypse-und-filterkaffee.podigee.io/feed/mp3"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
MAX_KEEP_EPISODES = 3
MAX_SNIPPETS = 3
UI_RECENT_EPISODES = 5
# Auto-queue only episodes published within this window of the newest RSS item
# (catches same-batch releases, not the whole back catalog).
CO_PUBLISH_WINDOW_SEC = 2 * 60 * 60


def ensure_dirs() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def feed_dir(slug: str) -> Path:
    return FEEDS_DIR / slug


def feed_raw_dir(slug: str) -> Path:
    return feed_dir(slug) / "raw"


def feed_processed_dir(slug: str) -> Path:
    return feed_dir(slug) / "processed"


def feed_snippets_dir(slug: str) -> Path:
    return feed_dir(slug) / "snippets"


def feed_xml_path(slug: str) -> Path:
    return feed_dir(slug) / "feed.xml"


def ensure_feed_dirs(slug: str) -> None:
    ensure_dirs()
    for path in (feed_raw_dir(slug), feed_processed_dir(slug), feed_snippets_dir(slug)):
        path.mkdir(parents=True, exist_ok=True)
