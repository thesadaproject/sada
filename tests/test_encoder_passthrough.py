"""The Sada Studio composes the picture: the encoder must lay nothing over its stream, whatever happened before.

A mosque template screen (`show_image`) is the shared background of the graph. When the Studio takes over
(`show` of a fully transparent scene) that background must be gone from the picture for good, also after an ffmpeg
restart, a change that overlaps the passthrough, or a graph that lost the state sent to it over ZeroMQ.
"""

import threading
import time

import zmq
from PIL import Image

from sada import encoder as enc_mod
from sada import transitions as tr
from sada.config import Config
from sada.encoder import Encoder, is_blank

W, H = 64, 36
TEMPLATE = Image.new("RGBA", (W, H), (0, 0, 255, 255))
BLANK = Image.new("RGBA", (W, H), (0, 0, 0, 0))


class FakeProc:
    returncode = None

    def poll(self):
        return None


def _enc(tmp_path, zmq_port=0, alive=False):
    cfg = Config(width=W, height=H, fps=10, zmq_port=zmq_port or 25000)
    e = Encoder(cfg, tmp_path, log=lambda _m: None)
    e.prepare(Image.new("RGBA", (W, H), (0, 0, 0, 255)))
    if alive:
        e.proc, e.wanted, e._opened = FakeProc(), True, True
        e._spawned_at = time.monotonic() - 60
    return e


def _alpha_max(path) -> int:
    return Image.open(path).convert("RGBA").getchannel("A").getextrema()[1]


def test_is_blank():
    assert is_blank(BLANK)
    assert not is_blank(TEMPLATE)


def test_passthrough_empties_the_layers_before_start(tmp_path):
    e = _enc(tmp_path)
    e.show_image("avant", True, TEMPLATE, "k1")
    assert _alpha_max(e.layer_png["fond"]) == 255 and e.levels["fond"] == 1.0
    e.show("studio:passthrough", False, BLANK)
    assert _alpha_max(e.layer_png["fond"]) == 0
    assert all(_alpha_max(e.layer_png[k]) == 0 for k in ("a", "b"))
    assert e.levels["fond"] == 0.0 and e.levels["a_a"] == 0.0 and e.levels["a_b"] == 0.0 and not e.full


def test_passthrough_after_a_restart_seeds_a_transparent_graph(tmp_path, monkeypatch):
    """Template on air, ffmpeg down (never opened its source), passthrough requested, ffmpeg relaunched."""
    monkeypatch.setattr(tr, "DELAI_CHARGEMENT", 0.05)
    e = _enc(tmp_path)
    e.wanted = True  # started; the process is not there (restart under way): no graph to drive
    e.show_image("avant", True, TEMPLATE, "k1")
    e.show("studio:passthrough", False, BLANK, transition="cut")
    deadline = time.monotonic() + 5
    while e.shown is None or e.shown[0] != "studio:passthrough" or e.levels["fond"] != 0.0:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    time.sleep(0.2)
    cmd = " ".join(e.ffmpeg_cmd(None, None))
    assert "colorchannelmixer@fond=aa=0," in cmd or "colorchannelmixer@fond=aa=0[" in cmd
    assert _alpha_max(e.layer_png["fond"]) == 0
    assert e.levels["a_a"] == 0.0 and e.levels["a_b"] == 0.0


def test_a_late_reveal_does_not_bring_the_template_back(tmp_path, monkeypatch):
    """show_image (reveal pending) then the passthrough: the reveal must not run over the passthrough's state."""
    monkeypatch.setattr(tr, "DELAI_CHARGEMENT", 0.3)
    e = _enc(tmp_path, alive=True)
    ran = []
    monkeypatch.setattr(e, "_animate", lambda p: ran.append(p) or 0)
    e.show_image("avant", True, TEMPLATE, "k1")  # alive: a reveal thread sleeps
    e.show("studio:passthrough", False, BLANK, transition="cut")  # takes over before it wakes
    deadline = time.monotonic() + 5
    while e._reveals > 0 or e._pending is not None:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    time.sleep(0.8)
    assert e.shown[0] == "studio:passthrough"
    assert e.levels["fond"] == 0.0 and e.full is False  # the reveal (fond -> 1) never ran
    assert all(p.fond_to == 0.0 for p in ran)  # only the passthrough's own transition played, never the reveal
    assert _alpha_max(e.layer_png["fond"]) == 0


def test_a_reveal_of_the_screen_still_on_air_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "DELAI_CHARGEMENT", 0.05)
    e = _enc(tmp_path, alive=True)
    ran = []
    monkeypatch.setattr(e, "_animate", lambda p: ran.append(p) or 0)
    e.show_image("avant", True, TEMPLATE, "k1")
    deadline = time.monotonic() + 5
    while e._reveals > 0:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert len(ran) == 1 and e.full is True


# --- reconcile: the graph is brought back to `levels` when it lost them


def _graph(port):
    """A stand-in for the graph's zmq filter: records every command and answers."""
    got: list[str] = []
    ctx = zmq.Context.instance()
    rep = ctx.socket(zmq.REP)
    rep.setsockopt(zmq.LINGER, 0)
    rep.bind(f"tcp://127.0.0.1:{port}")
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            if rep.poll(100):
                got.append(rep.recv_string())
                rep.send_string("0 Success")
        rep.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return got, lambda: (stop.set(), t.join())


def _free_port():
    s = zmq.Context.instance().socket(zmq.REP)
    port = s.bind_to_random_port("tcp://127.0.0.1", min_port=26000, max_port=29000)
    s.close()
    return port


def test_reconcile_reasserts_every_level(tmp_path):
    port = _free_port()
    e = _enc(tmp_path, zmq_port=port - 1, alive=True)
    assert e.zmq_vports[0] == port
    got, stop = _graph(port)
    try:
        e.levels.update({"fond": 0.0, "a_a": 0.0, "a_b": 0.0})
        assert e.reconcile() is True
    finally:
        stop()
    assert "colorchannelmixer@fond aa 0" in got
    assert "colorchannelmixer@ca aa 0" in got and "colorchannelmixer@cb aa 0" in got
    assert len(got) == len(e.levels)


def test_reconcile_waits_while_a_change_is_under_way(tmp_path):
    port = _free_port()
    e = _enc(tmp_path, zmq_port=port - 1, alive=True)
    got, stop = _graph(port)
    try:
        e._reveals = 1
        assert e.reconcile() is False
        e._reveals, e._pending = 0, ("x", False, BLANK, "cut")
        assert e.reconcile() is False
        e._pending = None
        with e._anim:  # a transition is playing
            assert e.reconcile() is False
    finally:
        stop()
    assert got == []


def test_reconcile_gives_up_quietly_when_nothing_answers(tmp_path, monkeypatch):
    e = _enc(tmp_path, alive=True)
    monkeypatch.setattr(e, "_send_levels", lambda levels: False)
    assert e.reconcile() is False
    assert e.proc.poll() is None  # never kills ffmpeg: that is not what a failed re-assert means


def test_reconcile_ignores_a_graph_that_is_not_up(tmp_path):
    e = _enc(tmp_path)  # no process
    assert e.reconcile() is False
    assert enc_mod.RECONCILE_EVERY_S > 0
