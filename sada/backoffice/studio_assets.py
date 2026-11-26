"""What the Sada Studio needs to compose the picture itself: scenes, the mosque's template screens, the logo.

When a studio device feeds the live, the orchestrator only relays its stream (`compositing: "studio"`): the
studio draws the scenes, the overlays and the mute. It draws them from the same sources the engine does:

* `scene_png` — a scene as the engine draws it (`screens.preview`, the engine's own `SceneRenderer`), for the
  instant the live is at (session, janaza, class on air). 1280×720; banner scenes are transparent RGBA, full
  screens opaque RGB;
* `screen_doc` — the mosque's imported template (`ecrans.html`) for one screen, as an HTML document the studio
  renders itself (it is a Chromium): fonts inlined, anything active removed, placeholders left in, plus the
  values the engine would put there and the intermission countdown's target;
* `logo_png` — the logo medallion of the overlay, as `SceneRenderer.render_overlays` lays it.

Every answer has an ETag digested from its content, so the studio revalidates cheaply (304). Images are drawn
once per distinct content and kept in a small memory cache.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import html
import io
import json
import os
import re
import threading
from collections import OrderedDict
from html.parser import HTMLParser

from PIL import Image

from .. import gabarit_antenne, scenes
from ..config import Config
from . import branding, custom_scenes, db, gabarit, live, variables_ecran
from . import screens as screens_mod
from .template_render import inline_fonts

W, H = 1280, 720
#: Scenes whose slate shows the event of the session on air (as Orchestrator._show).
EVENT_SCENES = ("dars", "tarawih", "tarawih_video")
#: Variable of the intermission countdown in a template, and the format the studio reproduces each second.
COUNTDOWN_VARIABLE = "decompte"

_CACHE: OrderedDict[str, tuple[str, bytes]] = OrderedDict()
_CACHE_MAX = 64
_LOCK = threading.Lock()


def _remember(key: str, make) -> tuple[str, bytes]:
    """(ETag, bytes) for `key`: made once (outside the lock), the ETag digested from the bytes themselves."""
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
            return hit
    body = make()
    out = ('"' + hashlib.sha256(body).hexdigest()[:32] + '"', body)
    with _LOCK:
        _CACHE[key] = out
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return out


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _stamp(path) -> str:
    try:
        st = os.stat(path) if path else None
    except OSError:
        return "missing"
    return f"{st.st_mtime_ns}:{st.st_size}" if st else ""


def matches(header: str | None, etag: str) -> bool:
    """If-None-Match names this ETag (or `*`)."""
    if not header:
        return False
    return header.strip() == "*" or etag in {t.strip().removeprefix("W/") for t in header.split(",")}


# ------------------------------------------------------------------ the instant the live is at


def live_state(mosque: dict, setup: bool = False) -> dict:
    """The part of the engine state the slates depend on (the rehearsal's while the caller's setup runs)."""
    st = live.status_cached(mosque, ttl=3.0)
    block = st.get("setup")
    if setup and isinstance(block, dict) and block.get("active") and not block.get("live"):
        st = {**st, **{k: block[k] for k in ("scene", "janaza_name", "janaza_info", "playing_event") if k in block}}
    return {
        "scene": st.get("scene"),
        "janaza_name": st.get("janaza_name"),
        "janaza_info": st.get("janaza_info"),
        "playing_event": st.get("playing_event") if isinstance(st.get("playing_event"), dict) else None,
    }


def moment_for(conn, mosque: dict, scene: str, state: dict) -> scenes.Moment:
    """The instant the engine would draw `scene` at: the mosque's real data (`moment_reel`) with what only the engine
    knows (the deceased's name, the event on air). Down to the minute, so a slate is drawn at most once a minute."""
    m = screens_mod.moment_reel(mosque, conn)
    event = m.event
    if scene in EVENT_SCENES and state.get("playing_event"):
        event = state["playing_event"]
    return dataclasses.replace(
        m,
        now=m.now.replace(second=0, microsecond=0),
        janaza_name=state.get("janaza_name"),
        janaza_info=state.get("janaza_info"),
        event=event if scene in EVENT_SCENES else m.event,
    )


def _moment_key(m: scenes.Moment) -> dict:
    nxt = m.next_event
    return {
        "now": m.now.isoformat(),
        "planned": m.planned.isoformat() if m.planned else None,
        "janaza": [m.janaza_name, m.janaza_info],
        "event": m.event,
        "next": [getattr(nxt, "starts", None), getattr(nxt, "title", None), getattr(nxt, "kind", None)],
    }


# ------------------------------------------------------------------ scene/{id}.png


def known_scene(scene_id: str) -> bool:
    return scene_id in scenes.SCENES or (
        scene_id.startswith("custom:") and custom_scenes.SLUG_RE.match(scene_id[len("custom:") :]) is not None
    )


def scene_png(conn, mosque: dict, scene_id: str, setup: bool = False) -> tuple[str, bytes] | None:
    """(ETag, PNG) of a scene as the engine draws it; None for an unknown scene (or a custom one without image)."""
    if scene_id.startswith("custom:"):
        return _custom_png(mosque, scene_id[len("custom:") :])
    if scene_id not in scenes.SCENES:
        return None
    textes = screens_mod.saved(conn, mosque["id"])
    moment = moment_for(conn, mosque, scene_id, live_state(mosque, setup))
    logo = screens_mod.overlay_logo(mosque)
    key = "scene:" + _digest(
        {
            "m": mosque["id"],
            "name": mosque.get("name") or "",
            "logo": [logo, _stamp(logo)],
            "scene": scene_id,
            "texts": textes,
            "moment": _moment_key(moment),
        }
    )
    return _remember(key, lambda: screens_mod.preview(mosque, textes, scene_id, True, conn, moment=moment))


def _custom_png(mosque: dict, slug: str) -> tuple[str, bytes] | None:
    path = custom_scenes.image_path(mosque, slug)
    if path is None:
        return None

    def make() -> bytes:
        with Image.open(path) as im:
            img = scenes.render_custom_scene(im, Config(width=W, height=H)).convert("RGB")
        out = io.BytesIO()
        img.save(out, "PNG")
        return out.getvalue()

    return _remember(f"custom:{mosque['id']}:{slug}:{_stamp(path)}", make)


# ------------------------------------------------------------------ logo.png


def logo_png(mosque: dict, scale: int = 1) -> tuple[str, bytes]:
    """(ETag, PNG) of the logo medallion exactly as the overlay lays it (`render_overlays`: diameter 74, ring 1.5 on the
    1280×720 base, with its shadow margin), drawn at `scale` times that size for a sharper picture."""
    scale = min(max(int(scale or 1), 1), 3)
    logo = screens_mod.overlay_logo(mosque)

    def make() -> bytes:
        r = scenes.SceneRenderer(
            Config(mosque_name=mosque.get("name") or "", logo=logo, width=W * scale, height=H * scale)
        )
        img = r.medallion(r.px(74), ring=max(1, r.px(1.5)))
        out = io.BytesIO()
        img.save(out, "PNG")
        return out.getvalue()

    return _remember(f"logo:{mosque['id']}:{logo}:{_stamp(logo)}:{scale}", make)


# ------------------------------------------------------------------ screen/{ecran}: the template as HTML

# Elements that may run, load or navigate: removed with their content.
_DROP = frozenset({"script", "iframe", "frame", "frameset", "object", "embed", "applet", "base", "link", "portal"})
# Void elements (no end tag).
_VOID = frozenset(
    {"area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr", "base"}
)
# Attributes that hold an address.
_URL_ATTRS = frozenset(
    {"src", "href", "srcset", "action", "formaction", "poster", "data", "background", "xlink:href", "ping", "cite"}
)
_PLACEHOLDER = re.compile(r"\{(" + "|".join(gabarit.VARIABLES) + r")\}")
_ONLY_PLACEHOLDER = re.compile(r"^\{(" + "|".join(gabarit.VARIABLES) + r")\}$")
_CSS_IMPORT = re.compile(r"@import\b[^;]*;?", re.IGNORECASE)
_CSS_URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", re.IGNORECASE | re.DOTALL)


def _safe_url(value: str) -> bool:
    """Only what loads nothing from outside: an embedded `data:` resource, a fragment, or a placeholder the studio
    fills with one (the logo is a `data:` URL)."""
    v = value.strip()
    return v.lower().startswith("data:") or v.startswith("#") or bool(_ONLY_PLACEHOLDER.match(v))


def _safe_css(css: str) -> str:
    """CSS without @import and without any url() but embedded ones (fonts are inlined beforehand)."""
    css = _CSS_IMPORT.sub("", css)
    return _CSS_URL.sub(lambda m: m.group(0) if _safe_url(m.group(2)) else "url()", css)


class _Sanitizer(HTMLParser):
    """Rebuilds the document from its tokens, keeping only what draws: no script, no frame, no external resource,
    no `on*` handler, no `javascript:`. Placeholders (`{heure}`...) are text and stay as they are."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0  # depth inside a dropped element
        self._raw = None  # inside <style>: its text is CSS

    def handle_decl(self, decl):
        if not self._skip:
            self.out.append(f"<!{decl}>")

    def _attrs(self, tag: str, attrs) -> str | None:
        kept = []
        if tag == "meta" and any(k.lower() == "http-equiv" for k, _v in attrs):
            return None  # refresh, content security policy...: a document that does nothing by itself
        for k, v in attrs:
            k = k.lower()
            if k.startswith("on") or k in ("srcdoc", "formaction", "ping", "integrity", "nonce"):
                continue
            if v is None:
                kept.append(k)
                continue
            if k in _URL_ATTRS and not _safe_url(v):
                continue
            if k == "style":
                v = _safe_css(v)
            kept.append(f'{k}="{html.escape(v, quote=True)}"')
        return " ".join(kept)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self._skip or tag in _DROP:
            if tag not in _VOID:
                self._skip += 1
            return
        a = self._attrs(tag, attrs)
        if a is None:
            return
        self.out.append(f"<{tag}{' ' + a if a else ''}>")
        if tag == "style":
            self._raw = tag

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if self._skip or tag in _DROP:
            return
        a = self._attrs(tag, attrs)
        if a is not None:
            self.out.append(f"<{tag}{' ' + a if a else ''}>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._skip:
            if tag in _DROP or tag not in _VOID:
                self._skip -= 1
            return
        if tag in _DROP or tag in _VOID:
            return
        if tag == self._raw:
            self._raw = None
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self._skip:
            return
        self.out.append(_safe_css(data) if self._raw else html.escape(data, quote=False))


def sanitize(page: str) -> str:
    """The template as a document that draws and does nothing else (see `_Sanitizer`)."""
    p = _Sanitizer()
    p.feed(page)
    p.close()
    return "".join(p.out)


def fill(page: str, values: dict[str, str]) -> str:
    """Reference of the substitution the studio reproduces: each `{name}` of `gabarit.VARIABLES` (exact, lowercase,
    no space) is replaced, in one pass, by `values[name]` HTML-escaped (`& < > " '`), or by nothing when the value is
    missing or empty. Any other `{...}` stays as written."""
    return _PLACEHOLDER.sub(lambda m: html.escape(values.get(m.group(1)) or "", quote=True), page)


def _template_page(mosque: dict, ecran: str) -> tuple[str, str] | None:
    """(digest, sanitized page) of this screen of the mosque's template, or None when it gives none."""
    path = gabarit.path_for(mosque)
    if ecran not in gabarit.CONNUS or not path.is_file():
        return None

    def make() -> bytes:
        page = gabarit.pour_ecran(gabarit.lire(mosque), ecran)
        return sanitize(inline_fonts(page)).encode("utf-8") if page else b""

    _etag, body = _remember(f"page:{mosque['id']}:{ecran}:{_stamp(path)}", make)
    return (hashlib.sha256(body).hexdigest(), body.decode("utf-8")) if body else None


def _values(conn, mosque: dict, ecran: str, moment: scenes.Moment) -> dict[str, str]:
    """The values the engine puts in this screen (gabarit_antenne.AntenneGabarit.valeurs, fed like the orchestrator
    is by /internal/gabarit), every variable present (empty when the engine has none)."""
    antenne = gabarit_antenne.AntenneGabarit(Config(mosque_name=mosque.get("name") or ""), rendu_factory=None)
    variables = variables_ecran.variables(conn, mosque)
    if variables.get("logo"):
        variables["logo"] = branding.data_url(mosque)  # the studio loads nothing from the network
    antenne._variables = variables
    values = {name: "" for name in gabarit.VARIABLES}
    values.update({k: v or "" for k, v in antenne.valeurs(ecran, moment).items() if k in values})
    return values


def _iso(mosque: dict, t: dt.datetime) -> str:
    """A naive mosque-local time (the engine's clock) as ISO 8601 with its offset."""
    return t.replace(tzinfo=db.timezone(mosque)).isoformat(timespec="seconds")


def screen_doc(conn, mosque: dict, ecran: str, setup: bool = False) -> tuple[str, dict] | None:
    """(ETag, body) of `GET /studio/live/screen/{ecran}`; None for an unknown screen."""
    if not known_scene(ecran):
        return None
    png = f"/api/v1/studio/live/scene/{ecran}.png" + ("?setup=1" if setup else "")
    page = _template_page(mosque, ecran)
    body: dict = {
        "screen": ecran,
        "source": "engine",
        "html": None,
        "values": {},
        "countdown": None,
        "transparent": ecran in gabarit.BANDEAUX or scenes.scene_kind(ecran) == "banner",
        "png": png,
    }
    if page is not None:
        moment = moment_for(conn, mosque, ecran, live_state(mosque, setup))
        target = gabarit_antenne.countdown_target(moment) if ecran == "entracte" else None
        body.update(
            source="gabarit",
            html=page[1],
            values=_values(conn, mosque, ecran, moment),
            countdown={"variable": COUNTDOWN_VARIABLE, "target": _iso(mosque, target)} if target else None,
        )
    etag = '"' + _digest({**body, "html": page[0] if page else None})[:32] + '"'
    return etag, body
