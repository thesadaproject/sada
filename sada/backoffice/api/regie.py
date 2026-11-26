"""Control room (“Régie”): live state for the page, and the two monitors proxied to the relay.

Every route needs a session open on a mosque and the `live` permission. The monitors never take a
stream name from the request: the path comes from the session's mosque (live_watch.path_of).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import OrderedDict
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ... import scenes, transitions
from ...i18n import _
from ...state import PICKABLE_SCENES
from .. import (
    custom_scenes,
    live,
    live_input,
    live_watch,
    studio_plan,
    studio_publisher,
    studio_service,
    studio_token,
)
from .. import screens as screens_mod
from ..context import CtxDep, NotFound
from ..studio_auth import Actor, ActorDep

router = APIRouter()

# The control room refreshes every few seconds: a fresher snapshot than the dashboard's.
STATUS_TTL = 3.0
MAX_SDP = 64 * 1024


def _path(ctx, which: str) -> str:
    if which not in live_watch.SOURCES:
        raise NotFound()
    return live_watch.path_of(ctx.conn, ctx.mosque, which) or ""


def _offline() -> JSONResponse:
    return JSONResponse({"error": "offline"}, status_code=404)


TRANSITION_SETTING_KEY = "regie_transition"


def _builtin_scenes() -> list[dict]:
    return [
        {
            "id": sc,
            "kind": "camera" if sc in ("khutba", "dars") else "slate",
            "custom": False,
            "label": sc,
            # how the scene sits over the camera (camera | banner | full), and whether the mic is open on it:
            # what a client composing the picture itself (the Sada Studio) needs
            "scene_kind": scenes.scene_kind(sc),
            "mic": scenes.scene_mic(sc),
        }
        for sc in PICKABLE_SCENES
    ]


def _all_scenes(conn, mosque: dict) -> list[dict]:
    custom = [
        {**c, "scene_kind": scenes.scene_kind(c["id"]), "mic": False} for c in custom_scenes.list_scenes(conn, mosque)
    ]
    return _builtin_scenes() + custom


def _setup_kwargs(setup: bool) -> dict:
    """Extra argument of the live client for a command sent from the setup view (none otherwise)."""
    return {"setup": True} if setup else {}


def _setup_failure(e: live.OrchestratorError) -> JSONResponse:
    """A setup command the orchestrator did not apply: its lease lapsed (409, the application re-enters), or it is down."""
    if isinstance(e, live.SetupLapsed):
        return JSONResponse({"error": str(e), "code": "setup_off"}, status_code=409)
    return JSONResponse({"error": str(e)}, status_code=503)


def live_flat(mosque: dict, forcer: bool = False, setup: bool = False) -> dict:
    """Engine snapshot in the flat protocol shape the studio application reads (LiveStatus).

    `forcer`: immediate read, used right after a command so the screen shows the consequence and not
    the previous snapshot. `setup`: the caller is in setup mode; while its rehearsal runs (and no real live is
    on air) scene, overlays, transition and mute are the rehearsal stage's, as they are what the view shows.
    """
    return flat(live.status_cached(mosque, ttl=STATUS_TTL, forcer=forcer), setup)


# What the setup block of the status overrides in the flat state while a rehearsal runs.
_SETUP_KEYS = ("state", "scene", "override", "transition", "overlays", "mic_muted", "rev", "compositing")


def flat(st: dict, setup: bool = False) -> dict:
    """A summarized status (live.summarize) in the flat shape of `live_flat`."""
    block = st.get("setup")
    if setup and isinstance(block, dict) and block.get("active") and not block.get("live"):
        st = {**st, **{k: block[k] for k in _SETUP_KEYS if k in block}}
    ok = bool(st.get("ok"))
    return {
        "ok": ok,
        "reachable": ok,
        "state": st.get("state"),
        "scene": st.get("scene"),
        "scene_kind": scenes.scene_kind(st.get("scene")),
        "override": bool(st.get("override")),
        "transition": st.get("transition"),
        "overlays": st.get("overlays"),
        "mic": bool(st.get("mic", False)),
        "mic_muted": bool(st.get("mic_muted", False)),
        "audio_level_db": st.get("audio_level_db"),
        "message": st.get("error") or st.get("last_reason") or "",
        "rev": st.get("rev") if isinstance(st.get("rev"), int) else None,
        "compositing": "studio" if st.get("compositing") == "studio" else "server",
    }


def after_command(mosque: dict, answer, setup: bool = False) -> dict:
    """The state right after a command, flat: the one the orchestrator answered with (no second request), else a
    fresh read (older engine). Also becomes the status snapshot, so the next polls do not go back in time."""
    summary = live.remember(mosque, answer if isinstance(answer, dict) else None)
    if summary is None:
        return live_flat(mosque, forcer=True, setup=setup)
    return flat(summary, setup)


def _with_state(out: dict, mosque: dict, answer, setup: bool) -> dict:
    """A command's own answer plus the whole state after it (`status`, flat) and its revision (`rev`)."""
    state = after_command(mosque, answer, setup)
    return {**out, "rev": state["rev"], "compositing": state["compositing"], "status": state}


def regie_data(conn, mosque: dict, setup: bool = False) -> dict:
    """Control room payload for a paired device (RegieData): mosque, engine state, scenes, commands."""
    st = live_flat(mosque, setup=setup)
    return {
        "mosque": mosque["name"],
        "slug": mosque["slug"],
        "status": st,
        "transition": st.get("transition") or _saved_transition(mosque),
        "scenes": _all_scenes(conn, mosque),
        "audio": {"mic_on": st["mic"], "muted": st["mic_muted"], "level_db": st["audio_level_db"]},
        "commands": list(live.COMMANDS),
        "extend_minutes": [str(m) for m in live.choices("extend")],
        "overlays": st.get("overlays"),
    }


def _body(corps) -> dict:
    return corps if isinstance(corps, dict) else {}


async def _json(request: Request) -> dict:
    """JSON body as sent; an empty, form-encoded or unreadable body is `{}`."""
    try:
        corps = await request.json()
    except Exception:  # noqa: BLE001 — empty or unreadable body
        corps = {}
    return corps if isinstance(corps, dict) else {}


async def apply_scene(conn, mosque: dict, scene_id, tr_mode, setup: bool = False) -> dict | JSONResponse:
    """Takes a scene (builtin or `custom:<slug>`), with an optional transition."""
    scene_id = str(scene_id or "").strip().lower()
    if tr_mode is not None:
        tr_mode = str(tr_mode).strip().lower()
        if tr_mode not in transitions.TRANSITIONS:
            return JSONResponse({"error": _("unknown transition: {mode}", mode=tr_mode)}, status_code=400)
    if scene_id.startswith("custom:"):
        raw = await run_in_threadpool(custom_scenes.image_bytes, mosque, scene_id[len("custom:") :])
        if raw is None:
            raise NotFound()
        try:
            r = await run_in_threadpool(
                live.set_custom_scene, mosque, scene_id, raw, transition=tr_mode, **_setup_kwargs(setup)
            )
        except live.OrchestratorError as e:
            return _setup_failure(e)
        out = {"ok": True, "scene": scene_id, "transition": tr_mode or _saved_transition(mosque), "result": r}
        return await run_in_threadpool(_with_state, out, mosque, r, setup)
    try:
        r = await run_in_threadpool(
            live.command, mosque, "scene", valeur=scene_id, transition=tr_mode, **_setup_kwargs(setup)
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except live.OrchestratorError as e:
        return _setup_failure(e)
    out = {"ok": True, "scene": scene_id, "transition": tr_mode or _saved_transition(mosque), "result": r}
    return await run_in_threadpool(_with_state, out, mosque, r, setup)


async def apply_mute(mosque: dict, muted, setup: bool = False) -> dict | JSONResponse:
    if not isinstance(muted, bool):
        return JSONResponse({"error": _("invalid body")}, status_code=400)
    try:
        r = await run_in_threadpool(live.set_mute, mosque, muted, **_setup_kwargs(setup))
    except live.OrchestratorError as e:
        return _setup_failure(e)
    out = {"ok": True, "muted": muted, "mic_muted": muted, "result": r}
    return await run_in_threadpool(_with_state, out, mosque, r, setup)


async def apply_transition(mosque: dict, mode, setup: bool = False) -> dict | JSONResponse:
    mode = str(mode or "").strip().lower()
    if mode not in transitions.TRANSITIONS:
        return JSONResponse({"error": _("unknown transition: {mode}", mode=mode)}, status_code=400)
    if not setup:  # the rehearsal's transition is not the mosque's setting
        await run_in_threadpool(custom_scenes.set_transition, mosque, mode)
    synced, r = True, None
    try:
        r = await run_in_threadpool(live.set_transition, mosque, mode, **_setup_kwargs(setup))
    except live.SetupLapsed as e:
        return _setup_failure(e)
    except live.OrchestratorError:
        synced = False
    out = {"ok": True, "transition": mode, "synced": synced}
    if not synced:
        return out  # the engine did not answer: no state to report beyond the saved setting
    return await run_in_threadpool(_with_state, out, mosque, r, setup)


def _saved_transition(mosque: dict) -> str:
    return custom_scenes.get_transition(mosque)


@router.get("/live/regie")
def regie(ctx: CtxDep):
    ctx.require("live")
    mosque = ctx.mosque
    assert mosque is not None
    paths = {w: live_watch.path_of(ctx.conn, mosque, w) for w in live_watch.SOURCES}
    health = {w: live_watch.health(p) for w, p in paths.items()}
    holder = studio_publisher.current(ctx.conn, mosque)
    live_st = live.status_cached(mosque, ttl=STATUS_TTL)
    tr_mode = live_st.get("transition") if live_st.get("transition") in transitions.TRANSITIONS else None
    if tr_mode is None:
        tr_mode = _saved_transition(mosque)
    return {
        "publisher": holder and {k: holder[k] for k in ("source", "label", "since", "text")},
        "live": live_st,
        # revision of the live state and who composes the picture (also inside `live`)
        "rev": live_st.get("rev"),
        "compositing": live_st.get("compositing") or "server",
        "transition": tr_mode,
        "scenes": _all_scenes(ctx.conn, mosque),
        "overlays": live_st.get("overlays"),
        "audio": {
            "mic_on": bool(live_st.get("mic", False)),
            "muted": bool(live_st.get("mic_muted", False)),
            "level_db": live_st.get("audio_level_db"),
        },
        "commands": [
            {"key": k, "destructive": k in live.DESTRUCTIVE, "choices": list(live.choices(k))} for k in live.COMMANDS
        ],
        # A monitor is only connected once its stream is received: an empty path (programme while the
        # engine is off, preview while OBS is not sending) would answer 404 on every retry.
        "monitors": {
            w: {"available": bool(p) and (health[w] is None or bool(health[w].get("online"))), "health": health[w]}
            for w, p in paths.items()
        },
    }


@router.post("/live/regie/mute")
async def regie_mute(request: Request, a: ActorDep):
    """Mutes the incoming microphone. Session (control room) or paired device (studio application)."""
    a.need_live()
    body = _body(await _json(request))
    setup = body.get("setup") is True
    out = await apply_mute(a.mosque, body.get("muted"), setup=setup)
    if isinstance(out, dict):
        a.audit("studio.live.sourdine", muted=out["muted"], setup=setup)
    return out


@router.post("/live/regie/transition")
async def regie_transition(request: Request, a: ActorDep):
    a.need_live()
    body = _body(await _json(request))
    setup = body.get("setup") is True
    out = await apply_transition(a.mosque, body.get("mode"), setup=setup)
    if isinstance(out, dict):
        a.audit("studio.live.transition", transition=out["transition"], setup=setup)
    return out


async def _read_bounded(file: UploadFile, limit: int) -> bytes:
    """The upload by chunks, refused as soon as it exceeds `limit`: the whole body is never held in memory."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(64 * 1024):
        total += len(chunk)
        if total > limit:
            raise ValueError(_("image too large (5 MB maximum)"))
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/live/regie/custom-scenes")
async def regie_custom_scene_create(
    ctx: CtxDep,
    file: Annotated[UploadFile, File(...)],
    label: str = Form(...),
    category: str = Form("autre"),
):
    ctx.need_csrf()
    ctx.require("live")
    mosque = ctx.mosque
    assert mosque is not None
    try:
        raw = await _read_bounded(file, custom_scenes.MAX_BYTES)
        created = await run_in_threadpool(  # decoding and re-encoding the image is CPU-bound
            custom_scenes.create,
            ctx.conn,
            mosque,
            label=label,
            category=category,
            filename=file.filename or "scene.png",
            content=raw,
            user_id=ctx.user["id"],
            ip=ctx.ip,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"scene": created, "scenes": _all_scenes(ctx.conn, mosque)}


@router.get("/live/regie/custom-scenes/{slug}/image")
def regie_custom_scene_image(slug: str, a: ActorDep):
    """Read by the control room (session) and by the studio application (device): `preview_url` of a scene."""
    a.need_live(write=False)
    raw = custom_scenes.image_bytes(a.mosque, slug)
    if raw is None:
        raise NotFound()
    return Response(raw, media_type="image/png", headers={"Cache-Control": "private, max-age=30"})


@router.delete("/live/regie/custom-scenes/{slug}")
def regie_custom_scene_delete(slug: str, ctx: CtxDep):
    ctx.need_csrf()
    ctx.require("live")
    mosque = ctx.mosque
    assert mosque is not None
    if not custom_scenes.delete(ctx.conn, mosque, slug, user_id=ctx.user["id"], ip=ctx.ip):
        raise NotFound()
    return {"ok": True, "scenes": _all_scenes(ctx.conn, mosque)}


@router.post("/live/regie/scene")
async def regie_take_scene(request: Request, a: ActorDep):
    a.need_live()
    body = await _json(request)
    setup = body.get("setup") is True
    out = await apply_scene(a.conn, a.mosque, body.get("scene"), body.get("transition"), setup=setup)
    if isinstance(out, dict):
        a.audit("studio.live.commande", commande="scene", valeur=out["scene"], setup=setup)
    return out


@router.get("/live/regie/scene/{name}.png")
async def scene_preview(name: str, a: ActorDep):
    """Studio mode: the scene as it would go on air, with the mosque's saved texts. Banner scenes come
    without background, to be laid over the preview feed."""
    a.need_live(write=False)
    if name not in live.choices("scene"):
        raise NotFound()
    textes = screens_mod.saved(a.conn, a.mosque["id"])
    png = await run_in_threadpool(screens_mod.preview, a.mosque, textes, name, True, a.conn)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=30"})


# ------------------------------------------------------------------ overlay layer
# The studio lays this PNG over its local monitor: the very layer the engine composites over the camera
# (SceneRenderer.render_overlays), for the overlay state the caller sees (the rehearsal's in setup mode).
# The ETag is a digest of what the drawing depends on, so the client revalidates cheaply (304) every few
# seconds and a new image is drawn only when an overlay (or the logo) changed. (The API middleware marks
# every response `no-store`: the client keeps the last image itself and sends If-None-Match.)

_LAYER_CACHE: OrderedDict[str, bytes] = OrderedDict()
_LAYER_CACHE_MAX = 32
_LAYER_LOCK = threading.Lock()


def _layer_etag(mosque: dict, overlays: dict | None) -> str:
    logo = screens_mod.overlay_logo(mosque)
    try:
        st = os.stat(logo) if logo else None
        stamp = f"{st.st_mtime_ns}:{st.st_size}" if st else ""
    except OSError:
        stamp = "missing"
    key = json.dumps(
        {"m": mosque["id"], "n": mosque.get("name") or "", "logo": [logo, stamp], "o": overlays or {}},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return '"ov-' + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24] + '"'


def overlay_layer(mosque: dict, overlays: dict | None) -> tuple[str, bytes]:
    """(ETag, PNG) of the overlay layer; drawn once per distinct state, then served from a small memory cache."""
    etag = _layer_etag(mosque, overlays)
    with _LAYER_LOCK:
        png = _LAYER_CACHE.get(etag)
        if png is not None:
            _LAYER_CACHE.move_to_end(etag)
            return etag, png
    png = screens_mod.overlays_layer(mosque, overlays)
    with _LAYER_LOCK:
        _LAYER_CACHE[etag] = png
        while len(_LAYER_CACHE) > _LAYER_CACHE_MAX:
            _LAYER_CACHE.popitem(last=False)
    return etag, png


def _matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    return header.strip() == "*" or etag in {t.strip().removeprefix("W/") for t in header.split(",")}


@router.get("/live/regie/overlays.png")
async def overlays_png(request: Request, a: ActorDep, setup: int = 0):
    """Transparent 1280×720 PNG of every overlay currently on air (logo, banner, QR), as the engine draws it.

    `?setup=1`: the rehearsal's overlays, while the caller's setup view is open (same rule as the status).
    The engine unreachable: 503 `offline` — the client then falls back to its own approximation.
    """
    a.need_live(write=False)
    st = await run_in_threadpool(live_flat, a.mosque, False, bool(setup))
    if not st.get("ok"):
        return JSONResponse(
            {"error": st.get("message") or _("engine unreachable"), "code": "offline"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    overlays = st.get("overlays") if isinstance(st.get("overlays"), dict) else None
    etag, png = await run_in_threadpool(overlay_layer, a.mosque, overlays)
    headers = {"ETag": etag}
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(png, media_type="image/png", headers=headers)


@router.post("/live/watch/{which}/whep")
async def whep_offer(which: str, request: Request, ctx: CtxDep):
    ctx.need_csrf()
    ctx.require("live")
    path = _path(ctx, which)
    if not path:
        return _offline()
    sdp = await request.body()
    if not sdp or len(sdp) > MAX_SDP:
        return JSONResponse({"error": _("bad offer")}, status_code=400)
    try:
        status, answer, session = await live_watch.whep_offer(path, sdp)
    except live_watch.RelayUnavailable:
        return JSONResponse({"error": _("relay unavailable")}, status_code=503)
    if status != 201 or not session:
        # 404 from the relay: nothing is published on this path right now
        return _offline() if status in (400, 404) else JSONResponse({"error": "relay"}, status_code=502)
    return Response(
        answer,
        status_code=201,
        media_type="application/sdp",
        headers={"Location": f"/api/v1/live/watch/{which}/whep/{session}", "Cache-Control": "no-store"},
    )


@router.delete("/live/watch/{which}/whep/{session}")
async def whep_close(which: str, session: str, ctx: CtxDep):
    ctx.need_csrf()
    ctx.require("live")
    path = _path(ctx, which)
    if not path or not live_watch.WHEP_SESSION.match(session):
        raise NotFound()
    try:
        await live_watch.whep_close(path, session)
    except live_watch.RelayUnavailable:
        pass  # the relay is gone, and the session with it
    return Response(status_code=200)


@router.get("/live/watch/{which}/hls/{name}")
async def hls(which: str, name: str, ctx: CtxDep, session: str | None = None):
    ctx.require("live")
    path = _path(ctx, which)
    if not path or not live_watch.HLS_FILE.match(name):
        return _offline()
    try:
        status, body, ctype = await live_watch.hls_file(path, name, session)
    except live_watch.RelayUnavailable:
        return JSONResponse({"error": _("relay unavailable")}, status_code=503)
    if status != 200:
        return _offline()
    return Response(body, media_type=ctype, headers={"Cache-Control": "no-store"})


# --- Studio: publish from the browser or from a paired device (WHIP), through the back office ------------
# The relay's WebRTC port is never reached by the client for signalling: the offer goes through here,
# behind the session and the `live` right (or a device credential), and carries a short-lived token bound to
# the user or the device and to the mosque. The stream name comes from the mosque, never from the request.

WHIP_SESSION = live_watch.WHEP_SESSION
ICE_TYPE = "application/trickle-ice-sdpfrag"


def _studio_path(a: Actor) -> str:
    return f"live/{live_input.slug(a.mosque)}"


def _studio_token(a: Actor) -> str:
    return studio_token.issue(a.user_id, a.mosque, device_id=a.device["id"] if a.device else None)[0]


def _need_push(a: Actor) -> JSONResponse | None:
    """The studio feeds the mosque's push input: a camera input is read by the relay itself."""
    if live_input.current(a.conn, a.mosque)["mode"] != "push":
        return JSONResponse({"error": "input is not push"}, status_code=409)
    return None


def _may_start(a: Actor) -> JSONResponse | None:
    """Before a token or an offer: the device is ordered to broadcast, and nobody else holds the stream."""
    if a.device:
        o = studio_service.order_for(a.conn, a.mosque, a.device)
        if o.order.command != studio_plan.LIVE:
            body = o.body() | {"error": o.body()["reason"], "code": "not_ordered"}
            return JSONResponse(body, status_code=409)
    holder = studio_publisher.current(a.conn, a.mosque)
    if holder is not None and not (holder["known"] and a.who().same_as(holder)):
        return JSONResponse(studio_publisher.refusal(holder), status_code=409)
    return None


@router.post("/live/studio/token")
def studio_token_issue(a: ActorDep):
    """Token to start a studio session: bound to the signed-in user (or the device) and the mosque."""
    a.need_live()
    if (refused := _need_push(a) or _may_start(a)) is not None:
        return refused
    token, life = studio_token.issue(a.user_id, a.mosque, device_id=a.device["id"] if a.device else None)
    a.audit("studio.jeton")
    return JSONResponse(
        {"token": token, "expires_in": life, "path": _studio_path(a)}, headers={"Cache-Control": "no-store"}
    )


@router.post("/live/studio/whip")
async def whip_offer(request: Request, a: ActorDep):
    a.need_live()
    if (refused := _need_push(a) or _may_start(a)) is not None:
        return refused
    sdp = await request.body()
    if not sdp or len(sdp) > MAX_SDP:
        return JSONResponse({"error": _("bad offer")}, status_code=400)
    try:
        r = await live_watch.whip_request("POST", _studio_path(a), _studio_token(a), body=sdp, ctype="application/sdp")
    except live_watch.RelayUnavailable:
        return JSONResponse({"error": _("relay unavailable")}, status_code=503)
    session = (r.headers.get("location") or "").rstrip("/").rsplit("/", 1)[-1]
    if r.status_code in (401, 403):
        holder = studio_publisher.current(a.conn, a.mosque)  # the relay refused: say why when somebody holds the stream
        if holder is not None and not (holder["known"] and a.who().same_as(holder)):
            return JSONResponse(studio_publisher.refusal(holder), status_code=409)
        return JSONResponse({"error": "relay refused"}, status_code=502)
    if r.status_code != 201 or not WHIP_SESSION.match(session):
        return JSONResponse({"error": "relay"}, status_code=409 if r.status_code == 400 else 502)
    a.audit("studio.whip.debut", session=session)
    return Response(
        r.content,
        status_code=201,
        media_type="application/sdp",
        headers={
            "Location": f"/api/v1/live/studio/whip/{session}",
            "Cache-Control": "no-store",
            "Accept-Patch": ICE_TYPE,
        },
    )


@router.patch("/live/studio/whip/{session}")
async def whip_ice(session: str, request: Request, a: ActorDep):
    a.need_live()
    if not WHIP_SESSION.match(session):
        raise NotFound()
    body = await request.body()
    if len(body) > MAX_SDP:
        return JSONResponse({"error": "bad request"}, status_code=400)
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype != ICE_TYPE:
        return JSONResponse({"error": "unsupported"}, status_code=415)
    try:
        r = await live_watch.whip_request("PATCH", _studio_path(a), _studio_token(a), session, body, ICE_TYPE)
    except live_watch.RelayUnavailable:
        return JSONResponse({"error": _("relay unavailable")}, status_code=503)
    if r.status_code == 404:
        raise NotFound()
    return Response(status_code=204 if r.status_code in (200, 204) else 502)


@router.delete("/live/studio/whip/{session}")
async def whip_close(session: str, a: ActorDep):
    a.need_live()
    if not WHIP_SESSION.match(session):
        raise NotFound()
    try:
        await live_watch.whip_request("DELETE", _studio_path(a), _studio_token(a), session)
    except live_watch.RelayUnavailable:
        pass  # the relay is gone, and the session with it
    a.audit("studio.whip.fin", session=session)
    return Response(status_code=200)


@router.post("/live/studio/takeover")
async def studio_takeover(ctx: CtxDep):
    """Explicit resumption, for an administrator of the mosque: cuts the stream that is running now.

    The body must say `{"confirm": true}` (the console asks first). The old publisher is kicked; a device
    displaced this way stays quiet for a while; the journal keeps who, when and whom it displaced."""
    body = await ctx.raw_body()  # CSRF
    ctx.require("admin")
    ctx.require("live")
    if body.get("confirm") not in (True, "true", "1", 1):
        return JSONResponse({"error": _("Confirmation required."), "code": "confirm"}, status_code=422)
    holder = await run_in_threadpool(studio_publisher.takeover, ctx.conn, ctx.mosque, ctx.user, ctx.ip)
    if holder is None:
        return JSONResponse(
            {"error": _("No live is running: nothing to take over."), "code": "no_live"}, status_code=409
        )
    return {
        "ok": True,
        "message": _("The stream of {source} was cut. You can publish now.", source=holder["text"]),
        "previous": {"source": holder["source"], "label": holder["label"]},
    }
