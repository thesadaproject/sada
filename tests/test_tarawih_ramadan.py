"""Ramadan: what a month of long tarawih nights asks of the engine."""

from __future__ import annotations

import datetime as dt

from test_setup_mode import make

from sada import setup_mode
from sada.config import Config
from sada.encoder import Encoder
from sada.state import Machine, MachineParams, State

DAY = dt.datetime(2026, 11, 20)


def test_a_tarawih_night_is_recorded_without_a_clean_copy(tmp_path):
    """No clip is ever cut from a tarawih: the clean copy would only double the disk of a night of hours."""
    cfg = Config()
    cfg.record_dir = str(tmp_path)
    enc = Encoder(cfg, tmp_path, log=lambda _m: None)
    rec, clean = enc.new_recording()
    assert clean and clean.endswith("_clean.mkv")  # the usual live
    enc.clean_wanted = False
    rec, clean = enc.new_recording()
    assert clean is None and rec.endswith(".mkv")
    cmd = enc.ffmpeg_cmd(rec, None)
    assert sum("[f=matroska]" in c for c in cmd) == 1 and not any("_clean" in c for c in cmd)  # the live one only


def _tarawih_orchestrator(monkeypatch, kind):
    o = make(monkeypatch)
    extra = {"kind": "tarawih", "mode": "audio", "reciters": ["A", "B"]} if kind == "tarawih" else {}
    o.machine = Machine([dt.datetime(2026, 11, 20, 12, 0)], MachineParams(), extras=[extra])
    o.machine.custom_known = o._custom_scenes.__contains__
    o.live_stage = setup_mode.Stage(o.machine, o.encoder)
    o.encoder.clean_wanted = True
    return o


def test_the_orchestrator_asks_for_no_clean_copy_when_a_tarawih_goes_on_air(monkeypatch):
    o = _tarawih_orchestrator(monkeypatch, "tarawih")
    o.manual("tarawih")
    assert o.machine.state == State.TARAWIH and o.encoder.wanted
    assert o.encoder.clean_wanted is False


def test_any_other_session_keeps_its_clean_copy_for_the_clips(monkeypatch):
    o = _tarawih_orchestrator(monkeypatch, "khutba")
    o.manual("start")
    assert o.encoder.wanted and o.encoder.clean_wanted is True
