"""Project path helpers."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = ROOT / "assets"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
STATE_PATH = DATA_DIR / "state.json"
FEED_PATH = DATA_DIR / "feed.xml"
JINGLE_REF_PATH = ASSETS_DIR / "jingle_ref.wav"

SOURCE_FEED_URL = "https://apokalypse-und-filterkaffee.podigee.io/feed/mp3"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def ensure_dirs() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
