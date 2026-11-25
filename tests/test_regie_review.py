"""Review fixes of the control room (regie) and its setup/custom-scene plumbing."""

from __future__ import annotations

import asyncio

from test_regie_studio import dev, engine  # noqa: F401  (fixture)

from sada.backoffice.api import regie


def _spy_on_loop(monkeypatch):
    """Replaces `live_flat` by a probe noting whether it ran on the event loop's thread."""
    on_loop: list[bool] = []
    real = regie.live_flat

    def probe(*a, **kw):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return real(*a, **kw)

    monkeypatch.setattr(regie, "live_flat", probe)
    return on_loop


def test_studio_async_routes_read_the_engine_off_the_event_loop(env, engine, monkeypatch):  # noqa: F811
    on_loop = _spy_on_loop(monkeypatch)
    d = dev(env)
    assert d.post("/api/v1/studio/live/command", json={"command": "scene", "arg": "khutba"}).status_code == 200
    assert d.patch("/api/v1/studio/live/overlays/qr", json={"visible": True, "url": "https://sada.example/q"}).status_code == 200
    assert len(on_loop) >= 2 and not any(on_loop), on_loop


# ------------------------------------------------------------------ 3: unknown custom scene
import base64  # noqa: E402
import datetime as dt  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from PIL import Image  # noqa: E402
from test_setup_mode import cfg, make, open_setup  # noqa: E402

from sada import api, encoder as enc_mod, i18n, transitions  # noqa: E402
from sada.backoffice import live  # noqa: E402
from sada.state import Machine, Signals, State  # noqa: E402

SIG = Signals(now=dt.datetime(2026, 11, 20, 12, 30), t=100.0)


def test_machine_refuses_a_custom_scene_without_a_known_image():
    m = Machine()
    msg = m.command("scene", SIG, "custom:ghost")
    assert m.state != State.CUSTOM and m.scene != "custom:ghost" and m.override is False
    assert "custom:ghost" in msg


def test_legacy_scene_command_refuses_custom_scenes_in_the_back_office():
    with pytest.raises(ValueError):
        live.command({"id": 1, "slug": "x"}, "scene", valeur="custom:ghost")


def test_orchestrator_scene_command_for_an_unknown_custom_scene_changes_nothing(monkeypatch, tmp_path):
    o = make(monkeypatch)
    before = o.machine.state
    o.manual("scene", "custom:ghost")
    assert o.machine.state == before and o.machine.scene != "custom:ghost"
    png = _png()
    o.set_custom_scene("custom:known", png)
    assert o.machine.scene == "custom:known"


def _png() -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", (200, 120), (10, 80, 40)).save(buf, "PNG")
    return buf.getvalue()


# ------------------------------------------------------------------ 5: slow work outside the lock
def test_closing_the_setup_stops_the_encoder_without_holding_the_engine_lock(monkeypatch, tmp_path):
    o = make(monkeypatch)
    open_setup(o, tmp_path)
    enc = o.rehearsal.encoder
    free: list[bool] = []

    def stop():
        got: list[bool] = []

        def other():  # another thread: an RLock held by the caller's thread would refuse it
            got.append(o.lock.acquire(timeout=1))
            if got[0]:
                o.lock.release()

        t = threading.Thread(target=other)
        t.start()
        t.join()
        free.extend(got)
        enc.wanted = False

    enc.stop = stop
    o.set_setup(False)
    assert free == [True]
    assert o.rehearsal is None


def test_reopening_the_setup_stops_the_previous_encoder_outside_the_lock_then_builds_a_new_one(monkeypatch, tmp_path):
    o = make(monkeypatch)
    open_setup(o, tmp_path)
    first = o.rehearsal
    o.setup.close()  # lease gone: the next open is a fresh one
    o.set_setup(True, 90)
    assert o.rehearsal is not first and first.encoder.stopped == 1 and o.rehearsal.encoder.wanted


# ------------------------------------------------------------------ 11: ports and memory
def test_setup_encoder_ports_never_overlap_the_live_block_and_can_be_configured():
    span = 1 + enc_mod.ZMQ_VIDEO
    live_cfg = SimpleNamespace(zmq_port=5556, zmq_port_setup=0)
    base = enc_mod.setup_zmq_port(live_cfg)
    assert base >= 5556 + span or base + span <= 5556
    assert enc_mod.setup_zmq_port(SimpleNamespace(zmq_port=5556, zmq_port_setup=6000)) == 6000
    overlapping = SimpleNamespace(zmq_port=5556, zmq_port_setup=5558)
    assert enc_mod.setup_zmq_port(overlapping) == base  # a block overlapping the live's is ignored


def test_custom_scene_images_are_bounded_and_the_scenes_on_air_survive(monkeypatch, tmp_path):
    from sada import orchestrator as orch

    o = make(monkeypatch)
    monkeypatch.setattr(orch, "MAX_CUSTOM_IMAGES", 3)
    png = _png()
    for i in range(6):
        o.set_custom_scene(f"custom:s{i}", png)
    assert len(o._custom_scenes) == 3
    assert "custom:s5" in o._custom_scenes  # the one on air is kept


# ------------------------------------------------------------------ 14: translated messages
@pytest.mark.parametrize("msg", ["muted must be a boolean", "bad offer", "relay unavailable"])
def test_messages_have_fr_and_ar_translations(msg):
    for lang in ("fr", "ar"):
        assert i18n.translate(msg, lang) != msg, (lang, msg)


def test_state_and_transition_errors_follow_the_language():
    tok = i18n.set_lang("fr")
    try:
        with pytest.raises(ValueError) as e1:
            Machine().set_mute("yes")  # type: ignore[arg-type]
        with pytest.raises(ValueError) as e2:
            transitions.duration("dissolve")
    finally:
        i18n.reset(tok)
    assert str(e1.value) != "muted must be a boolean"
    assert str(e2.value) == "transition inconnue : dissolve"


# ------------------------------------------------------------------ 15: token comparison
def test_api_token_is_compared_in_constant_time(monkeypatch):
    calls: list[tuple] = []
    real = api.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(api.hmac, "compare_digest", spy)
    orch = SimpleNamespace(status=lambda: {"ok": True})
    srv = api.make_server(orch, "127.0.0.1", 0, token="tok")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:

        def get(headers):
            req = urllib.request.Request(f"http://127.0.0.1:{port}/status", headers=headers)
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code

        assert get({"X-Token": "tok"}) == 200
        assert get({"Authorization": "Bearer tok"}) == 200
        assert get({"X-Token": "nope"}) == 401
        assert get({"Authorization": "Bearer tok2"}) == 401
        assert get({}) == 401
        assert get({"X-Token": "tök"}) == 401  # non-ASCII must not break the comparison
    finally:
        srv.shutdown()
    assert calls, "the token was not compared with hmac.compare_digest"


# ------------------------------------------------------------------ control room routes
import io  # noqa: E402

from conftest import client as make_client, one  # noqa: E402
from test_regie_studio import pair  # noqa: E402

from sada.backoffice import custom_scenes, models  # noqa: E402


@pytest.fixture
def scenes_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(custom_scenes, "DIR", tmp_path / "custom_scenes")
    return tmp_path / "custom_scenes"


def _upload_png(size=(320, 180)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 90, 60)).save(buf, "PNG")
    return buf.getvalue()


def test_scene_images_and_previews_are_readable_by_a_paired_device(env, engine, scenes_dir, monkeypatch):  # noqa: F811
    """`/studio/regie` hands out these `preview_url`s to bearer devices, which carry no cookie."""
    from sada.backoffice import screens

    monkeypatch.setattr(screens, "preview", lambda *a, **k: _upload_png())
    admin = make_client(env, "admin")
    r = admin.post(
        "/api/v1/live/regie/custom-scenes",
        data={"label": "Pause", "category": "pause"},
        files={"file": ("p.png", _upload_png(), "image/png")},
        headers={"X-CSRF": admin.csrf},
    )
    assert r.status_code == 200, r.text
    d = dev(env)
    assert d.get("/api/v1/live/regie/custom-scenes/pause/image").status_code == 200
    assert d.get("/api/v1/live/regie/scene/khutba.png").status_code == 200
    anon = make_client(env)
    assert anon.get("/api/v1/live/regie/custom-scenes/pause/image").status_code in (401, 403)


def _admin_upload(env, data: bytes, name="big.png", label="Grande"):
    admin = make_client(env, "admin")
    return admin.post(
        "/api/v1/live/regie/custom-scenes",
        data={"label": label, "category": "autre"},
        files={"file": (name, data, "image/png")},
        headers={"X-CSRF": admin.csrf},
    )


def test_oversized_upload_is_refused_by_chunks_before_any_decoding(env, scenes_dir, monkeypatch):
    seen: list[int] = []
    real = regie._read_bounded

    async def spy(file, limit):
        try:
            return await real(file, limit)
        finally:
            seen.append(limit)

    monkeypatch.setattr(regie, "_read_bounded", spy)
    monkeypatch.setattr(
        custom_scenes, "prepare_image", lambda *a, **k: pytest.fail("a refused upload must not be decoded")
    )
    r = _admin_upload(env, b"\0" * (custom_scenes.MAX_BYTES + 1))
    assert r.status_code == 400 and seen == [custom_scenes.MAX_BYTES]


def test_decompression_bomb_is_refused_without_decoding(env, scenes_dir, monkeypatch):
    monkeypatch.setattr(custom_scenes, "MAX_PIXELS", 1000)
    r = _admin_upload(env, _upload_png((320, 180)))
    assert r.status_code == 400
    with pytest.raises(ValueError):
        custom_scenes.prepare_image("a.png", _upload_png((320, 180)))


def test_upload_decoding_and_scene_image_reads_run_off_the_event_loop(env, engine, scenes_dir, monkeypatch):  # noqa: F811
    where: dict[str, bool] = {}

    def probe(name, fn):
        def wrapped(*a, **k):
            try:
                asyncio.get_running_loop()
                where[name] = True
            except RuntimeError:
                where[name] = False
            return fn(*a, **k)

        return wrapped

    monkeypatch.setattr(custom_scenes, "create", probe("create", custom_scenes.create))
    monkeypatch.setattr(custom_scenes, "image_bytes", probe("image_bytes", custom_scenes.image_bytes))
    monkeypatch.setattr(live, "set_custom_scene", lambda m, sc, raw, transition=None, **kw: {"ok": True})
    assert _admin_upload(env, _upload_png(), "a.png", "Alpha").status_code == 200
    admin = make_client(env, "admin")
    r = admin.post("/api/v1/live/regie/scene", json={"scene": "custom:alpha"}, headers={"X-CSRF": admin.csrf})
    assert r.status_code == 200, r.text
    assert where == {"create": False, "image_bytes": False}


def test_a_setup_transition_is_not_saved_and_a_lapsed_lease_is_a_409(env, engine, scenes_dir, monkeypatch):  # noqa: F811
    d = dev(env)
    assert d.post("/api/v1/live/regie/transition", json={"mode": "cut"}).status_code == 200
    assert custom_scenes.get_transition(_mosque(env)) == "cut"

    monkeypatch.setattr(live, "set_transition", lambda m, mode, setup=False: {"ok": True})
    assert d.post("/api/v1/live/regie/transition", json={"mode": "fade", "setup": True}).status_code == 200
    assert custom_scenes.get_transition(_mosque(env)) == "cut"  # the rehearsal did not touch the saved one

    def lapsed(m, mode, setup=False):
        raise live.SetupLapsed("setup lapsed")

    monkeypatch.setattr(live, "set_transition", lapsed)
    r = d.post("/api/v1/live/regie/transition", json={"mode": "fade", "setup": True})
    assert r.status_code == 409 and r.json()["code"] == "setup_off"
    assert custom_scenes.get_transition(_mosque(env)) == "cut"


def _mosque(env) -> dict:
    return one(env["conn"], models.Mosque, id=env["mid"])


def test_scene_mute_and_transition_are_audited(env, engine, scenes_dir):  # noqa: F811
    d = dev(env)
    assert d.post("/api/v1/live/regie/scene", json={"scene": "khutba"}).status_code == 200
    assert d.post("/api/v1/live/regie/mute", json={"muted": True}).status_code == 200
    assert d.post("/api/v1/live/regie/transition", json={"mode": "cut"}).status_code == 200
    for action in ("studio.live.commande", "studio.live.sourdine", "studio.live.transition"):
        row = one(env["conn"], models.Audit, action=action)
        assert row is not None, action
        assert json.loads(row["details"])["appareil"]
    # a refused command leaves no trace of a change
    assert d.post("/api/v1/live/regie/mute", json={"muted": "yes"}).status_code == 400


def test_custom_scene_audit_trail_exists(env, scenes_dir):
    assert _admin_upload(env, _upload_png(), "a.png", "Alpha").status_code == 200
    admin = make_client(env, "admin")
    assert admin.delete("/api/v1/live/regie/custom-scenes/alpha", headers={"X-CSRF": admin.csrf}).status_code == 200
    assert one(env["conn"], models.Audit, action="regie.custom_scene.create")
    assert one(env["conn"], models.Audit, action="regie.custom_scene.delete")


# ------------------------------------------------------------------ custom_scenes storage
def test_concurrent_manifest_updates_lose_nothing(scenes_dir):
    mosque = {"id": 1, "slug": "m1"}
    errors: list[BaseException] = []

    def make(i):
        try:
            custom_scenes.create(
                _NoAudit(), mosque, f"Scene {i}", "autre", "a.png", _upload_png(), None, None
            )
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=make, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors
    assert len(custom_scenes._raw_list(mosque)) == 8
    assert not list(scenes_dir.glob("m1/manifest.*.tmp"))  # no stray temporary file


class _NoAudit:
    """Stand-in connection: the audit insert and the commit are not what is under test."""

    def execute(self, *a, **k):
        return None

    def commit(self):
        return None


def test_scene_version_is_stable_across_processes_and_settings_key_is_gone():
    item = {"slug": "a", "updated_at": "2026-11-20T10:00:00"}
    import subprocess
    import sys

    code = (
        "from sada.backoffice import custom_scenes as c;"
        "print(c._format({'slug':'a','updated_at':'2026-11-20T10:00:00'})['preview_url'])"
    )
    outs = {
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout for _ in range(2)
    }
    assert len(outs) == 1 and custom_scenes._format(item)["preview_url"] in "".join(outs)
    assert not hasattr(custom_scenes, "SETTINGS_KEY")
