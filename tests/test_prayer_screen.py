"""The public prayer-time screen: clock page, days endpoint and the few assets served under the public prefix."""

import datetime as dt
import hashlib
import json
import re

import pytest

pytest.importorskip("fastapi")

from conftest import client, set_mosque  # noqa: E402

from sada.backoffice import prayer_screen  # noqa: E402
from sada.backoffice.api import public  # noqa: E402

CALC = {"lat": "48.9", "lon": "2.3", "method": "uoif"}
BASE = "/api/v1/public/mosques/ma-mosquee/prayer-times"


@pytest.fixture(autouse=True)
def _fresh_limits():
    public.reset()


def _choose(env, source="computed", **extra):
    c = client(env, "admin")
    body = {"source": source, "calc": CALC, "jumua": ["13:00", "14:15"], **extra}
    assert c.ecrire("/settings/prayer", body, methode="PUT").status_code == 200
    return c


def _data(html: str) -> dict:
    return json.loads(re.search(r'id="ps-data">(.*?)</script>', html, re.S).group(1))


def test_dates_are_in_french_with_the_hijri_date():
    assert prayer_screen.greg_text(dt.date(2027, 3, 9)) == "Mardi 9 mars 2027"
    assert prayer_screen.hijri_text(dt.date(2027, 3, 9)) == "1 Chawwal 1448"


def test_the_screen_shows_the_prayers_in_french_and_arabic_with_the_iqama_that_exists(env):
    _choose(env, calc={**CALC, "iqama": {"isha": 10}})
    r = client(env).get(BASE + "/page")  # no session at all
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"].startswith("public, max-age=60")
    h = r.text
    for word in ("Fajr", "Chourouk", "Dhuhr", "Asr", "Maghrib", "Isha", "الفجر", "العشاء", "Mosquée Exemple"):
        assert word in h, word
    day = _data(h)["days"][0]
    assert set(day["iqama"]) == {"isha"} and day["times"]["isha"] and day["date"] == dt.date.today().isoformat()
    assert 'lang="fr"' in h and 'role="status"' in h and "aria-label" in h


def test_chourouk_is_only_a_time_without_adhan_label_nor_iqama(env):
    _choose(env, calc={**CALC, "iqama": {"isha": 10}})
    h = client(env).get(BASE + "/page").text
    row = re.search(r'<li class="row sun".*?</li>', h, re.S).group(0)
    assert "Chourouk" in row and "<time>" in row
    assert "Adhan" not in row and "Iqama" not in row and 'class="iq"' not in row
    assert "sunrise" not in _data(h)["days"][0]["iqama"]
    js = open(prayer_screen.__file__.replace("prayer_screen.py", "static/prayer-screen.js")).read()
    assert 'ORDER = ["fajr", "dhuhr", "asr", "maghrib", "isha"]' in js  # never a countdown target


def test_without_an_iqama_none_is_shown_nor_invented(env):
    _choose(env)
    h = client(env).get(BASE + "/page").text
    assert _data(h)["days"][0]["iqama"] == {}
    assert "noiqama" in h
    assert "ne publie pas d'iqama" not in h and "publie pas d" not in h  # never written on a public screen
    assert not re.search(r'class="iq"(?! hidden)', h)


def test_jumua_only_on_friday_and_only_if_entered(env):
    _choose(env)
    c = client(env)
    fri, sat = "2027-03-05", "2027-03-06"
    assert c.get(BASE + "/days?from=" + fri).json()["days"][0]["jumua"] == ["13:00", "14:15"]
    assert c.get(BASE + "/days?from=" + sat).json()["days"][0]["jumua"] == []
    _choose(env, jumua=[])
    public.reset()
    assert client(env).get(BASE + "/days?from=" + fri).json()["days"][0]["jumua"] == []


def test_days_gives_today_and_tomorrow_and_refuses_bad_dates(env):
    _choose(env)
    c = client(env)
    d = c.get(BASE + "/days?from=2027-03-09").json()
    assert [x["date"] for x in d["days"]] == ["2027-03-09", "2027-03-10"]
    assert d["days"][0]["hijri"] == "1 Chawwal 1448" and d["timezone"] == "Europe/Paris"
    assert d["days"][0]["gregorian"] == "Mardi 9 mars 2027"
    assert c.get(BASE + "/days?from=09-03-2027").status_code == 422
    assert c.get(BASE + "/days").json()["days"][0]["date"] == dt.date.today().isoformat()


def test_a_manual_day_without_times_says_so(env):
    _choose(env, "manual")
    h = client(env).get(BASE + "/page").text
    assert "Aucun horaire saisi pour ce jour." in h and _data(h)["days"][0]["times"] == {}


def test_the_month_table_and_pdf_stay_reachable(env):
    _choose(env)
    c = client(env)
    h = c.get(BASE + "/page").text
    month = dt.date.today().strftime("%Y-%m")
    assert f'href="{BASE}/page?month={month}"' in h and f"{BASE}/export?format=pdf&amp;month={month}" in h
    assert "<table>" in c.get(BASE + "/page?month=" + month).text


def test_everything_is_escaped_and_nothing_comes_from_a_third_party(env):
    _choose(env)
    set_mosque(env["conn"], env["mid"], name="</script><script>alert(1)</script> & Cie")
    h = client(env).get(BASE + "/page").text
    assert "<script>alert" not in h and "</script><script>alert" not in h and "&lt;/script&gt;" in h
    assert not re.search(r'(?:src|href)="https?://', h)
    assert "token" not in h.lower()


def test_assets_are_served_under_the_public_prefix_and_nothing_else(env):
    c = client(env)
    css = c.get("/api/v1/public/assets/prayer-screen.css")
    js = c.get("/api/v1/public/assets/prayer-screen.js")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css") and "--night" in css.text
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    fonts = c.get("/api/v1/public/assets/fonts.css")
    assert "/static/fonts/" not in fonts.text and "/api/v1/public/assets/fonts/Amiri" in fonts.text
    assert c.get("/api/v1/public/assets/fonts/Amiri-normal-400-arabic.woff2").headers["content-type"] == "font/woff2"
    for bad in ("../app.py", "fonts/../../app.py", "emblem.svg", "fonts/x.txt", "..%2fapp.py"):
        assert c.get("/api/v1/public/assets/" + bad).status_code == 404, bad


def test_page_links_content_hashed_assets_and_they_are_immutable(env):
    _choose(env)
    c = client(env)
    page = c.get(BASE + "/page")
    assert page.status_code == 200
    # the HTML itself stays short-lived: it is what carries the current hashes
    assert page.headers["cache-control"].startswith("public, max-age=60")
    assert "immutable" not in page.headers["cache-control"]
    links = re.findall(r'(?:href|src)="(/api/v1/public/assets/[^"]+)"', page.text)
    assert sorted(links) == sorted([prayer_screen.CSS, prayer_screen.JS, prayer_screen.FONTS])
    for link in links:
        assert re.search(r"/(prayer-screen|fonts)\.[0-9a-f]{10}\.(css|js)$", link), link
        r = c.get(link)
        assert r.status_code == 200
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    plain = c.get("/api/v1/public/assets/prayer-screen.css")  # compatibility
    assert plain.status_code == 200 and "immutable" not in plain.headers["cache-control"]
    assert c.get(prayer_screen.CSS).content == plain.content


def test_asset_hash_follows_the_content_and_unknown_hashes_are_refused(env):
    c = client(env)
    css = prayer_screen.CSS.rsplit("/", 1)[1]
    digest = hashlib.sha256(c.get(prayer_screen.CSS).content).hexdigest()[:10]
    assert css == f"prayer-screen.{digest}.css"
    fonts = c.get(prayer_screen.FONTS)  # hashed after the /static -> /assets rewrite
    assert "/static/fonts/" not in fonts.text
    assert prayer_screen.FONTS.endswith(f"fonts.{hashlib.sha256(fonts.content).hexdigest()[:10]}.css")
    for bad in (
        "prayer-screen.0000000000.css",
        "prayer-screen.zzzzzzzzzz.js",
        "prayer-screen..css",
    ):
        r = c.get("/api/v1/public/assets/" + bad)
        assert r.status_code == 404 and r.headers["cache-control"] == "no-store", bad


def test_a_mawaqit_or_private_mosque_has_no_screen(env):
    c = _choose(env)
    c.ecrire("/settings/prayer", {"source": "computed", "calc": CALC, "public": "0"}, methode="PUT")
    assert client(env).get(BASE + "/page").status_code == 404
    assert client(env).get(BASE + "/days").status_code == 404


def test_one_column_header_names_adhan_and_iqama_only_when_the_mosque_publishes_iqama(env):
    _choose(env, calc={**CALC, "iqama": {"isha": 10}})
    h = client(env).get(BASE + "/page").text
    cols = re.search(r'<div class="cols[^"]*" id="cols".*?</div>', h, re.S).group(0)
    assert "Adhan" in cols and "Iqama" in cols and not cols.rstrip().split(">")[0].endswith(" hidden")
    assert " hidden>" not in cols
    assert h.count("Adhan") == 1 and h.count("Iqama") == 1  # once, not on every row
    _choose(env)
    h = client(env).get(BASE + "/page").text
    cols = re.search(r'<div class="cols[^"]*" id="cols".*?</div>', h, re.S).group(0)
    assert " hidden>" in cols  # without an iqama, the header is gone altogether
    assert "Adhan" not in re.sub(r'<div class="cols.*?</div>', "", h, flags=re.S)  # ... and the word shows nowhere


def test_the_row_of_a_prayer_carries_no_adhan_label(env):
    _choose(env, calc={**CALC, "iqama": {"isha": 10}})
    h = client(env).get(BASE + "/page").text
    for row in re.findall(r'<li class="row prayer".*?</li>', h, re.S):
        assert "Adhan" not in row and "Iqama" not in row and 'class="lbl"' not in row


def test_the_dates_never_end_on_an_orphan_separator(env):
    _choose(env)
    h = client(env).get(BASE + "/page").text
    dates = re.search(r'<p class="dates">(.*?)</p>', h, re.S).group(1)
    assert "·" not in dates and "sep" not in dates  # Gregorian and Hijri are two lines, no dot between
    assert 'id="greg"' in dates and 'id="hijri"' in dates


FULLSCREEN = (
    "html:fullscreen .links",
    "html:fullscreen .fs",
    "html.kiosk .links",
    "html.kiosk .fs",
    "display-mode: fullscreen",
)


def test_in_full_screen_the_links_the_button_and_the_pointer_are_gone_but_sadas_mark_stays(env):
    _choose(env)
    h = client(env).get(BASE + "/page").text
    # the links and the button are tagged so that CSS can hide them; the brand is outside of both
    assert re.search(r'<nav class="links".*?</nav>', h, re.S) and 'class="fs"' in h
    assert re.search(r'<footer class="foot">.*<span class="brand">', h, re.S)
    assert 'class="brand"' not in re.search(r'<nav class="links".*?</nav>', h, re.S).group(0)
    css = open(prayer_screen.__file__.replace("prayer_screen.py", "static/prayer-screen.css")).read()
    for sel in FULLSCREEN:
        assert sel in css, sel
    hidden = css[css.index("html:fullscreen .links") :].split("}")[0]
    assert "display: none" in hidden
    assert "html.idle" in css and "cursor: none" in css  # the pointer vanishes after a pause
    assert ".brand" in css and ".brand" not in hidden  # Sada's mark is not part of what is hidden
    js = open(prayer_screen.__file__.replace("prayer_screen.py", "static/prayer-screen.js")).read()
    assert "fullscreenchange" in js and '"kiosk"' in js and '"idle"' in js and "kiosk=1" in js


def test_the_logo_and_accent_appear_on_the_screen_only_when_chosen(env):
    c = _choose(env)
    plain = client(env).get(BASE + "/page").text
    assert "--accent" not in plain and 'class="logo"' not in plain  # Sada's own colours
    logo = env["tmp"] / "logo.png"
    from PIL import Image

    Image.new("RGBA", (40, 40), (10, 100, 50, 255)).save(logo)
    set_mosque(env["conn"], env["mid"], logo_path=str(logo))
    c.ecrire("/settings/prayer/identity", {"accent": "#101010", "show_logo": "1"}, methode="PUT")
    public.reset()
    h = client(env).get(BASE + "/page").text
    assert 'class="logo"' in h and f"{BASE.replace('/prayer-times', '')}/logo" in h
    style = re.search(r'<body style="([^"]*)"', h).group(1)
    assert "--accent:" in style and "#101010" not in style.split("--accent:")[1].split(";")[0]  # lightened to read


def test_the_phone_layout_is_sized_on_the_dynamic_viewport_with_safe_areas():
    css = (__import__("pathlib").Path(prayer_screen.__file__).parent / "static" / "prayer-screen.css").read_text()
    phone = css[css.index("Phone, portrait") :]
    assert "100dvh" in phone and "safe-area-inset-bottom" in phone and "clamp(" in phone
    assert "http" not in phone and "url(" not in phone  # nothing external
