"""A tarawih night on several recordings (signal lost then back, encoder relaunched) is imported whole."""

from __future__ import annotations

import datetime as dt
import io
import json
import shutil
from pathlib import Path

import pytest
from conftest import one
from PIL import Image
from test_session_media import _clip, _duration

from sada import runs, session_media
from sada.backoffice import importer, models
from sada.state import Machine, MachineParams, Signals

RUN = "20270221_190000"
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg needed")


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (160, 90), (20, 40, 30)).save(buf, "PNG")
    return buf.getvalue()


def _night(env, tmp_path, mode="audio", spans=True, marks=None):
    root = Path(env["root"])
    recs = [_clip(tmp_path / "a.mkv", 4, 440), _clip(tmp_path / "b.mkv", 3, 660)]
    state = root / "state" / RUN
    state.mkdir(parents=True, exist_ok=True)
    s = {
        "index": 0, "kind": "tarawih", "title": "Tarawih", "status": "done", "mode": mode, "night": 14,
        "reciters": ["Imam A", "Imam B", "Imam C"], "reciter_marks": marks or [],
        "start_pos": 1.0, "end_pos": None, "start_clock": "20:10:00", "end_clock": "20:10:07", "recording": 0,
    }  # fmt: skip
    if spans:
        s.update(end_recording=1, end_file_pos=2.0)
    data = {"run_id": RUN, "sessions": [s], "recordings": recs, "recordings_clean": []}
    (state / runs.SESSIONS).write_text(json.dumps(data))
    return data, recs


def _mosque(env):
    return dict(one(env["conn"], models.Mosque, id=env["mid"]))


def _import(env, **kw):
    return importer.import_tarawih(env["conn"], _mosque(env), RUN, log=lambda *a: None, slate=_png(), **kw)


# the recorded marks: one in the first file, one in the second (after the signal came back), one more in the second
MARKS = [
    {"at": 0.0, "name": "Imam A"},
    {"at": None, "name": "Imam B", "recording": 1, "pos": 0.5},
    {"at": None, "name": "Imam C", "recording": 1, "pos": 1.5},
]


@needs_ffmpeg
def test_a_night_on_two_recordings_is_imported_whole_with_its_chapters(env, tmp_path):
    data, recs = _night(env, tmp_path, marks=MARKS)
    assert _import(env) == 1
    k = one(env["conn"], models.Khutba, run_id=RUN)
    first = _duration(recs[0])
    assert k["recording"].endswith(session_media.LIVE_ALL) and k["start_pos"] == 1.0
    assert k["end_pos"] == pytest.approx(first + 2.0, abs=0.01)
    assert k["duration_s"] == pytest.approx(first + 1.0, abs=0.01)  # from 1 s in the first file to 2 s in the second
    segs = json.loads(k["chapters"])["segments"]
    # the marks of the second file are on the assembled timeline: first file's duration + position, from the start
    assert [x["name"] for x in segs] == ["Imam A", "Imam B", "Imam C"]
    assert segs[1]["start"] == pytest.approx(first + 0.5 - 1.0, abs=0.06)  # marks are kept to 0.1 s
    assert segs[2]["start"] == pytest.approx(first + 1.5 - 1.0, abs=0.06)
    assert segs[2]["end"] == pytest.approx(k["duration_s"], abs=0.06)  # the last chapter runs to the end of the night
    assert segs[0]["end"] == segs[1]["start"]
    # the replay is the whole night over the slate, not the first file only
    assert _duration(k["video_path"]) == pytest.approx(k["duration_s"], abs=1.5)


@needs_ffmpeg
def test_the_assembly_is_done_once_and_not_at_each_look(env, tmp_path, monkeypatch):
    _night(env, tmp_path, marks=MARKS)
    calls = []
    real = session_media._concat
    monkeypatch.setattr(session_media, "_concat", lambda paths, dest: calls.append(dest.name) or real(paths, dest))
    assert _import(env) == 1
    assert calls == [session_media.LIVE_ALL]  # the live recording only: a tarawih has no clips, no clean copy to join
    k = one(env["conn"], models.Khutba, run_id=RUN)
    mtime = Path(k["video_path"]).stat().st_mtime_ns
    for _ in range(3):
        assert _import(env) == 0
    assert calls == [session_media.LIVE_ALL]
    assert Path(k["video_path"]).stat().st_mtime_ns == mtime  # the replay is not made again either


@needs_ffmpeg
def test_a_failed_assembly_is_not_retried_at_every_look(env, tmp_path, monkeypatch):
    _night(env, tmp_path)
    calls = []
    monkeypatch.setattr(session_media, "_concat", lambda paths, dest: calls.append(1) and False)
    assert _import(env) == 1
    k = one(env["conn"], models.Khutba, run_id=RUN)
    assert k["recording"].endswith("a.mkv")  # the first recording, as before
    for _ in range(3):
        _import(env)
    assert len(calls) == 1  # the failure is remembered (media.failed), not redone at each scan
    sdir = Path(k["output_dir"])
    assert (sdir / session_media.FAILED).exists()


@needs_ffmpeg
def test_a_night_imported_cut_at_the_first_recording_is_completed(env, tmp_path):
    data, recs = _night(env, tmp_path, spans=False)  # how it was recorded and imported before the range existed
    assert _import(env) == 1
    k = one(env["conn"], models.Khutba, run_id=RUN)
    assert k["recording"] == recs[0] and k["end_pos"] is None
    old_video = k["video_path"]
    # the same night, now known to span two recordings (e.g. the sessions file was completed): the entry is repaired
    data["sessions"][0].update(end_recording=1, end_file_pos=2.0, reciter_marks=MARKS)
    (Path(env["root"]) / "state" / RUN / runs.SESSIONS).write_text(json.dumps(data))
    assert _import(env) == 0  # not a new entry
    k = one(env["conn"], models.Khutba, run_id=RUN)
    assert k["recording"].endswith(session_media.LIVE_ALL) and k["end_pos"] is not None
    assert [x["name"] for x in json.loads(k["chapters"])["segments"]] == ["Imam A", "Imam B", "Imam C"]
    assert (
        Path(k["video_path"]).exists()
        and _duration(k["video_path"]) > _duration(old_video if Path(old_video).exists() else recs[0]) - 0.1
    )


@needs_ffmpeg
def test_a_video_night_on_two_recordings_is_extracted_whole(env, tmp_path):
    _night(env, tmp_path, mode="video")
    assert _import(env) == 1
    k = one(env["conn"], models.Khutba, run_id=RUN)
    assert _duration(k["video_path"]) == pytest.approx(k["duration_s"], abs=1.5)


def test_a_night_on_one_recording_is_unchanged(env, tmp_path):
    root = Path(env["root"])
    rec = root / "rec.mkv"
    rec.write_bytes(b"\0" * 64)
    state = root / "state" / RUN
    state.mkdir(parents=True, exist_ok=True)
    s = {"index": 0, "kind": "tarawih", "status": "done", "mode": "audio", "night": 3, "reciters": ["A"],
         "reciter_marks": [{"at": 0.0, "name": "A"}, {"at": 600.0, "name": "A"}], "start_pos": 100.0, "end_pos": 4100.0,
         "recording": 0}  # fmt: skip
    (state / runs.SESSIONS).write_text(json.dumps({"sessions": [s], "recordings": [str(rec)]}))
    assert _import(env, extract_video=False) == 1
    k = one(env["conn"], models.Khutba, run_id=RUN)
    assert (k["recording"], k["start_pos"], k["end_pos"], k["duration_s"]) == (str(rec), 100.0, 4100.0, 4000.0)
    assert [x["start"] for x in json.loads(k["chapters"])["segments"]] == [0.0, 600.0]


def test_a_mark_that_cannot_be_placed_is_left_out_not_guessed():
    s = {"recording": 0, "start_pos": 1.0, "end_pos": None, "reciter_marks": MARKS}
    chapters = importer.reciter_chapters(s)  # not assembled: only what was in the first file is known
    assert [x["name"] for x in chapters["segments"]] == ["Imam A"]


# ------------------------------------------------------------------ the machine


def test_a_mark_made_in_a_later_recording_keeps_its_raw_position():
    day = dt.datetime(2027, 2, 21)
    where = {"v": (0, 100.0)}
    plan = [(day.replace(hour=20), {"kind": "tarawih", "reciters": ["A", "B"], "mode": "audio"})]
    m = Machine([p[0] for p in plan], MachineParams(), extras=[p[1] for p in plan], pos_fn=lambda: where["v"])
    sig = Signals(now=day.replace(hour=20, minute=10), t=10.0, voice_run=60.0, silence_run=0.0)
    m.command("tarawih", sig)
    where["v"] = (0, 160.0)
    m.command("next_reciter", sig)
    where["v"] = (2, 30.55)
    m.command("next_reciter", sig)
    assert m.live.reciter_marks == [
        {"at": 60.0, "name": "A"},
        {"at": None, "name": "B", "recording": 2, "pos": 30.6},
    ]
