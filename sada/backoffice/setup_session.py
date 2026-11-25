"""Setup mode of a studio device: wake the mosque's orchestrator, without ever broadcasting.

Hosted, the orchestrator does not run all the time: the platform arms it for the planned slots. An operator
setting up the screens in the Studio application needs it *now*, to see the programme as it would be composed
(the mosque's templates, texts, logo, QR code, banner). This module is the server's side of that:

* a **lease** per mosque (`setup_leases`), taken and renewed by the paired device every few seconds. It is the
  one thing a platform scaler has to read to know the orchestrator is wanted (`GET /internal/setup-leases`), and
  the orchestrator may go back to sleep as soon as it lapses: application closed, network lost, or `leave`;
* an optional **wake webhook** (`SADA_SETUP_WAKE_URL`), POSTed `{"mosque": slug, "action": "wake" | "sleep"}` with
  the internal token, for platforms that prefer to be told rather than to poll;
* the **orchestrator's own lease** (`live.set_setup`): in setup it composes a rehearsal programme into the
  monitoring copy only, never to the destinations (see `sada/setup_mode.py`). A lease the application stops
  renewing lapses there too, so the rehearsal ends by itself even if the sleep order never arrives.

The answer is protocol data only (states, numbers): the application writes its own sentences, in its language.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from sqlalchemy import delete, select

from . import internal, live, live_watch, orm
from .models import Mosque, SetupLease

log = logging.getLogger("sada")

#: Lease length handed to the application, which renews it every few seconds.
TTL_S = 90.0
#: A silent orchestrator is "waking" for this long after the lease was taken, then "unreachable".
WAKE_GRACE_S = 120.0
#: The wake order is repeated at most this often while the orchestrator does not answer.
WAKE_RETRY_S = 30.0
WAKE_ENV = "SADA_SETUP_WAKE_URL"

_last_wake: dict[str, float] = {}
_lock = threading.Lock()


def current(conn, mosque_id: int, now: float | None = None) -> dict | None:
    """The mosque's lease while it holds, else None."""
    now = time.time() if now is None else now
    row = orm.first(conn, SetupLease, mosque_id=mosque_id)
    return row if row and row["until"] > now else None


def take(conn, mosque: dict, device: dict | None, now: float | None = None) -> tuple[dict, bool]:
    """Takes or renews the lease. Returns (lease, fresh): fresh when it was not held (a new setup session)."""
    now = time.time() if now is None else now
    held = current(conn, mosque["id"], now)
    since = held["since"] if held else now
    orm.upsert(
        conn,
        SetupLease,
        ("mosque_id",),
        mosque_id=mosque["id"],
        device_id=device["id"] if device else None,
        since=since,
        until=now + TTL_S,
    )
    return {"since": since, "until": now + TTL_S}, held is None


def release(conn, mosque_id: int) -> bool:
    """Gives the lease back. True when one was held."""
    held = orm.first(conn, SetupLease, mosque_id=mosque_id)
    conn.execute(delete(SetupLease).where(SetupLease.mosque_id == mosque_id))
    orm.done(conn)
    return held is not None


def leases(conn, now: float | None = None) -> list[dict]:
    """Every lease that holds, with the mosque's slug: what a scaler reads to know which orchestrators to keep."""
    now = time.time() if now is None else now
    _purge_wake(conn, now)
    stmt = (
        select(Mosque.slug, SetupLease.until)
        .join(SetupLease, SetupLease.mosque_id == Mosque.id)
        .where(SetupLease.until > now)
        .order_by(Mosque.slug)
    )
    return [{"mosque": r["slug"], "until": r["until"]} for r in orm.rows(conn, stmt)]


_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The hook carries the internal token: a redirect must never carry it somewhere else."""

    def redirect_request(self, *args, **kwargs):
        return None


def _hook_allowed(url: str) -> bool:
    """https only; plain http is for a loopback host (development, tests)."""
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" or (parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK)


def _post_hook(url: str, slug: str, action: str) -> None:
    if not _hook_allowed(url):
        log.warning("setup %s hook for %s not sent: the address must be https", action, slug)
        return
    body = json.dumps({"mosque": slug, "action": action}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", internal.HEADER: internal.local_token()},
    )
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=3):  # noqa: S310 — operator-configured address
            pass
    except Exception as e:  # noqa: BLE001 — a platform hook that fails must never fail the setup
        log.warning("setup %s hook for %s failed: %s", action, slug, e)


def notify_platform(slug: str, action: str, poster=_post_hook) -> bool:
    """Tells the platform to wake or sleep the orchestrator. False when no hook is configured."""
    url = os.environ.get(WAKE_ENV, "").strip()
    if not url:
        return False
    threading.Thread(target=poster, args=(url, slug, action), daemon=True, name="setup-hook").start()
    return True


def _purge_wake(conn, now: float) -> None:
    """Forgets the wake bookkeeping of every mosque whose lease no longer holds (it is fresh again next time)."""
    stmt = select(Mosque.slug).join(SetupLease, SetupLease.mosque_id == Mosque.id).where(SetupLease.until > now)
    live_slugs = {r["slug"] for r in orm.rows(conn, stmt)}
    with _lock:
        for slug in [k for k in _last_wake if k not in live_slugs]:
            del _last_wake[slug]


def _wake_due(slug: str, now: float, fresh: bool) -> bool:
    with _lock:
        if fresh or now - _last_wake.get(slug, 0.0) >= WAKE_RETRY_S:
            _last_wake[slug] = now
            return True
    return False


def view(mosque: dict, lease: dict, reply: dict | None, now: float, relay_online: bool | None) -> dict:
    """What the application is told. `reply` is the orchestrator's setup block (None when it did not answer)."""
    if reply is not None:
        orchestrator = "ready"
    elif now - lease["since"] < WAKE_GRACE_S:
        orchestrator = "waking"
    else:
        orchestrator = "unreachable"
    return {
        "active": True,
        "expires_in": max(0, round(lease["until"] - now)),
        "orchestrator": orchestrator,
        # a real live is on air: the programme view is the real broadcast, and setup commands drive it as usual
        "live": bool(reply and reply.get("live")),
        "rehearsing": bool(reply and reply.get("rehearsing")),
        "available": bool(reply.get("available", True)) if reply else True,
        # the programme picture can be watched: the relay has it (None = the relay does not say)
        "program": relay_online,
    }


def enter(conn, mosque: dict, device: dict | None, now: float | None = None) -> dict:
    """Takes or renews the lease, wakes the orchestrator when needed, and says where things stand."""
    now = time.time() if now is None else now
    lease, fresh = take(conn, mosque, device, now)
    _purge_wake(conn, now)
    if _wake_due(mosque["slug"], now, fresh):
        notify_platform(mosque["slug"], "wake")
    try:
        reply = live.set_setup(mosque, True, TTL_S)
    except live.OrchestratorError:
        reply = None
    path = live_watch.path_of(conn, mosque, "program")
    health = live_watch.health(path) if reply else None
    online = None if health is None else bool(health.get("online"))
    return view(mosque, lease, reply, now, online)


def leave(conn, mosque: dict, device: dict | None = None, admin: bool = False) -> dict:
    """Ends the setup: the lease is given back, the orchestrator told (it stops the rehearsal and may sleep).

    A device only gives back the lease it holds: another device's lease stays (`held_by_other`), unless `admin`."""
    row = current(conn, mosque["id"])
    if row and device is not None and not admin and row["device_id"] not in (None, device["id"]):
        return {"active": True, "held_by_other": True}
    held = release(conn, mosque["id"])
    if held:
        try:
            live.set_setup(mosque, False)
        except live.OrchestratorError:
            pass  # asleep or gone: its own lease lapses by itself
        notify_platform(mosque["slug"], "sleep")
        with _lock:
            _last_wake.pop(mosque["slug"], None)
    return {"active": False}


def program_path(conn, mosque: dict) -> str:
    """Relay path of the mosque's programme, from the mosque and never from the request."""
    return live_watch.path_of(conn, mosque, "program") or ""
