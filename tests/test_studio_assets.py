"""What the Sada Studio composes from: a scene's PNG, the logo medallion, and the mosque's template screens as HTML.

The studio draws the picture itself when it feeds the live (`compositing: "studio"`); it reads the same sources the
engine draws from, behind its device credential, and revalidates them by ETag.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image
from test_regie_studio import dev

from sada import scenes
from sada.backoffice import gabarit


@pytest.fixture(autouse=True)
def _no_pairing_limit():
    """Pairing is rate-limited (10 a minute per address): one isolated environment per test would trip it."""
    from sada.backoffice.api import studio

    studio.reset()


def _png(body: bytes) -> Image.Image:
    return Image.open(io.BytesIO(body))


def test_scene_png_is_the_engine_screen(env, engine):
    r = dev(env).get("/api/v1/studio/live/scene/avant.png")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    img = _png(r.content)
    assert img.size == (1280, 720) and img.mode == "RGB"  # a full screen: opaque


def test_banner_scene_png_is_transparent(env, engine):
    """The banner scenes are laid over the camera: their PNG must leave the camera visible."""
    r = dev(env).get("/api/v1/studio/live/scene/khutba.png")
    assert r.status_code == 200
    img = _png(r.content)
    assert img.size == (1280, 720) and img.mode == "RGBA"
    assert img.getextrema()[3][0] == 0, "the top of the banner scene is the camera, not an opaque layer"


def test_scene_png_revalidates_and_forgets_nothing(env, engine):
    d = dev(env)
    first = d.get("/api/v1/studio/live/scene/priere.png")
    etag = first.headers["etag"]
    again = d.get("/api/v1/studio/live/scene/priere.png", headers={"If-None-Match": etag})
    assert again.status_code == 304 and not again.content
    assert again.headers["etag"] == etag


def test_unknown_scene_is_not_found(env, engine):
    d = dev(env)
    assert d.get("/api/v1/studio/live/scene/nope.png").status_code == 404
    assert d.get("/api/v1/studio/live/scene/custom:nope.png").status_code == 404
    assert d.get("/api/v1/studio/live/screen/nope").status_code == 404


def test_assets_are_refused_without_a_device_credential(env, engine):
    from conftest import client

    c = client(env)
    for path in (
        "/api/v1/studio/live/scene/khutba.png",
        "/api/v1/studio/live/logo.png",
        "/api/v1/studio/live/screen/avant",
    ):
        assert c.get(path).status_code == 401, path


def test_logo_png_is_the_overlay_medallion(env, engine):
    d = dev(env)
    r = d.get("/api/v1/studio/live/logo.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    img = _png(r.content)
    assert img.size[0] == img.size[1] and img.mode == "RGBA"
    bigger = _png(d.get("/api/v1/studio/live/logo.png?scale=2").content)
    assert bigger.size[0] == img.size[0] * 2
    assert d.get("/api/v1/studio/live/logo.png", headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_screen_doc_without_a_template_points_at_the_png(env, engine):
    d = dev(env)
    body = d.get("/api/v1/studio/live/screen/avant").json()
    assert body["source"] == "engine" and body["html"] is None
    assert body["png"] == "/api/v1/studio/live/scene/avant.png"
    assert body["transparent"] is False
    assert d.get("/api/v1/studio/live/screen/khutba").json()["transparent"] is True
    etag = d.get("/api/v1/studio/live/screen/avant").headers["etag"]
    assert d.get("/api/v1/studio/live/screen/avant", headers={"If-None-Match": etag}).status_code == 304


TEMPLATE = """<!DOCTYPE html><html><head><style>@font-face{font-family:x;src:url(../assets/fonts/Amiri-Regular.ttf)}</style>
<script>alert(1)</script><link rel="stylesheet" href="https://example.com/a.css"></head>
<body onload="steal()"><img src="https://example.com/t.png"><div class="ecran ecran-avant">{titre}</div></body></html>"""


def test_screen_doc_carries_the_template_safe_to_render(env, engine, monkeypatch, tmp_path):
    """The mosque's template is a document: the studio renders it, so nothing in it may run or reach out."""
    page = tmp_path / "ecrans.html"
    page.write_text(TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(gabarit, "path_for", lambda mosque: page)
    d = dev(env)
    body = d.get("/api/v1/studio/live/screen/avant").json()
    assert body["source"] == "gabarit"
    doc = body["html"]
    for forbidden in ("<script", "alert(", "onload", "https://example.com"):
        assert forbidden not in doc, forbidden
    assert "Amiri-Regular.ttf" not in doc and "data:font/ttf;base64" in doc, (
        "fonts are inlined: the studio loads nothing from disk"
    )
    assert "{titre}" in doc, "placeholders are left for the studio to fill"
    assert body["values"]["titre"] and set(body["values"]) >= {"titre", "heure", "decompte"}
    assert body["countdown"] is None  # not the intermission
    etag = d.get("/api/v1/studio/live/screen/avant").headers["etag"]
    assert d.get("/api/v1/studio/live/screen/avant", headers={"If-None-Match": etag}).status_code == 304


def test_intermission_countdown_targets_the_next_moment(env, engine):
    import datetime as dt

    from sada import gabarit_antenne

    class Moment:
        now = dt.datetime(2026, 11, 20, 13, 20)
        planned = dt.datetime(2026, 11, 20, 13, 30)
        next_event = type("E", (), {"kind": "cours", "starts": dt.datetime(2026, 11, 20, 13, 45), "title": "Tafsir"})()

    assert gabarit_antenne.countdown_target(Moment) == dt.datetime(2026, 11, 20, 13, 45)
    Moment.next_event = type("E", (), {"kind": "khutba", "starts": dt.datetime(2026, 11, 20, 14, 0), "title": ""})()
    assert gabarit_antenne.countdown_target(Moment) == dt.datetime(2026, 11, 20, 13, 30)


def test_a_scene_answers_its_kind(env, engine):
    """`scene_kind` is what tells the studio how to compose: over the camera, or masking it."""
    assert scenes.scene_kind("khutba") == "banner"
    assert scenes.scene_kind("avant") == "full"
    assert scenes.scene_kind("custom:x") == "full"
    assert scenes.scene_kind(None) is None and scenes.scene_kind("nope") is None
    body = dev(env).get("/api/v1/studio/regie").json()
    kinds = {s["id"]: s.get("scene_kind") for s in body["scenes"]}
    assert kinds.get("khutba") == "banner" and kinds.get("avant") == "full"
