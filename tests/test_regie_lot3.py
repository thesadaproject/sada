"""Tests for Lot 3: custom scenes (upload/delete/render/API), Cut vs Fade transitions, and Studio API sync."""

from __future__ import annotations

import base64
import datetime as dt
import io
import json
import urllib.request

import pytest
from PIL import Image

from sada import api, scenes, transitions
from sada.config import Config
from sada.state import Machine, Signals, State


def _png_bytes(size=(320, 180), color=(30, 80, 140)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_transitions_fade_and_cut():
    fade = transitions.plan("a", old_full=False, new_full=True, scale=1.0, mode="fade")
    assert transitions.duration("fade") == transitions.TOTAL
    v0 = fade.values(0.0)
    assert v0["fond"] == 0.0
    assert v0["a_b"] == 0.0
    vf = fade.values(transitions.TOTAL)
    assert vf["fond"] == 1.0
    assert vf["a_a"] == 0.0
    assert vf["a_b"] == 1.0

    cut = transitions.plan("a", old_full=False, new_full=True, scale=1.0, mode="cut")
    assert transitions.duration("cut") == 0.0
    vc = cut.values(0.0)
    assert vc == {"fond": 1.0, "a_a": 0.0, "a_b": 1.0, "x_b": 0.0, "y_b": 0.0}

    with pytest.raises(ValueError):
        transitions.plan("a", False, True, mode="wipe")


def test_machine_custom_scene_and_transition():
    m = Machine()
    sig = Signals(now=dt.datetime(2026, 11, 20, 12, 30), t=100.0)
    assert m.transition == "fade"
    assert m.status()["transition"] == "fade"

    m.set_transition("cut")
    assert m.transition == "cut"
    assert m.status()["transition"] == "cut"

    m.command("transition", sig, "fade")
    assert m.transition == "fade"

    with pytest.raises(ValueError):
        m.set_transition("dissolve")

    m.command("scene", sig, "custom:collecte")
    assert m.state != State.CUSTOM  # no image known for it: refused
    m.custom_known = {"custom:collecte", "custom:pause"}.__contains__
    m.command("scene", sig, "custom:collecte")
    assert m.state == State.CUSTOM
    assert m.scene == "custom:collecte"
    assert m.override is True

    # Switching between two custom scenes stays in CUSTOM and updates scene id
    m.command("scene", sig, "custom:pause")
    assert m.state == State.CUSTOM
    assert m.scene == "custom:pause"

    # Returning to built-in scene clears custom_scene
    m.command("scene", sig, "khutba")
    assert m.state == State.KHUTBA
    assert m.scene == "khutba"
    assert m.custom_scene is None


def test_render_custom_scene_fits_canvas():
    cfg = Config(width=1280, height=720)
    src = Image.new("RGB", (400, 400), (200, 120, 40))
    out = scenes.render_custom_scene(src, cfg)
    assert out.size == (1280, 720)
    assert out.mode == "RGBA"
    # Center pixel matches source color; left letterbox pixel is dark background
    assert out.getpixel((640, 360))[:3] == (200, 120, 40)
    assert out.getpixel((10, 360))[:3] == (10, 13, 18)


def test_local_api_transition_and_custom_scene():
    class DummyOrch:
        def __init__(self):
            self.machine = Machine()
            self.custom_images = {}

        def status(self):
            return self.machine.status()

        def set_transition(self, mode):
            return {"transition": self.machine.set_transition(mode), "state": self.machine.state.value}

        def set_custom_scene(self, scene_id, image_bytes, transition=None):
            if transition is not None:
                self.machine.set_transition(transition)
            if image_bytes:
                self.custom_images[scene_id] = image_bytes
            self.machine.custom_known = self.custom_images.__contains__
            sig = Signals(now=dt.datetime(2026, 11, 20, 12, 30), t=100.0)
            msg = self.machine.command("scene", sig, scene_id)
            return {"message": msg, "scene": scene_id, "transition": self.machine.transition}

        def manual(self, cmd, arg=None, transition=None):
            if transition is not None:
                self.machine.set_transition(transition)
            sig = Signals(now=dt.datetime(2026, 11, 20, 12, 30), t=100.0)
            return {"message": self.machine.command(cmd, sig, arg), "transition": self.machine.transition}

    orch = DummyOrch()
    srv = api.make_server(orch, "127.0.0.1", 0, token="tok")
    port = srv.server_address[1]
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/transition",
            data=json.dumps({"mode": "cut"}).encode(),
            headers={"Authorization": "Bearer tok", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert json.loads(resp.read())["transition"] == "cut"

        req2 = urllib.request.Request(
            f"http://127.0.0.1:{port}/custom-scene",
            data=json.dumps(
                {
                    "scene": "custom:collecte",
                    "image_b64": base64.b64encode(_png_bytes()).decode("ascii"),
                    "transition": "fade",
                }
            ).encode(),
            headers={"Authorization": "Bearer tok", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req2) as resp:
            body = json.loads(resp.read())
        assert body["scene"] == "custom:collecte"
        assert body["transition"] == "fade"
        assert "custom:collecte" in orch.custom_images
    finally:
        srv.shutdown()


def test_backoffice_custom_scenes_and_transitions(env, tmp_path, monkeypatch):
    from conftest import client as make_client

    from sada.backoffice import custom_scenes, live

    monkeypatch.setattr(custom_scenes, "DIR", tmp_path / "custom_scenes")
    client = make_client(env, "admin")
    hdr = {"X-CSRF": client.csrf}

    calls = []
    monkeypatch.setattr(
        live,
        "status_cached",
        lambda m, ttl=3.0, forcer=False: {"ok": True, "state": "KHUTBA", "scene": "khutba", "override": False},
    )
    monkeypatch.setattr(live, "set_transition", lambda m, mode: calls.append(("tr", mode)) or {"ok": True})
    monkeypatch.setattr(
        live,
        "set_custom_scene",
        lambda m, sc, raw, transition=None, **kw: calls.append(("custom", sc, len(raw), transition)) or {"ok": True},
    )
    monkeypatch.setattr(
        live,
        "command",
        lambda m, cmd, arg=None, info=None, valeur=None, transition=None, **kw: (
            calls.append(("cmd", cmd, valeur, transition)) or {"ok": True}
        ),
    )

    # Initial state includes transition=fade and built-in scenes
    r0 = client.get("/api/v1/live/regie")
    assert r0.status_code == 200
    assert r0.json()["transition"] == "fade"
    base_count = len(r0.json()["scenes"])
    assert base_count >= 7

    # Switch transition to cut
    r_tr = client.post("/api/v1/live/regie/transition", json={"mode": "cut"}, headers=hdr)
    assert r_tr.status_code == 200
    assert r_tr.json()["transition"] == "cut"
    assert ("tr", "cut") in calls

    # Invalid transition rejected
    assert client.post("/api/v1/live/regie/transition", json={"mode": "slide"}, headers=hdr).status_code == 400

    # Upload a custom scene (collecte)
    r_up = client.post(
        "/api/v1/live/regie/custom-scenes",
        data={"label": "Collecte Ramadan", "category": "collecte"},
        files={"file": ("collecte.png", _png_bytes(), "image/png")},
        headers=hdr,
    )
    assert r_up.status_code == 200
    created = r_up.json()["scene"]
    assert created["id"] == "custom:collecte-ramadan"
    assert created["category"] == "collecte"
    assert len(r_up.json()["scenes"]) == base_count + 1

    # Fetch preview image
    r_img = client.get(f"/api/v1/live/regie/custom-scenes/{created['slug']}/image")
    assert r_img.status_code == 200
    assert r_img.headers["content-type"].startswith("image/png")

    # Take custom scene to air with cut transition
    r_take = client.post(
        "/api/v1/live/regie/scene",
        json={"scene": created["id"], "transition": "cut"},
        headers=hdr,
    )
    assert r_take.status_code == 200
    assert any(c[0] == "custom" and c[1] == "custom:collecte-ramadan" and c[3] == "cut" for c in calls)

    # Reject bad file extension
    r_bad = client.post(
        "/api/v1/live/regie/custom-scenes",
        data={"label": "Bad", "category": "pause"},
        files={"file": ("evil.svg", b"<svg></svg>", "image/svg+xml")},
        headers=hdr,
    )
    assert r_bad.status_code == 400

    # Delete custom scene
    r_del = client.delete(f"/api/v1/live/regie/custom-scenes/{created['slug']}", headers=hdr)
    assert r_del.status_code == 200
    assert len(r_del.json()["scenes"]) == base_count
    assert client.get(f"/api/v1/live/regie/custom-scenes/{created['slug']}/image").status_code == 404
