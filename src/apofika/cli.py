"""Typer CLI for ApoFiKa chapter pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
import uvicorn

from apofika.detect import extract_jingle, parse_timestamp
from apofika.paths import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    JINGLE_REF_PATH,
    SOURCE_FEED_URL,
    ensure_dirs,
)
from apofika.pipeline import process_latest

app = typer.Typer(
    name="apofika",
    help="Add chapter markers to Apokalypse & Filterkaffee episodes.",
    add_completion=False,
)


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
        help="Public base URL for enclosure links (default http://127.0.0.1:8787)",
    ),
    jingle: Path = typer.Option(JINGLE_REF_PATH, "--jingle", help="Jingle reference WAV"),
) -> None:
    """Fetch the latest episode, detect jingles, embed chapters, refresh local feed."""
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
    if result.processed_path:
        typer.echo(f"Processed MP3: {result.processed_path}")
    if result.chapters_path:
        typer.echo(f"Chapters JSON: {result.chapters_path}")


@app.command("serve")
def serve_cmd(
    host: str = typer.Option(DEFAULT_HOST, "--host"),
    port: int = typer.Option(DEFAULT_PORT, "--port"),
) -> None:
    """Serve local RSS feed and processed media files."""
    ensure_dirs()
    typer.echo(f"Serving feed at http://{host}:{port}/feed.xml")
    uvicorn.run("apofika.serve:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
