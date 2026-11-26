"""Setup mode in the orchestrator: a rehearsal stage that can never reach a destination or a recording."""

from __future__ import annotations

import datetime as dt
import threading
from collections import OrderedDict
from types import SimpleNamespace

import pytest
from PIL import Image

from sada import encoder as enc_mod
from sada import orchestrator as orch
from sada import setup_mode
from sada.config import Config
from sada.state import Machine, MachineParams

# ------------------------------------------------------------------ the lease


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_the_lease_holds_until_it_lapses_and_a_renewal_is_not_a_new_session():
    clock = Clock()
    lease = setup_mode.SetupLease(clock)
    assert not lease.active()
    assert lease.open(90) is True  # new session
    clock.t += 60
    assert lease.open(90) is False  # renewed
    clock.t += 89
    assert lease.active() and lease.remaining() == pytest.approx(1)
    clock.t += 2
    assert not lease.active() and lease.remaining() == 0
    assert lease.open(90) is True  # lapsed: a new session


def test_close_says_whether_it_was_held():
    lease = setup_mode.SetupLease(Clock())
    assert lease.close() is False
    lease.open(30)
    assert lease.close() is True and not lease.active()


@pytest.mark.parametrize(
    ("given", "expected"),
    [(None, 90.0), ("x", 90.0), (float("nan"), 90.0), (1, 5.0), (60, 60.0), (10_000, setup_mode.TTL_MAX_S)],
)
def test_ttl_is_bounded_and_never_trusted(given, expected):
    assert setup_mode.clamp_ttl(given) == expected


# ------------------------------------------------------------------ the rehearsal encoder


def cfg(**kw):
    return Config(
        rtmp_urls=["rtmp://youtube.example/live/KEY"],
        preview_url="rtmp://receiver:1935/live/x-prog",
        camera_url="rtsp://receiver:8554/live/x",
        record_clean=True,
        **kw,
    )


def cmd_of(encoder):
    return encoder.ffmpeg_cmd("/rec/live.mkv", "/rec/live_clean.mkv")


def test_the_live_encoder_still_goes_to_the_destinations_and_records(tmp_path):
    c = " ".join(cmd_of(enc_mod.Encoder(cfg(), tmp_path)))
    assert "rtmp://youtube.example/live/KEY" in c and "/rec/live.mkv" in c and "rtsp://receiver:8554/live/x" in c


def test_the_rehearsal_encoder_has_no_destination_no_recording_no_camera(tmp_path):
    e = enc_mod.Encoder(cfg(), tmp_path, rehearsal=True)
    args = cmd_of(e)
    c = " ".join(args)
    assert "youtube" not in c and "KEY" not in c  # no destination
    assert "/rec/" not in c and "matroska" not in c and "-c:v:0" not in c  # no recording, no clean copy
    assert "rtsp://" not in c and "lavfi" in c  # the camera is not read
    assert enc_mod.PREVIEW_UDP in args[-1]  # the monitoring copy is the only output
    assert args[-1].count("|") == 0


def test_the_rehearsal_encoder_never_keeps_a_recording(tmp_path, monkeypatch):
    e = enc_mod.Encoder(cfg(), tmp_path, rehearsal=True)
    started = []

    class P:
        stdout = stderr = iter(())

        def poll(self):
            return None

    monkeypatch.setattr(enc_mod.subprocess, "Popen", lambda *a, **k: started.append(a[0]) or P())
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    e._spawn()
    assert e.recordings == [] and started and not (tmp_path / "live.mkv").exists()


# ------------------------------------------------------------------ the orchestrator's stages


class FakeEncoder:
    def __init__(self, cfg_, run_dir, log=print, rehearsal=False):
        self.cfg, self.rehearsal = cfg_, rehearsal
        self.wanted = False
        self.mic_on = False
        self.recordings: list = []
        self.shown: list = []
        self.overlay = None
        self.started = self.stopped = 0

    def prepare(self, bg):
        pass

    def start(self):
        self.wanted, self.started = True, self.started + 1

    def stop(self):
        self.wanted, self.stopped = False, self.stopped + 1

    def alive(self):
        return self.wanted

    def show(self, scene, full, content, transition=None):
        self.shown.append(scene)

    def show_image(self, *a):
        self.shown.append(a[0])

    def set_overlay(self, img):
        self.overlay = img

    def mic(self, on):
        self.mic_on = on

    def position(self):
        return 0, 0.0


class FakeRenderer:
    def background(self):
        return None

    def content(self, scene, moment):
        return scene

    def render_overlays(self, overlays):
        return overlays


def make(monkeypatch, preview="rtmp://receiver:1935/live/x-prog"):
    monkeypatch.setattr(orch, "Encoder", FakeEncoder)
    o = object.__new__(orch.Orchestrator)
    o.cfg = Config(preview_url=preview, rtmp_urls=["rtmp://youtube.example/live/KEY"])
    o.clock = SimpleNamespace(now=lambda: dt.datetime(2026, 11, 20, 12, 0, 0))
    o.run_dir = None
    o.renderer = FakeRenderer()
    o.gabarit = None
    o.lock = threading.RLock()
    o._custom_scenes = OrderedDict()
    o._setup_gate = threading.Lock()
    o._notified_state = None
    o._stream_since = None
    o._saved = None
    o.notifier = SimpleNamespace(enabled=False, notify_state=lambda *a: None)
    o.telemetry = SimpleNamespace(state_changed=lambda *a: None)
    o.uploader = SimpleNamespace(envoyer=lambda f: None)
    o.vad = SimpleNamespace(runs=lambda: (0.0, 0.0), last_db=lambda: None)
    o.presence = o.faces = None
    o.program, o.instances = [], []
    o.times = ["13:00"]
    o.day_plan = lambda day: ([dt.datetime(2026, 11, 20, 13, 0)], [{}])
    o._next_event = lambda now: None
    o._envoyer_rediffusions = lambda: None
    o._save_sessions = lambda: None
    o.signals = lambda: SimpleNamespace(now=dt.datetime(2026, 11, 20, 12, 0), t=1000.0)
    o.encoder = FakeEncoder(o.cfg, None)
    o.machine = Machine([dt.datetime(2026, 11, 20, 13, 0)], MachineParams(), extras=[{}])
    o.machine.custom_known = o._custom_scenes.__contains__
    o.live_stage = setup_mode.Stage(o.machine, o.encoder)
    o.setup = setup_mode.SetupLease()
    o.rehearsal = None
    return o


@pytest.fixture
def tmp_run(tmp_path):
    return tmp_path


def open_setup(o, tmp_path, ttl=90):
    o.run_dir = tmp_path
    return o.set_setup(True, ttl)


def test_opening_the_setup_composes_a_rehearsal_into_its_own_encoder(monkeypatch, tmp_path):
    o = make(monkeypatch)
    st = open_setup(o, tmp_path)
    assert st["active"] and st["rehearsing"] and st["live"] is False and st["scene"] == setup_mode.FIRST_SCENE
    r = o.rehearsal
    assert r.encoder.rehearsal and r.encoder.wanted and r.encoder.cfg.rtmp_urls == []  # no destination
    assert o.encoder.wanted is False and o.encoder.started == 0  # the live encoder was not touched
    assert r.encoder.cfg.zmq_port != o.cfg.zmq_port  # its own graph ports: both can exist at once


def test_setup_needs_the_monitoring_copy(monkeypatch, tmp_path):
    o = make(monkeypatch, preview="")
    o.run_dir = tmp_path
    with pytest.raises(ValueError, match="monitoring copy"):
        o.set_setup(True)
    assert not o.setup.active() and o.rehearsal is None


def test_a_setup_command_lands_on_the_rehearsal_and_never_starts_the_live(monkeypatch, tmp_path):
    o = make(monkeypatch)
    open_setup(o, tmp_path)
    o.manual("scene", "priere", setup=True)
    assert o.rehearsal.machine.scene == "priere" and o.rehearsal.encoder.shown[-1] == "priere"
    assert o.machine.stream_on is False and o.encoder.wanted is False and o.encoder.shown == []
    o.set_overlay("banner", {"visible": True, "title": "Soirée"}, setup=True)
    assert o.rehearsal.machine.overlays["banner"]["visible"] and not o.machine.overlays["banner"]["visible"]
    o.set_mute(True, setup=True)
    assert o.rehearsal.machine.mic_muted and not o.machine.mic_muted
    o.set_transition("cut", setup=True)
    assert o.rehearsal.machine.transition == "cut" and o.machine.transition != "cut"


def test_a_setup_command_is_refused_once_the_lease_lapsed(monkeypatch, tmp_path):
    o = make(monkeypatch)
    clock = Clock()
    o.setup = setup_mode.SetupLease(clock)
    open_setup(o, tmp_path, ttl=10)
    clock.t += 11
    with pytest.raises(setup_mode.SetupInactive):
        o.manual("scene", "priere", setup=True)
    assert o.machine.stream_on is False and o.encoder.wanted is False  # nothing went live by accident


def test_a_command_without_the_setup_mark_is_the_lives_as_before(monkeypatch, tmp_path):
    o = make(monkeypatch)
    open_setup(o, tmp_path)
    o.manual("scene", "priere")
    assert o.machine.scene == "priere" and o.encoder.wanted  # the console's "take it on air" still works


def test_the_lease_lapsing_stops_the_rehearsal_by_itself(monkeypatch, tmp_path):
    o = make(monkeypatch)
    clock = Clock()
    o.setup = setup_mode.SetupLease(clock)
    open_setup(o, tmp_path, ttl=10)
    enc = o.rehearsal.encoder
    clock.t += 11
    o._sync_setup()
    assert o.rehearsal is None and enc.wanted is False and enc.stopped == 1
    assert o.setup_status()["active"] is False and o.setup_status()["rehearsing"] is False


def test_leaving_stops_the_rehearsal_and_forgets_it(monkeypatch, tmp_path):
    o = make(monkeypatch)
    open_setup(o, tmp_path)
    enc = o.rehearsal.encoder
    st = o.set_setup(False)
    assert st["active"] is False and o.rehearsal is None and enc.stopped == 1


def test_a_live_that_starts_takes_over_and_the_rehearsal_steps_aside(monkeypatch, tmp_path):
    o = make(monkeypatch)
    open_setup(o, tmp_path)
    rehearsal_enc = o.rehearsal.encoder
    o.machine.command("scene", o.signals(), "khutba")  # the live goes on air (schedule, OBS, Studio…)
    o._sync()
    assert o.encoder.wanted and rehearsal_enc.wanted is False  # rehearsal stopped BEFORE the live started
    st = o.setup_status()
    assert st["live"] is True and st["rehearsing"] is False and st["active"] is True
    # while on air, a setup-marked command drives the real live (setup breaks nothing, the view is the real programme)
    o.manual("scene", "priere", setup=True)
    assert o.machine.scene == "priere" and o.rehearsal.machine.scene == setup_mode.FIRST_SCENE


def test_the_rehearsal_comes_back_when_the_live_ends_while_the_lease_holds(monkeypatch, tmp_path):
    o = make(monkeypatch)
    open_setup(o, tmp_path)
    o.machine.command("scene", o.signals(), "khutba")
    o._sync()
    o.machine.command("stop", o.signals())
    o.machine.state = o.machine.state.STOPPED
    o._sync()
    o._sync_setup()
    assert o.encoder.wanted is False and o.rehearsal.encoder.wanted is True


def test_status_carries_the_setup_block_and_the_rehearsal_picture(monkeypatch, tmp_path):
    o = make(monkeypatch)
    open_setup(o, tmp_path)
    o.manual("scene", "priere", setup=True)
    o.set_overlay("qr", {"visible": True, "url": "https://example.org/x", "label": "Don", "corner": "br"}, setup=True)
    blk = o.setup_status()
    assert blk["scene"] == "priere" and blk["overlays"]["qr"]["visible"] and blk["available"] is True


def test_every_setup_status_key_is_protocol_data():
    # the setup block feeds the application: keys and values, no sentence to translate
    o = object.__new__(orch.Orchestrator)
    o.cfg = SimpleNamespace(preview_url="")
    o.setup, o.rehearsal = setup_mode.SetupLease(), None
    o.machine = SimpleNamespace(stream_on=False)
    assert o.setup_status() == {
        "active": False,
        "remaining_s": 0.0,
        "available": False,
        "live": False,
        "rehearsing": False,
    }


# ------------------------------------------------------------------ the orchestrator's local API


def _http(port, path, body=None, token="tok"):
    import json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode() if body is not None else b"",
        method="POST",
        headers={"X-Token": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_local_api_setup_route_and_marked_commands():
    from sada.api import make_server

    seen = []

    class Orch:
        def set_setup(self, on, ttl=None):
            seen.append(("setup", on, ttl))
            return {"active": on}

        def manual(self, cmd, arg=None, transition=None, setup=False):
            seen.append(("manual", cmd, arg, setup))
            if setup and cmd == "pause":
                raise setup_mode.SetupInactive("setup mode is not active")
            return {"message": "ok"}

        def set_mute(self, muted, setup=False):
            seen.append(("mute", muted, setup))
            return {}

    srv = make_server(Orch(), "127.0.0.1", 0, token="tok")
    port = srv.server_address[1]
    try:
        assert _http(port, "/setup", {"on": True, "ttl": 60})[1]["active"] is True
        assert _http(port, "/setup", {"on": "yes"})[0] == 400
        assert _http(port, "/scene?name=priere&setup=1")[0] == 200
        assert _http(port, "/scene?name=priere")[0] == 200
        code, body = _http(port, "/pause?setup=1")
        assert (code, body["code"]) == (409, "setup_off")
        assert _http(port, "/mute", {"muted": True, "setup": True})[0] == 200
        assert _http(port, "/mute", {"muted": True})[0] == 200
    finally:
        srv.shutdown()
    assert seen == [
        ("setup", True, 60),
        ("manual", "scene", "priere", True),
        ("manual", "scene", "priere", False),
        ("manual", "pause", None, True),
        ("mute", True, True),
        ("mute", True, False),
    ]


def test_the_background_stays_in_memory_unless_a_template_needs_it_re_read(tmp_path):
    """Default: one image repeated in memory (no PNG read per frame, for every live). With a template, which
    replaces the background on each screen change (`show_image`), the file is re-read."""
    args = cmd_of(enc_mod.Encoder(cfg(), tmp_path))
    fond = args.index(str(tmp_path / "scene_fond.png"))
    assert args[fond - 7 : fond] == ["-f", "image2", "-loop", "1", "-framerate", "1", "-i"]
    graph = args[args.index("-filter_complex") + 1]
    assert "[1:v]format=rgba,loop=loop=-1:size=1," in graph

    reread = cmd_of(enc_mod.Encoder(cfg(), tmp_path, reload_background=True))
    graph = reread[reread.index("-filter_complex") + 1]
    assert "loop=loop" not in graph
    assert f"[1:v]format=rgba,colorchannelmixer@fond=aa=" in graph
    assert f",fps={cfg().fps}[fond]" in graph


def test_showing_a_template_image_switches_the_next_launch_to_a_re_read_background(tmp_path):
    e = enc_mod.Encoder(cfg(), tmp_path)
    assert e.reload_background is False
    e.show_image("prayer", True, Image.new("RGBA", (1280, 720), (1, 2, 3, 255)), "k")
    assert e.reload_background is True


def test_a_template_screen_replacing_the_camera_is_revealed_in_a_running_graph(tmp_path, monkeypatch):
    """`show_image` only wrote the new background: the running graph kept the camera's opacities and never showed it."""
    e = enc_mod.Encoder(cfg(), tmp_path)
    e.prepare(Image.new("RGBA", (1280, 720), (0, 0, 0, 255)))
    img = Image.new("RGBA", (1280, 720), (10, 40, 30, 255))
    started, played = [], []
    monkeypatch.setattr(e, "alive", lambda: True)
    monkeypatch.setattr(e, "_animate", lambda p: played.append(p) or 0)
    monkeypatch.setattr(enc_mod.tr, "DELAI_CHARGEMENT", 0)
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self.name) or self.run())
    e.full = False  # the camera is on air (khutba): background opacity 0
    e.show_image("priere", True, img, "k")
    assert started == ["encoder-fond"]
    (plan,) = played
    assert (plan.fond_from, plan.fond_to, plan.mode) == (0.0, 1.0, "cut")  # the background goes to 1
    assert e.full is True and e.shown == ("priere", plan.dst, "k")


def test_a_template_screen_before_the_start_only_seeds_the_graph(tmp_path, monkeypatch):
    e = enc_mod.Encoder(cfg(), tmp_path)
    e.prepare(Image.new("RGBA", (1280, 720), (0, 0, 0, 255)))
    img = Image.new("RGBA", (1280, 720), (10, 40, 30, 255))
    monkeypatch.setattr(threading.Thread, "start", lambda self: pytest.fail("nothing to drive before ffmpeg runs"))
    e.show_image("priere", True, img, "k")
    assert e.levels["fond"] == 1.0
