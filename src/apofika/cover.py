"""Badge podcast cover art so Splitcasts feeds are visually distinct."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from apofika.paths import ASSETS_DIR, ensure_feed_dirs, feed_dir

PLACEHOLDER_MP3 = ASSETS_DIR / "placeholder.mp3"
COVER_NAME = "cover.jpg"
RED = (196, 18, 48)


def cover_path(slug: str) -> Path:
    return feed_dir(slug) / COVER_NAME


def placeholder_mp3_path(slug: str) -> Path:
    """Per-feed copy of the silent placeholder enclosure."""
    ensure_feed_dirs(slug)
    dest = feed_dir(slug) / "processed" / "placeholder.mp3"
    if PLACEHOLDER_MP3.exists() and (
        not dest.exists() or dest.stat().st_size != PLACEHOLDER_MP3.stat().st_size
    ):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(PLACEHOLDER_MP3.read_bytes())
    return dest


def _load_image(source: str | Path) -> Image.Image:
    if isinstance(source, Path) or (isinstance(source, str) and not source.startswith("http")):
        path = Path(source)
        return Image.open(path).convert("RGB")
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        res = client.get(str(source))
        res.raise_for_status()
        return Image.open(io.BytesIO(res.content)).convert("RGB")


def apply_red_corner(image: Image.Image, *, fraction: float = 0.22) -> Image.Image:
    """Draw a solid red triangle in the top-left corner."""
    out = image.copy()
    draw = ImageDraw.Draw(out)
    w, h = out.size
    size = max(24, int(min(w, h) * fraction))
    draw.polygon([(0, 0), (size, 0), (0, size)], fill=RED)
    return out


def ensure_badged_cover(slug: str, source_image_url: str | None) -> Path | None:
    """
    Build/cache ``data/feeds/{slug}/cover.jpg`` with a red top-left corner.
    Returns the local path, or None if no source image is available.
    """
    ensure_feed_dirs(slug)
    dest = cover_path(slug)
    if not source_image_url:
        return dest if dest.exists() else None

    # Refresh when missing; callers can unlink to force rebuild.
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    try:
        img = _load_image(source_image_url)
    except Exception:
        return dest if dest.exists() else None

    # Podcast apps prefer reasonably large square art
    side = max(img.size)
    target = 1400 if side >= 600 else max(side, 600)
    img = img.resize((target, target), Image.Resampling.LANCZOS)
    badged = apply_red_corner(img)
    dest.parent.mkdir(parents=True, exist_ok=True)
    badged.save(dest, format="JPEG", quality=90, optimize=True)
    return dest


def refresh_badged_cover(slug: str, source_image_url: str | None) -> Path | None:
    dest = cover_path(slug)
    if dest.exists():
        dest.unlink()
    return ensure_badged_cover(slug, source_image_url)
