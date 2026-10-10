"""Splitcasts FastAPI app: admin UI + public feeds/media."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from apofika import config
from apofika.auth import configured_password_ok
from apofika.db import (
    create_podcast,
    delete_snippet,
    get_episode_by_guid,
    get_podcast_by_slug,
    init_db,
    list_podcasts,
    list_snippets,
    upsert_snippet,
    validate_slug,
)
from apofika.fetch import parse_recent
from apofika.paths import (
    STATIC_DIR,
    TEMPLATES_DIR,
    UI_RECENT_EPISODES,
    ensure_dirs,
    ensure_feed_dirs,
    feed_processed_dir,
    feed_snippets_dir,
    feed_xml_path,
)
from apofika.worker import process_podcast

STATUS_LABELS = {
    "split": "gesplittet",
    "processing": "in Arbeit",
    "error": "Fehler",
    "new": "nicht gesplittet",
    "skipped": "übersprungen",
    "purged": "gelöscht (Datei)",
    "unknown": "unbekannt",
}


def create_app() -> FastAPI:
    ensure_dirs()
    init_db()
    app = FastAPI(title="Splitcasts", version="0.2.0")
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.session_secret(),
        session_cookie="splitcasts_session",
        same_site="lax",
        https_only=False,
    )
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def flash(request: Request, message: str, error: bool = False) -> None:
        request.session["flash"] = message
        request.session["flash_error"] = error

    def pop_flash(request: Request) -> tuple[str | None, bool]:
        msg = request.session.pop("flash", None)
        err = bool(request.session.pop("flash_error", False))
        return msg, err

    def require_auth(request: Request) -> RedirectResponse | None:
        if not request.session.get("auth"):
            return RedirectResponse("/login", status_code=303)
        return None

    def render(request: Request, name: str, **ctx):
        flash_msg, flash_error = pop_flash(request)
        return templates.TemplateResponse(
            request,
            name,
            {
                "request": request,
                "flash": flash_msg,
                "flash_error": flash_error,
                **ctx,
            },
        )

    @app.get("/health")
    def health() -> Response:
        return Response("ok", media_type="text/plain")

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        if request.session.get("auth"):
            return RedirectResponse("/", status_code=303)
        return render(request, "login.html")

    @app.post("/login")
    async def login_submit(request: Request, password: str = Form(...)):
        if configured_password_ok(password):
            request.session["auth"] = True
            return RedirectResponse("/", status_code=303)
        flash(request, "Falsches Passwort.", error=True)
        return RedirectResponse("/login", status_code=303)

    @app.post("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        if (redir := require_auth(request)):
            return redir
        return render(request, "index.html", podcasts=list_podcasts())

    @app.get("/feeds/new", response_class=HTMLResponse)
    def feed_new_form(request: Request):
        if (redir := require_auth(request)):
            return redir
        return render(request, "feed_new.html")

    @app.post("/feeds/new")
    async def feed_new_submit(
        request: Request,
        title: str = Form(...),
        slug: str = Form(...),
        source_rss_url: str = Form(...),
    ):
        if (redir := require_auth(request)):
            return redir
        try:
            slug_norm = validate_slug(slug)
            podcast = create_podcast(slug_norm, title, source_rss_url)
            ensure_feed_dirs(podcast.slug)
            flash(request, f"Feed „{podcast.title}“ angelegt.")
            return RedirectResponse(f"/feeds/{podcast.slug}", status_code=303)
        except Exception as exc:
            flash(request, str(exc), error=True)
            return RedirectResponse("/feeds/new", status_code=303)

    # Public output feed — must be registered before /feeds/{slug}
    @app.get("/feeds/{slug}.xml")
    def public_feed(slug: str):
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            return Response("Not found", status_code=404)
        path = feed_xml_path(slug)
        if not path.exists():
            podcast = get_podcast_by_slug(slug)
            if podcast:
                from apofika.worker import rebuild_podcast_feed

                rebuild_podcast_feed(podcast, base_url=config.public_base())
        if not path.exists():
            return Response("Feed not generated yet", status_code=404)
        return Response(
            path.read_text(encoding="utf-8"),
            media_type="application/rss+xml; charset=utf-8",
        )

    @app.get("/feeds/{slug}", response_class=HTMLResponse)
    def feed_detail(request: Request, slug: str):
        if (redir := require_auth(request)):
            return redir
        if slug.endswith(".xml") or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            flash(request, "Feed nicht gefunden.", error=True)
            return RedirectResponse("/", status_code=303)
        podcast = get_podcast_by_slug(slug)
        if not podcast:
            flash(request, "Feed nicht gefunden.", error=True)
            return RedirectResponse("/", status_code=303)

        recent = []
        recent_error = None
        try:
            items, _ = parse_recent(podcast.source_rss_url, limit=UI_RECENT_EPISODES)
            for meta in items:
                ep = get_episode_by_guid(podcast.id, meta.guid)
                status = ep.status if ep else "new"
                recent.append(
                    {
                        "title": meta.title,
                        "published": meta.published,
                        "status": status,
                        "status_label": STATUS_LABELS.get(status, status),
                        "error": ep.error_message if ep else None,
                    }
                )
        except Exception as exc:
            recent_error = str(exc)

        snippets = {s.position: s for s in list_snippets(podcast.id)}
        return render(
            request,
            "feed_detail.html",
            podcast=podcast,
            recent=recent,
            recent_error=recent_error,
            snippets=snippets,
        )

    @app.post("/feeds/{slug}/process")
    async def feed_process(request: Request, slug: str):
        if (redir := require_auth(request)):
            return redir
        podcast = get_podcast_by_slug(slug)
        if not podcast:
            flash(request, "Feed nicht gefunden.", error=True)
            return RedirectResponse("/", status_code=303)
        result = process_podcast(podcast, base_url=config.public_base())
        flash(request, result.message, error=bool(result.error and not result.skipped))
        return RedirectResponse(f"/feeds/{slug}", status_code=303)

    @app.post("/feeds/{slug}/snippets/{position}")
    async def snippet_upload(
        request: Request,
        slug: str,
        position: int,
        file: UploadFile = File(...),
    ):
        if (redir := require_auth(request)):
            return redir
        podcast = get_podcast_by_slug(slug)
        if not podcast or position < 1 or position > 3:
            flash(request, "Ungültiger Upload.", error=True)
            return RedirectResponse("/", status_code=303)

        ensure_feed_dirs(podcast.slug)
        original = Path(file.filename or f"snippet{position}.wav").name
        ext = Path(original).suffix.lower() or ".wav"
        if ext not in {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}:
            flash(request, "Nur Audio-Dateien erlaubt.", error=True)
            return RedirectResponse(f"/feeds/{slug}", status_code=303)

        dest_name = f"snippet{position}{ext}"
        dest = feed_snippets_dir(podcast.slug) / dest_name
        # remove previous file for this slot if name differs
        old = delete_snippet(podcast.id, position)
        if old:
            old_path = feed_snippets_dir(podcast.slug) / old
            if old_path.exists() and old_path != dest:
                old_path.unlink()

        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        upsert_snippet(podcast.id, position, dest_name)
        flash(request, f"Snippet {position} gespeichert.")
        return RedirectResponse(f"/feeds/{slug}", status_code=303)

    @app.post("/feeds/{slug}/snippets/{position}/delete")
    async def snippet_delete(request: Request, slug: str, position: int):
        if (redir := require_auth(request)):
            return redir
        podcast = get_podcast_by_slug(slug)
        if not podcast:
            return RedirectResponse("/", status_code=303)
        filename = delete_snippet(podcast.id, position)
        if filename:
            path = feed_snippets_dir(podcast.slug) / filename
            if path.exists():
                path.unlink()
        flash(request, f"Snippet {position} gelöscht.")
        return RedirectResponse(f"/feeds/{slug}", status_code=303)

    @app.get("/media/{slug}/{filename}")
    def public_media(slug: str, filename: str):
        safe_slug = Path(slug).name
        safe_name = Path(filename).name
        path = feed_processed_dir(safe_slug) / safe_name
        if not path.exists() or not path.is_file():
            return Response("Not found", status_code=404)
        return FileResponse(path, media_type="audio/mpeg", filename=safe_name)

    # Back-compat for old single-feed URL
    @app.get("/feed.xml")
    def legacy_feed():
        return RedirectResponse("/feeds/apofika.xml", status_code=307)

    return app


app = create_app()
