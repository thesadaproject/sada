"""Control room (“Régie”): live state for the page, and the two monitors proxied to the relay.

Every route needs a session open on a mosque and the `live` permission. The monitors never take a
stream name from the request: the path comes from the session's mosque (live_watch.path_of).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ... import transitions
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
        {"id": sc, "kind": "camera" if sc in ("khutba", "dars") else "slate", "custom": False, "label": sc}
        for sc in PICKABLE_SCENES
    ]


def _all_scenes(conn, mosque: dict) -> list[dict]:
    return _builtin_scenes() + custom_scenes.list_scenes(conn, mosque)


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
    st = live.status_cached(mosque, ttl=STATUS_TTL, forcer=forcer)
    block = st.get("setup")
    if setup and isinstance(block, dict) and block.get("active") and not block.get("live"):
        st = {
            **st,
            **{
                k: block[k] for k in ("state", "scene", "override", "transition", "overlays", "mic_muted") if k in block
            },
        }
    ok = bool(st.get("ok"))
    return {
        "ok": ok,
        "reachable": ok,
        "state": st.get("state"),
        "scene": st.get("scene"),
        "override": bool(st.get("override")),
        "transition": st.get("transition"),
        "overlays": st.get("overlays"),
        "mic": bool(st.get("mic", False)),
        "mic_muted": bool(st.get("mic_muted", False)),
        "audio_level_db": st.get("audio_level_db"),
        "message": st.get("error") or st.get("last_reason") or "",
    }


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
        raw = custom_scenes.image_bytes(mosque, scene_id[len("custom:") :])
        if raw is None:
            raise NotFound()
        try:
            r = await run_in_threadpool(
                live.set_custom_scene, mosque, scene_id, raw, transition=tr_mode, **_setup_kwargs(setup)
            )
        except live.OrchestratorError as e:
            return _setup_failure(e)
        return {"ok": True, "scene": scene_id, "transition": tr_mode or _saved_transition(mosque), "result": r}
    try:
        r = await run_in_threadpool(
            live.command, mosque, "scene", valeur=scene_id, transition=tr_mode, **_setup_kwargs(setup)
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except live.OrchestratorError as e:
        return _setup_failure(e)
    return {"ok": True, "scene": scene_id, "transition": tr_mode or _saved_transition(mosque), "result": r}


async def apply_mute(mosque: dict, muted, setup: bool = False) -> dict | JSONResponse:
    if not isinstance(muted, bool):
        return JSONResponse({"error": _("invalid body")}, status_code=400)
    try:
        r = await run_in_threadpool(live.set_mute, mosque, muted, **_setup_kwargs(setup))
    except live.OrchestratorError as e:
        return _setup_failure(e)
    return {"ok": True, "muted": muted, "mic_muted": muted, "result": r}


async def apply_transition(mosque: dict, mode, setup: bool = False) -> dict | JSONResponse:
    mode = str(mode or "").strip().lower()
    if mode not in transitions.TRANSITIONS:
        return JSONResponse({"error": _("unknown transition: {mode}", mode=mode)}, status_code=400)
    custom_scenes.set_transition(mosque, mode)
    synced = True
    try:
        await run_in_threadpool(live.set_transition, mosque, mode, **_setup_kwargs(setup))
    except live.OrchestratorError:
        synced = False
    return {"ok": True, "transition": mode, "synced": synced}


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
    return await apply_mute(a.mosque, body.get("muted"), setup=body.get("setup") is True)


@router.post("/live/regie/transition")
async def regie_transition(request: Request, a: ActorDep):
    a.need_live()
    body = _body(await _json(request))
    return await apply_transition(a.mosque, body.get("mode"), setup=body.get("setup") is True)


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
    raw = await file.read()
    try:
        created = custom_scenes.create(
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
def regie_custom_scene_image(slug: str, ctx: CtxDep):
    ctx.require("live")
    mosque = ctx.mosque
    assert mosque is not None
    raw = custom_scenes.image_bytes(mosque, slug)
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
    return await apply_scene(
        a.conn, a.mosque, body.get("scene"), body.get("transition"), setup=body.get("setup") is True
    )


@router.get("/live/regie/scene/{name}.png")
async def scene_preview(name: str, ctx: CtxDep):
    """Studio mode: the scene as it would go on air, with the mosque's saved texts. Banner scenes come
    without background, to be laid over the preview feed."""
    ctx.require("live")
    if name not in live.choices("scene"):
        raise NotFound()
    textes = screens_mod.saved(ctx.conn, ctx.mosque["id"])
    png = await run_in_threadpool(screens_mod.preview, ctx.mosque, textes, name, True, ctx.conn)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=30"})


@router.post("/live/watch/{which}/whep")
async def whep_offer(which: str, request: Request, ctx: CtxDep):
    ctx.need_csrf()
    ctx.require("live")
    path = _path(ctx, which)
    if not path:
        return _offline()
    sdp = await request.body()
    if not sdp or len(sdp) > MAX_SDP:
        return JSONResponse({"error": "bad offer"}, status_code=400)
    try:
        status, answer, session = await live_watch.whep_offer(path, sdp)
    except live_watch.RelayUnavailable:
        return JSONResponse({"error": "relay unavailable"}, status_code=503)
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
        return JSONResponse({"error": "relay unavailable"}, status_code=503)
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
        return JSONResponse({"error": "bad offer"}, status_code=400)
    try:
        r = await live_watch.whip_request("POST", _studio_path(a), _studio_token(a), body=sdp, ctype="application/sdp")
    except live_watch.RelayUnavailable:
        return JSONResponse({"error": "relay unavailable"}, status_code=503)
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
        return JSONResponse({"error": "relay unavailable"}, status_code=503)
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
