"""The overlay layer for the studio's local monitor: the PNG the engine lays over the camera (logo, banner,
QR), drawn by `SceneRenderer.render_overlays`, for the live or the rehearsal, revalidated by ETag."""

from __future__ import annotations

import io
import json

import pytest
from conftest import client, one
from PIL import Image
from test_regie_studio import dev

from sada.backoffice import live, models, screens
from sada.backoffice.api import regie
from sada.backoffice.api import studio as studio_api
from sada.config import Config
from sada.scenes import SceneRenderer
from sada.state import default_overlays

QR = {"visible": True, "url": "https://sada.example/don", "label": "Dons", "corner": "tr"}
BANNER = {"visible": True, "title": "Conférence du vendredi", "subtitle": "Après Maghrib"}


def overlays(**on) -> dict:
    ov = default_overlays()
    for kind, data in on.items():
        ov[kind] = {**ov[kind], **data}
    return ov


@pytest.fixture
def engine(monkeypatch):
    """Fake orchestrator status: the live's overlays at the top level, the rehearsal's in the setup block."""
    st = {"ok": True, "state": "LIVE", "scene": "khutba", "overlays": overlays()}
    reads: list[bool] = []

    def status_cached(mosque, ttl=0, forcer=False):
        reads.append(forcer)
        return dict(st)

    monkeypatch.setattr(live, "status_cached", status_cached)
    regie._LAYER_CACHE.clear()
    return st


@pytest.fixture(autouse=True)
def _fresh_limits():
    studio_api.reset()  # the pairing throttle counts per minute and address, across tests


def png(r) -> Image.Image:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(r.content))
    assert img.size == (1280, 720) and img.mode == "RGBA"
    return img


def alpha_box(img: Image.Image):
    return img.getchannel("A").getbbox()


URL = "/api/v1/live/regie/overlays.png"


def test_nothing_visible_is_a_fully_transparent_layer(env, engine):
    img = png(dev(env).get(URL))
    assert alpha_box(img) is None
    assert img.getchannel("A").getextrema() == (0, 0)


def test_the_layer_is_the_engines_own_drawing(env, engine):
    """Byte for byte what render_overlays produces for the same state: nothing is redrawn server side."""
    engine["overlays"] = overlays(qr=QR, banner=BANNER, logo={"visible": True})
    img = png(dev(env).get(URL))
    mosque = one(env["conn"], models.Mosque, id=env["mid"])
    cfg = Config(mosque_name=mosque["name"], logo=screens.overlay_logo(mosque))
    ref = SceneRenderer(cfg).render_overlays(engine["overlays"])
    assert img.tobytes() == ref.tobytes()
    a = img.getchannel("A")
    assert a.getextrema() == (0, 255)  # opaque drawing over a truly transparent background
    assert a.getpixel((640, 360)) == 0


def test_logo_only_sits_top_left_and_leaves_the_rest_transparent(env, engine):
    engine["overlays"] = overlays(logo={"visible": True})
    img = png(dev(env).get(URL))
    x0, y0, x1, y1 = alpha_box(img)
    assert x1 < 200 and y1 < 200, (x0, y0, x1, y1)
    a = img.getchannel("A")
    assert a.getpixel((640, 360)) == 0 and a.getpixel((1270, 710)) == 0


def test_banner_only_sits_bottom_left(env, engine):
    engine["overlays"] = overlays(banner=BANNER)
    img = png(dev(env).get(URL))
    x0, y0, x1, y1 = alpha_box(img)
    assert x0 < 100 and y0 > 500 and y1 > 650, (x0, y0, x1, y1)


def test_a_long_banner_is_bounded_and_keeps_clear_of_a_bottom_right_qr(env, engine):
    long = {"visible": True, "title": "Très long titre " * 12, "subtitle": "Sous-titre " * 20}
    engine["overlays"] = overlays(banner=long)
    c = dev(env)
    alone = png(c.get(URL))
    assert alpha_box(alone)[2] < 1280  # never runs off the frame
    engine["overlays"] = overlays(banner=long, qr={**QR, "corner": "br"})
    both = png(c.get(URL))
    a = both.getchannel("A")
    # along the banner's middle row, the opaque panel stops before the QR card starts (only a soft shadow between)
    row = [a.getpixel((x, 640)) for x in range(1280)]
    assert min(row[1000:1075]) < 128, "banner and QR card should not touch"
    assert row[1100] > 200  # the card itself


@pytest.mark.parametrize(
    "corner, quadrant",
    [("tl", (0, 0)), ("tr", (1, 0)), ("bl", (0, 1)), ("br", (1, 1))],
)
def test_the_qr_card_lands_in_its_corner(env, engine, corner, quadrant):
    engine["overlays"] = overlays(qr={**QR, "corner": corner})
    img = png(dev(env).get(URL))
    x0, y0, x1, y1 = alpha_box(img)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    assert (int(cx > 640), int(cy > 360)) == quadrant, (corner, (x0, y0, x1, y1))


def test_etag_revalidates_and_changes_with_the_overlays(env, engine):
    c = dev(env)
    first = c.get(URL)
    etag = first.headers["etag"]
    assert etag.startswith('"ov-')
    again = c.get(URL, headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b"" and again.headers["etag"] == etag
    engine["overlays"] = overlays(banner=BANNER)  # an overlay changes on air
    changed = c.get(URL, headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] != etag
    assert alpha_box(png(changed)) is not None


def test_the_same_state_is_drawn_once(env, engine, monkeypatch):
    calls = []
    real = screens.overlays_layer
    monkeypatch.setattr(screens, "overlays_layer", lambda m, o: calls.append(1) or real(m, o))
    engine["overlays"] = overlays(qr=QR)
    c = dev(env)
    c.get(URL)
    c.get(URL)
    assert len(calls) == 1


def test_setup_mode_shows_the_rehearsals_overlays(env, engine):
    engine["setup"] = {"active": True, "live": False, "overlays": overlays(banner=BANNER)}
    c = dev(env)
    live_layer = png(c.get(URL))
    rehearsal = png(c.get(URL + "?setup=1"))
    assert alpha_box(live_layer) is None
    assert alpha_box(rehearsal) is not None


def test_setup_mode_yields_to_a_real_live(env, engine):
    """A live on air takes over the stage: the setup view then shows the live's overlays, as the status does."""
    engine["overlays"] = overlays(logo={"visible": True})
    engine["setup"] = {"active": True, "live": True, "overlays": overlays(banner=BANNER)}
    img = png(dev(env).get(URL + "?setup=1"))
    assert alpha_box(img)[3] < 200  # the logo, not the banner


def test_engine_unreachable_is_a_503_the_client_can_fall_back_on(env, engine):
    engine.clear()
    engine.update({"ok": False, "error": "connection refused"})
    r = dev(env).get(URL)
    assert r.status_code == 503 and r.json()["code"] == "offline"
    assert r.headers["cache-control"] == "no-store"


def test_the_control_room_session_reads_it_too_but_not_without_the_live_right(env, engine):
    admin = client(env, "admin")
    assert admin.get(URL).status_code == 200
    uid = env["ids"]["imam"]
    assert admin.ecrire(f"/users/{uid}", {"permissions": json.dumps(["validate"])}, methode="PATCH").status_code == 200
    assert client(env, "imam").get(URL).status_code == 403
    assert client(env).get(URL).status_code == 401
