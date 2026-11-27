"""The Sada Studio's picture on demand in the web control room: request, heartbeat, WHIP, relay authentication."""

from __future__ import annotations

import time

import httpx
import pytest
from conftest import client, one, update

from sada.backoffice import live_input, live_watch, models, studio_preview, studio_token
from sada.backoffice.api import studio as studio_api

HB = "/api/v1/studio/heartbeat"
WHIP = "/api/v1/live/studio/preview/whip"


@pytest.fixture(autouse=True)
def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("SADA_INTERNAL_TOKEN_FILE", str(tmp_path / "internal.token"))
    monkeypatch.setattr(live_input, "current", lambda conn, m: {"mode": "push", "url": ""})
    monkeypatch.setattr(live_watch, "publisher_info", lambda path, timeout=1.0: {"ready": False, "type": "", "id": ""})
    studio_api.reset()
    yield
    studio_api.reset()  # the pairing limits are process-wide: leave them as found for the next test file


@pytest.fixture
def relay(monkeypatch):
    """The relay's WHIP endpoint: records (method, path, token claims) and answers like MediaMTX."""
    calls = []

    async def fake(method, path, token, session=None, body=b"", ctype=None):
        calls.append((method, path, studio_token.verify(token, path.removeprefix("live/").removesuffix("-retour"))))
        if method == "POST":
            return httpx.Response(201, content=b"v=0 answer", headers={"Location": f"/{path}/whip/2f1c9a7e-5b1d-4c35"})
        return httpx.Response(204)

    monkeypatch.setattr(live_watch, "whip_request", fake)
    return calls


def pair(env, name="PC salle", user="responsable"):
    anon = client(env)
    start = anon.post("/api/v1/studio/pair/start").json()
    r = client(env, user).ecrire("/studio/devices/pair", {"user_code": start["user_code"], "name": name})
    assert r.status_code == 200, r.text
    poll = anon.post("/api/v1/studio/pair/poll", json={"device_code": start["device_code"]})
    return client(env, headers={"Authorization": f"Bearer {poll.json()['device_secret']}"}), r.json()["device"]["id"]


def beat(d):
    r = d.post(HB, json={"state": "standby", "version": "1.0.0", "camera": True, "microphone": True})
    assert r.status_code == 200, r.text
    return r.json()


def mosque(env):
    return one(env["conn"], models.Mosque, id=env["mid"])


def slug(env):
    return live_input.slug(mosque(env))


def publish(env, path, token):
    body = {"action": "publish", "path": path, "protocol": "webrtc", "token": token, "ip": "203.0.113.9"}
    return client(env).post("/api/v1/internal/publish-auth", json=body).status_code


# ------------------------------------------------------------------ request from the control room


def test_request_needs_the_live_right_and_csrf(env):
    assert client(env).post("/api/v1/live/regie/preview", json={"on": True}).status_code == 401
    c = client(env, "responsable")
    assert c.post("/api/v1/live/regie/preview", json={"on": True}).status_code == 403  # no CSRF header
    r = c.ecrire("/live/regie/preview", {"on": True})
    assert r.status_code == 200 and r.json()["requested"] is True and r.json()["expires_in"] > 30
    assert c.get("/api/v1/live/regie").json()["preview"]["requested"] is True
    assert c.ecrire("/live/regie/preview", {"on": False}).json()["requested"] is False
    assert c.get("/api/v1/live/regie").json()["preview"] == {"requested": False, "expires_in": 0}


def test_the_preview_monitor_reads_the_preview_path(env):
    assert live_watch.path_of(env["conn"], mosque(env), "preview") == studio_preview.path_of(mosque(env))
    assert studio_preview.path_of(mosque(env)) == f"live/{slug(env)}-retour"
    monitors = client(env, "responsable").get("/api/v1/live/regie").json()["monitors"]
    assert set(monitors) == {"source", "program", "preview"}


# ------------------------------------------------------------------ heartbeat


def test_heartbeat_is_faster_while_the_control_room_is_open(env):
    d, _ = pair(env)
    assert beat(d)["config"]["heartbeat_interval_s"] == 30
    assert beat(d)["preview"] is None
    client(env, "responsable").get("/api/v1/live/regie")
    assert beat(d)["config"]["heartbeat_interval_s"] == studio_preview.FAST_HEARTBEAT_S


def test_only_the_designated_device_is_asked_and_never_during_its_live(env, monkeypatch):
    first, _ = pair(env, name="PC salle")
    second, _ = pair(env, name="PC étage")
    beat(first), beat(second)
    client(env, "responsable").ecrire("/live/regie/preview", {"on": True})
    asked = beat(first)["preview"]
    assert asked["on"] is True and asked["whip_path"] == WHIP and asked["expires_in"] > 30
    assert beat(second)["preview"] is None
    # on air, the device already streams: the control room shows the programme, nothing more is asked
    from sada.backoffice import studio_plan

    live_order = studio_plan.Order(studio_plan.LIVE, "manual", "manual", None, None)
    real = studio_api.studio_service.order_for
    monkeypatch.setattr(
        studio_api.studio_service,
        "order_for",
        lambda conn, m, dev, now=None: studio_api.studio_service.DeviceOrder(live_order, []),
    )
    assert beat(first)["preview"] is None
    monkeypatch.setattr(studio_api.studio_service, "order_for", real)


def test_a_lapsed_request_is_no_longer_seen(env):
    d, _ = pair(env)
    client(env, "responsable").ecrire("/live/regie/preview", {"on": True})
    assert beat(d)["preview"] is not None
    update(env["conn"], models.PreviewRequest, {"until": time.time() - 1}, mosque_id=env["mid"])
    assert beat(d)["preview"] is None


# ------------------------------------------------------------------ WHIP of the device


def test_whip_is_refused_unless_the_control_room_asks(env, relay):
    d, _ = pair(env)
    beat(d)
    r = d.post(WHIP, content=b"v=0\r\n", headers={"Content-Type": "application/sdp"})
    assert r.status_code == 409 and r.json()["code"] == "not_requested"
    assert relay == []


def test_whip_goes_to_the_preview_path_with_a_preview_token(env, relay):
    d, did = pair(env)
    beat(d)
    client(env, "responsable").ecrire("/live/regie/preview", {"on": True})
    r = d.post(WHIP, content=b"v=0\r\n", headers={"Content-Type": "application/sdp"})
    assert r.status_code == 201, r.text
    assert r.headers["location"] == f"{WHIP}/2f1c9a7e-5b1d-4c35"
    method, path, claims = relay[-1]
    assert (method, path) == ("POST", f"live/{slug(env)}-retour")
    assert claims["p"] == 1 and claims["d"] == did
    ice = d.patch(
        f"{WHIP}/2f1c9a7e-5b1d-4c35",
        content=b"a=candidate",
        headers={"Content-Type": "application/trickle-ice-sdpfrag"},
    )
    assert ice.status_code == 204
    assert d.delete(f"{WHIP}/2f1c9a7e-5b1d-4c35").status_code == 200
    assert [c[0] for c in relay] == ["POST", "PATCH", "DELETE"]


def test_whip_needs_a_device_not_a_session(env, relay):
    c = client(env, "responsable")
    c.ecrire("/live/regie/preview", {"on": True})
    assert c.post(WHIP, content=b"v=0\r\n", headers={"Content-Type": "application/sdp"}).status_code == 401


# ------------------------------------------------------------------ relay authentication


def test_relay_accepts_a_preview_token_on_the_preview_path_only(env):
    d, did = pair(env)
    beat(d)
    m = mosque(env)
    preview = studio_token.issue(None, m, device_id=did, preview=True)[0]
    live_tok = studio_token.issue(None, m, device_id=did)[0]
    retour = f"live/{slug(env)}-retour"
    assert publish(env, retour, preview) == 401  # nobody asks for the picture
    client(env, "responsable").ecrire("/live/regie/preview", {"on": True})
    assert publish(env, retour, preview) == 200
    assert publish(env, retour, live_tok) == 401  # a live token never feeds the preview
    assert publish(env, f"live/{slug(env)}", preview) == 401  # a preview token never publishes the live
    # the preview never becomes the live's publisher
    assert one(env["conn"], models.StudioClaim, mosque_id=env["mid"]) is None


def test_relay_refuses_a_preview_token_of_a_revoked_device(env):
    d, did = pair(env)
    beat(d)
    client(env, "responsable").ecrire("/live/regie/preview", {"on": True})
    token = studio_token.issue(None, mosque(env), device_id=did, preview=True)[0]
    update(env["conn"], models.Device, {"revoked_at": time.time()}, id=did)
    assert publish(env, f"live/{slug(env)}-retour", token) == 401
