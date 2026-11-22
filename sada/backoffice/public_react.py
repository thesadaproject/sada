"""The public pages of a mosque (screen, month, refusals) as one small React bundle.

The bundle (`packages/public`, built by `npm run build` into `packages/public/dist`) is a Vite entry apart
from the console's: React and `@sada/ui` only, no router, no i18n library. This module is the server side:

* it serves the built `index.html` as the page shell, with a `<script id="boot">` JSON written into it (which
  view, the mosque's name, accent and logo, the labels of its language, today's data for the screen) and the
  title and icon. The HTTP status stays the server's: 404 for an unknown, unpublished or Mawaqit mosque, 422
  for a malformed month. The page never decides a status;
* it serves the bundle's files (hashed names, immutable) under `/api/v1/public/assets/p/`, the only prefix
  the public host forwards to the back office.

The times themselves are read by the bundle from the public API (`prayer-times?month=`, `prayer-times/days`).
When the bundle is not built (a checkout that never ran `npm run build`) `available()` is false and the caller
falls back to the server-rendered pages of `prayer_screen` and `public_page`.
"""

from __future__ import annotations

import json
import os
import re
from html import escape
from pathlib import Path
from urllib.parse import quote

from . import prayer_screen as ps
from .prayer_labels import DEFAULT_LANG, labels

#: Where the bundle is built; SADA_PUBLIC_DIST points tests (or a deployment) elsewhere.
DEFAULT_DIST = Path(__file__).resolve().parent.parent.parent / "packages" / "public" / "dist"
PREFIX = "/api/v1/public/assets/p/"
_FILE = re.compile(r"^[A-Za-z0-9_.-]+\.(js|css|woff2?)$")
_TYPES = {
    "js": "text/javascript; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "woff2": "font/woff2",
    "woff": "font/woff",
}
#: Keys of the language table the bundle needs (the rest stays on the server).
_LABEL_KEYS = (
    "page", "col", "weekdays", "months", "hijri_months", "hijri_short", "night", "jumua",
    "legend_friday", "legend_odd_nights", "legend_note", "legend_maghrib",
)  # fmt: skip


def dist() -> Path:
    return Path(os.environ.get("SADA_PUBLIC_DIST") or DEFAULT_DIST)


def _template() -> str | None:
    try:
        return (dist() / "index.html").read_text(encoding="utf-8")
    except OSError:
        return None


def available() -> bool:
    return _template() is not None


def asset(name: str) -> tuple[bytes, str] | None:
    """(body, media type) of a file of the bundle, None when the name is not one of its files."""
    if not _FILE.match(name):
        return None
    f = dist() / name
    if not f.is_file():
        return None
    return f.read_bytes(), _TYPES[name.rsplit(".", 1)[1]]


def _boot_json(boot: dict) -> str:
    return json.dumps(boot, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def shell(boot: dict, title: str) -> str:
    """The built page with the boot data and the title written in. Everything inserted is escaped."""
    html = _template() or ""
    return (
        html.replace("__ICON__", escape(ps.FAVICON, quote=True))
        .replace("__TITLE__", escape(title))
        .replace("__BOOT__", _boot_json(boot))
    )


def _base(slug: str, mosque: dict, who: dict, lang: str, today: str, view: str) -> dict:
    api = f"/api/v1/public/mosques/{quote(slug)}"
    lab = labels(lang)
    return {
        "view": view,
        "api": api,
        "name": mosque.get("name") or "",
        "timezone": "UTC",
        "today": today,
        "accent": who.get("accent") or "",
        "logo": f"{api}/logo" if who.get("logo") else "",
        "month": "",
        "labels": {k: lab[k] for k in _LABEL_KEYS},
        "days": [],
    }


def screen(slug: str, mosque: dict, payload: dict, today: str) -> str:
    """The screen: `payload` is `prayer_screen.days(...)` (today and tomorrow)."""
    boot = _base(slug, mosque, payload.get("identity") or {}, DEFAULT_LANG, today, "screen")
    boot.update(timezone=payload.get("timezone") or "UTC", days=payload["days"])
    return shell(boot, f"{mosque.get('name') or ''} — Horaires de prière")


def month(slug: str, mosque: dict, who: dict, month: str, today: str, timezone: str, lang: str = DEFAULT_LANG) -> str:
    """A month: the bundle reads its times from the public API."""
    boot = _base(slug, mosque, who, lang, today, "month")
    boot.update(timezone=timezone, month=month)
    lab = labels(lang)
    year, num = int(month[:4]), int(month[5:7])
    return shell(boot, f"{mosque.get('name') or ''} - {lab['months'][num - 1].capitalize()} {year}")


def refused(body: dict, status: int, lang: str = DEFAULT_LANG) -> str:
    """A refusal page; same wording as `public_page.refused`, the status is the caller's."""
    P = labels(lang)["page"]
    url = body.get("mawaqit_url") or ""
    if status == 422:
        title, text = P["month_title"], P["month_text"]
    elif status == 404 and url.startswith("https://"):
        title, text = P["mawaqit_title"], P["mawaqit_text"]
    else:
        title, text = P["missing_title"], P["missing_text"]
    boot = _base("", {}, {}, lang, "", "error")
    boot.update(api="", error={"status": status, "title": title, "text": text, "mawaqit_url": url, "site": ps.SITE})
    return shell(boot, f"{title} · Sadā")
