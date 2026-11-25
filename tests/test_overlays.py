"""Tests for independent live overlays (state, rendering, encoder and the local orchestrator API)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest

from sada.api import make_server
from sada.config import Config
from sada.encoder import Encoder
from sada.scenes import SceneRenderer as Renderer
from sada.state import Machine, Signals, default_overlays, normalize_overlay


def test_normalize_overlay_validation():
    with pytest.raises(ValueError):
        normalize_overlay("unknown", {"visible": True})
    with pytest.raises(ValueError):
        normalize_overlay("qr", {"visible": True, "url": "http://insecure.example"})
    with pytest.raises(ValueError):
        normalize_overlay("qr", {"visible": True, "url": ""})
    with pytest.raises(ValueError):
        normalize_overlay("qr", {"corner": "center"})
    with pytest.raises(ValueError):
        normalize_overlay("banner", {"visible": True, "title": "   "})

    qr = normalize_overlay("qr", {"visible": True, "url": "https://sada.example/don", "label": "Dons", "corner": "br"})
    assert qr == {"visible": True, "url": "https://sada.example/don", "label": "Dons", "corner": "br"}

    banner = normalize_overlay("banner", {"visible": True, "title": "Conférence", "subtitle": "Après Maghrib"})
    assert banner == {"visible": True, "title": "Conférence", "subtitle": "Après Maghrib"}

    logo = normalize_overlay("logo", {"visible": True})
    assert logo == {"visible": True}


def test_machine_overlays_independent_of_scene():
    m = Machine()
    sig = Signals(now=datetime(2026, 4, 20, 12, 0), t=0.0)
    m.tick(sig)
    scene_before = m.scene
    m.set_overlay("qr", {"visible": True, "url": "https://sada.example/don", "label": "Don", "corner": "tl"})
    m.set_overlay("banner", {"visible": True, "title": "Annonce", "subtitle": "Détail"})
    m.set_overlay("logo", {"visible": True})
    assert m.scene == scene_before
    assert not m.override
    st = m.status()
    assert st["overlays"]["qr"]["visible"] is True
    assert st["overlays"]["banner"]["title"] == "Annonce"
    assert st["overlays"]["logo"]["visible"] is True

    # Changing scene does not reset overlays.
    m.command("scene", sig, "avant")
    assert m.scene == "avant"
    assert m.status()["overlays"]["qr"]["visible"] is True
    assert m.status()["overlays"]["banner"]["visible"] is True
    assert m.status()["overlays"]["logo"]["visible"] is True


def test_renderer_overlays_all_combinations():
    r = Renderer(Config(mosque_name="Mosquée Test"))
    empty = r.render_overlays(default_overlays())
    assert empty.size == (r.W, r.H)
    assert empty.getbbox() is None

    for corner in ("tl", "tr", "bl", "br"):
        ov = default_overlays()
        ov["qr"] = {"visible": True, "url": "https://sada.example/don", "label": "Faire un don", "corner": corner}
        ov["banner"] = {"visible": True, "title": "Collecte du vendredi", "subtitle": "Merci pour votre soutien"}
        ov["logo"] = {"visible": True}
        img = r.render_overlays(ov)
        assert img.size == (r.W, r.H)
        assert img.getbbox() is not None

    # Banner without subtitle
    ov2 = default_overlays()
    ov2["banner"] = {"visible": True, "title": "Titre seul", "subtitle": ""}
    img2 = r.render_overlays(ov2)
    assert img2.getbbox() is not None


def test_encoder_overlay_layer(tmp_path: Path):
    cfg = Config(mosque_name="Test")
    enc = Encoder(cfg, tmp_path)
    r = Renderer(cfg)
    enc.prepare(r.background())
    ov_path = Path(enc.layer_png["ov"])
    assert ov_path.is_file()

    cmd = enc.ffmpeg_cmd(*enc.new_recording())
    joined = " ".join(cmd)
    assert str(ov_path) in cmd
    assert "overlay@ov" in joined

    ov = default_overlays()
    ov["logo"]["visible"] = True
    enc.set_overlay(r.render_overlays(ov))
    assert ov_path.stat().st_size > 0


def _post(port: int, path: str, payload: dict, token: str = "tok") -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Token": token},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_api_overlay_endpoint():
    """The local orchestrator API validates and applies one overlay without touching the scene."""
    m = Machine()

    class Orch:
        def set_overlay(self, kind: str, data: dict) -> dict:
            return {"overlays": m.set_overlay(kind, data), "state": m.state.value}

    srv = make_server(Orch(), "127.0.0.1", 0, token="tok")
    port = srv.server_address[1]
    try:
        code, body = _post(
            port,
            "/overlay",
            {"kind": "qr", "visible": True, "url": "https://mosquee.example/don", "label": "Dons", "corner": "br"},
        )
        assert code == 200
        assert body["ok"] is True
        assert body["overlays"]["qr"]["visible"] is True
        assert body["overlays"]["qr"]["corner"] == "br"

        # Insecure URL and unknown kind are rejected with 400, body without kind too.
        assert _post(port, "/overlay", {"kind": "qr", "visible": True, "url": "http://not-https.example"})[0] == 400
        assert _post(port, "/overlay", {"kind": "unknown", "visible": True})[0] == 400
        assert _post(port, "/overlay", {"visible": True})[0] == 400

        # The machine kept the last valid overlay, independent of the scene.
        assert m.status()["overlays"]["qr"]["url"] == "https://mosquee.example/don"
    finally:
        srv.shutdown()
        srv.server_close()
