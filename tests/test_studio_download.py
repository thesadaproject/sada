"""Download links of the Sada Studio: read from its latest release, the releases page when GitHub is silent."""

from __future__ import annotations

import pytest
from conftest import client

from sada.backoffice import studio_download as dl

RELEASE = {
    "tag_name": "v0.6.0",
    "html_url": "https://github.com/thesadaproject/sada-studio/releases/tag/v0.6.0",
    "assets": [
        {"name": "latest.yml", "browser_download_url": "https://github.com/x/latest.yml"},
        {"name": "Sada-Studio-0.6.0-setup.exe", "browser_download_url": "https://github.com/x/setup.exe"},
        {"name": "Sada-Studio-0.6.0-setup.exe.blockmap", "browser_download_url": "https://github.com/x/setup.blockmap"},
        {"name": "Sada-Studio-0.6.0-mac-arm64.dmg", "browser_download_url": "https://github.com/x/arm64.dmg"},
        {"name": "Sada-Studio-0.6.0-mac-x64.dmg", "browser_download_url": "https://github.com/x/x64.dmg"},
        {"name": "Sada-Studio-0.6.0-mac-arm64.zip", "browser_download_url": "https://github.com/x/arm64.zip"},
        {"name": "Sada-Studio-0.6.0-linux.AppImage", "browser_download_url": "https://github.com/x/app.AppImage"},
        {"name": "evil.exe", "browser_download_url": "javascript:alert(1)"},
    ],
}


@pytest.fixture(autouse=True)
def _fresh():
    dl.reset()
    yield
    dl.reset()


def test_installers_are_read_from_the_latest_release():
    out = dl.latest(fetch=lambda url: RELEASE, now=1000.0)
    assert out["version"] == "0.6.0"
    assert out["assets"] == {
        "windows": "https://github.com/x/setup.exe",
        "mac_arm64": "https://github.com/x/arm64.dmg",
        "mac_x64": "https://github.com/x/x64.dmg",
        "linux": "https://github.com/x/app.AppImage",
    }


def test_cached_for_an_hour_and_the_page_when_github_is_silent():
    calls = []
    dl.latest(fetch=lambda url: calls.append(url) or RELEASE, now=1000.0)
    dl.latest(fetch=lambda url: calls.append(url) or RELEASE, now=1000.0 + dl.TTL_S - 1)
    assert calls == ["https://api.github.com/repos/thesadaproject/sada-studio/releases/latest"]

    def down(url):
        raise OSError("no network")

    out = dl.latest(fetch=down, now=1000.0 + dl.TTL_S + 1)
    assert out == dl.fallback() and out["page"].endswith("/sada-studio/releases/latest")


def test_the_route_needs_a_session(env, monkeypatch):
    seen = []
    monkeypatch.setattr(dl, "_fetch", lambda url: seen.append(url) or RELEASE)
    assert client(env).get("/api/v1/studio/download").status_code == 401
    r = client(env, "responsable").get("/api/v1/studio/download")
    assert r.status_code == 200 and r.json()["assets"]["windows"] == "https://github.com/x/setup.exe"
    assert len(seen) == 1
