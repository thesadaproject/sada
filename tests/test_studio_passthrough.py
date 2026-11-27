"""The live state's revision (`rev`) and who composes the picture (`compositing`).

* `rev` grows at every mutation of the state (commands, overlays, mute, transition, and the automatic switches),
  and every command answers with the whole state after it and its `rev`;
* when the stream on the relay is a Sada Studio device's, the studio composes everything itself: the encoder lays
  nothing over its stream (no slate, no banner, no overlay) and never applies the mute. Any other source (camera,
  OBS) is composed by the server exactly as before.
"""

from __future__ import annotations

import datetime as dt

from test_setup_mode import make

from sada import orchestrator as orch
from sada import setup_mode, studio_link
from sada.state import REV_CLOCK, Machine, MachineParams, Signals, _RevClock

DAY = dt.datetime(2026, 11, 20)


def sig(hh: int, mm: int, t: float = 0.0, voice: float = 0.0, silence: float = 0.0) -> Signals:
    return Signals(now=DAY.replace(hour=hh, minute=mm), t=t, voice_run=voice, silence_run=silence)


# ------------------------------------------------------------------ rev, in the machine


def test_rev_grows_at_every_command_and_setter():
    m = Machine([DAY.replace(hour=13)], MachineParams(), extras=[{}])
    revs = [m.status()["rev"]]
    m.command("scene", sig(12, 0), "priere")
    revs.append(m.status()["rev"])
    m.command("auto", sig(12, 0))
    revs.append(m.rev)
    m.command("auto", sig(12, 0))  # nothing visible changes: still a new revision (the answer orders polls)
    revs.append(m.rev)
    m.set_overlay("banner", {"visible": True, "title": "Soirée"})
    revs.append(m.rev)
    m.set_mute(True)
    revs.append(m.rev)
    m.set_transition("cut")
    revs.append(m.rev)
    m.command("janaza", sig(12, 0), "Untel")
    revs.append(m.rev)
    m.command("bogus", sig(12, 0))  # unknown command: refused, nothing mutated, no revision
    revs.append(m.rev)
    assert all(b > a for a, b in zip(revs[:-2], revs[1:-1], strict=True)), revs
    assert revs[-1] == revs[-2]


def test_rev_grows_on_an_automatic_switch_and_stays_while_nothing_changes():
    m = Machine([DAY.replace(hour=13)], MachineParams(), extras=[{}])
    r0 = m.status()["rev"]
    m.tick(sig(12, 0, t=1.0))  # far from the session: IDLE stays IDLE
    assert m.status()["rev"] == r0
    m.tick(sig(12, 50, t=2.0))  # T-10: the window is armed by the machine itself
    assert m.state.value == "ARMED"
    r1 = m.status()["rev"]
    assert r1 > r0
    m.tick(sig(12, 59, t=3.0))  # T-1: the stream starts on the "before" screen
    assert m.state.value == "BEFORE" and m.status()["rev"] > r1


def test_rev_sees_a_change_made_outside_the_commands():
    """The studio link renames the session on air directly: the status still carries a newer revision."""
    m = Machine([DAY.replace(hour=13)], MachineParams(), extras=[{}])
    m.start_adhoc(sig(12, 0), "dars", "Premier titre")
    r0 = m.status()["rev"]
    m.live.title = "Titre corrigé"
    assert m.status()["rev"] > r0


def test_rev_is_one_sequence_for_every_machine_and_survives_a_restart():
    a = Machine([], MachineParams())
    b = Machine([], MachineParams())  # e.g. the rehearsal stage, built after the live one
    assert b.rev > a.rev
    a.touch()
    assert a.rev > b.rev
    # a restarted process starts from the wall clock: above what the old one handed out
    later = _RevClock(lambda: (REV_CLOCK.next() + 10_000) / 1000)
    assert later.next() > a.rev
    # a clock set back never makes it go down
    clock = iter([5.0, 1.0, 1.0])
    back = _RevClock(lambda: next(clock))
    x, y, z = back.next(), back.next(), back.next()
    assert x < y < z


def test_playing_event_is_the_session_on_air():
    m = Machine([DAY.replace(hour=13)], MachineParams(), extras=[{"kind": "dars", "title": "Planifié"}])
    assert m.status()["playing_event"]["title"] == "Planifié"


# ------------------------------------------------------------------ rev, in the orchestrator's answers


def test_every_command_answers_with_the_whole_state_and_its_rev(monkeypatch):
    o = make(monkeypatch)
    before = o.status()["rev"]
    seen = [before]
    for res in (
        o.manual("scene", "priere"),
        o.set_overlay("qr", {"visible": True, "url": "https://sada.example/don"}),
        o.set_mute(True),
        o.set_transition("cut"),
        o.manual("pause"),
        o.manual("auto"),
        o.manual("janaza", "Untel"),
        o.manual("tarawih"),  # refused (no tarawih tonight): still a fresh state
        o.manual("stop"),
    ):
        assert isinstance(res["rev"], int) and res["rev"] == res["status"]["rev"]
        assert res["compositing"] == res["status"]["compositing"] == "server"
        assert {"state", "scene", "overlays", "mic_muted", "transition", "setup"} <= set(res["status"])
        seen.append(res["rev"])
    assert all(b > a for a, b in zip(seen, seen[1:], strict=False)), seen
    assert o.status()["rev"] == seen[-1]  # no change since the last command: same revision


def test_the_rehearsal_stage_answers_with_its_own_rev_in_the_setup_block(monkeypatch, tmp_path):
    o = make(monkeypatch)
    o.run_dir = tmp_path
    o.set_setup(True, 60, compositing="studio")
    res = o.manual("scene", "priere", setup=True)
    block = res["status"]["setup"]
    assert block["rev"] == res["rev"] == o.rehearsal.machine.rev
    assert block["compositing"] == res["compositing"] == "studio"
    assert res["status"]["compositing"] == "server"  # the live stage is untouched


# ------------------------------------------------------------------ compositing: who feeds the relay


def ann(**data) -> studio_link.Announcement:
    return studio_link.Announcement.parse(data)


def test_the_announcement_says_who_composes():
    assert ann(publisher="device").compositing == "studio"
    assert ann(publisher="obs").compositing == "server"
    assert ann(publisher=None).compositing == "server"  # nobody publishes
    assert ann().compositing is None  # the back office did not say (relay silent, older back office)
    assert ann(publisher="weird").compositing == "server"


def test_studio_compositing_relays_the_stream_untouched(monkeypatch):
    o = make(monkeypatch)
    o._follow_editor(ann(publisher="device"))
    assert o.live_stage.compositing == "studio" and o.status()["compositing"] == "studio"
    o.manual("start")  # a scene off air only changes the picture: a live is needed for the encoder to show it
    o.manual("scene", "priere")  # a full screen, mic closed when the server composes
    o.set_overlay("banner", {"visible": True, "title": "Soirée"})
    o.set_mute(True)
    enc = o.encoder
    assert enc.shown == [orch.PASSTHROUGH_SCENE]  # no slate drawn
    assert enc.overlay is not None and enc.overlay.getbbox() is None  # an empty overlay layer
    assert enc.mic_on is True  # neither the scene nor the mute cut the studio's sound
    # the state goes on as usual, for the studio to read
    st = o.status()
    assert st["scene"] == "priere" and st["mic_muted"] is True and st["overlays"]["banner"]["visible"]
    o.manual("scene", "khutba")
    o.manual("janaza", "Untel")
    assert enc.shown == [orch.PASSTHROUGH_SCENE] and enc.mic_on is True


def test_server_compositing_is_unchanged(monkeypatch):
    o = make(monkeypatch)
    o._follow_editor(ann(publisher="obs"))
    assert o.live_stage.compositing == "server"
    o.manual("start")
    o.manual("scene", "priere")
    assert o.encoder.shown[-1] == "priere" and o.encoder.mic_on is False
    o.manual("scene", "khutba")
    assert o.encoder.shown[-1] == "khutba" and o.encoder.mic_on is True
    o.set_mute(True)
    assert o.encoder.mic_on is False  # the server applies the mute
    o.set_overlay("banner", {"visible": True, "title": "Soirée"})
    assert o.encoder.overlay["banner"]["visible"] is True  # FakeRenderer hands the overlays back as drawn


def test_a_silent_back_office_keeps_the_mode_and_a_change_redraws(monkeypatch):
    o = make(monkeypatch)
    o.manual("start")
    o.manual("scene", "priere")
    r0 = o.status()["rev"]
    o._follow_editor(ann(publisher="device"))
    assert o.status()["rev"] > r0  # who composes is part of the state
    o._follow_editor(None)  # back office silent
    o._follow_editor(ann())  # relay silent
    assert o.live_stage.compositing == "studio"
    o._sync()
    assert o.encoder.shown[-1] == orch.PASSTHROUGH_SCENE
    o._follow_editor(ann(publisher=None), now=100.0)  # the studio's stream drops: a blip, nothing changes yet
    assert o.live_stage.compositing == "studio"
    o._follow_editor(ann(publisher=None), now=100.0 + o.STUDIO_GONE_S)  # gone for good: the server composes again
    o._sync()
    assert o.live_stage.compositing == "server" and o.encoder.shown[-1] == "priere"


def test_a_studio_reconnection_never_flashes_the_server_picture(monkeypatch):
    o = make(monkeypatch)
    o._follow_editor(ann(publisher="device"), now=0.0)
    for t in (5.0, 10.0, 15.0):  # WHIP reconnection: nobody, then a publisher not claimed yet
        o._follow_editor(ann(publisher=None if t < 15 else "unknown"), now=t)
        assert o.live_stage.compositing == "studio"
    o._follow_editor(ann(publisher="device"), now=19.0)  # back: the absence count starts over
    o._follow_editor(ann(publisher=None), now=30.0)
    assert o.live_stage.compositing == "studio"


def test_obs_taking_the_relay_is_composed_by_the_server_at_once(monkeypatch):
    o = make(monkeypatch)
    o._follow_editor(ann(publisher="device"), now=0.0)
    o._follow_editor(ann(publisher="obs"), now=1.0)
    assert o.live_stage.compositing == "server"


def test_the_rehearsal_of_a_studio_device_is_relayed_too(monkeypatch, tmp_path):
    o = make(monkeypatch)
    o.run_dir = tmp_path
    o.set_setup(True, 60, compositing="studio")
    r = o.rehearsal
    assert r.compositing == "studio" and r.encoder.shown == [orch.PASSTHROUGH_SCENE]
    o.manual("scene", "priere", setup=True)
    o.set_mute(True, setup=True)
    assert r.encoder.shown == [orch.PASSTHROUGH_SCENE] and r.encoder.mic_on is True
    assert o.live_stage.compositing == "server"
    # renewed by someone composing on the server side: the rehearsal is drawn again
    o.set_setup(True, 60, compositing="server")
    assert r.compositing == "server"
    o._sync_setup()
    assert r.encoder.shown[-1] == "priere"


def test_a_setup_without_a_mode_keeps_the_server_composition(monkeypatch, tmp_path):
    o = make(monkeypatch)
    o.run_dir = tmp_path
    o.set_setup(True, 60)
    assert o.rehearsal.compositing == "server"
    assert o.rehearsal.encoder.shown == [setup_mode.FIRST_SCENE]


# ------------------------------------------------------------------ the back office tells who feeds the relay


def test_internal_studio_live_says_who_publishes(env, monkeypatch):
    from conftest import client

    from sada.backoffice import internal, studio_publisher

    internal_client = client(env, headers={"X-Internal-Token": internal.local_token()})
    monkeypatch.setattr(studio_publisher, "editor", lambda conn, mosque: (True, "device"))
    body = internal_client.get("/api/v1/internal/studio-live").json()
    assert body["publisher"] == "device" and studio_link.Announcement.parse(body).compositing == "studio"
    monkeypatch.setattr(studio_publisher, "editor", lambda conn, mosque: (True, None))
    assert internal_client.get("/api/v1/internal/studio-live").json()["publisher"] is None
    monkeypatch.setattr(studio_publisher, "editor", lambda conn, mosque: (False, None))  # relay API silent
    body = internal_client.get("/api/v1/internal/studio-live").json()
    assert "publisher" not in body and studio_link.Announcement.parse(body).compositing is None


def test_editor_reads_the_relay_once_and_knows_when_it_is_silent(env, monkeypatch):
    from sada.backoffice import live_watch, studio_publisher

    mosque = {"id": env["mid"], "slug": "m"}
    calls = []
    monkeypatch.setattr(live_watch, "publisher_info", lambda path, timeout=1.0: calls.append(path) or None)
    assert studio_publisher.editor(env["conn"], mosque) == (False, None)
    monkeypatch.setattr(live_watch, "publisher_info", lambda path, timeout=1.0: {"ready": False, "type": "", "id": ""})
    assert studio_publisher.editor(env["conn"], mosque) == (True, None)
    studio_publisher.record(env["conn"], mosque, studio_publisher.Who("device", device_id=None, label="Studio"))
    monkeypatch.setattr(
        live_watch, "publisher_info", lambda path, timeout=1.0: {"ready": True, "type": "webRTCSession", "id": "x"}
    )
    assert studio_publisher.editor(env["conn"], mosque) == (True, "device")
    assert len(calls) == 1
