"""Encoder start-up and end screen: no ffmpeg before the relay publishes the input; no relaunch on the end screen."""

import time

from sada import source
from sada.config import Config
from sada.encoder import SOURCE_WAIT_MAX_S, STUCK_GRACE_S, Encoder


class FakeProc:
    def __init__(self):
        self.killed = False
        self.returncode = -9

    def poll(self):
        return -9 if self.killed else None

    def kill(self):
        self.killed = True


def _enc(tmp_path, ready):
    enc = Encoder(Config(), tmp_path, log=lambda _m: None)
    enc.source_ready = ready
    spawned = []
    enc._spawn = lambda: spawned.append(time.monotonic())  # no real ffmpeg
    enc._spawn_preview = lambda: None
    enc._watch = lambda: None
    return enc, spawned


# --- F1: wait for the relay path instead of failing eight times


def test_start_waits_for_the_published_input(tmp_path):
    answers = [False]
    enc, spawned = _enc(tmp_path, lambda: answers[0])
    enc.start()
    assert spawned == [] and enc.wanted
    enc._tick()
    assert spawned == []  # still not published: no ffmpeg, no failure counted
    assert enc.failures == 0
    answers[0] = True
    enc._tick()
    assert len(spawned) == 1


def test_start_launches_at_once_when_the_input_is_ready_or_unknown(tmp_path):
    for answer in (True, None):
        enc, spawned = _enc(tmp_path, lambda a=answer: a)
        enc.start()
        assert len(spawned) == 1


def test_a_probe_that_fails_never_blocks_the_live(tmp_path):
    def boom():
        raise RuntimeError("relay API down")

    enc, spawned = _enc(tmp_path, boom)
    enc.start()
    assert len(spawned) == 1


def test_the_wait_is_bounded(tmp_path):
    enc, spawned = _enc(tmp_path, lambda: False)
    enc.start()
    assert spawned == []
    enc._waiting_since = time.monotonic() - SOURCE_WAIT_MAX_S - 1
    enc._tick()
    assert len(spawned) == 1


def test_no_probe_no_wait(tmp_path):
    enc, spawned = _enc(tmp_path, None)
    enc.start()
    assert len(spawned) == 1


def test_relay_ready_reads_the_relay_api(monkeypatch):
    from sada.backoffice import live_watch

    seen = []

    def info(path, timeout=1.0):
        seen.append(path)
        return {"ready": False, "type": "", "id": ""}

    monkeypatch.setattr(live_watch, "publisher_info", info)
    assert source.relay_ready("rtsp://127.0.0.1:8554/mosque-1") is False
    assert seen == ["mosque-1"]
    monkeypatch.setattr(live_watch, "publisher_info", lambda p, timeout=1.0: {"ready": True, "type": "", "id": ""})
    assert source.relay_ready("rtsp://localhost:8554/mosque-1") is True
    monkeypatch.setattr(live_watch, "publisher_info", lambda p, timeout=1.0: None)
    assert source.relay_ready("rtsp://127.0.0.1:8554/mosque-1") is None  # API unreachable: unknown


def test_relay_ready_ignores_other_inputs():
    assert source.relay_ready("rtsp://192.168.1.20:554/stream") is None  # a real camera
    assert source.relay_ready("rtmp://127.0.0.1:1935/live") is None
    assert source.relay_ready("") is None


# --- F3: nothing relaunches the encoder on the end screen


def test_end_screen_never_forces_a_restart(tmp_path):
    enc = Encoder(Config(), tmp_path, log=lambda _m: None)
    enc.proc, enc.wanted = FakeProc(), True
    enc._spawned_at = time.monotonic() - STUCK_GRACE_S - 1
    enc.hold = True
    assert enc.restart_if_stuck("transition") is False
    assert not enc.proc.killed
    enc.hold = False
    assert enc.restart_if_stuck("transition") is True


def test_end_screen_does_not_relaunch_a_dropped_destination(tmp_path):
    enc = Encoder(Config(), tmp_path, log=lambda _m: None)
    enc.proc, enc.wanted = FakeProc(), True
    enc._spawned_at = time.monotonic() - STUCK_GRACE_S - 1
    enc._dropped, enc.hold = True, True
    enc._tick()
    assert not enc.proc.killed


def test_end_screen_does_not_respawn_a_dead_encoder(tmp_path):
    enc, spawned = _enc(tmp_path, None)
    enc.wanted, enc.hold = True, True
    enc._tick()
    assert spawned == []
