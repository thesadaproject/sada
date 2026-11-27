"""Signal loss: the live whose picture disappears stays open on the destinations (reconnection screen) for a fixed
grace, comes back to the relay if the signal returns, and ends like a normal stop otherwise. A voluntary stop never
shows the reconnection screen."""

from __future__ import annotations

import datetime as dt

import pytest
from PIL import Image
from test_setup_mode import make

from sada import encoder as enc_mod
from sada import orchestrator as orch
from sada import signal_screen, studio_link
from sada.backoffice import studio_plan
from sada.backoffice.api import studio as studio_api
from sada.config import Config
from sada.encoder import FALLBACK_AFTER_S, PROBE_EVERY_S, RETURN_PROBES, Encoder
from sada.state import Machine, MachineParams, Signals, State

DAY = dt.datetime(2026, 11, 20)


# ------------------------------------------------------------------ the encoder


class FakeProc:
    """A stand-in ffmpeg: alive until terminated or killed."""

    def __init__(self, cmd=None):
        self.cmd = cmd
        self.returncode = None
        self.terminated = False
        self.stdout = iter(())
        self.stderr = iter(())

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated, self.returncode = True, -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class Relay:
    """What the relay says about the input: True (published), False (gone), None (cannot tell)."""

    def __init__(self):
        self.ready: bool | None = True

    def __call__(self):
        return self.ready


class Time:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def tick(self, seconds: float, enc: Encoder, steps: float = PROBE_EVERY_S):
        """Moves the clock by `seconds`, supervising once per `steps`."""
        end = self.t + seconds
        while self.t < end:
            self.t = min(end, self.t + steps)
            enc._tick()


@pytest.fixture
def rig(tmp_path, monkeypatch):
    launched: list[FakeProc] = []

    def popen(cmd, *a, **k):
        p = FakeProc(cmd)
        launched.append(p)
        return p

    monkeypatch.setattr(enc_mod.subprocess, "Popen", popen)
    monkeypatch.setattr(enc_mod.Encoder, "_spawn_preview", lambda self: None)
    cfg = Config(rtmp_urls=["rtmp://fb.example/live/KEY", "rtmp://yt.example/live/KEY"], width=1280, height=720)
    cfg.record_dir = str(tmp_path / "rec")
    logs: list[str] = []
    enc = Encoder(cfg, tmp_path, log=logs.append)
    clock, relay = Time(), Relay()
    enc.clock, enc.wall = clock, lambda: 1_700_000_000.0 + (clock.t - 1000.0)
    enc.source_ready = relay
    monkeypatch.setattr(enc_mod.time, "monotonic", clock)  # the encoder's own delays follow the same clock
    enc.start()
    enc._opened = enc._had_signal = True  # the programme ffmpeg opened its input
    return enc, clock, relay, launched, logs


def _is_fallback(proc: FakeProc) -> bool:
    return "anullsrc=r=48000:cl=stereo" in proc.cmd


def test_fallback_command_is_the_programme_without_recording_nor_graph(tmp_path):
    cfg = Config(rtmp_urls=["rtmp://fb.example/live/KEY"], width=1920, height=1080, fps=25, video_bitrate="6000k")
    cmd = Encoder(cfg, tmp_path).fallback_cmd("/x/signal_lost.png")
    joined = " ".join(cmd)
    assert cmd[0] == "ffmpeg" and "/x/signal_lost.png" in cmd
    assert cmd[cmd.index("-framerate") + 1] == "25" and "-loop" in cmd  # the still picture, at the programme's rate
    assert "anullsrc=r=48000:cl=stereo" in cmd  # and silence
    assert cmd[cmd.index("-b:v") + 1] == cmd[cmd.index("-maxrate") + 1] == "6000k"
    assert cmd[cmd.index("-g") + 1] == "50"
    assert "scale=1920:1080" in joined and "pad=1920:1080" in joined and "fps=25" in joined
    assert cmd[-1] == "[f=flv:onfail=ignore]rtmp://fb.example/live/KEY"  # same destinations, through the tee
    assert "matroska" not in joined and "zmq" not in joined and ".mkv" not in joined  # nothing recorded, nothing driven


def test_loss_switches_to_the_reconnection_screen_after_a_few_seconds(rig):
    enc, clock, relay, launched, logs = rig
    main = enc.proc
    recordings = list(enc.recordings)
    relay.ready = False
    clock.tick(FALLBACK_AFTER_S - 3, enc)
    assert not enc.fallback and enc.proc is main  # a blip: nothing yet
    clock.tick(6, enc)
    assert enc.fallback and main.terminated  # the programme ffmpeg is stopped (its recording closed cleanly)
    assert _is_fallback(enc.proc) and enc.proc is launched[-1]
    assert enc.recordings == recordings  # no file for the reconnection screen
    assert enc.current_recording() is None
    assert enc.graph_up() is False and enc.alive() is True
    png = Image.open(enc.run_dir / "signal_lost.png")
    assert png.size == (1280, 720)  # the programme's size
    assert any("input lost" in m for m in logs)


def test_the_grace_counts_from_the_loss_and_the_wall_clock_is_exposed(rig):
    enc, clock, relay, *_ = rig
    relay.ready = False
    clock.tick(PROBE_EVERY_S, enc)
    lost_at = enc.lost_wall
    assert lost_at is not None and enc.signal_lost_for() is None  # not on the reconnection screen yet
    clock.tick(FALLBACK_AFTER_S + PROBE_EVERY_S, enc)
    assert enc.fallback and enc.lost_wall == lost_at  # unchanged while it lasts
    clock.tick(30, enc)
    assert enc.signal_lost_for() == pytest.approx(clock.t - (1000.0 + PROBE_EVERY_S), abs=PROBE_EVERY_S)
    assert enc.signal_lost_for() > 30


def test_signal_back_resumes_on_the_relay_with_a_new_recording(rig):
    enc, clock, relay, launched, logs = rig
    relay.ready = False
    clock.tick(FALLBACK_AFTER_S + 4, enc)
    fb = enc.proc
    assert enc.fallback
    relay.ready = True
    clock.tick(PROBE_EVERY_S * (RETURN_PROBES + 1), enc)
    assert not enc.fallback and fb.terminated
    assert not _is_fallback(enc.proc) and enc.proc is launched[-1]  # the programme ffmpeg is back on the relay
    assert len(enc.recordings) == 2  # the resumption opens its own file: the gap is a file boundary
    assert enc.signal_lost_for() is None and enc.lost_wall is None
    assert any("input back" in m for m in logs)


def test_a_flapping_relay_does_not_bring_the_programme_back_on_one_good_probe(rig):
    enc, clock, relay, launched, _ = rig
    relay.ready = False
    clock.tick(FALLBACK_AFTER_S + 4, enc)
    relay.ready = True
    clock.tick(PROBE_EVERY_S, enc)  # one answer only
    relay.ready = False
    clock.tick(PROBE_EVERY_S * 3, enc)
    assert enc.fallback and len(enc.recordings) == 1


def test_a_session_ended_on_the_reconnection_screen_ends_where_its_recording_ends(rig):
    """The reconnection screen is not recorded: the position stays where the file stopped."""
    enc, clock, relay, launched, _ = rig
    m = Machine([DAY.replace(hour=13)], MachineParams(), extras=[{}], pos_fn=enc.position)
    enc.out_time = 12.0
    m.start_adhoc(sig(12, 0), "khutba", "A")
    enc.out_time = 600.0  # ten minutes on air
    relay.ready = False
    clock.tick(FALLBACK_AFTER_S + 4, enc)
    assert enc.fallback and enc.position() == (0, 600.0)
    m.end_lost(sig(12, 12, t=900.0), "signal perdu")
    r = m.records[-1]
    assert (r.recording, r.start_pos, r.end_pos, r.status) == (0, 12.0, 600.0, "done")


def test_a_session_resumed_after_the_gap_is_kept_up_to_the_end_of_its_first_recording(rig):
    """The resumption opens a new file: as for any encoder restart, the session stays on the file it started in."""
    enc, clock, relay, launched, _ = rig
    m = Machine([DAY.replace(hour=13)], MachineParams(), extras=[{}], pos_fn=enc.position)
    enc.out_time = 12.0
    m.start_adhoc(sig(12, 0), "khutba", "B")
    relay.ready = False
    clock.tick(FALLBACK_AFTER_S + 4, enc)
    relay.ready = True
    clock.tick(PROBE_EVERY_S * (RETURN_PROBES + 1), enc)
    assert not enc.fallback and len(enc.recordings) == 2 and enc.position()[0] == 1
    m.end_adhoc(sig(12, 30))
    m.tick(sig(12, 31, t=5000.0))
    assert m.records[-1].recording == 0 and m.records[-1].end_pos is None


def test_a_live_that_never_had_its_input_is_only_waiting(rig):
    enc, clock, relay, launched, _ = rig
    enc._had_signal = False
    relay.ready = False
    clock.tick(FALLBACK_AFTER_S * 5, enc)
    assert not enc.fallback and all(not _is_fallback(p) for p in launched)


def test_an_input_the_relay_cannot_tell_about_is_never_a_lost_one(rig):
    enc, clock, relay, *_ = rig
    relay.ready = None  # camera, OBS elsewhere, relay API down
    clock.tick(FALLBACK_AFTER_S * 5, enc)
    assert not enc.fallback and enc.lost_wall is None


def test_a_voluntary_end_never_shows_the_reconnection_screen(rig):
    enc, clock, relay, launched, _ = rig
    relay.ready = False
    enc.no_fallback = True  # the orchestrator is ending the live (end screen)
    clock.tick(FALLBACK_AFTER_S * 3, enc)
    assert not enc.fallback and all(not _is_fallback(p) for p in launched)


def test_a_stop_while_the_reconnection_screen_is_up_cuts_it_at_once(rig):
    enc, clock, relay, launched, _ = rig
    relay.ready = False
    clock.tick(FALLBACK_AFTER_S + 4, enc)
    fb = enc.proc
    enc.hold = enc.no_fallback = True
    n = len(launched)
    clock.tick(PROBE_EVERY_S, enc)
    assert not enc.fallback and fb.terminated and enc.proc is None
    clock.tick(30, enc)
    assert len(launched) == n  # nothing relaunched while the live ends


def test_a_dead_reconnection_ffmpeg_is_relaunched_quickly(rig):
    enc, clock, relay, launched, _ = rig
    relay.ready = False
    clock.tick(FALLBACK_AFTER_S + 4, enc)
    enc.proc.returncode = 1  # the destinations refused, ffmpeg exited
    clock.tick(enc_mod.FALLBACK_RETRY_S + 1, enc, steps=1.0)
    assert enc.fallback and enc.proc.poll() is None and _is_fallback(enc.proc)  # no exponential backoff


def test_a_stuck_check_never_kills_the_reconnection_ffmpeg(rig):
    enc, clock, relay, *_ = rig
    relay.ready = False
    clock.tick(FALLBACK_AFTER_S + 4, enc)
    clock.tick(enc_mod.STUCK_GRACE_S + 1, enc)
    assert enc.restart_if_stuck("audio") is False and enc.proc.poll() is None


def test_a_transition_during_the_reconnection_screen_does_not_drive_a_missing_graph(rig):
    enc, clock, relay, *_ = rig
    relay.ready = False
    clock.tick(FALLBACK_AFTER_S + 4, enc)
    p = enc_mod.tr.plan("a", True, False, scale=1.0, mode="cut")
    assert enc._animate(p) == 0  # no ZeroMQ round trip, no "no longer answers" restart
    assert enc.proc.poll() is None


def test_stopping_the_encoder_ends_the_reconnection_state(rig):
    enc, clock, relay, *_ = rig
    relay.ready = False
    clock.tick(FALLBACK_AFTER_S + 4, enc)
    fb = enc.proc
    enc.stop()
    assert fb.terminated and not enc.fallback and enc.signal_lost_for() is None


# ------------------------------------------------------------------ the screen


def test_the_reconnection_screen_is_drawn_at_the_size_of_the_programme(tmp_path):
    out = signal_screen.write(tmp_path / "s.png", 1920, 1080)
    img = Image.open(out).convert("RGB")
    assert img.size == (1920, 1080) and img.getpixel((5, 5)) == signal_screen.BACKGROUND
    assert len({img.getpixel((x, 540)) for x in range(0, 1920, 7)}) > 1  # something is drawn on the middle line
    assert not (tmp_path / "s.png.tmp.png").exists()


def test_the_reconnection_screen_is_not_one_of_the_mosques_screens():
    import inspect

    from sada import scenes, screens

    for module in (screens, scenes):
        assert "signal_screen" not in inspect.getsource(module)  # fixed Sada screen: no template, no customisation


# ------------------------------------------------------------------ the machine


def sig(hh: int, mm: int, t: float = 0.0) -> Signals:
    return Signals(now=DAY.replace(hour=hh, minute=mm), t=t, voice_run=0.0, silence_run=0.0)


def test_end_lost_closes_the_session_without_an_end_screen_and_keeps_the_plan():
    m = Machine([DAY.replace(hour=13), DAY.replace(hour=18)], MachineParams(), extras=[{}, {}])
    m.start_adhoc(sig(12, 0), "khutba", "Titre")
    assert m.stream_on and m.adhoc_on_air
    m.end_lost(sig(12, 10, t=600.0), "signal perdu")
    assert not m.stream_on and m.live is None and not m.override
    assert m.state == State.IDLE  # the sessions still to come stay planned
    assert m.records[-1].status == "done" and m.records[-1].end_reason == "signal perdu"


def test_end_lost_of_a_planned_session_ends_it_and_hands_back_to_the_plan():
    m = Machine([DAY.replace(hour=13), DAY.replace(hour=20)], MachineParams(), extras=[{}, {}])
    m.command("scene", sig(13, 0), "khutba")
    assert m.live is not None and m.stream_on
    m.end_lost(sig(13, 20, t=100.0), "signal perdu")
    assert not m.stream_on and m.live is None
    assert m.records[0].status == "done"


def test_end_lost_on_the_last_session_stops_the_day():
    m = Machine([DAY.replace(hour=13)], MachineParams(), extras=[{}])
    m.start_adhoc(sig(12, 0), "dars", "")
    m.end_lost(sig(12, 5), "signal perdu")
    assert m.state in (State.STOPPED, State.IDLE) and not m.stream_on


def test_end_lost_off_air_changes_nothing():
    m = Machine([DAY.replace(hour=13)], MachineParams(), extras=[{}])
    before = m.state
    m.end_lost(sig(12, 0), "signal perdu")
    assert m.state == before


# ------------------------------------------------------------------ the orchestrator


def _on_air(monkeypatch):
    o = make(monkeypatch)
    o._signal_lost = False
    o.manual("start")
    assert o.machine.stream_on and o.encoder.wanted
    return o


def test_the_status_says_when_the_signal_was_lost_and_until_when(monkeypatch):
    o = _on_air(monkeypatch)
    st = o.status()
    assert st["signal_lost_since"] is None and st["fallback_until"] is None and st["encoder"]["fallback"] is False
    r0 = o.status()["rev"]
    o.encoder.fallback, o.encoder.lost_wall, o.encoder.lost_for = True, 1_700_000_000.0, 48.0
    o._sync()
    st = o.status()
    assert st["signal_lost_since"] == 1_700_000_000.0
    assert st["fallback_until"] == 1_700_000_000.0 + studio_link.SIGNAL_GRACE_S
    assert st["fallback_remaining_s"] == pytest.approx(studio_link.SIGNAL_GRACE_S - 48.0)
    assert st["encoder"]["fallback"] is True and st["rev"] > r0  # a change of state for the readers
    assert st["stream_on"] is True  # the live is still on air


def test_signal_back_within_the_grace_clears_the_status_and_the_live_goes_on(monkeypatch):
    o = _on_air(monkeypatch)
    o.encoder.fallback, o.encoder.lost_wall, o.encoder.lost_for = True, 1_700_000_000.0, 90.0
    o._sync()
    assert o.machine.stream_on
    o.encoder.fallback, o.encoder.lost_wall, o.encoder.lost_for = False, None, None
    o._sync()
    st = o.status()
    assert st["signal_lost_since"] is None and st["fallback_remaining_s"] is None
    assert o.machine.stream_on and o.encoder.wanted


def test_the_live_ends_like_a_normal_stop_once_the_grace_is_over(monkeypatch):
    o = _on_air(monkeypatch)
    stopped = []
    o._envoyer_rediffusions = lambda: stopped.append("replays")
    o.encoder.fallback, o.encoder.lost_wall = True, 1_700_000_000.0
    o.encoder.lost_for = studio_link.SIGNAL_GRACE_S - 1
    o._sync()
    assert o.machine.stream_on and o.encoder.wanted  # one second short
    o.encoder.lost_for = studio_link.SIGNAL_GRACE_S
    o._sync()
    assert not o.machine.stream_on and not o.encoder.wanted  # stream stopped
    assert o.encoder.stopped == 1 and stopped == ["replays"]  # replays sent, as for any end
    live = [r for r in o.machine.records if r.status == "done"]
    assert live and live[-1].end_reason == "signal perdu"  # the session is closed


def test_a_voluntary_stop_forbids_the_reconnection_screen(monkeypatch):
    o = _on_air(monkeypatch)
    assert o.encoder.no_fallback is False
    o.manual("stop")
    assert o.machine.state == State.ENDED and o.encoder.no_fallback is True and o.encoder.hold is True


def test_a_studio_stop_announced_by_the_back_office_forbids_it_too(monkeypatch):
    o2 = make(monkeypatch)
    o2._signal_lost = False
    o2.studio = studio_link.Follower()
    s = Signals(now=DAY.replace(hour=12), t=10.0, voice_run=0.0, silence_run=0.0)
    o2.studio.step(o2.machine, s, studio_link.Announcement(live=True, source="manual", type="khutba", title="x"))
    o2._sync()
    assert o2.machine.adhoc_on_air and o2.encoder.no_fallback is False
    o2.studio.step(o2.machine, s, studio_link.Announcement(live=False))  # stopped from the studio: live is false
    o2._sync()
    assert o2.machine.state in (State.ENDED, State.DARS_END) and o2.encoder.no_fallback is True


def test_the_server_does_not_take_the_picture_back_during_the_grace(monkeypatch):
    o = _on_air(monkeypatch)
    ann = studio_link.Announcement(live=True, publisher=None, publisher_known=True)
    dev = studio_link.Announcement(live=True, publisher="device", publisher_known=True)
    o._follow_editor(dev, now=0.0)
    assert o.live_stage.compositing == "studio"
    o._signal_lost = True
    o._follow_editor(ann, now=100.0)
    o._follow_editor(ann, now=100.0 + o.STUDIO_GONE_S * 3)
    assert o.live_stage.compositing == "studio"  # no useless switch to a server composition without any picture
    o._signal_lost = False
    o._follow_editor(ann, now=500.0)
    o._follow_editor(ann, now=500.0 + o.STUDIO_GONE_S)
    assert o.live_stage.compositing == "server"  # unchanged behaviour once the encoder has its input again


# ------------------------------------------------------------------ the back office


def test_the_manual_live_silence_delay_is_the_grace_and_covers_several_heartbeats():
    assert studio_plan.MANUAL_SILENCE_S == studio_link.SIGNAL_GRACE_S == 120
    assert studio_plan.MANUAL_SILENCE_S >= 3 * studio_api.HEARTBEAT_S  # at least three missed beats before it ends
    assert studio_plan.MANUAL_SILENCE_S > studio_plan.ONLINE_S  # an offline device is flagged before its live ends


def test_the_orchestrator_and_the_encoder_share_the_same_grace():
    assert orch.studio_link.SIGNAL_GRACE_S == studio_link.SIGNAL_GRACE_S
    assert FALLBACK_AFTER_S > studio_link.POLL_S  # a voluntary stop is seen before the reconnection screen shows


def test_the_back_office_forwards_the_signal_state_to_the_control_room():
    from sada.backoffice import live

    out = live.summarize(
        {"signal_lost_since": 1_700_000_000.0, "fallback_until": 1_700_000_120.0, "fallback_remaining_s": 72}
    )
    assert out["signal_lost_since"] == 1_700_000_000.0 and out["fallback_remaining_s"] == 72.0
    assert out["fallback_until"] == 1_700_000_120.0
    quiet = live.summarize({"signal_lost_since": None, "fallback_until": "x", "fallback_remaining_s": True})
    assert quiet["signal_lost_since"] is quiet["fallback_until"] is quiet["fallback_remaining_s"] is None
