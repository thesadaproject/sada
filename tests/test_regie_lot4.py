"""Tests for Lot 4: incoming audio mute state, orchestrator API and backoffice regie mute endpoints."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from sada.api import make_server
from sada.state import Machine


def test_machine_mute_flag():
    m = Machine()
    assert m.mic_muted is False
    assert m.status()["mic_muted"] is False

    assert m.set_mute(True) is True
    assert m.mic_muted is True
    assert m.status()["mic_muted"] is True

    assert m.set_mute(False) is False
    assert m.mic_muted is False

    with pytest.raises(ValueError):
        m.set_mute("yes")  # type: ignore[arg-type]


def test_api_mute_endpoint():
    class FakeOrch:
        def __init__(self):
            self.muted = False

        def status(self):
            return {"state": "KHUTBA", "mic": not self.muted, "mic_muted": self.muted}

        def set_mute(self, muted: bool):
            self.muted = muted
            return {"mic_muted": self.muted, "mic": not self.muted, "state": "KHUTBA"}

    orch = FakeOrch()
    srv = make_server(orch, "127.0.0.1", 0, token="tok")
    port = srv.server_address[1]
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/mute",
            method="POST",
            data=json.dumps({"muted": True}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Token": "tok"},
        )
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read().decode())
        assert data["ok"] is True
        assert data["mic_muted"] is True
        assert data["mic"] is False
        assert orch.muted is True

        # Non-boolean muted rejected with 400
        bad = urllib.request.Request(
            f"http://127.0.0.1:{port}/mute",
            method="POST",
            data=json.dumps({"muted": "true"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Token": "tok"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(bad)
        assert exc.value.code == 400
    finally:
        srv.shutdown()
        srv.server_close()


def test_backoffice_regie_audio_and_mute(env, monkeypatch):
    from conftest import client as make_client

    from sada.backoffice import live

    client = make_client(env, "admin")
    hdr = {"X-CSRF": client.csrf}

    calls: list[bool] = []
    monkeypatch.setattr(
        live,
        "status_cached",
        lambda m, ttl=3.0, forcer=False: {
            "ok": True,
            "state": "KHUTBA",
            "scene": "khutba",
            "override": False,
            "mic": True,
            "mic_muted": False,
            "audio_level_db": -18.5,
        },
    )
    monkeypatch.setattr(
        live,
        "set_mute",
        lambda m, muted: calls.append(muted) or {"ok": True, "mic_muted": muted, "mic": not muted},
    )

    r0 = client.get("/api/v1/live/regie")
    assert r0.status_code == 200
    audio = r0.json()["audio"]
    assert audio == {"mic_on": True, "muted": False, "level_db": -18.5}

    r_mute = client.post("/api/v1/live/regie/mute", json={"muted": True}, headers=hdr)
    assert r_mute.status_code == 200
    assert r_mute.json()["muted"] is True
    assert r_mute.json()["mic_muted"] is True
    assert calls == [True]

    r_unmute = client.post("/api/v1/live/regie/mute", json={"muted": False}, headers=hdr)
    assert r_unmute.status_code == 200
    assert r_unmute.json()["muted"] is False
    assert calls == [True, False]

    # Invalid payload rejected
    r_bad = client.post("/api/v1/live/regie/mute", json={"muted": 1}, headers=hdr)
    assert r_bad.status_code == 400

    # Orchestrator unreachable returns 503
    def _fail(m, muted):
        raise live.OrchestratorError("offline")

    monkeypatch.setattr(live, "set_mute", _fail)
    r_off = client.post("/api/v1/live/regie/mute", json={"muted": True}, headers=hdr)
    assert r_off.status_code == 503
