"""Studio setup mode, server side: a paired device wakes the mosque's orchestrator and reads the programme.

What must hold: the lease is the one thing a scaler needs (and it lapses by itself); the application is told
`waking` / `ready` / `unreachable` / a live on air, never a sentence; commands sent from the setup view reach the
rehearsal stage only (the live is told `setup`); a device only ever watches its own mosque's programme.
"""

from __future__ import annotations

import pytest
from conftest import client, one
from test_regie_studio import dev

from sada.backoffice import internal, live, live_watch, models, orm, setup_session
from sada.backoffice.api import studio as studio_api


@pytest.fixture(autouse=True)
def _fresh_limits():
    studio_api.reset()  # the pairing throttle counts per minute and address, across tests
    setup_session._last_wake.clear()


@pytest.fixture
def orch(monkeypatch):
    """Fake orchestrator: `answers` drives what `set_setup` returns (None = does not answer)."""
    state = {"answers": None, "calls": [], "status": {"ok": True, "state": "IDLE", "scene": None, "transition": "fade"}}

    def set_setup(mosque, on, ttl=None, timeout=4.0):
        state["calls"].append(("setup", mosque["slug"], on, ttl))
        if state["answers"] is None:
            raise live.OrchestratorError("orchestrator unreachable")
        return dict(state["answers"], active=on)

    def command(mosque, cmd, arg=None, valeur=None, transition=None, setup=False):
        state["calls"].append(("command", cmd, valeur if valeur is not None else arg, setup))
        if state.get("lapsed") and setup:
            raise live.SetupLapsed("setup mode is not active")
        return {"ok": True}

    def status_cached(mosque, ttl=0, forcer=False):
        return dict(state["status"])

    monkeypatch.setattr(live, "set_setup", set_setup)
    monkeypatch.setattr(live, "command", command)
    monkeypatch.setattr(live, "status_cached", status_cached)
    monkeypatch.setattr(live_watch, "health", lambda path, timeout=1.0: {"online": True})
    monkeypatch.setattr(
        setup_session,
        "notify_platform",
        lambda slug, action, poster=None: state["calls"].append(("hook", slug, action)) or True,
    )
    return state


READY = {"ok": True, "available": True, "live": False, "rehearsing": True}


def test_enter_wakes_the_orchestrator_and_reports_waking_while_it_does_not_answer(env, orch):
    d = dev(env)
    r = d.post("/api/v1/studio/setup", json={"on": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active"] is True and body["orchestrator"] == "waking" and body["live"] is False
    assert ("hook", "ma-mosquee", "wake") in orch["calls"]  # the platform was told to wake it
    assert one(env["conn"], models.SetupLease) is not None


def test_enter_reports_ready_once_the_orchestrator_answers_and_does_not_wake_again(env, orch):
    d = dev(env)
    d.post("/api/v1/studio/setup", json={"on": True})
    orch["answers"] = READY
    orch["calls"].clear()
    body = d.post("/api/v1/studio/setup", json={"on": True}).json()
    assert body["orchestrator"] == "ready" and body["rehearsing"] is True and body["program"] is True
    assert ("hook", "ma-mosquee", "wake") not in orch["calls"]  # renewal, not a new session


def test_a_silent_orchestrator_becomes_unreachable_after_the_grace_period():
    lease = {"since": 1000.0, "until": 1090.0}
    mosque = {"slug": "x"}
    early = setup_session.view(mosque, lease, None, 1000.0 + setup_session.WAKE_GRACE_S - 1, None)
    late = setup_session.view(mosque, lease, None, 1000.0 + setup_session.WAKE_GRACE_S + 1, None)
    assert (early["orchestrator"], late["orchestrator"]) == ("waking", "unreachable")


def test_a_live_on_air_is_reported_and_setup_does_not_claim_the_rehearsal(env, orch):
    orch["answers"] = {**READY, "live": True, "rehearsing": False}
    body = dev(env).post("/api/v1/studio/setup", json={"on": True}).json()
    assert body["live"] is True and body["rehearsing"] is False and body["orchestrator"] == "ready"


def test_leave_releases_the_lease_and_tells_the_orchestrator_and_the_platform(env, orch):
    d = dev(env)
    orch["answers"] = READY
    d.post("/api/v1/studio/setup", json={"on": True})
    orch["calls"].clear()
    assert d.post("/api/v1/studio/setup", json={"on": False}).json() == {"active": False}
    assert one(env["conn"], models.SetupLease) is None
    assert ("setup", "ma-mosquee", False, None) in orch["calls"] and ("hook", "ma-mosquee", "sleep") in orch["calls"]


def test_leave_without_a_lease_changes_nothing(env, orch):
    assert dev(env).post("/api/v1/studio/setup", json={"on": False}).json() == {"active": False}
    assert orch["calls"] == []


def test_body_must_say_on(env, orch):
    assert dev(env).post("/api/v1/studio/setup", json={}).status_code == 400


def test_setup_needs_a_paired_device(env, orch):
    assert client(env).post("/api/v1/studio/setup", json={"on": True}).status_code in (401, 403)


def test_the_lease_lapses_by_itself_and_leaves_the_scaler_nothing(env, orch):
    d = dev(env)
    d.post("/api/v1/studio/setup", json={"on": True})
    conn = env["conn"]
    assert [x["mosque"] for x in setup_session.leases(conn)] == ["ma-mosquee"]
    later = one(conn, models.SetupLease)["until"] + 1
    assert setup_session.leases(conn, now=later) == []
    assert setup_session.current(conn, one(conn, models.SetupLease)["mosque_id"], now=later) is None


def test_renewal_keeps_the_start_and_a_lapsed_lease_starts_a_new_session(env, orch):
    conn = env["conn"]
    mosque = orm.first(conn, models.Mosque, slug="ma-mosquee")
    lease, fresh = setup_session.take(conn, mosque, None, now=1000.0)
    assert fresh and lease["since"] == 1000.0
    lease, fresh = setup_session.take(conn, mosque, None, now=1030.0)
    assert not fresh and lease["since"] == 1000.0
    lease, fresh = setup_session.take(conn, mosque, None, now=1030.0 + setup_session.TTL_S + 1)
    assert fresh and lease["since"] == 1030.0 + setup_session.TTL_S + 1


def test_scaler_endpoint_needs_the_platform_token(env, orch):
    dev(env).post("/api/v1/studio/setup", json={"on": True})
    anon = client(env)
    assert anon.get("/api/v1/internal/setup-leases").status_code == 403
    ok = anon.get("/api/v1/internal/setup-leases", headers={internal.HEADER: internal.local_token()})
    assert ok.status_code == 200 and [x["mosque"] for x in ok.json()["leases"]] == ["ma-mosquee"]


# ------------------------------------------------------------------ commands of the setup view


def test_a_command_from_the_setup_view_is_marked_so_the_live_is_never_driven(env, orch):
    d = dev(env)
    r = d.post("/api/v1/studio/live/command", json={"command": "scene", "arg": "priere", "setup": True})
    assert r.status_code == 200, r.text
    assert ("command", "scene", "priere", True) in orch["calls"]


def test_a_command_without_the_mark_is_a_live_command_as_before(env, orch):
    dev(env).post("/api/v1/studio/live/command", json={"command": "scene", "arg": "priere"})
    assert ("command", "scene", "priere", False) in orch["calls"]


def test_a_setup_command_after_the_lease_lapsed_is_refused_not_applied(env, orch):
    orch["lapsed"] = True
    r = dev(env).post("/api/v1/studio/live/command", json={"command": "scene", "arg": "priere", "setup": True})
    assert r.status_code == 409 and r.json()["code"] == "setup_off"


def test_status_in_setup_shows_the_rehearsal_stage(env, orch):
    orch["status"] = {
        "ok": True, "state": "IDLE", "scene": None, "transition": "fade", "overlays": {"qr": {"visible": False}},
        "setup": {"active": True, "live": False, "state": "BEFORE", "scene": "avant", "transition": "cut",
                  "overlays": {"qr": {"visible": True}}, "mic_muted": True},
    }  # fmt: skip
    d = dev(env)
    plain = d.get("/api/v1/studio/live/status").json()
    inside = d.get("/api/v1/studio/live/status?setup=1").json()
    assert plain["scene"] is None  # the live's own state
    assert (inside["scene"], inside["transition"], inside["overlays"]["qr"]["visible"], inside["mic_muted"]) == (
        "avant", "cut", True, True,
    )  # fmt: skip


def test_a_live_on_air_wins_over_the_rehearsal_in_the_status(env, orch):
    orch["status"] = {
        "ok": True, "state": "KHUTBA", "scene": "khutba", "transition": "fade",
        "setup": {"active": True, "live": True, "scene": "avant"},
    }  # fmt: skip
    assert dev(env).get("/api/v1/studio/live/status?setup=1").json()["scene"] == "khutba"


# ------------------------------------------------------------------ the programme, over WHEP


@pytest.fixture
def relay(monkeypatch):
    seen = []

    async def offer(path, sdp):
        seen.append(("offer", path))
        return 201, b"v=0 answer", "11111111-2222-3333-4444-555555555555"

    async def close(path, session):
        seen.append(("close", path, session))
        return 200

    monkeypatch.setattr(live_watch, "whep_offer", offer)
    monkeypatch.setattr(live_watch, "whep_close", close)
    return seen


def test_whep_needs_the_lease(env, orch, relay):
    d = dev(env)
    r = d.post("/api/v1/studio/setup/whep", content=b"v=0", headers={"Content-Type": "application/sdp"})
    assert r.status_code == 409 and r.json()["code"] == "setup_off" and relay == []


def test_whep_reads_the_programme_of_the_devices_own_mosque(env, orch, relay):
    d = dev(env)
    d.post("/api/v1/studio/setup", json={"on": True})
    r = d.post("/api/v1/studio/setup/whep", content=b"v=0", headers={"Content-Type": "application/sdp"})
    assert r.status_code == 201 and r.content == b"v=0 answer"
    assert relay == [("offer", "live/ma-mosquee-prog")]
    assert r.headers["location"].startswith("/api/v1/studio/setup/whep/")
    sid = r.headers["location"].rsplit("/", 1)[-1]
    assert d.delete(f"/api/v1/studio/setup/whep/{sid}").status_code == 200
    assert relay[-1] == ("close", "live/ma-mosquee-prog", sid)


def test_whep_says_offline_when_the_programme_is_not_published_yet(env, orch, monkeypatch):
    async def offer(path, sdp):
        return 404, b"", None

    monkeypatch.setattr(live_watch, "whep_offer", offer)
    d = dev(env)
    d.post("/api/v1/studio/setup", json={"on": True})
    r = d.post("/api/v1/studio/setup/whep", content=b"v=0", headers={"Content-Type": "application/sdp"})
    assert r.status_code == 404 and r.json()["error"] == "offline"


def test_whep_refuses_an_empty_or_huge_offer(env, orch, relay):
    d = dev(env)
    d.post("/api/v1/studio/setup", json={"on": True})
    assert d.post("/api/v1/studio/setup/whep", content=b"").status_code == 400
    assert d.post("/api/v1/studio/setup/whep", content=b"x" * (70 * 1024)).status_code == 400


def test_whep_close_rejects_a_malformed_session(env, orch, relay):
    assert dev(env).delete("/api/v1/studio/setup/whep/..%2Fx").status_code in (404, 405)
    assert relay == []


def test_two_mosques_two_leases_two_programmes(env, orch, relay):
    """Isolation: each device holds its own mosque's lease and can only read its own mosque's programme."""
    conn = env["conn"]
    a = dev(env)
    a.post("/api/v1/studio/setup", json={"on": True})
    # a device of another mosque: same code path, its own mosque's lease and programme
    from sada.backoffice import db

    mid2 = db.create_mosque(conn, "autre", "Autre Mosquée")
    mosque2 = orm.first(conn, models.Mosque, id=mid2)
    assert setup_session.current(conn, mid2) is None  # A's setup does not hold B's lease
    setup_session.take(conn, mosque2, None)
    assert sorted(x["mosque"] for x in setup_session.leases(conn)) == ["autre", "ma-mosquee"]
    assert setup_session.program_path(conn, mosque2) == "live/autre-prog"
    # A's device reads A's programme whatever it sends
    a.post("/api/v1/studio/setup/whep", content=b"v=0", headers={"Content-Type": "application/sdp"})
    assert relay == [("offer", "live/ma-mosquee-prog")]
