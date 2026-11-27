"""Client of the orchestrator API (sada/api.py): live status and manual commands.

Mode A: the orchestrator runs on the same machine (http://127.0.0.1:8088). Mode B: URL + token per mosque
(tunnel/VPN to the mosque's machine); the code does not change.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import runs
from ..i18n import _
from ..state import EXTEND_MINUTES, PICKABLE_SCENES, Machine

# Commands offered on the dashboard: derived from the engine, in its display order. No copy of the
# list lives here, so a command added to the machine shows up by itself.
COMMANDS = tuple(Machine.COMMANDS)

# Commands that stop or cancel the live: the front end asks for confirmation and paints them red.
DESTRUCTIVE = frozenset({"stop", "cancel"})

# Commands that take a value: parameter name on the orchestrator side, and allowed values. These are
# protocol keys, translated by the front end (dashboard.choice.<value>) — never labels.
_VARIED = {"extend": ("min", EXTEND_MINUTES), "scene": ("name", PICKABLE_SCENES)}


def choices(cmd: str) -> tuple:
    """Allowed values of a command, empty if it takes none."""
    return _VARIED.get(cmd, ("", ()))[1]


class OrchestratorError(Exception):
    pass


class SetupLapsed(OrchestratorError):
    """A command of the setup view reached an orchestrator whose setup lease has lapsed (it was not applied)."""


def _call(
    mosque: dict,
    method: str,
    path: str,
    params: dict | None = None,
    timeout: float = 3.0,
    json_body: dict | None = None,
) -> dict:
    base = (mosque.get("orchestrator_url") or "").rstrip("/")
    if not base:
        raise OrchestratorError(_("orchestrator address not configured"))
    url = f"{base}/{path}" + (("?" + urllib.parse.urlencode(params)) if params else "")
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
    else:
        data = b"" if method == "POST" else None
    req = urllib.request.Request(url, method=method, data=data)
    if json_body is not None:
        req.add_header("Content-Type", "application/json")
    if mosque.get("orchestrator_token"):
        req.add_header("X-Token", mosque["orchestrator_token"])
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        if e.code == 409:
            raise SetupLapsed(_("setup mode is not active")) from e
        raise OrchestratorError(_("orchestrator: HTTP error {code}", code=e.code)) from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise OrchestratorError(_("orchestrator unreachable (is the live not started on this machine?)")) from e


def status(mosque: dict, timeout: float = 3.0) -> dict:
    return _call(mosque, "GET", "status", timeout=timeout)


# --- Cached status
#
# A powered-off orchestrator does not answer: each read costs several seconds of waiting. The
# dashboard read it at every display, hence the impression that it never finished loading.
# We therefore keep a snapshot: the first read waits a little, the following ones are immediate and
# trigger a refresh in the background. An outage shows up at most one cycle later,
# which is enough for an indicator.
STATUS_TTL = 10.0
_caches: dict[str, tuple[float, dict]] = {}
_en_cours: set[str] = set()
_verrou = threading.Lock()


def _cle(mosque: dict) -> str:
    return (mosque.get("orchestrator_url") or "").rstrip("/")


def _lire(mosque: dict, timeout: float = 1.5) -> dict:
    try:
        return {"ok": True, **summarize(status(mosque, timeout=timeout))}
    except OrchestratorError as e:
        return {"ok": False, "error": str(e)}


def status_cached(mosque: dict, ttl: float = STATUS_TTL, forcer: bool = False) -> dict:
    """Orchestrator status, refreshed at most once every `ttl` seconds.

    `forcer`: immediate and blocking read (after a command, we want the real consequence)."""
    cle = _cle(mosque)
    entree = None
    if not forcer:
        with _verrou:
            entree = _caches.get(cle)
            if entree and (time.monotonic() - entree[0] < ttl or cle in _en_cours):
                return entree[1]
            if entree is not None:
                _en_cours.add(cle)
        if entree is not None:  # stale: we serve the snapshot, refresh behind
            threading.Thread(target=_rafraichir, args=(mosque, cle), daemon=True, name="statut-live").start()
            return entree[1]
    resultat = _lire(mosque)  # first call (or forced read): we wait
    with _verrou:
        old = _caches.get(cle)
        if _older(resultat, old[1] if old else None):
            return old[1]  # a command answered meanwhile with a newer state: that one is the truth
        _caches[cle] = (time.monotonic(), resultat)
    return resultat


def _older(new: dict, old: dict | None) -> bool:
    """`new` carries an older revision than the snapshot kept (both reachable): it must not replace it."""
    if not old or not new.get("ok") or not old.get("ok"):
        return False
    a, b = new.get("rev"), old.get("rev")
    return isinstance(a, int) and isinstance(b, int) and a < b


def remember(mosque: dict, answer: dict | None) -> dict | None:
    """The status a command answered with (`status`, see the orchestrator's commands), summarized and kept as the
    snapshot: the next reads serve the consequence of the command, not the state before it. None when the
    orchestrator did not send one (older engine): the caller then reads the status itself."""
    raw = answer.get("status") if isinstance(answer, dict) else None
    if not isinstance(raw, dict):
        return None
    resultat = {"ok": True, **summarize(raw)}
    cle = _cle(mosque)
    with _verrou:
        old = _caches.get(cle)
        # a poll that went out before the command may come back after it: the newest revision stays
        if not _older(resultat, old[1] if old else None):
            _caches[cle] = (time.monotonic(), resultat)
    return resultat


def _rafraichir(mosque: dict, cle: str) -> None:
    try:
        resultat = _lire(mosque)
        with _verrou:
            old = _caches.get(cle)
            if not _older(resultat, old[1] if old else None):
                _caches[cle] = (time.monotonic(), resultat)
    finally:
        with _verrou:
            _en_cours.discard(cle)


def command(
    mosque: dict,
    cmd: str,
    arg: str | None = None,
    info: str | None = None,
    valeur: str | None = None,
    transition: str | None = None,
    setup: bool = False,
) -> dict:
    """arg: name of the deceased (janaza); info: note on the janaza record; valeur: choice of a
    command with a parameter (minutes of extend, scene name of scene).

    A value outside the allowed list is refused here, before any network call. A command never
    goes through the status cache: it leaves immediately."""
    if cmd not in COMMANDS:
        raise OrchestratorError(_("unknown command"))
    permises = choices(cmd)
    params = {}
    if permises:
        valeur = valeur or (permises[0] if cmd == "extend" else None)  # extend: first value by default
        # a `custom:<slug>` scene goes through set_custom_scene (it carries the image), never through here
        if valeur not in permises:
            raise ValueError(_("invalid value for “{command}”", command=cmd))
        params[_VARIED[cmd][0]] = valeur
    if cmd == "janaza":
        if arg:
            params["name"] = arg[:80]
        if info and arg:  # a note alone makes no sense without a name
            params["info"] = info[:60]
    if transition is not None:
        params["transition"] = transition
    if setup:
        params["setup"] = "1"  # the setup rehearsal stage, never the live (see sada/setup_mode.py)
    return _call(mosque, "POST", cmd, params or None)


def set_transition(mosque: dict, mode: str, setup: bool = False) -> dict:
    return _call(mosque, "POST", "transition", json_body={"mode": mode, **({"setup": True} if setup else {})})


def set_custom_scene(
    mosque: dict,
    scene_id: str,
    image_bytes: bytes | None = None,
    transition: str | None = None,
    setup: bool = False,
) -> dict:
    body: dict[str, object] = {"scene": scene_id}
    if setup:
        body["setup"] = True
    if image_bytes:
        body["image_b64"] = base64.b64encode(image_bytes).decode("ascii")
    if transition is not None:
        body["transition"] = transition
    return _call(mosque, "POST", "custom-scene", json_body=body, timeout=5.0)


def set_overlay(mosque: dict, kind: str, data: dict, setup: bool = False) -> dict:
    return _call(mosque, "POST", "overlay", json_body={"kind": kind, **data, **({"setup": True} if setup else {})})


def set_mute(mosque: dict, muted: bool, setup: bool = False) -> dict:
    return _call(mosque, "POST", "mute", json_body={"muted": bool(muted), **({"setup": True} if setup else {})})


def set_setup(
    mosque: dict, on: bool, ttl: float | None = None, timeout: float = 4.0, compositing: str | None = None
) -> dict:
    """Takes, renews or releases the setup lease on the mosque's orchestrator (a short wait: it may be asleep).

    `compositing`: "studio" when the lease is a Sada Studio device's (it composes the rehearsal picture itself)."""
    body: dict[str, object] = {"on": bool(on)}
    if ttl is not None:
        body["ttl"] = ttl
    if compositing is not None:
        body["compositing"] = compositing
    return _call(mosque, "POST", "setup", json_body=body, timeout=timeout)


def _tarawih(ev: dict | None) -> dict | None:
    """Tonight's tarawih as the control room needs it: night number, reciters, current reciter
    (None until the control room says who: never guessed)."""
    if not isinstance(ev, dict) or ev.get("kind") != "tarawih":
        return None
    return {
        "night": ev.get("night"),
        "mode": ev.get("mode"),
        "reciters": list(ev.get("reciters") or []),
        "reciter": ev.get("reciter"),
    }


# States in which the mosque is on the air (the top bar shows "Live"). ARMED and ENDED are part of
# a live run but nothing is broadcast yet / any more.
ON_AIR_STATES = frozenset({"BEFORE", "KHUTBA", "PRAYER", "INTERMISSION", "JANAZA", "DARS", "TARAWIH"})


def on_air(st: dict) -> bool:
    """True when a summarized status says the mosque is broadcasting right now."""
    return bool(st.get("ok")) and (st.get("state") in ON_AIR_STATES or bool(st.get("stream_on")))


SESSION_STATUSES = frozenset({"pending", "live", "done", "skipped", "janaza"})


def _day(sessions: list) -> list[dict]:
    """Today's programme, one entry per session in order: keys and times only (the front end words it)."""
    out = []
    for s in sessions:
        if not isinstance(s, dict):
            continue
        status = s.get("status") if s.get("status") in SESSION_STATUSES else "pending"
        planned = str(s.get("planned") or "")
        out.append(
            {
                # "studio@…": a live started by hand from Sada Studio, outside the schedule
                "planned": "" if planned.startswith("studio@") else planned,
                "status": status,
                "kind": str(s.get("kind") or "khutba"),
                "title": str(s.get("title") or ""),
                "speaker": str(s.get("speaker") or ""),
                "started": s.get("start_clock"),
                "ended": s.get("end_clock"),
            }
        )
    return out


def summarize(st: dict) -> dict:
    """Raw orchestrator status -> protocol data: keys and values, no interface text.

    The current session is sent structured ({n, total, planned}) so the front end composes its own
    sentence and the server never writes a French label.
    """
    sessions = st.get("sessions") or []
    live = next((s for s in sessions if s.get("status") == "live"), None)
    planned = [s for s in sessions if runs.produces_content(s)]
    cur = live or next((s for s in planned if s.get("status") == "pending"), None)
    session = None
    if cur is not None:
        n = planned.index(cur) + 1 if cur in planned else None
        session = {"n": n, "total": len(planned), "planned": cur.get("planned"), "started": cur.get("start_clock")}
    return {
        "state": st.get("state"),
        "scene": st.get("scene"),
        # picture picked off air from the control room (Studio, preview): nothing is broadcast
        "preview_scene": st.get("preview_scene"),
        "clock": st.get("clock"),
        "session": session,
        "day": _day(sessions),
        "has_sessions": bool(planned),
        "next_session": st.get("next_session"),
        "stream_on": bool(st.get("stream_on")),
        "mic": bool(st.get("mic")),
        "override": bool(st.get("override")),
        "paused": bool(st.get("paused")),
        "last_reason": st.get("last_reason") or "",
        "run_id": st.get("run_id"),
        "janaza_name": st.get("janaza_name"),
        "janaza_info": st.get("janaza_info"),
        "tarawih": _tarawih(st.get("event")),
        "encoder_alive": bool((st.get("encoder") or {}).get("alive")),
        "vad_connected": bool((st.get("vad") or {}).get("connected")),
        "transition": st.get("transition") or "fade",
        "overlays": st.get("overlays"),
        "mic_muted": bool(st.get("mic_muted", False)),
        "audio_level_db": st.get("audio_level_db"),
        "setup": st.get("setup") if isinstance(st.get("setup"), dict) else None,
        # revision of this state (grows at every change); None from an engine that predates it
        "rev": st.get("rev") if isinstance(st.get("rev"), int) else None,
        # "studio": a Sada Studio device composes the picture itself, the engine only relays its stream
        "compositing": "studio" if st.get("compositing") == "studio" else "server",
        "playing_event": st.get("playing_event") if isinstance(st.get("playing_event"), dict) else None,
    }
