"""Tests for independent live overlays (state, rendering, encoder, back-office API & Studio auth)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sada.backoffice import app as bo_app, auth, db, live, paths, studio_auth
from sada.config import Config
from sada.encoder import Encoder
from sada.scenes import Renderer
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
    m = Machine(Config())
    sig = Signals(now=datetime(2026, 4, 20, 12, 0), camera_ok=True)
    m.tick(sig)
    scene_before = m.scene
    m.set_overlay("qr", {"visible": True, "url": "https://sada.example/don", "label": "Don", "corner": "tl"})
    m.set_overlay("banner", {"visible": True, "title": "Annonce", "subtitle": "Détail"})
    m.set_overlay("logo", {"visible": True})
    assert m.scene == scene_before
    assert m.override is None
    st = m.status()
    assert st["overlays"]["qr"]["visible"] is True
    assert st["overlays"]["banner"]["title"] == "Annonce"
    assert st["overlays"]["logo"]["visible"] is True

    # Changing scene does not reset overlays.
    m.command("before", sig)
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

    cmd = enc._build_cmd()
    joined = " ".join(cmd)
    assert str(ov_path) in cmd
    assert "overlay@ov" in joined

    ov = default_overlays()
    ov["logo"]["visible"] = True
    enc.set_overlay(r.render_overlays(ov))
    assert ov_path.stat().st_size > 0


@pytest.fixture()
def bo_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setenv("SADA_AGENT_TOKEN", "agent-secret")
    live.reset_push_state()
    studio_auth.reset_sessions()
    db.init()
    mosque_id = db.add_mosque("grande", "Grande Mosquée")
    db.add_user("regisseur", auth.hash_password("secret123"), mosque_id=mosque_id)
    app = bo_app.create_app()
    client = TestClient(app)
    return client, {"id": mosque_id, "slug": "grande"}


def test_regie_and_studio_overlay_sync(bo_client):
    client, mosque = bo_client
    # Login via Studio API to obtain X-Sada-Studio-Token
    r_login = client.post("/api/studio/login", json={"username": "regisseur", "password": "secret123"})
    assert r_login.status_code == 200
    studio_headers = {studio_auth.STUDIO_HEADER: r_login.json()["token"]}

    # Unauthenticated request is rejected
    assert client.get("/api/live/overlays").status_code == 401

    # Agent pushes status so queue mode is active
    r_push = client.post(
        "/api/live/agent/status",
        headers={live.AGENT_HEADER: "agent-secret", "X-Sada-Mosque": mosque["slug"]},
        json={"state": "LIVE", "scene": "direct", "stream_on": True},
    )
    assert r_push.status_code == 200

    # Studio updates QR overlay via the shared Régie API
    r_put = client.put(
        "/api/live/overlays/qr",
        headers=studio_headers,
        json={"visible": True, "url": "https://mosquee.example/don", "label": "Dons", "corner": "br"},
    )
    assert r_put.status_code == 200
    body = r_put.json()
    assert body["ok"] is True
    assert body["queued"] is True
    assert body["overlays"]["qr"]["visible"] is True
    assert body["overlays"]["qr"]["corner"] == "br"

    # Invalid URL is rejected with 400
    r_bad = client.put(
        "/api/live/overlays/qr",
        headers=studio_headers,
        json={"visible": True, "url": "http://not-https.example"},
    )
    assert r_bad.status_code == 400

    # Agent pulls the queued overlay command
    r_pull = client.post(
        "/api/live/agent/status",
        headers={live.AGENT_HEADER: "agent-secret", "X-Sada-Mosque": mosque["slug"]},
        json={"state": "LIVE", "scene": "direct", "stream_on": True},
    )
    cmds = r_pull.json()["commands"]
    assert len(cmds) == 1
    assert cmds[0]["cmd"] == "overlay"
    assert cmds[0]["params"]["kind"] == "qr"

    # Web Régie (or Studio) reads /api/live/regie and /api/live/status and sees the synced overlay
    r_regie = client.get("/api/live/regie", headers=studio_headers)
    assert r_regie.status_code == 200
    assert r_regie.json()["overlays"]["qr"]["url"] == "https://mosquee.example/don"

    r_status = client.get("/api/live/status", headers=studio_headers)
    assert r_status.status_code == 200
    assert r_status.json()["overlays"]["qr"]["visible"] is True
