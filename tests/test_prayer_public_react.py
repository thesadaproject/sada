"""The public pages as a React bundle: the server still owns the status codes, the boot data and the assets."""

import json
import re

import pytest

pytest.importorskip("fastapi")

from conftest import client  # noqa: E402

from sada.backoffice.api import public  # noqa: E402

CALC = {"lat": "48.9", "lon": "2.3", "method": "uoif"}
URL = "/api/v1/public/mosques/ma-mosquee/prayer-times"
INDEX = (
    '<!doctype html><html><head><link rel="icon" href="__ICON__"><title>__TITLE__</title>'
    '<script type="module" src="/api/v1/public/assets/p/index-abc.js"></script></head>'
    '<body><div id="root"></div><script type="application/json" id="boot">__BOOT__</script></body></html>'
)


@pytest.fixture(autouse=True)
def _bundle(monkeypatch, tmp_path):
    public.reset()
    (tmp_path / "index.html").write_text(INDEX, encoding="utf-8")
    (tmp_path / "index-abc.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "font-x.woff2").write_bytes(b"wOF2")
    monkeypatch.setenv("SADA_PUBLIC_DIST", str(tmp_path))


def _choose(env, **extra):
    c = client(env, "admin")
    r = c.ecrire("/settings/prayer", {"source": "computed", "calc": CALC, "jumua": ["13:00"], **extra}, methode="PUT")
    assert r.status_code == 200, r.text
    return c


def _boot(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="boot">(.*?)</script>', html, re.S)
    assert m, html
    return json.loads(m.group(1))


def test_the_screen_is_the_bundle_with_its_boot_data(env):
    _choose(env)
    r = client(env).get(URL + "/page")
    assert r.status_code == 200
    b = _boot(r.text)
    assert b["view"] == "screen" and b["name"] == "Mosquée Exemple" and b["timezone"] == "Europe/Paris"
    assert b["api"] == "/api/v1/public/mosques/ma-mosquee" and len(b["days"]) == 2
    assert b["days"][0]["times"]["fajr"] and b["accent"] == "" and b["logo"] == ""
    assert "Horaires de prière" in r.text and "__BOOT__" not in r.text and "index-abc.js" in r.text


def test_the_screen_has_no_fullscreen_or_kiosk_button_and_no_legacy_script(env):
    _choose(env)
    h = client(env).get(URL + "/page").text.lower()
    for word in ("plein écran", "fullscreen", "kiosk", "prayer-screen"):
        assert word not in h


def test_the_month_is_the_bundle_and_carries_the_french_labels(env):
    _choose(env)
    r = client(env).get(URL + "/page?month=2027-03")
    assert r.status_code == 200
    b = _boot(r.text)
    assert b["view"] == "month" and b["month"] == "2027-03"
    L = b["labels"]
    assert L["col"]["sunrise"] == "Chourouk" and L["months"][2] == "mars" and L["page"]["pdf"] == "Télécharger le PDF"
    # the legend never designates a single night
    assert "dix dernières nuits" in L["legend_note"] and "27" not in L["legend_note"] + L["legend_odd_nights"]
    assert "Mars 2027" in r.text


def test_unknown_mosque_is_a_real_404_in_french(env):
    r = client(env).get("/api/v1/public/mosques/inconnue/prayer-times/page")
    assert r.status_code == 404
    e = _boot(r.text)["error"]
    assert e["status"] == 404 and e["title"] == "Page introuvable" and e["site"] == "sadakhutbah.org"
    assert "Sadā" in r.text and "not found" not in r.text.lower()


def test_bad_month_is_a_real_422_in_french(env):
    _choose(env)
    r = client(env).get(URL + "/page?month=abc")
    assert r.status_code == 422
    e = _boot(r.text)["error"]
    assert e["status"] == 422 and e["title"] == "Mois invalide" and "2027-03" in e["text"]


def test_an_unpublished_mosque_is_the_same_404(env):
    r = client(env).get(URL + "/page")  # nothing chosen yet
    assert r.status_code == 404 and _boot(r.text)["error"]["title"] == "Page introuvable"


def test_the_boot_data_cannot_close_its_script_tag():
    from sada.backoffice import public_react

    html = public_react.shell({"name": "</script><img src=x onerror=alert(1)> & co"}, "<b>t</b>")
    assert html.count("</script>") == 2  # the module script and the boot block, nothing more
    assert "<img" not in html and "&lt;b&gt;t&lt;/b&gt;" in html
    assert _boot(html)["name"] == "</script><img src=x onerror=alert(1)> & co"


def test_bundle_files_are_served_immutable_under_the_public_prefix(env):
    c = client(env)
    r = c.get("/api/v1/public/assets/p/index-abc.js")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"] and "javascript" in r.headers["content-type"]
    assert c.get("/api/v1/public/assets/p/font-x.woff2").headers["content-type"] == "font/woff2"
    assert c.get("/api/v1/public/assets/p/nothing.js").status_code == 404
    assert c.get("/api/v1/public/assets/p/..%2Fapp.py").status_code == 404
    assert c.get("/api/v1/public/assets/p/index.html").status_code == 404  # only js, css, fonts


def test_without_the_bundle_the_pages_still_work(env, monkeypatch, tmp_path):
    monkeypatch.setenv("SADA_PUBLIC_DIST", str(tmp_path / "absent"))
    _choose(env)
    r = client(env).get(URL + "/page?month=2027-03")
    assert r.status_code == 200 and 'class="monthpage"' in r.text
