"""A live ended after a signal loss is closed at the back office too, so the studio device goes back to standby."""

from __future__ import annotations

import time

import pytest
from conftest import client, one
from test_setup_mode import make
from test_studio_devices import (  # noqa: F401 — fixtures and helpers of the studio tests
    _setup,
    audits,
    dev,
    heartbeat,
    oneoff,
    pair,
    program,
    relay,
)

from sada import studio_link
from sada.backoffice import internal, models, studio_service
from sada.state import Signals

pytestmark = pytest.mark.usefixtures("relay")

END = "/api/v1/internal/studio-live/end"
LIVE = "/api/v1/internal/studio-live"


def internal_client(env):
    return client(env, headers={"X-Internal-Token": internal.local_token()})


# ------------------------------------------------------------------ the back office


def test_a_manual_live_ended_by_the_orchestrator_is_closed_and_the_device_goes_back_to_standby(env):
    bearer, _did = pair(env)
    d = dev(env, bearer)
    d.post("/api/v1/studio/live/start", json={"type": "khutba", "title": "Jumua"})
    assert heartbeat(d).json()["command"] == "live"
    assert internal_client(env).get(LIVE).json()["live"] is True
    r = internal_client(env).post(END, json={"lost_at": time.time()})
    assert r.status_code == 200 and r.json()["ended"] == ["manual"]
    assert internal_client(env).get(LIVE).json()["live"] is False  # the announcement reads `live: false`
    hb = heartbeat(d).json()
    assert hb["command"] == "standby"  # what the device sees at its next heartbeat: standby, so it stops publishing
    assert one(env["conn"], models.StudioRun, origin="manual")["ended_at"]
    (row,) = audits(env, "studio.direct.manuel.fin")
    assert "signal_perdu" in str(row)


def test_a_scheduled_slot_is_marked_stopped_so_that_it_does_not_restart(env):
    program(env, oneoff("d1", -1, "Tafsir"), oneoff("d2", 200, "Fiqh"))
    bearer, _did = pair(env)
    d = dev(env, bearer)
    assert heartbeat(d).json()["command"] == "live"
    r = internal_client(env).post(END, json={"lost_at": time.time()})
    assert r.json()["ended"] == ["slot"]
    for _ in range(3):
        hb = heartbeat(d).json()
        assert hb["command"] == "standby" and hb["reason_code"] == "slot_stopped"
    assert internal_client(env).get(LIVE).json()["live"] is False
    assert audits(env, "studio.creneau.arret")


def test_a_live_started_after_the_loss_is_left_alone(env):
    bearer, _did = pair(env)
    d = dev(env, bearer)
    lost_at = time.time() - 600
    d.post("/api/v1/studio/live/start", json={"type": "dars", "title": "Nouveau"})  # began after the loss
    r = internal_client(env).post(END, json={"lost_at": lost_at})
    assert r.json()["ended"] == []
    assert heartbeat(d).json()["command"] == "live"


def test_ending_twice_or_with_nothing_on_air_is_not_an_error(env):
    pair(env)
    for _ in range(2):
        r = internal_client(env).post(END, json={})
        assert r.status_code == 200 and r.json()["ended"] == []
    assert internal_client(env).post(END, content=b"not json").status_code == 200


def test_the_end_needs_the_internal_token(env):
    assert client(env).post(END, json={}).status_code == 403
    assert client(env, headers={"X-Internal-Token": "wrong"}).post(END, json={}).status_code == 403


def test_the_claim_of_the_device_is_released_with_the_live(env, monkeypatch):
    kicked = []
    from sada.backoffice import live_watch

    monkeypatch.setattr(live_watch, "kick", lambda path, timeout=2.0: kicked.append(path) or True)
    bearer, did = pair(env)
    d = dev(env, bearer)
    d.post("/api/v1/studio/live/start", json={"type": "khutba", "title": "J"})
    env["conn"].add(models.StudioClaim(mosque_id=env["mid"], source="device", device_id=did, since=time.time()))
    env["conn"].commit()
    internal_client(env).post(END, json={"lost_at": time.time()})
    assert kicked and not env["conn"].execute(models.StudioClaim.__table__.select()).fetchall()


def test_end_lost_is_a_plain_service_call(env):
    bearer, _did = pair(env)
    dev(env, bearer).post("/api/v1/studio/live/start", json={"type": "dars", "title": "x"})
    mosque = one(env["conn"], models.Mosque, id=env["mid"])
    assert studio_service.end_lost(env["conn"], mosque, time.time()) == {"ended": ["manual"]}
    assert studio_service.end_lost(env["conn"], mosque, time.time()) == {"ended": []}


# ------------------------------------------------------------------ the poller (orchestrator side)


class Back:
    """A back office double: what it announces, whether it answers the end, and what it was told."""

    def __init__(self):
        self.live = True
        self.down = False
        self.told: list[dict] = []

    def get(self, url, token):
        if self.down:
            raise OSError("down")
        return {"live": self.live, "source": "manual", "publisher": None}

    def post(self, url, token, body):
        if self.down:
            raise OSError("down")
        self.told.append(body)
        self.live = False
        return {"ended": ["manual"]}


@pytest.fixture
def poller(monkeypatch, tmp_path):
    monkeypatch.setenv("SADA_INTERNAL_TOKEN_FILE", str(tmp_path / "t"))
    back = Back()
    return studio_link.Poller("http://back", 8088, getter=back.get, poster=back.post), back


def test_the_poller_tells_the_back_office_once_then_sees_live_false(poller):
    p, back = poller
    assert p._look().live is True and back.told == []  # nothing to tell while nothing ended
    p.request_end(123.0)
    ann = p._look()
    assert back.told == [{"lost_at": 123.0}] and ann.live is False and p.end_pending is None
    p._look()
    assert len(back.told) == 1  # not repeated


def test_a_failed_call_is_retried_at_the_next_look_while_the_announcement_says_live(poller):
    p, back = poller
    p.request_end(5.0)
    back.down = True
    assert p._look() is None and p.end_pending == 5.0  # back office unreachable: nothing lost, nothing raised
    back.down = False
    assert p._look().live is False and back.told == [{"lost_at": 5.0}] and p.end_pending is None


def test_the_end_is_dropped_once_the_announcement_no_longer_says_live(poller):
    p, back = poller
    back.live = False  # stopped by hand meanwhile
    p.request_end(5.0)
    assert p._look().live is False
    assert back.told == [] and p.end_pending is None  # a later live must never be closed by a stale request


def test_without_a_back_office_there_is_nothing_to_tell():
    p = studio_link.Poller("", 0)
    p.request_end(1.0)
    assert p.end_pending is None
    assert studio_link.end_live("", 0, 1.0) is False


def test_end_live_never_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("SADA_INTERNAL_TOKEN_FILE", str(tmp_path / "t"))

    def boom(url, token, body):
        raise OSError("down")

    assert studio_link.end_live("http://back", 8088, 1.0, poster=boom) is False
    assert studio_link.end_live("http://back", 8088, 1.0, poster=lambda *a: {}) is True


# ------------------------------------------------------------------ the orchestrator


def test_the_orchestrator_reports_the_end_to_the_back_office(monkeypatch):
    o = make(monkeypatch)
    o._signal_lost = False
    o.manual("start")
    o.encoder.fallback, o.encoder.lost_wall = True, 1_700_000_000.0
    o.encoder.lost_for = studio_link.SIGNAL_GRACE_S - 1
    o._sync()
    assert o.ended_at_back_office == []  # still within the grace
    o.encoder.lost_for = studio_link.SIGNAL_GRACE_S
    o._sync()
    assert not o.machine.stream_on and o.ended_at_back_office == [1_700_000_000.0]
    o._sync()
    assert o.ended_at_back_office == [1_700_000_000.0]  # once
    # the announcement still says `live` for a moment: it never reopens the session that just ended
    follower, live = (
        studio_link.Follower(),
        studio_link.Announcement(live=True, source="manual", type="khutba", title="x"),
    )
    s = Signals(now=o.signals().now, t=2000.0, voice_run=0.0, silence_run=0.0)
    follower._was_on_air = True  # it had seen the session on air
    follower.step(o.machine, s, live)
    assert not o.machine.stream_on
