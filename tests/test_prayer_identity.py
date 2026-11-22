"""The mosque's look on its public prayer pages: accent colours, logo, and the readability guarantee."""

import io
import itertools
import re

import pytest

pytest.importorskip("fastapi")

from conftest import client, one, rows, set_mosque  # noqa: E402

from sada.backoffice import identity, models, prayer_export, prayer_times  # noqa: E402
from sada.backoffice.api import public  # noqa: E402

CALC = {"lat": "48.9", "lon": "2.3", "method": "uoif"}
BASE = "/api/v1/public/mosques/ma-mosquee"


@pytest.fixture(autouse=True)
def _fresh_limits():
    public.reset()


def _choose(env):
    c = client(env, "admin")
    body = {"source": "computed", "calc": CALC, "jumua": ["13:00"]}
    assert c.ecrire("/settings/prayer", body, methode="PUT").status_code == 200
    return c


def _mosque(env):
    return one(env["conn"], models.Mosque, id=env["mid"])


def _png(path, rgba=(122, 30, 60, 255)):
    from PIL import Image

    Image.new("RGBA", (64, 48), rgba).save(path)


# ------------------------------------------------------------------ colours


def test_a_colour_is_normalised_or_refused():
    assert identity.normalize("#ABC") == "#aabbcc" and identity.normalize("1A7F5A") == "#1a7f5a"
    assert identity.normalize("") == "" and identity.normalize(None) == ""
    for bad in ("red", "#12345", "#gggggg", "rgb(1,2,3)", "#1a7f5a;}</style>"):
        with pytest.raises(ValueError):
            identity.normalize(bad)


GRID = [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in itertools.product(range(0, 256, 51), repeat=3)]


@pytest.mark.parametrize("colour", GRID)
def test_whatever_the_colour_the_text_derived_from_it_is_readable(colour):
    p = identity.palette(colour, colour)
    for key in ("on_dark", "on_dark2"):  # text and lines on the dark ground and its panels
        assert identity.contrast(p[key], identity.DEEP) >= identity.MIN_TEXT, (colour, key)
        assert identity.contrast(p[key], identity.NIGHT) >= identity.MIN_TEXT, (colour, key)
    for fill, ink in (("fill", "fill_ink"), ("fill2", "fill2_ink")):  # a surface painted with the accent
        assert identity.contrast(p[ink], p[fill]) >= identity.MIN_TEXT, (colour, fill)
    for key in ("on_light", "on_light2"):  # text on paper
        assert identity.contrast(p[key], identity.PAPER) >= identity.MIN_TEXT, (colour, key)


def test_sada_colours_apply_when_the_mosque_chose_none():
    p = identity.palette("", "")
    assert p["accent"] == identity.SADA_ACCENT and p["accent2"] == identity.SADA_ACCENT2
    assert identity.css_vars("", "") == ""  # the stylesheet's own defaults, nothing injected


def test_a_dark_accent_is_lightened_on_the_dark_ground_and_a_light_one_gets_a_dark_ink():
    p = identity.palette("#101010", "")
    assert p["on_dark"] != "#101010" and identity.contrast(p["on_dark"], identity.NIGHT) >= 4.5
    assert identity.palette("#fff2c0", "")["fill_ink"] == identity.INK_DARK
    assert identity.palette("#0a1f44", "")["fill_ink"] == identity.INK_LIGHT


# ------------------------------------------------------------------ API


def test_the_identity_is_saved_through_the_api_and_shown_in_the_settings(env):
    c = _choose(env)
    r = c.ecrire(
        "/settings/prayer/identity", {"accent": "#8A1C3D", "accent2": "#1f6f8b", "show_logo": "1"}, methode="PUT"
    )
    assert r.status_code == 200, r.text
    ident = r.json()["prayer"]["identity"]
    assert ident == {"accent": "#8a1c3d", "accent2": "#1f6f8b", "show_logo": True}
    # choosing the source again does not wipe the look
    assert c.ecrire("/settings/prayer", {"source": "computed", "calc": CALC}, methode="PUT").status_code == 200
    row = rows(env["conn"], models.PrayerSettings)[0]
    assert (row["accent"], row["accent2"], row["show_logo"]) == ("#8a1c3d", "#1f6f8b", 1)


def test_a_bad_colour_is_refused_and_nothing_is_stored(env):
    c = _choose(env)
    r = c.ecrire("/settings/prayer/identity", {"accent": "javascript:alert(1)"}, methode="PUT")
    assert r.status_code == 422
    assert rows(env["conn"], models.PrayerSettings)[0]["accent"] == ""


def test_only_an_admin_changes_the_look(env):
    _choose(env)
    for who in ("imam", "responsable"):
        r = client(env, who).ecrire("/settings/prayer/identity", {"accent": "#8a1c3d"}, methode="PUT")
        assert r.status_code in (401, 403), (who, r.status_code)


def test_the_look_needs_a_chosen_source(env):
    c = client(env, "admin")
    r = c.ecrire("/settings/prayer/identity", {"accent": "#8a1c3d"}, methode="PUT")
    assert r.status_code == 422


# ------------------------------------------------------------------ public pages and PDF


def test_the_public_logo_is_served_only_when_the_mosque_chose_to_show_it(env):
    c = _choose(env)
    logo = env["tmp"] / "logo.png"
    _png(logo)
    set_mosque(env["conn"], env["mid"], logo_path=str(logo))
    assert client(env).get(BASE + "/logo").status_code == 404  # uploaded for the back office, not public
    c.ecrire("/settings/prayer/identity", {"show_logo": "1"}, methode="PUT")
    r = client(env).get(BASE + "/logo")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert r.headers["x-content-type-options"] == "nosniff"
    c.ecrire("/settings/prayer/identity", {"show_logo": "0"}, methode="PUT")
    assert client(env).get(BASE + "/logo").status_code == 404


def test_the_days_payload_carries_the_identity_but_no_path(env):
    c = _choose(env)
    logo = env["tmp"] / "logo.png"
    _png(logo)
    set_mosque(env["conn"], env["mid"], logo_path=str(logo))
    c.ecrire("/settings/prayer/identity", {"accent": "#8a1c3d", "show_logo": "1"}, methode="PUT")
    body = client(env).get(BASE + "/prayer-times/days").json()
    assert body["identity"] == {"accent": "#8a1c3d", "accent2": "", "logo": True}
    assert str(logo) not in str(body)


def test_the_pdf_takes_the_accent_and_the_logo(env):
    pypdf = pytest.importorskip("pypdf")
    c = _choose(env)
    plain = c.get("/api/v1/settings/prayer/export?format=pdf&month=2027-03").content
    logo = env["tmp"] / "logo.png"
    _png(logo)
    set_mosque(env["conn"], env["mid"], logo_path=str(logo))
    c.ecrire("/settings/prayer/identity", {"accent": "#8a1c3d", "accent2": "#1f6f8b", "show_logo": "1"}, methode="PUT")
    styled = c.get("/api/v1/settings/prayer/export?format=pdf&month=2027-03").content
    assert b"/Subtype /Image" in styled and b"/Subtype /Image" not in plain  # the logo is drawn
    assert len(pypdf.PdfReader(io.BytesIO(styled)).pages) == 1
    # the mosque's colour is in the page content, Sada's gold rule is not
    stream = b"".join(p.get_contents().get_data() for p in pypdf.PdfReader(io.BytesIO(styled)).pages)
    assert re.search(rb"\.5411\d* \.1098\d* \.2392\d* rg", stream)  # #8a1c3d = 0.541 0.110 0.239


def test_the_look_is_off_in_the_pdf_when_the_logo_is_not_chosen(env):
    c = _choose(env)
    logo = env["tmp"] / "logo.png"
    _png(logo)
    set_mosque(env["conn"], env["mid"], logo_path=str(logo))
    a = c.get("/api/v1/settings/prayer/export?format=pdf&month=2027-03").content
    assert b"/Subtype /Image" not in a  # a logo uploaded for the back office never reaches a printed page by itself
    c.ecrire("/settings/prayer/identity", {"show_logo": "1"}, methode="PUT")
    assert b"/Subtype /Image" in c.get("/api/v1/settings/prayer/export?format=pdf&month=2027-03").content


def test_the_prayer_export_helper_keeps_working_without_a_look():
    assert prayer_export.Look().accent == prayer_export.LEAF2
    assert prayer_times.identity.normalize("#FFF") == "#ffffff"
