"""Broadcast quality of a mosque: resolution, video bit rate, frame rate.

One setting per mosque, 720p at 30 images/s by default, and never less. The orchestrator reads it at start
(`/internal/stream-quality`) and encodes at that size; Sada Studio reads it in each heartbeat and captures at the
same size, so nothing is scaled up or down between the two. 1080p is opt-in: it costs about twice the CPU of
720p on the server.
"""

from __future__ import annotations

from ..i18n import _
from . import orm
from .models import StreamQuality

HEIGHTS = {720: 1280, 1080: 1920}  # height -> width (16:9)
#: 30 images/s is the floor (a sermon filmed at 25 looks jerky on the platforms); 60 is opt-in, like 1080p.
FPS = (30, 60)
KBPS_RANGE = (1000, 12000)
#: video bit rate sent to the platforms when the mosque did not choose one.
DEFAULT_KBPS = {720: 2500, 1080: 4500}
DEFAULT_HEIGHT = 720
DEFAULT_FPS = 30
#: floor of the Studio -> server uplink (what it was before the setting existed).
UPLINK_FLOOR_KBPS = 4500


class InvalidQuality(ValueError):
    """A value the screen sent cannot be used."""


def effective(conn, mosque_id: int) -> dict:
    """What the encoder and the Studio apply: width, height, fps, video_kbps, uplink_kbps."""
    row = orm.first(conn, StreamQuality, mosque_id=mosque_id) or {}
    height = int(row.get("height") or DEFAULT_HEIGHT)
    if height not in HEIGHTS:
        height = DEFAULT_HEIGHT
    fps = int(row.get("fps") or 0)
    if fps not in FPS:  # 0 (the old "automatic") and 25, saved before the floor: 30
        fps = DEFAULT_FPS
    kbps = int(row.get("video_kbps") or 0) or DEFAULT_KBPS[height]
    return {
        "width": HEIGHTS[height],
        "height": height,
        "fps": fps,
        "video_kbps": kbps,
        "uplink_kbps": max(UPLINK_FLOOR_KBPS, min(KBPS_RANGE[1], round(kbps * 1.8))),
    }


def view(conn, mosque_id: int) -> dict:
    """What the settings screen shows: the saved choice (0 = automatic bit rate) and the allowed values."""
    row = orm.first(conn, StreamQuality, mosque_id=mosque_id) or {}
    eff = effective(conn, mosque_id)
    return {
        "height": eff["height"],
        "video_kbps": int(row.get("video_kbps") or 0),
        "fps": eff["fps"],
        "effective_kbps": eff["video_kbps"],
        "heights": sorted(HEIGHTS),
        "fps_choices": list(FPS),
        "kbps_range": list(KBPS_RANGE),
        "default_kbps": DEFAULT_KBPS,
    }


def save(conn, mosque_id: int, form: dict) -> dict:
    try:
        height = int(form.get("height") or DEFAULT_HEIGHT)
        fps = int(form.get("fps") or DEFAULT_FPS)
        raw = form.get("video_kbps")
        kbps = int(raw) if str(raw if raw is not None else "").strip() else 0
    except (TypeError, ValueError) as e:
        raise InvalidQuality(_("The broadcast quality must be made of whole numbers.")) from e
    if height not in HEIGHTS:
        raise InvalidQuality(_("The resolution must be 720p or 1080p."))
    if fps not in FPS:
        raise InvalidQuality(_("The frame rate must be 30 or 60 images per second."))
    lo, hi = KBPS_RANGE
    if kbps and not lo <= kbps <= hi:
        raise InvalidQuality(_("The video bit rate must be between {lo} and {hi} kbit/s.", lo=lo, hi=hi))
    orm.upsert(conn, StreamQuality, ("mosque_id",), mosque_id=mosque_id, height=height, video_kbps=kbps, fps=fps)
    return view(conn, mosque_id)


def for_studio(conn, mosque_id: int) -> dict:
    """What Sada Studio is told in each heartbeat: the same as the engine."""
    return effective(conn, mosque_id)
