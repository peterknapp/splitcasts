"""Local FastAPI server for RSS + media."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response

from apofika.paths import FEED_PATH, PROCESSED_DIR, ensure_dirs


def create_app(
    feed_path: Path = FEED_PATH,
    media_dir: Path = PROCESSED_DIR,
) -> FastAPI:
    ensure_dirs()
    app = FastAPI(title="ApoFiKa Chapters", version="0.1.0")

    @app.get("/")
    def root() -> dict:
        return {
            "service": "apofika-chapters",
            "feed": "/feed.xml",
            "media": "/media/{filename}",
        }

    @app.get("/feed.xml")
    def feed() -> Response:
        if not feed_path.exists():
            raise HTTPException(
                status_code=404,
                detail="Feed not generated yet. Run `apofika process` first.",
            )
        content = feed_path.read_text(encoding="utf-8")
        return Response(content=content, media_type="application/rss+xml; charset=utf-8")

    @app.get("/media/{filename}")
    def media(filename: str) -> FileResponse:
        # prevent path traversal
        safe = Path(filename).name
        path = media_dir / safe
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="Media file not found")
        return FileResponse(
            path,
            media_type="audio/mpeg",
            filename=safe,
        )

    @app.get("/health")
    def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    return app


app = create_app()
