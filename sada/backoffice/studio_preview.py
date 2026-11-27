"""The Sada Studio's picture in the web control room, on demand, outside any live.

The control room is the remote control of the Sada Studio: the person driving it from another room (or from
home) wants to see what the studio composes before going on air. The studio does not stream all the time;
it streams when somebody asks:

* the control room takes a **request** (`preview_requests`, one row per mosque) and renews it every few
  seconds while its monitor is open; closing it, or simply leaving the page, lets it lapse in `TTL_S`;
* the heartbeat answer of the **designated device** carries `preview` while the request holds (the device on
  air, else the one seen last); the device then publishes its composed programme over WHIP to the mosque's
  **preview path** (`live/<slug>-retour`) and stops when `preview` goes away;
* that path is read by the control room only. No orchestrator reads it, no destination, no recording: a
  preview can never reach the public. The publish token is scoped to it (`studio_token`, claim `p`), and a
  preview token is refused on the live path (and the other way round) by the relay's authentication.

While the control room is open (`watched_until`) the devices are asked to beat more often, so a request is
seen within seconds rather than at the next 30-second heartbeat.

During a live the studio already streams: the control room shows the programme and asks for nothing.
"""

from __future__ import annotations

import time

from sqlalchemy import select

from . import live_input, orm, studio_devices, studio_plan
from .models import Device, PreviewRequest

#: A request lapses this long after its last renewal (the control room renews it every PREVIEW_RENEW_S).
TTL_S = 45.0
#: The control room counts as open this long after its last poll.
WATCH_TTL_S = 20.0
#: Heartbeat interval asked of the devices while the control room is open (instead of the usual 30 s).
FAST_HEARTBEAT_S = 5
#: Suffix of the preview path on the relay (never a mosque slug of its own: see `path_of`).
SUFFIX = "-retour"


def path_of(mosque: dict) -> str:
    return f"live/{live_input.slug(mosque)}{SUFFIX}"


def slug_of_path(slug: str) -> str | None:
    """The mosque's slug of a relay stream name `<slug>-retour`, else None."""
    if slug.endswith(SUFFIX) and len(slug) > len(SUFFIX):
        return slug[: -len(SUFFIX)]
    return None


def _row(conn, mosque_id: int) -> dict | None:
    return orm.first(conn, PreviewRequest, mosque_id=mosque_id)


def current(conn, mosque_id: int, now: float | None = None) -> dict | None:
    """The mosque's request while it holds, else None."""
    now = time.time() if now is None else now
    row = _row(conn, mosque_id)
    return row if row and row["until"] > now else None


def _upsert(conn, mosque_id: int, **values) -> None:
    row = _row(conn, mosque_id)
    base = {"user_id": None, "since": 0.0, "until": 0.0, "watched_until": 0.0}
    if row:
        base |= {k: row[k] for k in base}
    orm.upsert(conn, PreviewRequest, ("mosque_id",), mosque_id=mosque_id, **(base | values))
    orm.done(conn)


def request(conn, mosque: dict, user_id: int | None, now: float | None = None) -> dict:
    """Takes or renews the request (and marks the control room open)."""
    now = time.time() if now is None else now
    held = current(conn, mosque["id"], now)
    since = held["since"] if held else now
    _upsert(conn, mosque["id"], user_id=user_id, since=since, until=now + TTL_S, watched_until=now + WATCH_TTL_S)
    return {"since": since, "until": now + TTL_S}


def release(conn, mosque_id: int) -> None:
    """The control room closed its monitor: the device stops at its next heartbeat."""
    if _row(conn, mosque_id):
        _upsert(conn, mosque_id, until=0.0)


def watched(conn, mosque_id: int, now: float | None = None) -> None:
    """The control room polled: the devices beat faster for a while (at most one write every few seconds)."""
    now = time.time() if now is None else now
    row = _row(conn, mosque_id)
    if row and row["watched_until"] - now > WATCH_TTL_S - 5:
        return
    _upsert(conn, mosque_id, watched_until=now + WATCH_TTL_S)


def is_watched(conn, mosque_id: int, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    row = _row(conn, mosque_id)
    return bool(row and (row["watched_until"] > now or row["until"] > now))


def designated(conn, mosque: dict, now: float | None = None) -> dict | None:
    """The device asked for its picture: the one a scheduled live would go out from (the oldest online, not held
    back after a takeover), so the control room sees the machine it is about to put on air."""
    now = time.time() if now is None else now
    rows = orm.rows(
        conn,
        select(Device).where(Device.mosque_id == mosque["id"], Device.revoked_at.is_(None)).order_by(Device.id),
    )
    online = [d for d in rows if studio_devices.is_online(d, now) and d["held_until"] <= now]
    return min(online, key=lambda d: d["id"], default=None)


def for_device(conn, mosque: dict, dev: dict, order: studio_plan.Order, now: float | None = None) -> dict | None:
    """The `preview` block of a heartbeat answer, or None: only the designated device, never during its live."""
    now = time.time() if now is None else now
    req = current(conn, mosque["id"], now)
    if req is None or order.command == studio_plan.LIVE:
        return None
    chosen = designated(conn, mosque, now)
    if chosen is None or chosen["id"] != dev["id"]:
        return None
    return {
        "on": True,
        "expires_in": max(0, round(req["until"] - now)),
        "whip_path": "/api/v1/live/studio/preview/whip",
    }


def allowed(conn, mosque: dict, dev: dict, now: float | None = None) -> bool:
    """May this device publish its preview now (offer, ICE): a request holds and it is the designated one."""
    now = time.time() if now is None else now
    if current(conn, mosque["id"], now) is None:
        return False
    chosen = designated(conn, mosque, now)
    return chosen is not None and chosen["id"] == dev["id"]
