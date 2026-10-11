"""Splitcasts FastAPI app: admin UI + public feeds/media."""

from __future__ import annotations

import mimetypes
import re
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
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
    get_process_run,
    init_db,
    list_podcasts,
    list_snippets,
    set_process_run,
    suggest_slug,
    update_podcast_image,
    upsert_snippet,
    validate_slug,
)
from apofika.fetch import channel_meta, fetch_parsed, parse_recent
from apofika.formatting import format_published
from apofika.jobs import is_running, start_process_job
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


def _fetch_channel_image(source_rss_url: str) -> str | None:
    try:
        parsed = fetch_parsed(source_rss_url)
        return channel_meta(parsed).get("image")
    except Exception:
        return None

STATUS_LABELS = {
    "split": "gesplittet",
    "processing": "in Arbeit",
    "error": "Fehler",
    "new": "nicht gesplittet",
    "skipped": "übersprungen",
    "purged": "gelöscht (Datei)",
    "unknown": "unbekannt",
}


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" in accept or request.query_params.get("format") == "json"


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
        base = config.public_base()
        podcasts = list_podcasts()
        # Backfill missing cover art once when listing
        for podcast in podcasts:
            if not podcast.image_url:
                image = _fetch_channel_image(podcast.source_rss_url)
                if image:
                    update_podcast_image(podcast.id, image)
                    podcast.image_url = image
        return render(
            request,
            "index.html",
            podcasts=podcasts,
            public_base=base,
        )

    @app.get("/feeds/new", response_class=HTMLResponse)
    def feed_new_form(request: Request):
        if (redir := require_auth(request)):
            return redir
        return render(request, "feed_new.html", step=1)

    @app.post("/feeds/new/preview", response_class=HTMLResponse)
    async def feed_new_preview(request: Request, source_rss_url: str = Form(...)):
        if (redir := require_auth(request)):
            return redir
        url = source_rss_url.strip()
        try:
            parsed = fetch_parsed(url)
            meta = channel_meta(parsed)
            title = (meta.get("title") or "").strip() or "Podcast"
            slug = suggest_slug(title, url)
            # Avoid colliding with existing slug by appending -2, -3, ...
            base_slug = slug
            n = 2
            while get_podcast_by_slug(slug) is not None:
                slug = f"{base_slug}-{n}"
                n += 1
            return render(
                request,
                "feed_new.html",
                step=2,
                source_rss_url=url,
                title=title,
                slug=slug,
                image_url=meta.get("image"),
            )
        except Exception as exc:
            flash(request, f"Feed konnte nicht geladen werden: {exc}", error=True)
            return render(
                request,
                "feed_new.html",
                step=1,
                source_rss_url=url,
            )

    @app.post("/feeds/new")
    async def feed_new_submit(
        request: Request,
        title: str = Form(...),
        slug: str = Form(...),
        source_rss_url: str = Form(...),
        image_url: str = Form(""),
    ):
        if (redir := require_auth(request)):
            return redir
        try:
            slug_norm = validate_slug(slug)
            image = image_url.strip() or _fetch_channel_image(source_rss_url)
            podcast = create_podcast(
                slug_norm,
                title.strip(),
                source_rss_url.strip(),
                image_url=image or None,
            )
            ensure_feed_dirs(podcast.slug)
            flash(request, f"Feed „{podcast.title}“ angelegt.")
            return RedirectResponse(f"/feeds/{podcast.slug}", status_code=303)
        except Exception as exc:
            flash(request, str(exc), error=True)
            return render(
                request,
                "feed_new.html",
                step=2,
                source_rss_url=source_rss_url,
                title=title,
                slug=slug,
                image_url=image_url or None,
            )

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

    def _load_recent_episodes(podcast) -> tuple[list[dict], str | None]:
        recent: list[dict] = []
        try:
            items, _ = parse_recent(podcast.source_rss_url, limit=UI_RECENT_EPISODES)
            for meta in items:
                ep = get_episode_by_guid(podcast.id, meta.guid)
                status = ep.status if ep else "new"
                recent.append(
                    {
                        "guid": meta.guid,
                        "title": meta.title,
                        "published": meta.published,
                        "published_fmt": format_published(meta.published),
                        "status": status,
                        "status_label": STATUS_LABELS.get(status, status),
                        "error": ep.error_message if ep else None,
                    }
                )
            return recent, None
        except Exception as exc:  # noqa: BLE001
            return [], str(exc)

    def _process_status_payload(podcast_id: int) -> dict:
        run = get_process_run(podcast_id)
        running = is_running(podcast_id)
        # After a server restart the DB can still say "running" while no thread exists.
        if run.status == "running" and not running:
            run = set_process_run(
                podcast_id,
                status="error",
                message="Verarbeitung wurde unterbrochen (Server-Neustart). Bitte erneut starten.",
                finished=True,
            )
        return {
            "status": run.status,
            "message": run.message,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "running": running,
        }

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

        snippets = {s.position: s for s in list_snippets(podcast.id)}
        return render(
            request,
            "feed_detail.html",
            podcast=podcast,
            snippets=snippets,
            process_status=_process_status_payload(podcast.id),
            public_feed_url=f"{config.public_base()}/feeds/{podcast.slug}.xml",
        )

    @app.get("/feeds/{slug}/episodes.json")
    def feed_episodes_json(request: Request, slug: str):
        if not request.session.get("auth"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        podcast = get_podcast_by_slug(slug)
        if not podcast:
            return JSONResponse({"error": "not_found"}, status_code=404)

        if not podcast.image_url:
            image = _fetch_channel_image(podcast.source_rss_url)
            if image:
                update_podcast_image(podcast.id, image)
                podcast.image_url = image

        recent, recent_error = _load_recent_episodes(podcast)
        return JSONResponse(
            {
                "episodes": recent,
                "error": recent_error,
                "image_url": podcast.image_url,
                "process": _process_status_payload(podcast.id),
            }
        )

    @app.get("/feeds/{slug}/process-status")
    def feed_process_status(request: Request, slug: str):
        if not request.session.get("auth"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        podcast = get_podcast_by_slug(slug)
        if not podcast:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return JSONResponse(_process_status_payload(podcast.id))

    @app.post("/feeds/{slug}/process")
    async def feed_process(request: Request, slug: str):
        if (redir := require_auth(request)):
            return redir
        podcast = get_podcast_by_slug(slug)
        if not podcast:
            if _wants_json(request):
                return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
            flash(request, "Feed nicht gefunden.", error=True)
            return RedirectResponse("/", status_code=303)

        started, message = start_process_job(podcast.id)
        payload = {
            "ok": True,
            "started": started,
            "message": message,
            "process": _process_status_payload(podcast.id),
        }
        if _wants_json(request):
            return JSONResponse(payload)
        flash(request, message, error=not started and "läuft bereits" not in message.lower())
        return RedirectResponse(f"/feeds/{slug}", status_code=303)

    @app.post("/feeds/{slug}/process-status/dismiss")
    async def feed_process_dismiss(request: Request, slug: str):
        if (redir := require_auth(request)):
            return redir
        podcast = get_podcast_by_slug(slug)
        if not podcast:
            return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
        if is_running(podcast.id):
            return JSONResponse(
                {"ok": False, "error": "running", "process": _process_status_payload(podcast.id)},
                status_code=409,
            )
        set_process_run(
            podcast.id,
            status="idle",
            message=None,
            finished=True,
        )
        return JSONResponse({"ok": True, "process": _process_status_payload(podcast.id)})

    @app.get("/feeds/{slug}/snippets/{position}/audio")
    def snippet_audio(request: Request, slug: str, position: int):
        if (redir := require_auth(request)):
            return redir
        podcast = get_podcast_by_slug(slug)
        if not podcast or position < 1 or position > 3:
            return Response("Not found", status_code=404)
        snippets = {s.position: s for s in list_snippets(podcast.id)}
        snip = snippets.get(position)
        if not snip:
            return Response("Not found", status_code=404)
        path = feed_snippets_dir(podcast.slug) / snip.filename
        if not path.exists():
            return Response("Not found", status_code=404)
        media_type, _ = mimetypes.guess_type(str(path))
        return FileResponse(
            path,
            media_type=media_type or "application/octet-stream",
            filename=snip.filename,
        )

    @app.post("/feeds/{slug}/jingle/preview")
    async def jingle_preview(
        request: Request,
        slug: str,
        guid: str = Form(...),
        start: str = Form(...),
        duration: float = Form(3.0),
    ):
        if (redir := require_auth(request)):
            return redir
        podcast = get_podcast_by_slug(slug)
        if not podcast:
            return Response("Not found", status_code=404)
        try:
            from apofika.jingle_edit import ensure_episode_audio, render_clip_wav_bytes

            source = ensure_episode_audio(podcast, guid)
            wav = render_clip_wav_bytes(source, start, duration)
            return Response(wav, media_type="audio/wav")
        except Exception as exc:
            return Response(str(exc), status_code=400, media_type="text/plain")

    @app.post("/feeds/{slug}/jingle/save")
    async def jingle_save(
        request: Request,
        slug: str,
        guid: str = Form(...),
        start: str = Form(...),
        duration: float = Form(3.0),
        position: int = Form(...),
    ):
        if (redir := require_auth(request)):
            return redir
        podcast = get_podcast_by_slug(slug)
        if not podcast:
            flash(request, "Feed nicht gefunden.", error=True)
            return RedirectResponse("/", status_code=303)
        try:
            from apofika.jingle_edit import save_clip_to_slot

            save_clip_to_slot(podcast, guid, start, duration, position)
            flash(request, f"Jingle in Slot {position} gespeichert.")
        except Exception as exc:
            flash(request, str(exc), error=True)
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
