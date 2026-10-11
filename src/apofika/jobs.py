"""Background process jobs so the web UI never blocks on detection."""

from __future__ import annotations

import threading

from apofika import config
from apofika.db import get_podcast, get_process_run, set_process_run
from apofika.worker import process_podcast

_lock = threading.Lock()
_running: set[int] = set()


def is_running(podcast_id: int) -> bool:
    with _lock:
        return podcast_id in _running


def start_process_job(podcast_id: int, *, force: bool = False) -> tuple[bool, str]:
    """Start process_podcast in a daemon thread. Returns (started, message)."""
    podcast = get_podcast(podcast_id)
    if not podcast:
        return False, "Feed nicht gefunden."

    with _lock:
        if podcast_id in _running:
            run = get_process_run(podcast_id)
            return False, run.message or "Verarbeitung läuft bereits."
        _running.add(podcast_id)

    set_process_run(
        podcast_id,
        status="running",
        message="Verarbeitung gestartet… Episode wird geladen und analysiert.",
        started=True,
    )

    def _run() -> None:
        try:
            result = process_podcast(
                podcast,
                force=force,
                base_url=config.public_base(),
            )
            error = bool(result.error and not result.skipped)
            set_process_run(
                podcast_id,
                status="error" if error else "done",
                message=result.message,
                finished=True,
            )
        except Exception as exc:  # noqa: BLE001 — surface any failure to UI
            set_process_run(
                podcast_id,
                status="error",
                message=f"Unerwarteter Fehler: {exc}",
                finished=True,
            )
        finally:
            with _lock:
                _running.discard(podcast_id)

    threading.Thread(
        target=_run,
        name=f"process-{podcast.slug}",
        daemon=True,
    ).start()
    return True, "Verarbeitung gestartet."
