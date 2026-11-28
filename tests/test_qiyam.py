"""Qiyam / tahajjud at a fixed hour: planned after midnight on the night of the evening before, broadcast like a
tarawih (no transcript, no clips), imported as the right night, and given to the Studio as a slot."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from conftest import client, one
from test_tarawih_replay import _mosque

from sada import events, runs
from sada.backoffice import events_store, importer, models, studio_plan, tarawih
from sada.state import Machine, MachineParams, Signals, State

PARIS = ZoneInfo("Europe/Paris")
RAW = {
    "uid": "qiyam", "kind": "tarawih", "title": "Qiyam", "mode": "audio", "time": "02:30",
    "period": {"from": "2027-03-01", "until": "2027-03-09"}, "night_origin": "2027-02-08", "reciters": ["Imam A"],
}  # fmt: skip


def _machine(day: dt.date):
    inst = events.instances_on([events.parse(RAW)], day, {})
    assert len(inst) == 1
    return Machine([inst[0].starts], MachineParams(), extras=[inst[0].as_event()]), inst[0]


def test_the_machine_waits_for_the_fixed_hour_then_broadcasts_on_the_voice():
    m, inst = _machine(dt.date(2027, 3, 2))
    rec = m.records[0]
    assert (rec.kind, rec.title, rec.night, rec.night_date) == ("tarawih", "Qiyam", 22, "2027-03-01")
    sig = lambda h, mi, t, v=0.0: Signals(dt.datetime(2027, 3, 2, h, mi), t, v, 0.0)  # noqa: E731
    m.tick(sig(2, 0, 1.0, 60.0))
    assert m.state == State.IDLE  # voice in the room at 02:00: nothing before the hour
    m.tick(sig(2, 30, 2.0))
    assert m.state == State.ARMED
    m.tick(sig(2, 31, 3.0, 60.0))
    assert m.state == State.TARAWIH and m.scene == "tarawih"  # no offset, no waiting for an after-isha time
    assert m.live.kind == "tarawih" and not runs.produces_content({"kind": m.live.kind, "status": "live"})  # no clips


def _night(env, tmp_path):
    root = Path(env["root"])
    rec = root / "rec.mkv"
    rec.write_bytes(b"\0" * 64)
    run = "20270302_000100"  # the run opened at the midnight roll: dated the 2nd
    state = root / "state" / run
    state.mkdir(parents=True, exist_ok=True)
    s = {
        "index": 0, "kind": "tarawih", "title": "Qiyam", "status": "done", "mode": "audio", "night": 22,
        "night_date": "2027-03-01", "reciters": ["Imam A"], "reciter_marks": [], "start_pos": 10.0, "end_pos": 4000.0,
        "start_clock": "02:31:00", "end_clock": "03:37:00", "recording": 0,
    }  # fmt: skip
    (state / runs.SESSIONS).write_text(json.dumps({"sessions": [s], "recordings": [str(rec)]}))
    return run


def test_a_qiyam_is_imported_as_the_night_that_began_the_evening_before(env, tmp_path):
    run = _night(env, tmp_path)
    assert importer.import_tarawih(env["conn"], _mosque(env), run, extract_video=False, log=lambda *a: None) == 1
    k = one(env["conn"], models.Khutba, run_id=run)
    assert k["date"] == "2027-03-01"  # not the 2nd, the day of the run
    assert k["kind"] == "tarawih" and k["title"] == "Qiyam" and k["label"] == "Qiyam · night 22"
    assert one(env["conn"], models.Clip, khutba_id=k["id"]) is None and k["session_no"] == 22


def test_a_tarawih_without_a_night_date_keeps_the_date_of_its_run(env, tmp_path):
    run = _night(env, tmp_path)
    p = Path(env["root"]) / "state" / run / runs.SESSIONS
    data = json.loads(p.read_text())
    data["sessions"][0].pop("night_date")
    data["sessions"][0]["title"] = "Tarawih"  # a night recorded before the qiyam existed
    p.write_text(json.dumps(data))
    importer.import_tarawih(env["conn"], _mosque(env), run, extract_video=False, log=lambda *a: None)
    k = one(env["conn"], models.Khutba, run_id=run)
    assert k["date"] == "2027-03-02" and k["label"] == "Tarawih · night 22"


def test_the_studio_gets_a_slot_for_the_qiyam_and_for_the_nightly_tarawih(env):
    c = client(env, "admin")
    form = {"mode": "audio", "start": "2027-02-08", "end": "2027-03-09", "offset_min": "20",
            "qiyam_time": "02:30", "qiyam_start": "2027-03-01", "qiyam_end": "2027-03-09"}  # fmt: skip
    assert c.ecrire("/settings/tarawih", form, methode="PUT").status_code == 200
    events_store.write(env["conn"], env["mid"], [])
    mosque = one(env["conn"], models.Mosque, id=env["mid"])
    day = dt.date(2027, 3, 2)
    ctx = studio_plan.SlotContext(
        env["conn"], mosque, PARIS, studio_plan.settings(env["conn"], env["mid"]), day,
        {day: ({"isha": "19:45", "isha_iqama": "20:00"}, [])},
    )  # fmt: skip
    slots = studio_plan.ProgrammeSource().slots_on(day, ctx)
    got = {(s.uid, s.kind, s.title): s.starts.astimezone(PARIS).strftime("%H:%M") for s in slots}
    # the nightly tarawih: from the end of isha, where the device goes live; the qiyam: its fixed hour
    assert got == {("tarawih", "tarawih", "Tarawih"): "20:10", ("qiyam", "tarawih", "Qiyam"): "02:30"}
    assert tarawih.qiyam_event(env["conn"], env["mid"])["night_origin"] == "2027-02-08"
