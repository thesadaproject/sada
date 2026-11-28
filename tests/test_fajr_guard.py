"""Every live still on air at the fajr adhan ends (5 minutes of margin), manual or planned, override or pause."""

from __future__ import annotations

import datetime as dt
import time

import pytest
from test_setup_mode import make
from test_signal_end import END, internal_client  # noqa: F401
from test_studio_devices import _setup, audits, dev, heartbeat, oneoff, pair, program, relay  # noqa: F401

from sada import setup_mode
from sada.state import Machine, MachineParams, Signals, State

pytestmark = pytest.mark.usefixtures("relay")

D = dt.datetime(2026, 11, 20)
FAJR = {D.date(): dt.datetime(2026, 11, 20, 5, 30), (D + dt.timedelta(days=1)).date(): dt.datetime(2026, 11, 21, 5, 31)}


def machine(sessions=()):
    m = Machine(list(sessions), MachineParams(), extras=[{} for _ in sessions])
    m.fajr_at = FAJR.get
    return m


def sg(now, t=0.0, voice=0.0, silence=0.0):
    return Signals(now, t, voice, silence)


def test_the_margin_is_five_minutes():
    assert MachineParams().fajr_margin_min == 5.0
    m = machine()
    m.command("start", sg(D.replace(hour=2), 1.0))
    m.tick(sg(D.replace(hour=5, minute=34, second=59), 2.0))
    assert m.stream_on  # 4 min 59 after the adhan: the last du'a
    m.tick(sg(D.replace(hour=5, minute=35), 3.0))
    assert not m.stream_on and m.fajr_end_pending


def test_a_manual_live_in_override_ends_at_the_fajr():
    m = machine()
    m.command("start", sg(D.replace(hour=1), 1.0))
    m.command("scene", sg(D.replace(hour=1, minute=5), 2.0), "avant")  # override, a scene picked by hand
    assert m.override and m.manual_live
    m.tick(sg(D.replace(hour=5, minute=36), 3.0))
    assert not m.stream_on and not m.manual_live


def test_a_paused_live_ends_at_the_fajr():
    m = machine([D.replace(hour=22)])
    m.command("start", sg(D.replace(hour=1), 1.0))
    m.command("pause", sg(D.replace(hour=1, minute=10), 2.0))
    assert m.paused_from is not None
    m.tick(sg(D.replace(hour=5, minute=40), 3.0))
    assert not m.stream_on and m.paused_from is None and m.idx == 0  # the 22:00 session is still planned


def test_a_planned_session_ends_at_the_fajr_and_the_plan_moves_on():
    m = machine([D.replace(hour=2), D.replace(hour=20)])
    m.command("scene", sg(D.replace(hour=2), 1.0), "khutba")
    assert m.live is not None and m.live.planned == "02:00"
    m.tick(sg(D.replace(hour=5, minute=45), 2.0, voice=60.0))
    assert not m.stream_on and m.idx == 1 and m.records[0].status == "done"


def test_an_end_screen_in_progress_is_left_alone_to_finish():
    m = machine()
    m.command("start", sg(D.replace(hour=5, minute=20), 1.0))
    m.command("stop", sg(D.replace(hour=5, minute=33), 2.0))
    assert m.state == State.ENDED
    m.tick(sg(D.replace(hour=5, minute=40), 3.0))  # already ending: no second end
    assert m.state == State.ENDED and not m.fajr_end_pending


def test_a_live_that_began_after_the_fajr_belongs_to_the_day():
    m = machine()
    m.command("start", sg(D.replace(hour=6, minute=30), 1.0))  # the morning of that day
    m.tick(sg(D.replace(hour=13), 2.0))
    assert m.stream_on
    m.tick(sg(D.replace(hour=23, minute=59), 3.0))  # still before the next fajr
    assert m.stream_on


def test_the_evening_live_is_not_cut_by_the_fajr_already_behind_it():
    m = machine()
    m.command("start", sg(D.replace(hour=21), 1.0))
    m.tick(sg(D.replace(hour=23, minute=50), 2.0))  # today's fajr (05:30) is hours behind
    assert m.stream_on
    m.tick(sg(D + dt.timedelta(days=1, hours=5, minutes=36), 3.0))  # tomorrow's, 05:31 + 5 min
    assert not m.stream_on


def test_without_a_known_fajr_nothing_changes():
    m = Machine([], MachineParams(), extras=[])  # fajr_at is the default: unknown
    m.command("start", sg(D.replace(hour=1), 1.0))
    m.tick(sg(D.replace(hour=12), 2.0))
    assert m.stream_on and not m.fajr_end_pending


def test_a_night_ending_exactly_at_the_fajr_ends_by_itself_before_the_guard():
    m = machine()
    m.command("start", sg(D.replace(hour=2), 1.0))
    m.command("stop", sg(D.replace(hour=5, minute=30), 2.0))  # the imam stops on the adhan
    m.tick(sg(D.replace(hour=5, minute=32), 3.0 + 50.0))
    m.tick(sg(D.replace(hour=5, minute=33), 3.0 + 110.0))
    assert not m.stream_on and not m.fajr_end_pending  # the usual end, the guard had nothing to do


def _orch(monkeypatch):
    o = make(monkeypatch)
    o.machine = Machine([], MachineParams(), extras=[])
    o.machine.fajr_at = FAJR.get
    o.machine.custom_known = o._custom_scenes.__contains__
    o.live_stage = setup_mode.Stage(o.machine, o.encoder)
    o._signal_lost = False
    told = []
    o.studio_poll = type("P", (), {"request_end": lambda self, at, reason="x": told.append(reason)})()
    return o, told


def test_the_orchestrator_tells_the_back_office_once(monkeypatch):
    o, told = _orch(monkeypatch)
    o.signals = lambda: Signals(D.replace(hour=1), 1.0, 0.0, 0.0)
    o.manual("start")
    o._sync()
    o.signals = lambda: Signals(D.replace(hour=5, minute=40), 2.0, 0.0, 0.0)
    o.machine.tick(o.signals())
    o._sync()
    o._sync()
    assert not o.machine.stream_on and told == ["adhan_du_fajr"]


def test_the_orchestrator_gives_the_machine_the_fajr(monkeypatch):
    o = make(monkeypatch)
    o.times_data = {"times": ["05:30", "13:00", "16:00", "18:30", "20:00"]}
    assert o._fajr_at(D.date()) == D.replace(hour=5, minute=30)


def test_the_back_office_closes_the_manual_live_and_the_slot_for_the_fajr(env):
    bearer, _did = pair(env)
    d = dev(env, bearer)
    d.post("/api/v1/studio/live/start", json={"type": "dars", "title": "Veillée"})
    r = internal_client(env).post(END, json={"lost_at": time.time(), "reason": "adhan_du_fajr"})
    assert r.json()["ended"] == ["manual"]
    assert heartbeat(d).json()["command"] == "standby"
    (row,) = audits(env, "studio.direct.manuel.fin")
    assert "adhan_du_fajr" in str(row)


def test_the_back_office_stops_the_running_slot_for_the_fajr(env):
    program(env, oneoff("d1", -1, "Tafsir"))
    bearer, _did = pair(env)
    d = dev(env, bearer)
    assert heartbeat(d).json()["command"] == "live"
    r = internal_client(env).post(END, json={"lost_at": time.time(), "reason": "adhan_du_fajr"})
    assert r.json()["ended"] == ["slot"]
    assert heartbeat(d).json()["reason_code"] == "slot_stopped"
