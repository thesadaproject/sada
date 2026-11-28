"""A full disk never cuts the live: the recording may fail alone, the mosque is warned once, new recordings stop."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_setup_mode import make

from sada import diskwatch
from sada import encoder as enc_mod
from sada.config import Config
from sada.encoder import Encoder

GB = 1e9


class Disk:
    def __init__(self, free_gb):
        self.free_gb = free_gb
        self.fail = False

    def __call__(self, path):
        if self.fail:
            raise OSError("gone")
        return SimpleNamespace(free=int(self.free_gb * GB))


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def watch(free_gb, **cfg):
    c = Config(video_bitrate="2500k", record_clean=cfg.get("clean", True))
    disk, clock, sent, logs = Disk(free_gb), Clock(), [], []
    return diskwatch.DiskWatch(c, sent.append, logs.append, usage=disk, clock=clock), disk, clock, sent, logs


def look(w, clock, disk, free_gb):
    disk.free_gb = free_gb
    clock.t += diskwatch.EVERY_S + 1
    return w.poll()


def test_thresholds_follow_the_configured_bit_rate():
    low, critical = diskwatch.thresholds(Config(video_bitrate="2500k", record_clean=True))
    per_s = (2500 + 128) * 1000 / 8 * 2  # programme + clean copy
    assert low == pytest.approx(per_s * 3 * 3600 * 2) and critical == pytest.approx(per_s * 3600)
    assert low / GB == pytest.approx(14.2, abs=0.1) and critical / GB == pytest.approx(2.4, abs=0.1)
    one, _c = diskwatch.thresholds(Config(video_bitrate="6000k", record_clean=False))
    assert one / GB == pytest.approx((6128 * 125) * 21600 / GB, abs=0.01)  # a bigger picture asks for more room


def test_one_alert_per_episode_not_one_per_look():
    w, disk, clock, sent, logs = watch(100)
    assert w.poll() == diskwatch.OK and sent == []
    assert look(w, clock, disk, 10) == diskwatch.LOW and len(sent) == 1 and "running low" in sent[0]
    for gb in (9, 8, 7, 9):
        assert look(w, clock, disk, gb) == diskwatch.LOW
    assert len(sent) == 1  # still the same episode: no spam
    assert w.status() == {"level": "low", "free_gb": 9.0, "low_gb": 14.2, "critical_gb": 2.4}


def test_critical_is_announced_once_more_and_stops_new_recordings():
    w, disk, clock, sent, _ = watch(10)
    w.poll()
    assert look(w, clock, disk, 1.0) == diskwatch.CRITICAL and w.critical
    assert len(sent) == 2 and "critical" in sent[1]  # the low alert, then the critical one
    look(w, clock, disk, 0.5)
    assert len(sent) == 2


def test_the_episode_ends_only_once_the_space_is_clearly_back_then_a_new_one_speaks_again():
    w, disk, clock, sent, logs = watch(10)
    w.poll()
    low_gb = w.status()["low_gb"]
    assert look(w, clock, disk, low_gb + 0.5) == diskwatch.LOW  # barely above the threshold: still the episode
    assert look(w, clock, disk, low_gb * 1.2) == diskwatch.OK
    assert any("back to normal" in m for m in logs) and len(sent) == 1  # recovery is logged, not announced
    assert look(w, clock, disk, 5) == diskwatch.LOW and len(sent) == 2  # a new episode


def test_the_probe_is_throttled_and_a_failing_probe_claims_nothing():
    w, disk, clock, sent, _ = watch(100)
    w.poll()
    disk.free_gb = 1
    assert w.poll() == diskwatch.OK  # too soon: not looked at again
    clock.t += diskwatch.EVERY_S + 1
    disk.fail = True
    assert w.poll() == diskwatch.OK and w.free == 100 * GB  # no answer: the last known state stays
    assert sent == []


def test_an_alert_that_cannot_be_sent_never_raises():
    c = Config()
    w = diskwatch.DiskWatch(c, lambda t: 1 / 0, lambda m: None, usage=Disk(1), clock=Clock())
    assert w.poll(force=True) == diskwatch.CRITICAL


def test_the_folder_may_not_exist_yet(tmp_path):
    c = Config()
    c.record_dir = str(tmp_path / "not" / "yet")
    w = diskwatch.DiskWatch(c)
    assert w.poll(force=True) in (diskwatch.OK, diskwatch.LOW, diskwatch.CRITICAL) and w.free is not None


# ------------------------------------------------------------------ the encoder


class FakeProc:
    def __init__(self, cmd=None):
        self.cmd, self.returncode = cmd, None
        self.stdout = iter(())
        self.stderr = iter(())

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def enc(tmp_path, monkeypatch):
    launched = []
    monkeypatch.setattr(
        enc_mod.subprocess, "Popen", lambda cmd, *a, **k: launched.append(FakeProc(cmd)) or launched[-1]
    )
    cfg = Config(rtmp_urls=["rtmp://yt/live/k", "rtmp://fb/live/k"], preview_url="rtmp://r/live/x-prog")
    cfg.record_dir = str(tmp_path / "rec")
    e = Encoder(cfg, tmp_path, log=lambda m: None)
    e.launched = launched
    return e


def test_the_recording_may_fail_on_its_own_like_a_destination(enc):
    rec = "/rec/live.mkv"
    tee = enc.ffmpeg_cmd(rec, None)[-1]
    parts = tee.split("|")
    assert parts[-1] == f"[f=matroska:onfail=ignore]{rec}"  # last, and not fatal
    assert len(parts) == 4 and enc._rec_slave == 3  # two destinations, the monitoring copy, then the recording


def test_a_failed_recording_does_not_relaunch_the_encoder_but_a_failed_destination_does(enc, tmp_path):
    enc.ffmpeg_cmd("/rec/live.mkv", None)
    proc = enc.proc = FakeProc()
    proc.stderr = iter(["[tee @ 0x1] Slave muxer #3 failed: No space left on device, continuing with 3/4 slaves.\n"])
    with open(tmp_path / "encoder.log", "ab") as f:
        enc._read_errors(proc, f)
    assert enc.recording_failed and not enc._dropped  # the destinations were not touched
    proc.stderr = iter(["[tee @ 0x1] Slave muxer #1 failed: Broken pipe, continuing with 3/4 slaves.\n"])
    with open(tmp_path / "encoder.log", "ab") as f:
        enc._read_errors(proc, f)
    assert enc._dropped  # a destination: reconnected by the usual relaunch


def test_with_the_disk_critical_the_live_is_launched_without_any_recording(enc):
    enc.disk_critical = True
    enc.wanted = True
    enc._spawn()
    cmd = enc.launched[-1].cmd
    assert "-f" in cmd and cmd[-1].count("rtmp://") == 2  # both destinations are fed
    assert "matroska" not in " ".join(cmd) and not any("_clean" in c for c in cmd)
    assert enc.recordings == [(None, None)] and enc.current_recording() is None
    enc.disk_critical = False
    enc.proc.returncode = None
    enc.stop()
    enc.wanted = True
    enc._spawn()  # the space is back: recordings are opened again
    assert enc.recordings[-1][0] and enc.recordings[-1][0].endswith(".mkv")


def test_a_session_on_air_without_a_recording_points_at_no_file(enc):
    import datetime as dt

    from sada.state import Machine, MachineParams, Signals

    enc.disk_critical, enc.wanted = True, True
    enc._spawn()
    day = dt.datetime(2026, 11, 20)
    m = Machine([day.replace(hour=13)], MachineParams(), extras=[{}], pos_fn=enc.position)
    m.start_adhoc(Signals(now=day.replace(hour=12), t=1.0, voice_run=0.0, silence_run=0.0), "khutba", "x")
    r = m.records[-1]
    assert r.recording == 0 and enc.recordings[r.recording] == (None, None)  # the pipeline finds no file: it skips


# ------------------------------------------------------------------ the orchestrator


def test_the_orchestrator_feeds_the_encoder_and_the_status_from_the_probe(monkeypatch):
    o = make(monkeypatch)
    sent = []
    w, disk, clock, _s, _l = watch(100)
    w.notify = sent.append
    o.diskwatch = w
    o._signal_lost = False
    o.manual("start")
    assert o.encoder.disk_critical is False and o.status()["disk"]["level"] == "ok"
    look(w, clock, disk, 1.0)
    o._sync()
    assert o.encoder.disk_critical is True and o.status()["disk"]["level"] == "critical"
    assert o.machine.stream_on and o.encoder.wanted  # the live is not touched
    assert len(sent) == 1  # straight to critical: one message, not two
    from sada.backoffice import live

    assert live.summarize(o.status())["disk"]["level"] == "critical"
