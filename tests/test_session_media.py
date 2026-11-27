"""A session on air across several recordings (signal lost then back, encoder relaunched) is read as ONE recording."""

from __future__ import annotations

import datetime as dt
import shutil
import subprocess

import pytest

from sada import runs, session_media
from sada.state import Machine, MachineParams, Signals

DAY = dt.datetime(2026, 11, 20)
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg needed")


def sig(mm: int, t: float = 0.0) -> Signals:
    return Signals(now=DAY.replace(hour=12, minute=mm), t=t, voice_run=0.0, silence_run=0.0)


def _clip(path, seconds: float, freq: int) -> str:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=160x90:rate=10:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", "-c:v", "libx264", "-g", "10",
         "-c:a", "aac", str(path)],
        check=True,
    )  # fmt: skip
    return str(path)


def _duration(path: str) -> float:
    return session_media._duration(path) or 0.0


def _run(tmp_path, spans: bool = True):
    recs = [_clip(tmp_path / "a.mkv", 4, 440), _clip(tmp_path / "b.mkv", 3, 660)]
    cleans = [_clip(tmp_path / "a_clean.mkv", 4, 440), _clip(tmp_path / "b_clean.mkv", 3, 660)]
    s = {"index": 0, "planned": "12:00", "status": "done", "recording": 0, "start_pos": 1.0, "end_pos": None}
    if spans:
        s.update(end_recording=1, end_file_pos=2.0)
    return {"run_id": "20261120_120000", "recordings": recs, "recordings_clean": cleans, "sessions": [s]}, s


# ------------------------------------------------------------------ the machine records the range


def test_a_session_closed_in_another_recording_records_where_it_ends():
    where = {"v": (0, 5.0)}
    m = Machine([DAY.replace(hour=13)], MachineParams(), extras=[{}], pos_fn=lambda: where["v"])
    m.start_adhoc(sig(0), "khutba", "A")
    where["v"] = (2, 30.0)  # encoder relaunched twice meanwhile
    m.end_adhoc(sig(30))
    m.tick(sig(31, t=5000.0))
    r = m.records[-1]
    assert (r.recording, r.start_pos) == (0, 5.0)
    assert r.end_pos is None  # legacy view: "first file to its end"
    assert (r.end_recording, r.end_file_pos) == (2, 30.0)


def test_a_session_closed_in_its_own_recording_is_unchanged():
    where = {"v": (0, 5.0)}
    m = Machine([DAY.replace(hour=13)], MachineParams(), extras=[{}], pos_fn=lambda: where["v"])
    m.start_adhoc(sig(0), "khutba", "A")
    where["v"] = (0, 90.0)
    m.end_adhoc(sig(30))
    m.tick(sig(31, t=5000.0))
    r = m.records[-1]
    assert (r.end_pos, r.end_recording, r.end_file_pos) == (90.0, 0, 90.0)


# ------------------------------------------------------------------ which recordings a session spans


def test_the_range_of_recordings():
    data = {"recordings": ["a", "b", "c"]}
    assert session_media.indexes(data, {"recording": 0, "end_recording": 2}) == [0, 1, 2]
    assert session_media.indexes(data, {"recording": 1, "end_recording": 1}) == [1]
    assert session_media.indexes(data, {"recording": 1}) == [1]  # a run recorded before the range existed
    assert session_media.indexes(data, {}) == [2]  # older still: the last recording
    assert session_media.indexes(data, {"recording": 0, "end_recording": 3}) == [0]  # past the list: not trusted
    assert session_media.indexes(data, {"recording": 2, "end_recording": 1}) == [2]
    assert session_media.indexes({"recordings": []}, {"recording": 0}) == []


def test_an_old_session_is_read_as_before(tmp_path):
    data = {"recordings": ["a.mkv", "b.mkv"], "recordings_clean": ["a_c.mkv", "b_c.mkv"]}
    s = {"recording": 0, "start_pos": 3.0, "end_pos": 40.0}
    assert session_media.session_media(data, s, tmp_path, build=True) == session_media.Media(
        "a.mkv", "a_c.mkv", 3.0, 40.0
    )
    assert not list(tmp_path.iterdir())  # nothing assembled, nothing written


# ------------------------------------------------------------------ the assembly


@needs_ffmpeg
def test_a_session_on_two_recordings_is_assembled_into_one(tmp_path):
    data, s = _run(tmp_path)
    out = tmp_path / "session1"
    media = session_media.session_media(data, s, out, build=True)
    assert media.live == str(out / session_media.LIVE_ALL) and media.clean == str(out / session_media.CLEAN_ALL)
    assert media.start == 1.0  # the session still starts where it started in the first file
    first = _duration(data["recordings"][0])
    assert media.end == pytest.approx(first + 2.0, abs=0.01)  # the end is in the second file, 2 s in: no gap in between
    total = _duration(media.live)
    assert total == pytest.approx(first + _duration(data["recordings"][1]), abs=0.3)  # whole files, joined
    assert _duration(media.clean) == pytest.approx(total, abs=0.3)  # the clean one the same way: still aligned
    assert (out / session_media.SIDECAR).exists()
    again = session_media.session_media(data, s, out, build=False)  # the back office reads what was left
    assert again == media


@needs_ffmpeg
def test_the_back_office_does_not_assemble(tmp_path):
    data, s = _run(tmp_path)
    media = session_media.session_media(data, s, tmp_path / "session1", build=False)
    assert media.live == data["recordings"][0] and not (tmp_path / "session1").exists()  # first recording, as before


@needs_ffmpeg
def test_a_missing_clean_file_only_loses_the_clean_video(tmp_path):
    data, s = _run(tmp_path)
    (tmp_path / "b_clean.mkv").unlink()
    media = session_media.session_media(data, s, tmp_path / "s", build=True)
    assert media.live.endswith(session_media.LIVE_ALL) and media.clean is None


@needs_ffmpeg
def test_an_assembly_that_cannot_be_done_falls_back_to_the_first_recording(tmp_path):
    data, s = _run(tmp_path)
    (tmp_path / "b.mkv").unlink()  # a recording of the range is gone
    media = session_media.session_media(data, s, tmp_path / "s", build=True)
    assert media.live == data["recordings"][0] and media.end is None


@needs_ffmpeg
def test_a_session_ended_in_the_last_recording_to_its_end(tmp_path):
    data, s = _run(tmp_path)
    s["end_file_pos"] = None
    media = session_media.session_media(data, s, tmp_path / "s", build=True)
    assert media.end is None and media.start == 1.0


def test_the_pipeline_and_the_importer_read_the_media_through_it():
    import inspect

    from sada.backoffice import importer
    from sada.pipeline import run

    assert "session_media(" in inspect.getsource(run) and "session_media(" in inspect.getsource(importer)
    assert runs.sources  # the plain lookup is still there for what needs only the files


def test_the_back_office_imports_a_session_on_several_recordings_as_the_pipeline_read_it(env):
    import json
    from pathlib import Path

    from conftest import make_run, one

    from sada.backoffice import db, importer, models

    mosque = one(env["conn"], models.Mosque, id=env["mid"])
    dirs = db.mosque_dirs(mosque)
    root, run = Path(dirs["output"]).parent, "20261107_100000"
    make_run(root, run)
    assembled = root / "assembled.mkv"
    assembled.write_bytes(b"x")
    sdir = root / "output" / run / "session1"
    sessions = {
        "run_id": run,
        "recordings": ["/r/a.mkv", "/r/b.mkv"],
        "recordings_clean": [],
        "sessions": [
            {"index": 0, "planned": "13:30", "status": "done", "recording": 0, "start_pos": 100.0, "end_pos": None,
             "end_recording": 1, "end_file_pos": 20.0}
        ],
    }  # fmt: skip
    (root / "state" / run / "sessions.json").write_text(json.dumps(sessions))
    (sdir / session_media.SIDECAR).write_text(
        json.dumps({"live": str(assembled), "clean": None, "start": 100.0, "end": 520.0})
    )
    importer.import_run(env["conn"], mosque, run, extract_video=False, log=lambda *a: None)
    k = one(env["conn"], models.Khutba, run_id=run)
    assert (k["recording"], k["start_pos"], k["end_pos"], k["duration_s"]) == (str(assembled), 100.0, 520.0, 420.0)
