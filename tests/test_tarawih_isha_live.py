"""A tarawih night is on air from the end of isha, continuously: the pause until the tarawih proper is on the waiting
screen (countdown to the tarawih), then the tarawih follows in the same stream. The night itself begins with the tarawih."""

from __future__ import annotations

import datetime as dt

from test_setup_mode import make

from sada import events as events_mod
from sada import orchestrator as orch
from sada import setup_mode
from sada.scenes import SCENES
from sada.state import Machine, MachineParams, Signals, State

ISHA_END = dt.datetime(2027, 2, 20, 19, 50)
OFFSET = 20


def machine(after_isha=False, **extra):
    meta = {
        "kind": "tarawih",
        "title": "Tarawih",
        "mode": "audio",
        "offset_min": OFFSET,
        "after_isha": after_isha,
        **extra,
    }
    pos = {"v": (0, 0.0)}
    m = Machine([ISHA_END], MachineParams(), extras=[meta], pos_fn=lambda: pos["v"])
    m.pos = pos
    return m


def tick(m, now, t, voice=0.0, silence=0.0):
    m.tick(Signals(now, t, voice, silence))


def test_the_stream_is_on_from_the_end_of_isha_on_the_waiting_screen():
    m = machine()
    tick(m, ISHA_END - dt.timedelta(seconds=1), 1.0)
    assert m.state == State.IDLE and not m.stream_on  # isha itself is never on air
    tick(m, ISHA_END, 2.0)
    assert m.state == State.INTERMISSION and m.stream_on and m.scene == "entracte"
    assert SCENES["entracte"].mic is False  # the pause is not a recitation: the microphone stays closed
    for i in range(1, 15):  # 15 minutes of pause, voices in the room
        tick(m, ISHA_END + dt.timedelta(minutes=i), 2.0 + 60 * i, voice=60.0)
    assert m.state == State.INTERMISSION and m.live is None  # no session, nothing recorded as the night yet


def test_the_tarawih_follows_in_the_same_stream_and_the_session_begins_there():
    m = machine()
    tick(m, ISHA_END, 2.0)
    m.pos["v"] = (0, 600.0)  # ten minutes of pause have been recorded
    tick(m, ISHA_END + dt.timedelta(minutes=OFFSET), 3.0, voice=60.0)
    assert m.state == State.TARAWIH and m.stream_on
    assert (
        m.live.recording == 0 and m.live.start_pos == 600.0
    )  # the session starts at the tarawih: the pause is outside


def test_the_countdown_runs_to_the_tarawih_proper():
    m = machine()
    start, rec = m.tarawih_countdown()
    assert start == ISHA_END + dt.timedelta(minutes=OFFSET) and rec.kind == "tarawih"
    m.command("tarawih", Signals(ISHA_END + dt.timedelta(minutes=30), 5.0, 60.0, 0.0))
    assert m.tarawih_countdown() is None  # on air: nothing to wait for
    other = Machine([ISHA_END], MachineParams(), extras=[{"kind": "dars"}])
    assert other.tarawih_countdown() is None


def test_after_isha_announcements_start_the_night_at_once():
    m = machine(after_isha=True)
    tick(m, ISHA_END, 2.0, voice=60.0)
    assert m.state == State.TARAWIH and "après l'isha" in m.last_reason


def test_a_qiyam_at_a_fixed_hour_has_no_pause_before_it():
    raw = {"uid": "qiyam", "kind": "tarawih", "title": "Qiyam", "time": "02:30", "mode": "audio",
           "period": {"from": "2027-02-20", "until": "2027-02-20"}}  # fmt: skip
    inst = events_mod.instances_on([events_mod.parse(raw)], dt.date(2027, 2, 21), {})[0]
    m = Machine([inst.starts], MachineParams(), extras=[inst.as_event()])
    tick(m, inst.starts - dt.timedelta(minutes=30), 1.0)
    assert m.state == State.IDLE and not m.stream_on
    tick(m, inst.starts, 2.0)
    assert m.state == State.ARMED and not m.stream_on  # it listens from its hour, nothing on air before the voice
    tick(m, inst.starts + dt.timedelta(minutes=1), 3.0, voice=60.0)
    assert m.state == State.TARAWIH


def test_a_pause_that_never_ends_in_a_tarawih_closes_with_the_window():
    m = machine()
    tick(m, ISHA_END, 2.0)
    late = ISHA_END + dt.timedelta(minutes=OFFSET + 61)  # the window (60 min after the tarawih proper) is over
    tick(m, late, 3.0)
    assert m.state != State.INTERMISSION and m.records[0].status == "skipped"


def test_the_reconnection_grace_of_the_pause_is_the_night_s_and_the_night_stays_to_come():
    m = machine()
    tick(m, ISHA_END, 2.0)
    assert orch.Orchestrator._grace(m) == 600.0  # the next thing on air is a tarawih
    m.end_lost(Signals(ISHA_END + dt.timedelta(minutes=12), 700.0, 0.0, 0.0), "signal perdu")
    assert not m.stream_on and m.state == State.IDLE
    assert m.records[0].status == "pending" and m.idx == 0  # the night can still come, nothing was consumed


def test_the_recording_of_the_pause_has_no_clean_copy_and_is_not_a_session(monkeypatch):
    o = make(monkeypatch)
    meta = {"kind": "tarawih", "title": "Tarawih", "mode": "audio", "offset_min": OFFSET, "reciters": ["A"]}
    o.machine = Machine([ISHA_END], MachineParams(), extras=[meta])
    o.machine.custom_known = o._custom_scenes.__contains__
    o.live_stage = setup_mode.Stage(o.machine, o.encoder)
    o._signal_lost = False
    o.encoder.clean_wanted = True
    o.machine.tick(Signals(ISHA_END, 1.0, 0.0, 0.0))
    o._sync()
    assert o.machine.state == State.INTERMISSION and o.encoder.wanted
    assert o.encoder.clean_wanted is False  # a tarawih: no clean copy, from the very first second of the pause
    assert o.machine.live is None


class Recorder:
    """A renderer that keeps the moments the screens are drawn for."""

    def __init__(self):
        self.moments = []

    def background(self):
        return None

    def content(self, scene, moment):
        self.moments.append((scene, moment))
        return scene

    def render_overlays(self, overlays):
        return overlays


def test_the_waiting_screen_is_drawn_for_the_tarawih(monkeypatch):
    o = make(monkeypatch)
    o.renderer = Recorder()
    meta = {"kind": "tarawih", "title": "Tarawih", "mode": "audio", "offset_min": OFFSET}
    o.machine = Machine([ISHA_END], MachineParams(), extras=[meta])
    o.machine.custom_known = o._custom_scenes.__contains__
    o.live_stage = setup_mode.Stage(o.machine, o.encoder)
    o._signal_lost = False
    o.clock = type("C", (), {"now": staticmethod(lambda: ISHA_END + dt.timedelta(minutes=5)), "speed": 1.0})()
    o.machine.tick(Signals(ISHA_END, 1.0, 0.0, 0.0))
    o._sync()
    scene, moment = o.renderer.moments[-1]
    assert scene == "entracte"
    assert moment.next_event.kind == "tarawih" and moment.next_event.starts == ISHA_END + dt.timedelta(minutes=OFFSET)


def test_the_real_screen_counts_down_to_the_tarawih():
    from sada.config import Config
    from sada.scenes import Moment, SceneRenderer

    r = SceneRenderer(Config())
    when = ISHA_END + dt.timedelta(minutes=OFFSET)
    nxt = events_mod.EventInstance(starts=when, kind="tarawih", title="Tarawih")
    img = r.content("entracte", Moment(ISHA_END + dt.timedelta(minutes=5), ISHA_END, next_event=nxt))
    assert img.size == (1280, 720) and img.getbbox() is not None
