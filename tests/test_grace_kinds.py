"""The reconnection grace depends on the kind of the session: 2 minutes, 10 for a night prayer."""

from __future__ import annotations

import datetime as dt
import time

import pytest
from test_setup_mode import make
from test_signal_end import END, internal_client  # noqa: F401
from test_studio_devices import _setup, dev, pair, relay  # noqa: F401

from sada import setup_mode, studio_link
from sada.backoffice import models, studio_plan
from sada.state import Machine, MachineParams, State

pytestmark = pytest.mark.usefixtures("relay")


def test_one_function_decides_the_grace():
    assert studio_link.grace_s("khutba") == studio_link.grace_s("dars") == studio_link.grace_s("conference") == 120
    assert studio_link.grace_s("tarawih") == 600
    assert studio_link.grace_s(None) == studio_link.grace_s("anything") == studio_link.SIGNAL_GRACE_S


def _orchestrator(monkeypatch, kind):
    o = make(monkeypatch)
    extra = {"kind": "tarawih", "mode": "audio", "reciters": ["A"]} if kind == "tarawih" else {}
    o.machine = Machine([dt.datetime(2026, 11, 20, 12, 0)], MachineParams(), extras=[extra])
    o.machine.custom_known = o._custom_scenes.__contains__
    o.live_stage = setup_mode.Stage(o.machine, o.encoder)
    o._signal_lost = False
    o.manual("tarawih" if kind == "tarawih" else "start")
    assert o.machine.stream_on
    return o


def _lost(o, seconds):
    o.encoder.fallback, o.encoder.lost_wall, o.encoder.lost_for = True, 1_700_000_000.0, float(seconds)
    o._sync()


def test_a_tarawih_night_lives_ten_minutes_on_the_reconnection_screen(monkeypatch):
    o = _orchestrator(monkeypatch, "tarawih")
    assert o.machine.state == State.TARAWIH
    _lost(o, 130)  # past the khutba grace
    assert o.machine.stream_on
    st = o.status()
    assert st["fallback_until"] == 1_700_000_600.0 and st["fallback_remaining_s"] == pytest.approx(470.0)
    _lost(o, 599)
    assert o.machine.stream_on and o.ended_at_back_office == []
    _lost(o, 600)
    assert not o.machine.stream_on and o.ended_at_back_office == [1_700_000_000.0]


def test_a_khutba_keeps_its_two_minutes(monkeypatch):
    o = _orchestrator(monkeypatch, "khutba")
    _lost(o, 119)
    assert o.machine.stream_on and o.status()["fallback_remaining_s"] == pytest.approx(1.0)
    _lost(o, 120)
    assert not o.machine.stream_on


# ------------------------------------------------------------------ the back office


def test_a_silent_device_ends_its_manual_live_after_the_grace_of_its_kind(env):
    bearer, did = pair(env)
    dev(env, bearer).post("/api/v1/studio/live/start", json={"type": "dars", "title": "Cours"})
    now = time.time()
    run = env["conn"].execute(models.StudioRun.__table__.select()).first()._mapping
    assert studio_plan.silence_s(run["kind"]) == 120 and studio_plan.silence_s("tarawih") == 600
    from conftest import update

    update(env["conn"], models.Device, {"last_seen_at": now - 100}, id=did)
    assert studio_plan.manual_run(env["conn"], env["mid"], now) is not None  # 100 s of silence: still live
    update(env["conn"], models.Device, {"last_seen_at": now - 130}, id=did)
    assert studio_plan.manual_run(env["conn"], env["mid"], now) is None  # 130 s: over


def test_the_silence_delay_covers_the_heartbeats_for_every_kind():
    from sada.backoffice.api import studio as studio_api

    for kind in ("khutba", "dars", "conference", "tarawih"):
        assert studio_plan.silence_s(kind) >= 3 * studio_api.HEARTBEAT_S
