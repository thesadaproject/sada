"""Tarawih of a mosque: how the Ramadan night prayers are broadcast.

No prayer is ever filmed by default. Tarawih is the one exception, and only as the mosque chose:

- ``off``: nothing is broadcast;
- ``audio`` (default): the recitation is heard, a fixed full screen replaces the camera;
- ``video``: camera and sound. Refused unless the request confirms it explicitly (the mosque takes
  responsibility for filming the prayer); who confirmed it and when is kept and audited.

Nothing is planned outside the period (start and end dates), so a forgotten setting cannot run all
year. Nothing is armed before the end of isha (its iqama, else the adhan plus a usual delay,
plus ``isha_min``): isha itself is never broadcast. Then, with ``after_isha`` on, sustained voice
starts the broadcast at once (announcements, appeals for donations); otherwise only from the tarawih
proper, ``offset_min`` later. There is no fixed end: a silence longer than the pauses between sets
of rak'as (``silence_end_min``) with nobody at the front ends the night, or a stop, or a signal
lost for good, or at the fajr adhan at the latest; a maximum length (``max_min``) exists only when
the mosque chose one. A qiyam / tahajjud at a fixed hour (``qiyam_time``) is planned on its own
period of nights, like the tarawih; at an hour before noon it is the end of the night that began the
evening before. A night usually has several reciters: an ordered roster, optionally replaced for a
given night; the control room says who recites (never guessed).
"""

from __future__ import annotations

import datetime as dt
import json
import re

from ..events import TARAWIH_MODES
from ..i18n import _
from . import db, orm
from .models import Tarawih, TarawihOptions

DEFAULT_MODE = "audio"
DEFAULT_OFFSET_MIN, MIN_OFFSET_MIN, MAX_OFFSET_MIN = 20, 5, 120
LEGACY_MAX_MIN = 180  # what the old `max_min` column is still given (never read): a cap exists only in the options
MIN_MAX_MIN, MAX_MAX_MIN = 30, 720
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DEFAULT_ISHA_MIN, MIN_ISHA_MIN, MAX_ISHA_MIN = 10, 5, 30
DEFAULT_SILENCE_MIN, MIN_SILENCE_MIN, MAX_SILENCE_MIN = 6, 3, 30
MAX_PERIOD_DAYS = 31  # a Ramadan, with a day of margin for the moon sighting
MAX_IMAM_LEN = 80
MAX_RECITERS = 8
UID = "tarawih"
QIYAM_UID = "qiyam"


class InvalidTarawih(ValueError):
    """Readable refusal of a setting."""


def _row(conn, mosque_id: int) -> dict:
    return orm.first(conn, Tarawih, mosque_id=mosque_id) or {}


def _options(conn, mosque_id: int) -> dict:
    return orm.first(conn, TarawihOptions, mosque_id=mosque_id) or {}


def _json(text, default):
    try:
        value = json.loads(text or "")
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


def view(conn, mosque_id: int) -> dict:
    """What the Settings tab shows: saved values (defaults when nothing is saved) and the bounds."""
    r = _row(conn, mosque_id)
    o = _options(conn, mosque_id)
    return {
        "mode": r.get("mode") or DEFAULT_MODE,
        "start": r.get("start_date") or "",
        "end": r.get("end_date") or "",
        "offset_min": r.get("offset_min") or DEFAULT_OFFSET_MIN,
        "max_min": o.get("cap_min"),  # None: no limit
        "qiyam_time": o.get("qiyam_time") or "",
        "qiyam_start": o.get("qiyam_start") or "",
        "qiyam_end": o.get("qiyam_end") or "",
        "after_isha": bool(r.get("after_isha")),
        "isha_min": r.get("isha_min") or DEFAULT_ISHA_MIN,
        "silence_end_min": r.get("silence_end_min") or DEFAULT_SILENCE_MIN,
        "reciters": _json(r.get("reciters"), []),
        "nights": _json(r.get("nights"), {}),
        "video_confirmed_at": r.get("video_confirmed_at") if r.get("mode") == "video" else None,
        "modes": list(TARAWIH_MODES),
        "bounds": {
            "offset_min": [MIN_OFFSET_MIN, MAX_OFFSET_MIN],
            "max_min": [MIN_MAX_MIN, MAX_MAX_MIN],
            "isha_min": [MIN_ISHA_MIN, MAX_ISHA_MIN],
            "silence_end_min": [MIN_SILENCE_MIN, MAX_SILENCE_MIN],
            "reciters": MAX_RECITERS,
            "period_days": MAX_PERIOD_DAYS,
        },
    }


def _int(value, lo: int, hi: int, default: int, message: str) -> int:
    text = str(value if value is not None else "").strip()
    if not text:
        return default
    try:
        n = int(float(text.replace(",", ".")))
    except ValueError as e:
        raise InvalidTarawih(message) from e
    if not lo <= n <= hi:
        raise InvalidTarawih(message)
    return n


def _date(value) -> dt.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError as e:
        raise InvalidTarawih(_("Invalid date: {date}.", date=text)) from e


def _yes(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "on", "yes", "oui")


def _names(value) -> list[str]:
    """Ordered list of reciters: a JSON list, a list, or one name per line. Readable refusals."""
    if isinstance(value, str):
        text = value.strip()
        value = _json(text, []) if text.startswith("[") else text.splitlines()
    names, seen = [], set()
    for raw in value or []:
        name = " ".join(str(raw or "").split())
        if not name or name.casefold() in seen:
            continue
        if len(name) > MAX_IMAM_LEN:
            raise InvalidTarawih(_("Imam name too long ({max} characters at most).", max=MAX_IMAM_LEN))
        seen.add(name.casefold())
        names.append(name)
    if len(names) > MAX_RECITERS:
        raise InvalidTarawih(_("{max} reciters at most.", max=MAX_RECITERS))
    return names


def _nights(value, start: dt.date | None, end: dt.date | None) -> dict[str, list[str]]:
    """Per-night reciters, kept only for nights inside the period (an empty list: the roster)."""
    raw = _json(value, {}) if isinstance(value, str) else (value or {})
    out = {}
    for day, names in raw.items():
        d = _date(day)
        if d is None or start is None or end is None or not start <= d <= end:
            raise InvalidTarawih(_("Night {date} is outside the period.", date=day))
        names = _names(names)
        if names:
            out[d.isoformat()] = names
    return out


def _cap(value) -> int | None:
    """The maximum length of a night when the mosque chose one; empty: no limit."""
    if not str(value if value is not None else "").strip():
        return None
    return _int(
        value,
        MIN_MAX_MIN,
        MAX_MAX_MIN,
        0,
        _("Maximum length: from {min} to {max} minutes, or empty for none.", min=MIN_MAX_MIN, max=MAX_MAX_MIN),
    )


def _qiyam(form: dict, start: dt.date | None, end: dt.date | None) -> dict:
    """Validated qiyam / tahajjud: {time, start, end} ("" when there is none). Its nights default to the tarawih's."""
    t = str(form.get("qiyam_time") or "").strip()
    if not t:
        return {"time": "", "start": "", "end": ""}
    if not HHMM.match(t):
        raise InvalidTarawih(_("Invalid time: {time} (expected HH:MM).", time=t))
    qs, qe = _date(form.get("qiyam_start")), _date(form.get("qiyam_end"))
    if (qs is None) != (qe is None):
        raise InvalidTarawih(_("Give both the first and the last night of the qiyam."))
    if qs is None:
        if start is None or end is None:
            raise InvalidTarawih(_("Give the nights of the qiyam, or the period of the tarawih."))
        qs, qe = start, end
    if qe < qs:
        raise InvalidTarawih(_("The period ends before it starts."))
    if (qe - qs).days + 1 > MAX_PERIOD_DAYS:
        raise InvalidTarawih(_("The period cannot exceed {days} nights.", days=MAX_PERIOD_DAYS))
    return {"time": t, "start": qs.isoformat(), "end": qe.isoformat()}


def _span(start: dt.date | None, end: dt.date | None, qiyam: dict) -> tuple[dt.date | None, dt.date | None]:
    """The nights a per-night reciter list may name: those of the tarawih and of the qiyam together."""
    firsts = [d for d in (start, _date(qiyam["start"])) if d]
    lasts = [d for d in (end, _date(qiyam["end"])) if d]
    return (min(firsts), max(lasts)) if firsts and lasts else (None, None)


def check(form: dict) -> dict:
    """Validated values of a form (text values, as the API receives them). Raises InvalidTarawih."""
    mode = str(form.get("mode") or DEFAULT_MODE).strip().lower()
    if mode not in TARAWIH_MODES:
        raise InvalidTarawih(_("Unknown tarawih mode: {mode}.", mode=mode))
    if mode == "video" and not _yes(form.get("confirm_video")):
        raise InvalidTarawih(
            _("Filming the prayer needs an explicit confirmation: tick the box, the mosque is responsible for it.")
        )
    start, end = _date(form.get("start")), _date(form.get("end"))
    if (start is None) != (end is None):
        raise InvalidTarawih(_("Give both the first and the last night of the period."))
    if start is not None and end is not None:
        if end < start:
            raise InvalidTarawih(_("The period ends before it starts."))
        if (end - start).days + 1 > MAX_PERIOD_DAYS:
            raise InvalidTarawih(_("The period cannot exceed {days} nights.", days=MAX_PERIOD_DAYS))
    reciters = _names(form.get("reciters"))
    qiyam = _qiyam(form, start, end)
    nights = _nights(form.get("nights"), *_span(start, end, qiyam))
    return {
        "qiyam": qiyam,
        "cap_min": _cap(form.get("max_min")),
        "mode": mode,
        "start_date": start.isoformat() if start else "",
        "end_date": end.isoformat() if end else "",
        "offset_min": _int(
            form.get("offset_min"),
            MIN_OFFSET_MIN,
            MAX_OFFSET_MIN,
            DEFAULT_OFFSET_MIN,
            _("Delay after isha: from {min} to {max} minutes.", min=MIN_OFFSET_MIN, max=MAX_OFFSET_MIN),
        ),
        "max_min": LEGACY_MAX_MIN,
        "after_isha": 1 if _yes(form.get("after_isha")) else 0,
        "isha_min": _int(
            form.get("isha_min"),
            MIN_ISHA_MIN,
            MAX_ISHA_MIN,
            DEFAULT_ISHA_MIN,
            _("Length of isha: from {min} to {max} minutes.", min=MIN_ISHA_MIN, max=MAX_ISHA_MIN),
        ),
        "silence_end_min": _int(
            form.get("silence_end_min"),
            MIN_SILENCE_MIN,
            MAX_SILENCE_MIN,
            DEFAULT_SILENCE_MIN,
            _("Silence that ends the night: from {min} to {max} minutes.", min=MIN_SILENCE_MIN, max=MAX_SILENCE_MIN),
        ),
        "reciters": json.dumps(reciters, ensure_ascii=False),
        "nights": json.dumps(nights, ensure_ascii=False),
    }


def save(conn, mosque: dict, form: dict, user: dict | None, ip: str | None = None) -> dict:
    vals = check(form)
    qiyam, cap = vals.pop("qiyam"), vals.pop("cap_min")
    before = _row(conn, mosque["id"])
    now = db.now_iso()
    video = vals["mode"] == "video"
    keep = video and before.get("mode") == "video"  # still filmed: the first confirmation stands
    orm.upsert(
        conn,
        Tarawih,
        ("mosque_id",),
        mosque_id=mosque["id"],
        **vals,
        video_confirmed_by=(before.get("video_confirmed_by") if keep else (user or {}).get("id")) if video else None,
        video_confirmed_at=(before.get("video_confirmed_at") if keep else now) if video else None,
        updated_at=now,
    )
    orm.upsert(
        conn,
        TarawihOptions,
        ("mosque_id",),
        mosque_id=mosque["id"],
        cap_min=cap,
        qiyam_time=qiyam["time"],
        qiyam_start=qiyam["start"],
        qiyam_end=qiyam["end"],
    )
    db.audit(
        conn,
        mosque["id"],
        (user or {}).get("id"),
        "tarawih.configure",
        "mosque",
        mosque["id"],
        ip=ip,
        mode=vals["mode"],
        mode_avant=before.get("mode") or "",
        debut=vals["start_date"],
        fin=vals["end_date"],
        video_confirmee=video,
        qiyam=qiyam["time"],
        maximum=cap,
    )
    return view(conn, mosque["id"])


def _mode(r: dict) -> str:
    mode = r.get("mode") or DEFAULT_MODE
    if mode == "video" and not r.get("video_confirmed_at"):
        mode = "audio"  # never filmed without a recorded confirmation
    return mode


def event(conn, mosque_id: int) -> dict | None:
    """The nightly tarawih as a raw programme entry for the engine (`sada.events`), or None when
    nothing is to be broadcast (mode off, no period)."""
    r = _row(conn, mosque_id)
    if (r.get("mode") or DEFAULT_MODE) == "off" or not r.get("start_date") or not r.get("end_date"):
        return None
    cap = _options(conn, mosque_id).get("cap_min")
    out = {
        "uid": UID,
        "kind": "tarawih",
        "title": "Tarawih",
        "mode": _mode(r),
        "period": {"from": r["start_date"], "until": r["end_date"]},
        "recurrence": {"after": "isha", "offset_min": r.get("offset_min") or DEFAULT_OFFSET_MIN},
        "after_isha": bool(r.get("after_isha")),
        "isha_min": r.get("isha_min") or DEFAULT_ISHA_MIN,
        "silence_end_min": r.get("silence_end_min") or DEFAULT_SILENCE_MIN,
        "reciters": _json(r.get("reciters"), []),
        "nights": _json(r.get("nights"), {}),
    }
    if cap:  # only a maximum the mosque chose: a night has no other limit than its own ending
        out["max_min"] = cap
    return out


def qiyam_event(conn, mosque_id: int) -> dict | None:
    """The qiyam / tahajjud at a fixed hour, as a raw programme entry (a tarawih with a `time`), or None."""
    r, o = _row(conn, mosque_id), _options(conn, mosque_id)
    if (r.get("mode") or DEFAULT_MODE) == "off" or not o.get("qiyam_time") or not o.get("qiyam_start"):
        return None
    out = {
        "uid": QIYAM_UID,
        "kind": "tarawih",
        "title": "Qiyam",
        "mode": _mode(r),
        "time": o["qiyam_time"],
        "period": {"from": o["qiyam_start"], "until": o["qiyam_end"]},
        "silence_end_min": r.get("silence_end_min") or DEFAULT_SILENCE_MIN,
        "reciters": _json(r.get("reciters"), []),
        "nights": _json(r.get("nights"), {}),
    }
    if r.get("start_date"):
        out["night_origin"] = r["start_date"]  # its nights are numbered like the tarawih's of the same Ramadan
    if o.get("cap_min"):
        out["max_min"] = o["cap_min"]
    return out


def events(conn, mosque_id: int) -> list[dict]:
    """Every raw entry the Tarawih settings give the engine: the nightly tarawih and the qiyam."""
    return [e for e in (event(conn, mosque_id), qiyam_event(conn, mosque_id)) if e]
