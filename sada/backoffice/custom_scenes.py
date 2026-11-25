"""Custom live slates (cartons/images personnalisés) per mosque: upload, storage and listing.

Files live under `data/backoffice/custom_scenes/<mosque_slug>/<slug>.png`, normalized to RGB PNG
(max 1920x1080) on upload. Metadata (scene list, saved transition) is a `manifest.json` next to the images;
every read-modify-write of it runs under a per-mosque lock (threads of this process, and other processes
through a lock file).
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import io
import json
import os
import re
import tempfile
import threading
import unicodedata
from collections.abc import Iterator
from pathlib import Path

from PIL import Image

from .. import paths, transitions
from ..i18n import _
from . import db

DIR = paths.DATA / "backoffice" / "custom_scenes"
CATEGORIES = ("attente", "pause", "collecte", "autre")
EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_BYTES = 5 * 1024 * 1024
MAX_SCENES = 12
MAX_LABEL = 60
MAX_DIM = (1920, 1080)
MAX_PIXELS = 40_000_000  # decoded size cap: a small file can still inflate to gigabytes of pixels
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


def _slugify(label: str) -> str:
    norm = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")[:36]
    return slug or "carton"


def _mosque_dir(mosque: dict) -> Path:
    return DIR / mosque["slug"]


def _manifest_path(mosque: dict) -> Path:
    return _mosque_dir(mosque) / "manifest.json"


def _read_manifest(mosque: dict) -> dict:
    p = _manifest_path(mosque)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


@contextlib.contextmanager
def _locked(mosque: dict) -> Iterator[None]:
    """Serialises the read-modify-write of a mosque's manifest (and its image files)."""
    with _LOCKS_GUARD:
        thread_lock = _LOCKS.setdefault(mosque["slug"], threading.Lock())
    d = _mosque_dir(mosque)
    d.mkdir(parents=True, exist_ok=True)
    with thread_lock, open(d / ".lock", "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _write_manifest(mosque: dict, data: dict) -> None:
    d = _mosque_dir(mosque)
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix="manifest.", suffix=".tmp")  # unique: never shared by two writers
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, indent=1))
        os.replace(tmp, _manifest_path(mosque))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def get_transition(mosque: dict) -> str:
    val = _read_manifest(mosque).get("transition")
    return val if val in transitions.TRANSITIONS else transitions.DEFAULT_TRANSITION


def set_transition(mosque: dict, mode: str) -> str:
    if mode not in transitions.TRANSITIONS:
        raise ValueError(_("unknown transition: {mode}", mode=mode))
    with _locked(mosque):
        data = _read_manifest(mosque)
        data["transition"] = mode
        _write_manifest(mosque, data)
    return mode


def _raw_list(mosque: dict) -> list[dict]:
    raw = _read_manifest(mosque).get("scenes")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("slug"), str) and SLUG_RE.match(item["slug"]):
            out.append(item)
    return out


def _save_list(mosque: dict, items: list[dict]) -> None:
    data = _read_manifest(mosque)
    data["scenes"] = items
    _write_manifest(mosque, data)


def _format(item: dict) -> dict:
    slug = item["slug"]
    ver = int(hashlib.sha1((item.get("updated_at") or slug).encode("utf-8")).hexdigest()[:6], 16)  # stable across runs
    return {
        "id": f"custom:{slug}",
        "slug": slug,
        "kind": "custom",
        "custom": True,
        "category": item.get("category", "autre"),
        "label": item.get("label", slug),
        "preview_url": f"/api/v1/live/regie/custom-scenes/{slug}/image?v={ver:x}",
        "updated_at": item.get("updated_at", ""),
    }


def list_scenes(conn, mosque: dict) -> list[dict]:
    del conn
    d = _mosque_dir(mosque)
    return [_format(item) for item in _raw_list(mosque) if (d / f"{item['slug']}.png").is_file()]


def get_scene(conn, mosque: dict, slug: str) -> dict | None:
    del conn
    if not SLUG_RE.match(slug):
        return None
    for item in _raw_list(mosque):
        if item["slug"] == slug and (_mosque_dir(mosque) / f"{slug}.png").is_file():
            return _format(item)
    return None


def image_path(mosque: dict, slug: str) -> Path | None:
    if not SLUG_RE.match(slug):
        return None
    p = _mosque_dir(mosque) / f"{slug}.png"
    return p if p.is_file() else None


def image_bytes(mosque: dict, slug: str) -> bytes | None:
    p = image_path(mosque, slug)
    return p.read_bytes() if p is not None else None


def prepare_image(filename: str, content: bytes) -> bytes:
    """Validates an upload and returns it as a bounded RGB PNG. CPU-bound: call it off the event loop."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in EXT:
        raise ValueError(_("accepted format: png, jpg or webp"))
    if not content:
        raise ValueError(_("empty image file"))
    if len(content) > MAX_BYTES:
        raise ValueError(_("image too large (5 MB maximum)"))
    try:
        im = Image.open(io.BytesIO(content))
        if im.width * im.height > MAX_PIXELS:  # header only: nothing is decoded yet
            raise ValueError(_("image dimensions too large"))
        im.load()
        if min(im.size) < 64:
            raise ValueError(_("image too small (64 px minimum)"))
        im = im.convert("RGB")
        if im.width > MAX_DIM[0] or im.height > MAX_DIM[1]:
            im.thumbnail(MAX_DIM, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except ValueError:
        raise
    except Exception:
        raise ValueError(_("unreadable image file")) from None


def create(
    conn,
    mosque: dict,
    label: str,
    category: str,
    filename: str,
    content: bytes,
    user_id=None,
    ip: str | None = None,
) -> dict:
    clean_label = (label or "").strip()[:MAX_LABEL]
    if not clean_label:
        raise ValueError(_("scene label is required"))
    cat = (category or "autre").strip().lower()
    if cat not in CATEGORIES:
        raise ValueError(_("unknown category: {category}", category=cat))
    png_bytes = prepare_image(filename, content)  # slow part: outside the manifest lock

    with _locked(mosque):
        return _create_locked(conn, mosque, clean_label, cat, png_bytes, user_id, ip)


def _create_locked(conn, mosque: dict, clean_label: str, cat: str, png_bytes: bytes, user_id, ip) -> dict:
    items = _raw_list(mosque)
    if len(items) >= MAX_SCENES:
        raise ValueError(_("maximum number of custom scenes reached ({max})", max=MAX_SCENES))
    base_slug = _slugify(clean_label)
    existing_slugs = {it["slug"] for it in items}
    slug = base_slug
    n = 2
    while slug in existing_slugs:
        slug = f"{base_slug[:40]}-{n}"
        n += 1

    d = _mosque_dir(mosque)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.png").write_bytes(png_bytes)

    record = {
        "slug": slug,
        "label": clean_label,
        "category": cat,
        "updated_at": db.now_iso(),
    }
    items.append(record)
    _save_list(mosque, items)
    db.audit(
        conn,
        mosque["id"],
        user_id,
        "regie.custom_scene.create",
        "mosque",
        mosque["id"],
        ip=ip,
        slug=slug,
        category=cat,
    )
    conn.commit()
    return _format(record)


def delete(conn, mosque: dict, slug: str, user_id=None, ip: str | None = None) -> bool:
    if not SLUG_RE.match(slug):
        return False
    with _locked(mosque):
        items = _raw_list(mosque)
        kept = [it for it in items if it["slug"] != slug]
        if len(kept) == len(items):
            return False
        _save_list(mosque, kept)
        (_mosque_dir(mosque) / f"{slug}.png").unlink(missing_ok=True)
    db.audit(
        conn,
        mosque["id"],
        user_id,
        "regie.custom_scene.delete",
        "mosque",
        mosque["id"],
        ip=ip,
        slug=slug,
    )
    conn.commit()
    return True
