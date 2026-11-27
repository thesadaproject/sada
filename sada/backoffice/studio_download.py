"""Where to download the Sada Studio: the installers of its latest release, per system.

The getting-started screen sends people to the Sada Studio (OBS is no longer offered there). The installers are
published on the studio's GitHub releases with the version in their names, so the links are read from the latest
release (GitHub API, cached for an hour); when GitHub does not answer, every link falls back to the releases page.
Nothing of the mosque or of the user is sent: it is an anonymous read of a public page.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request

REPO_ENV = "SADA_STUDIO_REPO"
DEFAULT_REPO = "thesadaproject/sada-studio"
TTL_S = 3600.0
#: A failed read is retried after this long (the fallback is served meanwhile).
RETRY_S = 300.0

#: Installer of each system, recognised by the end of its file name (electron-builder's names).
PLATFORMS = {
    "windows": re.compile(r"-setup\.exe$"),
    "mac_arm64": re.compile(r"-mac-arm64\.dmg$"),
    "mac_x64": re.compile(r"-mac-x64\.dmg$"),
    "linux": re.compile(r"\.AppImage$"),
}

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "ok": False, "value": None}


def repo() -> str:
    r = os.environ.get(REPO_ENV, "").strip()
    return r if re.fullmatch(r"[\w.-]+/[\w.-]+", r) else DEFAULT_REPO


def page() -> str:
    return f"https://github.com/{repo()}/releases/latest"


def _fetch(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": "sada-backoffice"}
    )
    with urllib.request.urlopen(req, timeout=4) as r:  # noqa: S310 — fixed https address
        return json.loads(r.read().decode())


def parse(release: dict) -> dict:
    """{version, page, assets: {platform: url | None}} from a GitHub release object."""
    assets = {k: None for k in PLATFORMS}
    for a in release.get("assets") or []:
        name, url = str(a.get("name") or ""), a.get("browser_download_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        for k, pattern in PLATFORMS.items():
            if assets[k] is None and pattern.search(name):
                assets[k] = url
    tag = str(release.get("tag_name") or "")
    return {"version": tag.removeprefix("v") or None, "page": release.get("html_url") or page(), "assets": assets}


def fallback() -> dict:
    return {"version": None, "page": page(), "assets": {k: None for k in PLATFORMS}}


def latest(fetch=None, now: float | None = None) -> dict:
    """The latest release's installers; the releases page alone when GitHub cannot be read."""
    now = time.time() if now is None else now
    fetch = fetch or _fetch
    with _lock:
        age = now - _cache["at"]
        if _cache["value"] is not None and age < (TTL_S if _cache["ok"] else RETRY_S):
            return _cache["value"]
    try:
        value, ok = parse(fetch(f"https://api.github.com/repos/{repo()}/releases/latest")), True
    except Exception:  # noqa: BLE001 — network, rate limit, unexpected answer: the page is enough
        value, ok = fallback(), False
    with _lock:
        _cache.update(at=now, ok=ok, value=value)
    return value


def reset() -> None:
    """For tests: forget the cache."""
    with _lock:
        _cache.update(at=0.0, ok=False, value=None)
