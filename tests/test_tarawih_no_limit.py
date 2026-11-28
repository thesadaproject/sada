"""A night prayer has no time limit: it ends on a stop, a silence, a signal lost for good, or at the fajr adhan."""

from __future__ import annotations

import datetime as dt
import math
import time

import pytest
from test_setup_mode import make
from test_signal_end import END, LIVE, internal_client  # noqa: F401
from test_studio_devices import _setup, audits, dev, heartbeat, oneoff, pair, program, relay  # noqa: F401

from sada import setup_mode, studio_link
from sada.backoffice import studio_plan
from sada.state import TARAWIH_TIMING, Machine, MachineParams, Signals, State

pytestmark = pytest.mark.usefixtures("relay")

D = dt.datetime(2027, 3, 2)
FAJR = {D.date(): dt.datetime(2027, 3, 2, 5, 30), (D + dt.timedelta(days=1)).date(): dt.datetime(2027, 3, 3, 5, 29)}


def night(extra=None, start=(21, 0), fajr=True):
    meta = {"kind": "tarawih", "mode": "audio", "reciters": ["A"], "silence_end_min": 6, **(extra or {})}
    when = D.replace(hour=start[0], minute=start[1])
    m = Machine([when], MachineParams(), extras=[meta])
    if fajr:
        m.fajr_at = lambda day: FAJR.get(day)
    m.command("tarawih", Signals(when, 0.0, 60.0, 0.0))
    assert m.state == State.TARAWIH
    return m


def tick(m, t, now, voice=60.0, silence=0.0, presence=True):
    m.tick(Signals(now, t, voice, silence, presence))


def test_there_is_no_default_maximum_length():
    assert TARAWIH_TIMING.max_s == math.inf


def test_a_night_of_nine_hours_with_a_voice_never_ends_by_the_clock():
    m = night(fajr=False)
    for h in range(1, 10):
        tick(m, 3600.0 * h, D.replace(hour=21) + dt.timedelta(hours=h))
        assert m.state == State.TARAWIH, h


def test_a_maximum_chosen_by_the_mosque_is_kept():
    m = night({"max_min": 120}, fajr=False)
    tick(m, 7000.0, D.replace(hour=22, minute=56))
    assert m.state == State.TARAWIH
    tick(m, 7201.0, D.replace(hour=23, minute=1))
    assert m.state != State.TARAWIH and m.records[0].status == "done"


def test_the_night_ends_at_the_fajr_adhan_even_with_a_voice_and_people_in_the_room():
    m = night()
    tick(m, 3600.0, D.replace(hour=23, minute=30))  # before midnight: the fajr of that same day is behind
    assert m.state == State.TARAWIH
    tick(m, 30000.0, D + dt.timedelta(days=1, hours=5, minutes=33))
    assert m.state == State.TARAWIH  # fajr of the 3rd is 05:29, and the guard has its 5 minutes
    tick(m, 30100.0, D + dt.timedelta(days=1, hours=5, minutes=34))
    assert m.state != State.TARAWIH and m.last_reason == "adhan du fajr" and m.records[0].status == "done"


def test_the_fajr_wins_over_an_extension():
    m = night()
    m.extend_until_t = 10**9  # "extend" asked by the control room
    tick(m, 30100.0, D + dt.timedelta(days=1, hours=5, minutes=35))
    assert m.state != State.TARAWIH


def test_a_qiyam_after_midnight_ends_at_the_fajr_of_that_same_morning():
    m = night(start=(2, 30))
    tick(m, 3000.0, D.replace(hour=5, minute=34))
    assert m.state == State.TARAWIH
    tick(m, 3100.0, D.replace(hour=5, minute=35))
    assert m.state != State.TARAWIH and m.last_reason == "adhan du fajr"


def test_without_the_fajr_nothing_else_changes():
    m = night(fajr=False)
    tick(m, 99999.0, D + dt.timedelta(days=1, hours=7))
    assert m.state == State.TARAWIH  # the other conditions (silence, stop, signal) still apply


def test_the_silence_rule_still_ends_a_night():
    m = night()
    tick(m, 2000.0, D.replace(hour=22), voice=0.0, silence=500.0, presence=False)  # silence + nobody: grace starts
    tick(m, 2100.0, D.replace(hour=22, minute=2), voice=0.0, silence=600.0, presence=False)
    assert m.state != State.TARAWIH


# ------------------------------------------------------------------ the orchestrator


def test_the_orchestrator_gives_the_machine_the_fajr_of_the_day(monkeypatch):
    o = make(monkeypatch)
    o.times_data = {"times": ["05:30", "13:00", "16:00", "18:30", "20:00"]}
    assert o._fajr_at(dt.date(2027, 3, 3)) == dt.datetime(2027, 3, 3, 5, 30)
    o.times_data = {"times": []}
    assert o._fajr_at(dt.date(2027, 3, 3)) is None
    o.times_data = {"times": ["xx:yy"]}
    assert o._fajr_at(dt.date(2027, 3, 3)) is None


def _on_air(monkeypatch):
    o = make(monkeypatch)
    extra = {"kind": "tarawih", "mode": "audio", "reciters": ["A"]}
    o.machine = Machine([dt.datetime(2026, 11, 20, 12, 0)], MachineParams(), extras=[extra])
    o.machine.custom_known = o._custom_scenes.__contains__
    o.live_stage = setup_mode.Stage(o.machine, o.encoder)
    o._signal_lost = False
    reasons = []
    o.studio_poll = type("P", (), {"request_end": lambda self, at, reason="x": reasons.append(reason)})()
    o.manual("tarawih")
    assert o.machine.state == State.TARAWIH
    return o, reasons


def test_a_night_ending_normally_is_told_to_the_back_office_once(monkeypatch):
    o, reasons = _on_air(monkeypatch)
    o._sync()
    assert reasons == []  # on air: nothing to say
    o.machine.command("stop", o.signals())  # or a silence, or the fajr: any end of the session
    o._sync()
    o._sync()
    assert reasons == ["fin_de_nuit"]


# ------------------------------------------------------------------ the back office


def test_a_night_ending_closes_its_slot_and_only_its_slot(env):
    program(env, oneoff("d1", -1, "Tafsir"))
    bearer, _did = pair(env)
    d = dev(env, bearer)
    assert heartbeat(d).json()["command"] == "live"
    r = internal_client(env).post(END, json={"lost_at": time.time(), "reason": "fin_de_nuit"})
    assert r.json()["ended"] == ["slot"]
    assert heartbeat(d).json()["reason_code"] == "slot_stopped"  # the device goes back to standby
    rows = audits(env, "studio.creneau.arret")
    assert rows and "fin_de_nuit" in str(rows[-1])


def test_a_night_ending_does_not_close_a_manual_live(env):
    bearer, _did = pair(env)
    d = dev(env, bearer)
    d.post("/api/v1/studio/live/start", json={"type": "dars", "title": "Cours"})
    r = internal_client(env).post(END, json={"lost_at": time.time(), "reason": "fin_de_nuit"})
    assert r.json()["ended"] == []
    assert heartbeat(d).json()["command"] == "live"


def test_an_unknown_reason_is_journaled_as_a_signal_loss(env):
    bearer, _did = pair(env)
    dev(env, bearer).post("/api/v1/studio/live/start", json={"type": "dars", "title": "x"})
    internal_client(env).post(END, json={"lost_at": time.time(), "reason": "<script>"})
    (row,) = audits(env, "studio.direct.manuel.fin")
    assert "signal_perdu" in str(row) and "script" not in str(row)


def test_a_stopped_night_slot_does_not_hide_the_qiyam_that_starts_inside_it():
    """The night's slot runs until the fajr: the qiyam at 02:30 begins while it is still 'running' (and stopped)."""
    utc = dt.UTC
    t0 = dt.datetime(2027, 3, 2, 19, 0, tzinfo=utc)
    night_slot = studio_plan.Slot("tarawih", "programme", "tarawih", "Tarawih", t0, t0 + dt.timedelta(hours=10))
    q0 = t0 + dt.timedelta(hours=7, minutes=30)
    qiyam = studio_plan.Slot("qiyam", "programme", "tarawih", "Qiyam", q0, q0 + dt.timedelta(hours=3))
    now = (q0 + dt.timedelta(minutes=5)).timestamp()
    order = studio_plan.decide(now, [night_slot, qiyam], None, {night_slot.key}, {}, 120)
    assert order.command == "live" and order.current["title"] == "Qiyam"
    only = studio_plan.decide(now, [night_slot], None, {night_slot.key}, {}, 120)
    assert only.command == "standby" and only.code == "slot_stopped"  # alone, a stopped slot still stands by


def test_the_two_ends_share_the_reasons_the_back_office_knows():
    from sada.backoffice import studio_service

    assert set(studio_service.REASONS) == {"signal_perdu", "fin_de_nuit", "adhan_du_fajr"}
    assert studio_link.grace_s("tarawih") == 600
