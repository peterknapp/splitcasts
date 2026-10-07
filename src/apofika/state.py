"""Persistent processing state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from apofika.paths import STATE_PATH, ensure_dirs


@dataclass
class EpisodeRecord:
    guid: str
    title: str
    processed_file: str
    chapters_file: str
    published: str | None = None


@dataclass
class AppState:
    processed_guids: list[str] = field(default_factory=list)
    episodes: list[dict[str, Any]] = field(default_factory=list)

    def has_guid(self, guid: str) -> bool:
        return guid in self.processed_guids

    def add_episode(self, record: EpisodeRecord) -> None:
        if record.guid not in self.processed_guids:
            self.processed_guids.append(record.guid)
        # newest first
        self.episodes = [e for e in self.episodes if e.get("guid") != record.guid]
        self.episodes.insert(0, asdict(record))


def load_state(path: Path = STATE_PATH) -> AppState:
    ensure_dirs()
    if not path.exists():
        return AppState()
    data = json.loads(path.read_text(encoding="utf-8"))
    return AppState(
        processed_guids=list(data.get("processed_guids", [])),
        episodes=list(data.get("episodes", [])),
    )


def save_state(state: AppState, path: Path = STATE_PATH) -> None:
    ensure_dirs()
    path.write_text(
        json.dumps(asdict(state), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
