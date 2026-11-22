"""Pure parts of scripts/smoke_prod.py (no network)."""

import importlib.util
import json
from datetime import date
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "smoke_prod", Path(__file__).resolve().parent.parent / "scripts" / "smoke_prod.py"
)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)

PAGE = """<!doctype html><html><head>
<link rel="icon" href="data:image/svg+xml,x.css">
<script type="module" crossorigin src="/api/v1/public/assets/p/index-abc.js"></script>
<link rel="stylesheet" crossorigin href="/api/v1/public/assets/p/index-def.css">
<link rel="modulepreload" href="/api/v1/public/assets/p/index-abc.js">
</head><body><script type="application/json" id="boot">{"view": "screen", "api": "/api/v1/public/mosques/test"}</script></body></html>"""


def test_parse_page_collects_js_css_once_and_the_boot():
    refs, boot = smoke.parse_page(PAGE)
    assert refs == ["/api/v1/public/assets/p/index-abc.js", "/api/v1/public/assets/p/index-def.css"]
    assert boot["api"] == "/api/v1/public/mosques/test"


def test_parse_page_without_boot():
    assert smoke.parse_page("<html><body>nope</body></html>") == ([], None)


def test_version_of_tag():
    assert smoke.version_of_tag("sada-v0.1.0-alpha.14") == "0.1.0-alpha.14"
    assert smoke.version_of_tag("v1.2.3") == "1.2.3"
    assert smoke.version_of_tag("0.1.0-alpha.14") == "0.1.0-alpha.14"


def test_current_month():
    assert smoke.current_month(date(2026, 3, 9)) == "2026-03"


def test_range_filename_pattern():
    assert smoke.RANGE_PDF.match("prayer-times-2027-02-08_2027-03-08.pdf")
    assert not smoke.RANGE_PDF.match("prayer-times-2026-11.pdf")


def test_wait_for_version_polls_until_it_matches(monkeypatch):
    seen = iter(["0.1.0-alpha.13", "0.1.0-alpha.13", "0.1.0-alpha.14"])

    def fake_fetch(url, timeout=30.0):
        return smoke.Reply(200, {}, json.dumps({"ok": True, "version": next(seen)}).encode())

    sleeps = []
    monkeypatch.setattr(smoke, "fetch", fake_fetch)
    assert smoke.wait_for_version("https://c", "0.1.0-alpha.14", 900, 1, sleeps.append)
    assert len(sleeps) == 2


def test_wait_for_version_gives_up(monkeypatch):
    monkeypatch.setattr(smoke, "fetch", lambda url, timeout=30.0: smoke.Reply(503, {}, b""))
    assert not smoke.wait_for_version("https://c", "x", 0, 1, lambda s: None)
