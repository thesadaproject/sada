"""Live control from the studio application: the paired device reads the control room and drives the
engine (scene, overlays, microphone, transition) with its own credential, no web session."""

from __future__ import annotations

from conftest import client, one

from sada.backoffice import live, models


def pair(env, name="Studio essai", user="responsable"):
    """Full pairing: returns the device bearer."""
    anon = client(env)
    start = anon.post("/api/v1/studio/pair/start").json()
    r = client(env, user).ecrire("/studio/devices/pair", {"user_code": start["user_code"], "name": name})
    assert r.status_code == 200, r.text
    poll = anon.post("/api/v1/studio/pair/poll", json={"device_code": start["device_code"]})
    assert poll.status_code == 200, poll.text
    return poll.json()["device_secret"]


def dev(env, bearer=None):
    if bearer is None:
        bearer = pair(env)
    return client(env, headers={"Authorization": f"Bearer {bearer}"})


# ------------------------------------------------------------------ reading


def test_device_reads_the_control_room(env, engine):
    d = dev(env)
    r = d.get("/api/v1/studio/regie")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mosque"] and body["slug"] == one(env["conn"], models.Mosque, id=env["mid"])["slug"]
    assert body["status"]["state"] == "IDLE" and body["status"]["scene"] == "slate"
    assert body["status"]["reachable"] is True
    assert any(s["id"] == "khutba" for s in body["scenes"]), [s["id"] for s in body["scenes"]]
    assert body["commands"] == list(live.COMMANDS)
    assert body["audio"]["level_db"] is None and body["audio"]["muted"] is False
    assert r.headers["cache-control"] == "no-store"


def test_device_reads_the_flat_status(env, engine):
    r = dev(env).get("/api/v1/studio/live/status")
    assert r.status_code == 200, r.text
    assert r.json()["scene"] == "slate" and r.json()["transition"] == "fade"


def test_status_refused_without_credential(env, engine):
    c = client(env)
    assert c.get("/api/v1/studio/live/status").status_code == 401
    assert c.get("/api/v1/studio/regie").status_code == 401
    assert c.post("/api/v1/studio/live/command", json={"command": "scene", "arg": "khutba"}).status_code == 401


# ------------------------------------------------------------------ writing


def test_device_takes_a_scene(env, engine):
    r = dev(env).post("/api/v1/studio/live/command", json={"command": "scene", "arg": "khutba"})
    assert r.status_code == 200, r.text
    assert ("command", "scene", "khutba", None) in engine
    assert r.json()["scene"] == "khutba"
    assert ("status", True) in engine  # the answer is a forced read, never the cached snapshot


def test_device_scene_with_transition_and_bad_mode(env, engine):
    c = dev(env)
    assert (
        c.post(
            "/api/v1/studio/live/command", json={"command": "scene", "arg": "priere", "transition": "cut"}
        ).status_code
        == 200
    )
    assert ("command", "scene", "priere", "cut") in engine
    bad = c.post("/api/v1/studio/live/command", json={"command": "scene", "arg": "priere", "transition": "spin"})
    assert bad.status_code == 400 and "spin" in bad.text


def test_device_command_unknown_is_refused(env, engine):
    r = dev(env).post("/api/v1/studio/live/command", json={"command": "explode"})
    assert r.status_code == 400
    assert not [s for s in engine if s[0] == "command"]


def test_device_relays_a_plain_command(env, engine):
    r = dev(env).post("/api/v1/studio/live/command", json={"command": "pause"})
    assert r.status_code == 200, r.text
    assert ("command", "pause", None, None) in engine


def test_device_updates_an_overlay(env, engine):
    r = dev(env).patch("/api/v1/studio/live/overlays/qr", json={"visible": True, "url": "https://sada.example/qr"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["overlays"]["qr"]["visible"] is True
    sent = [s for s in engine if s[0] == "overlay"]
    assert sent[-1][1] == "qr"
    # an engine that answers without its status: the state after the command is a forced read
    assert engine[-1] == ("status", True) and "status" in r.json()


def test_device_overlay_kind_and_payload_are_validated(env, engine):
    c = dev(env)
    assert c.patch("/api/v1/studio/live/overlays/nope", json={"visible": True}).status_code == 422
    bad = c.patch("/api/v1/studio/live/overlays/qr", json={"url": "javascript:alert(1)"})
    assert bad.status_code == 400 and "https" in bad.text
    assert not [s for s in engine if s[0] == "overlay"]


def test_device_mutes_and_sets_the_transition(env, engine):
    c = dev(env)
    m = c.post("/api/v1/live/regie/mute", json={"muted": True})
    assert m.status_code == 200, m.text and m.text
    assert m.json()["mic_muted"] is True and ("mute", True) in engine
    t = c.post("/api/v1/live/regie/transition", json={"mode": "cut"})
    assert t.status_code == 200, t.text
    assert t.json()["transition"] == "cut" and ("transition", "cut") in engine
    assert c.post("/api/v1/live/regie/mute", json={"muted": "yes"}).status_code == 400


def test_web_routes_still_need_a_session(env, engine):
    c = client(env)
    assert c.post("/api/v1/live/regie/mute", json={"muted": True}).status_code == 401
    assert c.post("/api/v1/live/regie/transition", json={"mode": "cut"}).status_code == 401
    assert c.post("/api/v1/live/regie/scene", json={"scene": "khutba"}).status_code == 401
