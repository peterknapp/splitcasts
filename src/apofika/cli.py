"""Typer CLI for Splitcasts / ApoFiKa chapter pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
import uvicorn

from apofika.auth import hash_password
from apofika.detect import extract_jingle, parse_timestamp
from apofika.paths import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    JINGLE_REF_PATH,
    SOURCE_FEED_URL,
    ensure_dirs,
)
from apofika.pipeline import process_latest
from apofika.runtime import limit_compute_threads

app = typer.Typer(
    name="apofika",
    help="Splitcasts: chapter markers for podcast feeds.",
    add_completion=False,
)

# Cap BLAS/OpenMP early so heavy detection does not starve the Pi.
limit_compute_threads(1)


@app.command("download")
def download_cmd(
    feed_url: str = typer.Option(SOURCE_FEED_URL, "--feed", help="Source RSS URL"),
) -> None:
    """Download the latest episode MP3 without processing chapters."""
    from apofika.fetch import download_episode, parse_latest

    ensure_dirs()
    meta, _ = parse_latest(feed_url)
    path = download_episode(meta)
    typer.echo(f"Downloaded: {path}")
    typer.echo(f"Title: {meta.title}")
    typer.echo(f"GUID: {meta.guid}")


@app.command("extract-jingle")
def extract_jingle_cmd(
    source: Path = typer.Option(..., "--from", help="Source MP3 path"),
    start: str = typer.Option(..., "--start", help="Start time MM:SS or seconds"),
    duration: float = typer.Option(3.0, "--dur", help="Clip duration in seconds"),
    dest: Path = typer.Option(JINGLE_REF_PATH, "--dest", help="Output WAV path"),
) -> None:
    """Extract a jingle reference clip from an episode."""
    ensure_dirs()
    start_sec = parse_timestamp(start)
    out = extract_jingle(source, start_sec=start_sec, duration_sec=duration, dest=dest)
    typer.echo(f"Wrote jingle reference: {out} (start={start_sec}s, dur={duration}s)")


@app.command("process")
def process_cmd(
    feed_url: str = typer.Option(SOURCE_FEED_URL, "--feed", help="Source RSS URL"),
    force: bool = typer.Option(False, "--force", help="Reprocess even if guid known"),
    threshold: float = typer.Option(0.55, "--threshold", help="NCC peak threshold"),
    min_distance: float = typer.Option(
        60.0, "--min-distance", help="Minimum seconds between jingle hits"
    ),
    public_base: Optional[str] = typer.Option(
        None,
        "--public-base",
        help="Public base URL for enclosure links",
    ),
    jingle: Path = typer.Option(JINGLE_REF_PATH, "--jingle", help="Jingle reference WAV"),
) -> None:
    """Legacy single-feed process (prefer process-all / web UI)."""
    result = process_latest(
        feed_url=feed_url,
        force=force,
        threshold=threshold,
        min_distance_sec=min_distance,
        public_base=public_base,
        jingle_path=jingle,
    )
    typer.echo(result.message)
    if result.jingle_times is not None:
        typer.echo("Jingle times: " + ", ".join(f"{t:.1f}s" for t in result.jingle_times))
    if result.warnings:
        for w in result.warnings:
            typer.echo(f"Warning: {w}")


@app.command("process-all")
def process_all_cmd(
    force: bool = typer.Option(False, "--force"),
    public_base: Optional[str] = typer.Option(None, "--public-base"),
) -> None:
    """Process latest episode for every active podcast in the DB."""
    from apofika.db import init_db
    from apofika.worker import process_all

    init_db()
    results = process_all(force=force, base_url=public_base)
    if not results:
        typer.echo("No active podcasts. Run `apofika migrate` or create feeds in the UI.")
        return
    for result in results:
        typer.echo(f"[{result.slug}] {result.message}")


@app.command("process-slug")
def process_slug_cmd(
    slug: str = typer.Argument(..., help="Podcast slug from the admin UI"),
    force: bool = typer.Option(False, "--force"),
    public_base: Optional[str] = typer.Option(None, "--public-base"),
) -> None:
    """Process one podcast (used by the web UI as a separate low-priority process)."""
    from apofika.db import get_podcast_by_slug, init_db, set_process_run
    from apofika.worker import process_podcast

    init_db()
    podcast = get_podcast_by_slug(slug)
    if not podcast:
        typer.echo(f"Unknown slug: {slug}", err=True)
        raise typer.Exit(code=1)

    set_process_run(
        podcast.id,
        status="running",
        message=f"Verarbeite {podcast.title}…",
        started=True,
    )
    result = process_podcast(podcast, force=force, base_url=public_base)
    error = bool(result.error and not result.skipped)
    set_process_run(
        podcast.id,
        status="error" if error else "done",
        message=result.message,
        finished=True,
    )
    typer.echo(result.message)
    if error:
        raise typer.Exit(code=1)


@app.command("migrate")
def migrate_cmd() -> None:
    """Create ApoFiKa podcast and import legacy data/ files."""
    from apofika.worker import migrate_apofika_legacy

    podcast = migrate_apofika_legacy()
    if podcast:
        typer.echo(f"Migrated/ready: {podcast.title} (/{podcast.slug})")
    else:
        typer.echo("Nothing to migrate.")


@app.command("hash-password")
def hash_password_cmd(
    password: str = typer.Option(..., "--password", prompt=True, hide_input=True),
) -> None:
    """Print a PBKDF2 hash for SPLITCASTS_PASSWORD_HASH."""
    typer.echo(hash_password(password))


@app.command("serve")
def serve_cmd(
    host: str = typer.Option(DEFAULT_HOST, "--host"),
    port: int = typer.Option(DEFAULT_PORT, "--port"),
) -> None:
    """Serve Splitcasts admin UI, output feeds and media."""
    from apofika.db import init_db

    ensure_dirs()
    init_db()
    typer.echo(f"Splitcasts UI at http://{host}:{port}/")
    typer.echo(f"Public feeds at http://{host}:{port}/feeds/{{slug}}.xml")
    uvicorn.run("apofika.webapp:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
