"""Broadcast quality (resolution, frame rate, video bit rate), read from the back office at start-up.

The mosque chooses it in the interface (Settings → Live → Quality); 720p, 25 images/s, 2500 kbit/s is what
applies when nothing was saved or when the back office does not answer: the live never depends on it.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from urllib.parse import urlencode

from .i18n import _

Fetch = Callable[[str, str], dict]


def _http_get(url: str, token: str) -> dict:  # pragma: no cover (network)
    from .backoffice.internal import HEADER

    req = urllib.request.Request(url, headers={HEADER: token})
    with urllib.request.urlopen(req, timeout=3) as r:  # noqa: S310 — configured back office
        return json.loads(r.read(65536))


def from_backoffice(
    backoffice_url: str, api_port: int, fetch: Fetch | None = None, log: Callable[[str], None] = lambda _m: None
) -> dict:
    """{width, height, fps, video_bitrate} saved for this mosque; empty dict when absent or on failure."""
    if not backoffice_url:
        return {}
    from .backoffice.internal import token

    url = backoffice_url.rstrip("/") + "/api/v1/internal/stream-quality?" + urlencode({"port": api_port or 0})
    try:
        data = (fetch or _http_get)(url, token()) or {}
        width, height, fps, kbps = (int(data[k]) for k in ("width", "height", "fps", "video_kbps"))
    except Exception as e:  # noqa: BLE001 — any failure: keep the local setting
        log(_("Live: back-office broadcast quality unreachable ({error}) — local setting kept", error=e))
        return {}
    if not (320 <= width <= 3840 and 180 <= height <= 2160 and 0 <= fps <= 60 and 300 <= kbps <= 50000):
        log(_("Live: broadcast quality out of range — local setting kept"))
        return {}
    log(
        _(
            "Live: quality {width}x{height} at {fps} fps, {kbps} kbit/s",
            width=width,
            height=height,
            fps=fps or "—",
            kbps=kbps,
        )
    )
    out = {"width": width, "height": height, "video_bitrate": f"{kbps}k"}
    if fps:  # 0 = automatic: the engine keeps its own rate (SADA_FPS)
        out["fps"] = fps
    return out
