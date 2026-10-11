"""Background process jobs via subprocess so the web server stays responsive."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from apofika import config
from apofika.db import get_podcast, get_process_run, set_process_run
from apofika.paths import DATA_DIR
from apofika.runtime import compute_env

_lock = threading.Lock()
_procs: dict[int, subprocess.Popen] = {}


def _pid_path(podcast_id: int) -> Path:
    return DATA_DIR / "jobs" / f"process-{podcast_id}.pid"


def _write_pid(podcast_id: int, pid: int) -> None:
    path = _pid_path(podcast_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def _clear_pid(podcast_id: int) -> None:
    path = _pid_path(podcast_id)
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


def _tracked_running(podcast_id: int) -> bool:
    with _lock:
        proc = _procs.get(podcast_id)
        if proc is not None:
            if proc.poll() is None:
                return True
            _procs.pop(podcast_id, None)
            _clear_pid(podcast_id)
    path = _pid_path(podcast_id)
    if path.exists():
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except ValueError:
            _clear_pid(podcast_id)
            return False
        if _pid_alive(pid):
            return True
        _clear_pid(podcast_id)
    return False


def is_running(podcast_id: int) -> bool:
    return _tracked_running(podcast_id)


def _apofika_cmd() -> list[str]:
    """Prefer the installed console script next to this interpreter."""
    bindir = Path(sys.executable).resolve().parent
    script = bindir / "apofika"
    if script.is_file() and os.access(script, os.X_OK):
        return [str(script)]
    which = shutil.which("apofika")
    if which:
        return [which]
    return [sys.executable, "-m", "apofika.cli"]


def start_process_job(podcast_id: int, *, force: bool = False) -> tuple[bool, str]:
    """Start `apofika process-slug` in a nice'd subprocess. Returns (started, message)."""
    podcast = get_podcast(podcast_id)
    if not podcast:
        return False, "Feed nicht gefunden."

    if _tracked_running(podcast_id):
        run = get_process_run(podcast_id)
        return False, run.message or "Verarbeitung läuft bereits."

    set_process_run(
        podcast_id,
        status="running",
        message="Verarbeitung gestartet… Episode wird geladen und analysiert.",
        started=True,
    )

    cmd = _apofika_cmd() + [
        "process-slug",
        podcast.slug,
        "--public-base",
        config.public_base(),
    ]
    if force:
        cmd.append("--force")

    # Prefer nice/ionice so LAN services (status page, tunnel) keep CPU time.
    launcher: list[str] = []
    if shutil.which("nice"):
        launcher.extend(["nice", "-n", "15"])
    if shutil.which("ionice"):
        launcher.extend(["ionice", "-c", "3"])

    # Project root: src/apofika/jobs.py -> parents[2]
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
        set_process_run(
            podcast_id,
            status="error",
            message=f"Verarbeitung konnte nicht gestartet werden: {exc}",
            finished=True,
        )
        return False, f"Start fehlgeschlagen: {exc}"

    with _lock:
        _procs[podcast_id] = proc
    _write_pid(podcast_id, proc.pid)

    def _watch() -> None:
        code = proc.wait()
        with _lock:
            _procs.pop(podcast_id, None)
        _clear_pid(podcast_id)
        run = get_process_run(podcast_id)
        # CLI updates DB on success; recover if the child died without finishing.
        if run.status == "running":
            set_process_run(
                podcast_id,
                status="error",
                message=(
                    f"Verarbeitung abgebrochen (Exit {code})."
                    if code
                    else "Verarbeitung beendet ohne Status-Update."
                ),
                finished=True,
            )

    threading.Thread(
        target=_watch,
        name=f"watch-process-{podcast.slug}",
        daemon=True,
    ).start()
    return True, "Verarbeitung gestartet."
