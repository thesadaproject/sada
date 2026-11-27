"""What the studio device is told, and the manual live (start, stop, announce).

`order_for` turns the mosque's order (`studio_plan.decide`) into the order of *this* device: only one device
per mosque is designated to publish, a device told to stay quiet (taken over) stays in standby, and a
standby always says why. The manual commands write to the journal and answer 409 with the reason when the
mosque already has a live from another source.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import select, update

from ..i18n import _
from . import db, live_watch, orm, studio_devices, studio_plan, studio_publisher
from .models import Device, StudioClaim, StudioRun

TYPES = ("khutba", "dars", "conference")


class Conflict(Exception):
    def __init__(self, status: int, body: dict):
        super().__init__(body.get("error", ""))
        self.status, self.body = status, body


def reason_text(code: str, **kw) -> str:
    return {
        "idle": _("No live planned for now."),
        "slot": _("A live is planned: start broadcasting."),
        "manual": _("A live started from the device is in progress."),
        "slot_stopped": _("This live was stopped by hand; it will not restart by itself."),
        "held": _("An administrator took the stream over: the device stays quiet for now."),
        "other_device": _("Another device of the mosque ({name}) takes care of the live.", name=kw.get("name", "?")),
    }[code]


@dataclass(frozen=True)
class DeviceOrder:
    order: studio_plan.Order
    slots: list
    other: str = ""

    def body(self) -> dict:
        o = self.order
        return {
            "command": o.command,
            "reason_code": o.code,
            "reason": reason_text(o.code, name=self.other),
            "current": o.current,
            "next": o.next,
        }


def _designated(conn, mosque_id: int, order: studio_plan.Order, dev: dict, now: float) -> dict:
    """The device that publishes: the manual live's, else the holder of the stream, else the oldest online."""
    devices = [
        d
        for d in orm.rows(conn, select(Device).where(Device.mosque_id == mosque_id, Device.revoked_at.is_(None)))
        if d["held_until"] <= now and (d["id"] == dev["id"] or studio_devices.is_online(d, now))
    ]
    by_id = {d["id"]: d for d in devices}
    if order.source == "manual":
        run = orm.first(conn, StudioRun, StudioRun.ended_at.is_(None), mosque_id=mosque_id, origin="manual")
        if run and run["device_id"] in by_id:
            return by_id[run["device_id"]]
    claim = orm.first(conn, StudioClaim, mosque_id=mosque_id)
    if claim and claim["device_id"] in by_id:
        return by_id[claim["device_id"]]
    return min(devices, key=lambda d: d["id"]) if devices else dev


def order_for(conn, mosque: dict, dev: dict, now: float | None = None) -> DeviceOrder:
    now = time.time() if now is None else now
    order, slots = studio_plan.current_order(conn, mosque, now)
    if dev["held_until"] > now:
        return DeviceOrder(studio_plan.Order(studio_plan.STANDBY, None, "held", None, order.next), slots)
    if order.command == studio_plan.LIVE:
        chosen = _designated(conn, mosque["id"], order, dev, now)
        if chosen["id"] != dev["id"]:
            return DeviceOrder(
                studio_plan.Order(studio_plan.STANDBY, None, "other_device", None, order.next), slots, chosen["name"]
            )
    return DeviceOrder(order, slots)


def who_of(dev: dict) -> studio_publisher.Who:
    return studio_publisher.Who("device", device_id=dev["id"], label=dev["name"])


# ------------------------------------------------------------------ manual live


def _guard_free(conn, mosque: dict, dev: dict) -> None:
    holder = studio_publisher.current(conn, mosque)
    if holder is not None and not (holder["known"] and who_of(dev).same_as(holder)):
        raise Conflict(409, studio_publisher.refusal(holder))


def start_manual(
    conn, mosque: dict, dev: dict, kind: str, title: str, ip: str | None, now: float | None = None
) -> dict:
    now = time.time() if now is None else now
    kind = str(kind or "").strip().lower()
    title = " ".join(str(title or "").split())[:200]
    if kind not in TYPES:
        raise Conflict(
            422,
            {"error": _("Unknown type: choose khutba, dars or conference."), "code": "bad_type"},
        )
    if dev["held_until"] > now:
        raise Conflict(409, {"error": reason_text("held"), "code": "held"})
    _guard_free(conn, mosque, dev)
    run = studio_plan.manual_run(conn, mosque["id"], now)
    if run is not None and run["device_id"] != dev["id"]:
        other = orm.first(conn, Device, id=run["device_id"]) or {}
        raise Conflict(
            409,
            {
                "error": _(
                    "A live is already running from {source}.",
                    source=_("the device “{name}”", name=other.get("name", "?")),
                ),
                "code": "live_active",
                "since": studio_publisher.iso(run["started_at"]),
                "source": {"kind": "device", "label": other.get("name", ""), "since": run["started_at"]},
            },
        )
    if run is None:
        conn.add(
            StudioRun(
                mosque_id=mosque["id"], device_id=dev["id"], origin="manual", kind=kind, title=title, started_at=now
            )
        )
        orm.done(conn)
        db.audit(
            conn, mosque["id"], None, "studio.direct.manuel.debut", "appareil", dev["id"],
            ip=ip, type=kind, titre=title, appareil=dev["name"],
        )  # fmt: skip
    else:  # the same device asks again (retry): its live goes on, the announcement is refreshed
        conn.execute(update(StudioRun).where(StudioRun.id == run["id"]).values(kind=kind, title=title))
        orm.done(conn)
    return answer(conn, mosque, dev, now)


def stop(conn, mosque: dict, dev: dict, ip: str | None, now: float | None = None) -> dict:
    """Manual stop: ends the manual live and the scheduled slot running now, which then does not restart."""
    now = time.time() if now is None else now
    order, slots = studio_plan.current_order(conn, mosque, now)
    stopped = []
    run = studio_plan.manual_run(conn, mosque["id"], now)
    if run is not None:
        conn.execute(update(StudioRun).where(StudioRun.id == run["id"]).values(ended_at=now))
        orm.done(conn)
        stopped.append("manual")
        db.audit(
            conn, mosque["id"], None, "studio.direct.manuel.fin", "appareil", dev["id"],
            ip=ip, motif="arret", titre=run["title"], appareil=dev["name"],
        )  # fmt: skip
        order, slots = studio_plan.current_order(conn, mosque, now)
    slot = studio_plan.running_slot(order, slots)
    if slot is not None:
        studio_plan.stop_marks(conn, mosque["id"], slot.key, now)
        stopped.append("slot")
        db.audit(
            conn, mosque["id"], None, "studio.creneau.arret", "appareil", dev["id"],
            ip=ip, creneau=slot.key, titre=slot.title, appareil=dev["name"],
        )  # fmt: skip
    claim = orm.first(conn, StudioClaim, mosque_id=mosque["id"])
    if claim and claim["device_id"] == dev["id"]:
        live_watch.kick(studio_publisher.path_of(mosque))  # the stream ends even if the app forgets to close it
        studio_publisher.release(conn, mosque["id"])
    return {"stopped": stopped} | answer(conn, mosque, dev, now)


def end_lost(conn, mosque: dict, lost_at: float | None = None, now: float | None = None) -> dict:
    """The orchestrator ended the live because the picture never came back (see `studio_link.SIGNAL_GRACE_S`): the
    manual live is closed and the scheduled slot running now is marked as stopped, exactly as a manual stop does, so the
    announcement says `live: false` and the device, at its next heartbeat, goes back to standby and does not restart it.

    `lost_at` (epoch s): only what began before the loss is closed, so a live started since is never touched by a late
    or repeated call. Nothing to close is not an error (the call may be repeated)."""
    now = time.time() if now is None else now
    limit = now if lost_at is None else float(lost_at)
    ended = []
    run = orm.first(conn, StudioRun, StudioRun.ended_at.is_(None), mosque_id=mosque["id"], origin="manual")
    if run is not None and run["started_at"] <= limit:
        conn.execute(update(StudioRun).where(StudioRun.id == run["id"]).values(ended_at=now))
        orm.done(conn)
        ended.append("manual")
        db.audit(
            conn, mosque["id"], None, "studio.direct.manuel.fin", "appareil", run["device_id"],
            motif="signal_perdu", titre=run["title"],
        )  # fmt: skip
    order, slots = studio_plan.current_order(conn, mosque, now)
    slot = studio_plan.running_slot(order, slots)
    if slot is not None and slot.starts.timestamp() <= limit:
        studio_plan.stop_marks(conn, mosque["id"], slot.key, now)
        ended.append("slot")
        db.audit(
            conn, mosque["id"], None, "studio.creneau.arret", "appareil", None,
            motif="signal_perdu", creneau=slot.key, titre=slot.title,
        )  # fmt: skip
    if ended:
        claim = orm.first(conn, StudioClaim, mosque_id=mosque["id"])
        if claim:  # the stream, if it is still there, is no longer wanted: the device must not stay on air
            live_watch.kick(studio_publisher.path_of(mosque))
            studio_publisher.release(conn, mosque["id"])
    return {"ended": ended}


def announce(conn, mosque: dict, dev: dict, kind: str, title: str, ip: str | None, now: float | None = None) -> dict:
    """Type and title of the live in progress (kept with it, for the replay)."""
    now = time.time() if now is None else now
    kind = str(kind or "").strip().lower()
    title = " ".join(str(title or "").split())[:200]
    if kind not in TYPES:
        raise Conflict(422, {"error": _("Unknown type: choose khutba, dars or conference."), "code": "bad_type"})
    order, slots = studio_plan.current_order(conn, mosque, now)
    if order.command != studio_plan.LIVE:
        raise Conflict(409, {"error": _("No live is in progress to announce."), "code": "no_live"})
    if order.source == "manual":
        run = studio_plan.manual_run(conn, mosque["id"], now)
        conn.execute(update(StudioRun).where(StudioRun.id == run["id"]).values(kind=kind, title=title))
        orm.done(conn)
    else:
        studio_plan.announce_slot(conn, mosque["id"], dev["id"], order.current["slot_id"], kind, title, now)
    db.audit(
        conn, mosque["id"], None, "studio.direct.annonce", "appareil", dev["id"],
        ip=ip, type=kind, titre=title, source=order.source, appareil=dev["name"],
    )  # fmt: skip
    return answer(conn, mosque, dev, now)


def answer(conn, mosque: dict, dev: dict, now: float) -> dict:
    return order_for(conn, mosque, dev, now).body()


def current_announcement(conn, mosque: dict, now: float | None = None) -> dict:
    """What the orchestrator reads to attach type and title to the replay: {live, source, type, title}."""
    order, _slots = studio_plan.current_order(conn, mosque, now)
    cur = order.current or {}
    return {
        "live": order.command == studio_plan.LIVE,
        "source": cur.get("source"),
        "type": cur.get("type"),
        "title": cur.get("title"),
        "slot_id": cur.get("slot_id"),
    }


# ------------------------------------------------------------------ the web control room drives the studio
# The control room is the Sada Studio's remote control: a command that puts the mosque on air from there must
# also tell the studio to publish (else the engine goes on air with nothing to relay), and stopping there stops
# the studio too. It is the studio's own manual live, on the designated device, so everything that follows a
# manual live (the orchestrator's session, the silence watch, the journal) works unchanged.

#: Commands of the control room that put the mosque on air, and the ones that take it off air. A scene is in
#: neither: taken off air it only changes the picture (Studio and preview), it never starts a live; only
#: "start" (and "tarawih") broadcasts.
ON_AIR = frozenset({"start", "tarawih"})
OFF_AIR = frozenset({"stop", "cancel"})


def follow_regie(conn, mosque: dict, cmd: str, valeur: str | None, ip: str | None, now: float | None = None) -> str:
    """Aligns the studio on a control-room command. Returns what happened, for the answer:

    `ordered` (the studio was told to publish), `already` (it already is: a slot or a manual live),
    `stopped`, `no_studio` (no paired device online: OBS or a camera feeds the mosque, or the PC is off),
    `busy` (another source holds the stream, or the device is held back), `none` (nothing to do)."""
    from . import live_input, studio_preview

    now = time.time() if now is None else now
    if live_input.current(conn, mosque)["mode"] != "push":
        return "none"  # a camera read by the relay: no studio to drive
    if cmd == "scene":
        return "none"  # off air a scene only changes the picture; during a live the studio already publishes
    if cmd in ON_AIR:
        order, _slots = studio_plan.current_order(conn, mosque, now)
        if order.command == studio_plan.LIVE:
            return "already"
        dev = studio_preview.designated(conn, mosque, now)
        if dev is None:
            return "no_studio"
        try:
            start_manual(conn, mosque, dev, "khutba", "", ip, now)
        except Conflict:
            return "busy"
        return "ordered"
    if cmd in OFF_AIR:
        run = studio_plan.manual_run(conn, mosque["id"], now)
        order, slots = studio_plan.current_order(conn, mosque, now)
        if run is None and studio_plan.running_slot(order, slots) is None:
            return "none"
        claim = orm.first(conn, StudioClaim, mosque_id=mosque["id"])
        did = (run or {}).get("device_id") or (claim or {}).get("device_id")
        dev = orm.first(conn, Device, id=did) if did else studio_preview.designated(conn, mosque, now)
        if dev is None:
            return "none"
        stop(conn, mosque, dev, ip, now)
        return "stopped"
    return "none"
