"""Start the global queue worker as a nice'd subprocess (keeps the web UI free)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from apofika import config
from apofika.paths import DATA_DIR
from apofika.runtime import compute_env

_lock = threading.Lock()
_worker: subprocess.Popen | None = None


def _pid_path() -> Path:
    return DATA_DIR / "jobs" / "queue-worker.pid"


def _write_pid(pid: int) -> None:
    path = _pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def _clear_pid() -> None:
    path = _pid_path()
    if path.exists():
        path.unlink()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def is_queue_worker_running() -> bool:
    global _worker
    with _lock:
        if _worker is not None:
            if _worker.poll() is None:
                return True
            _worker = None
            _clear_pid()
    path = _pid_path()
    if path.exists():
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except ValueError:
            _clear_pid()
            return False
        if _pid_alive(pid):
            return True
        _clear_pid()
    return False


def _apofika_cmd() -> list[str]:
    bindir = Path(sys.executable).resolve().parent
    script = bindir / "apofika"
    if script.is_file() and os.access(script, os.X_OK):
        return [str(script)]
    which = shutil.which("apofika")
    if which:
        return [which]
    return [sys.executable, "-m", "apofika.cli"]


def ensure_queue_worker() -> tuple[bool, str]:
    """Start `apofika queue-run` if no worker is active. Returns (started, message)."""
    global _worker
    if is_queue_worker_running():
        return False, "Pipeline-Worker läuft bereits."

    cmd = _apofika_cmd() + [
        "queue-run",
        "--public-base",
        config.public_base(),
    ]
    launcher: list[str] = []
    if shutil.which("nice"):
        launcher.extend(["nice", "-n", "15"])
    if shutil.which("ionice"):
        launcher.extend(["ionice", "-c", "3"])

    cwd = str(Path(__file__).resolve().parents[2])
    try:
        proc = subprocess.Popen(
            launcher + cmd,
            cwd=cwd,
            env=compute_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return False, f"Pipeline-Start fehlgeschlagen: {exc}"

    with _lock:
        _worker = proc
    _write_pid(proc.pid)

    def _watch() -> None:
        global _worker
        proc.wait()
        with _lock:
            if _worker is proc:
                _worker = None
        _clear_pid()

    threading.Thread(target=_watch, name="watch-queue-worker", daemon=True).start()
    return True, "Pipeline-Worker gestartet."


def is_running(podcast_id: int) -> bool:
    """True if this podcast has a pending/running queue job (or legacy pid)."""
    from apofika.db import list_queue_jobs

    return any(
        j.podcast_id == podcast_id and j.status in ("pending", "running")
        for j in list_queue_jobs(active_only=True, limit=200)
    )


def start_process_job(podcast_id: int, *, force: bool = False) -> tuple[bool, str]:
    """Enqueue co-publish batch for one podcast and ensure the global worker runs."""
    from apofika.db import get_podcast, set_process_run
    from apofika.queue import enqueue_podcast_scan

    podcast = get_podcast(podcast_id)
    if not podcast:
        return False, "Feed nicht gefunden."
    try:
        guids = enqueue_podcast_scan(podcast, force_all_in_batch=force)
    except Exception as exc:  # noqa: BLE001
        return False, f"Scan fehlgeschlagen: {exc}"

    started, msg = ensure_queue_worker()
    if guids:
        set_process_run(
            podcast.id,
            status="running" if is_queue_worker_running() else "done",
            message=f"{len(guids)} Episode(n) in Pipeline: {', '.join(guids[:3])}"
            + ("…" if len(guids) > 3 else ""),
            started=True,
        )
        return True, f"{len(guids)} Episode(n) eingereiht. {msg}"
    set_process_run(
        podcast.id,
        status="done",
        message="Keine neuen Episoden im Co-Publish-Fenster.",
        finished=True,
    )
    return True, "Keine neuen Episoden zum Einreihen."
