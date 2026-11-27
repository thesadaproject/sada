"""The web control room is the studio's remote: on air from there, the Sada Studio publishes; stop, it stops."""

from __future__ import annotations

import pytest
from conftest import client, one

from sada.backoffice import live_input, live_watch, models

HB = "/api/v1/studio/heartbeat"


@pytest.fixture(autouse=True)
def _push(monkeypatch, tmp_path):
    monkeypatch.setenv("SADA_INTERNAL_TOKEN_FILE", str(tmp_path / "internal.token"))
    monkeypatch.setattr(live_input, "current", lambda conn, m: {"mode": "push", "url": ""})
    monkeypatch.setattr(live_watch, "publisher_info", lambda path, timeout=1.0: {"ready": False, "type": "", "id": ""})
    monkeypatch.setattr(live_watch, "kick", lambda path, timeout=2.0: True)


def pair(env, name="PC salle"):
    anon = client(env)
    start = anon.post("/api/v1/studio/pair/start").json()
    r = client(env, "responsable").ecrire("/studio/devices/pair", {"user_code": start["user_code"], "name": name})
    assert r.status_code == 200, r.text
    poll = anon.post("/api/v1/studio/pair/poll", json={"device_code": start["device_code"]})
    return client(env, headers={"Authorization": f"Bearer {poll.json()['device_secret']}"})


def beat(d):
    r = d.post(HB, json={"state": "standby", "version": "1", "camera": True, "microphone": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_start_from_the_control_room_orders_the_studio(env, engine):
    d = pair(env)
    assert beat(d)["command"] == "standby"
    c = client(env, "responsable")
    r = c.ecrire("/live/start")
    assert r.status_code == 200, r.text
    assert r.json()["studio"] == "ordered"
    assert any(e[:2] == ("command", "start") for e in engine)
    order = beat(d)
    assert order["command"] == "live" and order["current"]["source"] == "manual"
    # a second command on air does not open a second live
    assert c.ecrire("/live/start").json()["studio"] == "already"
    run = one(env["conn"], models.StudioRun, mosque_id=env["mid"], origin="manual")
    assert run["kind"] == "khutba" and run["ended_at"] is None


def test_a_scene_taken_off_air_orders_the_studio_with_the_right_type(env, engine):
    d = pair(env)
    beat(d)
    r = client(env, "responsable").ecrire("/live/regie/scene", {"scene": "dars"})
    assert r.status_code == 200, r.text
    assert r.json()["studio"] == "ordered"
    assert beat(d)["command"] == "live"
    assert one(env["conn"], models.StudioRun, mosque_id=env["mid"], origin="manual")["kind"] == "dars"


def test_stop_from_the_control_room_stops_the_studio(env, engine):
    d = pair(env)
    beat(d)
    c = client(env, "responsable")
    c.ecrire("/live/start")
    assert beat(d)["command"] == "live"
    r = c.ecrire("/live/stop")
    assert r.status_code == 200, r.text
    assert r.json()["studio"] == "stopped"
    assert beat(d)["command"] == "standby"
    assert c.ecrire("/live/stop").json()["studio"] == "none"


def test_without_a_studio_online_the_engine_command_still_goes(env, engine):
    r = client(env, "responsable").ecrire("/live/start")
    assert r.status_code == 200, r.text
    assert r.json()["studio"] == "no_studio"
    assert any(e[:2] == ("command", "start") for e in engine)
    assert one(env["conn"], models.StudioRun, mosque_id=env["mid"]) is None


def test_a_camera_read_by_the_relay_has_no_studio_to_drive(env, engine, monkeypatch):
    d = pair(env)
    beat(d)
    monkeypatch.setattr(live_input, "current", lambda conn, m: {"mode": "camera", "url": "rtsp://cam/x"})
    assert client(env, "responsable").ecrire("/live/start").json()["studio"] == "none"
    assert beat(d)["command"] == "standby"


def test_the_studio_itself_taking_a_scene_does_not_open_a_live(env, engine):
    d = pair(env)
    beat(d)
    r = d.post("/api/v1/live/regie/scene", json={"scene": "khutba"})
    assert r.status_code == 200, r.text
    assert "studio" not in r.json()
    assert beat(d)["command"] == "standby"
