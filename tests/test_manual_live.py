"""A live started by hand is manual: "auto", the end of the plan, silence, presence, a slot ending never stop it."""

from __future__ import annotations

import datetime as dt

from sada import studio_link
from sada.state import Machine, MachineParams, Signals, State

DAY = dt.datetime(2026, 11, 20)


def at(h, m=0, s=0):
    return DAY.replace(hour=h, minute=m, second=s)


def sig(now, t, voice=0.0, silence=0.0, presence=None):
    return Signals(now, t, voice, silence, presence)


def empty_day():
    return Machine([], MachineParams(), extras=[])


def test_the_prod_sequence_start_scenes_then_auto_does_not_end_the_live():
    """01:15 start with nothing planned, scenes clicked, 01:19 'auto': it used to end on 'plus aucune session'."""
    m = empty_day()
    m.command("start", sig(at(1, 15, 55), 1.0))
    assert m.stream_on and m.manual_live and m.override
    m.command("scene", sig(at(1, 16), 2.0), "avant")
    m.command("scene", sig(at(1, 17), 3.0), "priere")
    m.command("scene", sig(at(1, 18), 4.0), "avant")
    assert m.state == State.BEFORE and m.stream_on
    m.command("auto", sig(at(1, 19, 10), 5.0))
    assert not m.override
    for i in range(1, 200):  # minutes pass, silent, nobody there, no session left
        m.tick(sig(at(1, 19, 10) + dt.timedelta(seconds=30 * i), 5.0 + 30 * i, silence=30.0 * i, presence=False))
    assert m.state == State.BEFORE and m.stream_on and m.manual_live  # still on air


def test_only_stop_ends_it_and_the_plan_is_kept():
    m = Machine([at(20)], MachineParams(), extras=[{}])
    m.command("start", sig(at(1, 0), 1.0))  # nothing is due: a live nobody planned
    assert m.manual_live
    m.command("auto", sig(at(1, 1), 2.0))
    m.tick(sig(at(1, 2), 3.0))
    assert m.stream_on
    m.command("stop", sig(at(1, 3), 4.0))
    assert m.state == State.ENDED and not m.manual_live
    m.tick(sig(at(1, 3, 59), 4.0 + 46.0))
    assert m.state == State.IDLE and not m.stream_on and m.idx == 0  # the 20:00 session is still planned


def test_cancel_ends_it_too():
    m = empty_day()
    m.command("start", sig(at(1, 0), 1.0))
    m.command("cancel", sig(at(1, 1), 2.0))
    assert not m.manual_live and m.state in (State.ENDED, State.STOPPED)


def test_silence_presence_and_a_long_time_do_not_end_a_manual_khutba():
    m = empty_day()
    m.command("start", sig(at(2, 0), 1.0))
    assert m.state == State.KHUTBA and m.manual_live
    m.command("auto", sig(at(2, 0, 5), 2.0))
    for i in range(1, 400):  # six hours of silence, an empty minbar: the khutba rules would have ended it long ago
        m.tick(sig(at(2, 0, 5) + dt.timedelta(seconds=60 * i), 2.0 + 60 * i, silence=60.0 * i, presence=False))
    assert m.state == State.KHUTBA and m.stream_on


def test_a_planned_session_that_arrives_takes_over_in_the_same_stream_when_auto():
    m = Machine([at(13)], MachineParams(), extras=[{}])
    m.command("start", sig(at(11, 0), 1.0))  # window of the 13:00 session is not open: a live nobody planned
    assert m.manual_live
    m.command("auto", sig(at(11, 1), 2.0))
    m.tick(sig(at(12, 0), 100.0))
    assert m.manual_live and m.state == State.KHUTBA  # not due yet
    m.tick(sig(at(12, 45), 200.0))  # the arming window opens: the plan takes the stream over, no cut
    assert not m.manual_live and m.stream_on and m.state == State.INTERMISSION
    assert [r.status for r in m.records if r.planned == "13:00"] == ["pending"]  # the planned one is still to be played
    m.tick(sig(at(12, 59), 300.0, voice=60.0))
    m.tick(sig(at(13, 0, 5), 310.0, voice=60.0))
    assert m.state == State.KHUTBA and m.live.planned == "13:00"  # chained, as for any session


def test_in_override_a_planned_session_does_not_take_over():
    m = Machine([at(13)], MachineParams(), extras=[{}])
    m.command("start", sig(at(11, 0), 1.0))
    m.command("scene", sig(at(11, 1), 2.0), "avant")  # override: the control room is driving
    m.tick(sig(at(13, 30), 300.0, voice=60.0))
    assert m.manual_live and m.stream_on and m.state == State.BEFORE


def test_a_planned_session_put_in_override_by_a_scene_is_not_a_manual_live():
    """The difference the rule needs: here "auto" gives the planning back its usual behaviour."""
    m = Machine([at(13)], MachineParams(), extras=[{}])
    m.command("start", sig(at(12, 55), 1.0))  # inside the window of the planned 13:00: it is that session, in override
    assert not m.manual_live and m.live is not None and m.live.planned == "13:00"
    m.command("scene", sig(at(12, 56), 2.0), "priere")
    m.command("auto", sig(at(12, 57), 3.0))
    m.tick(sig(at(12, 58), 4.0 + 4000.0))  # the usual rules apply again (maximum duration here)
    assert not m.manual_live and m.state != State.KHUTBA


def test_a_slot_ending_does_not_end_a_manual_live():
    m = empty_day()
    m.command("start", sig(at(1, 0), 1.0))
    f = studio_link.Follower()
    f.slot_on = True  # a Studio slot was ordered, then it is over
    note = f.step(m, sig(at(1, 5), 2.0), studio_link.Announcement(live=False))
    assert m.stream_on and m.manual_live and (note is None or "over" not in note.lower() or "no planned" in note)


def test_a_studio_manual_live_survives_a_scene_and_ends_on_the_studio_stop():
    m = empty_day()
    f = studio_link.Follower()
    live = studio_link.Announcement(live=True, source="manual", type="khutba", title="Jumua")
    f.step(m, sig(at(1, 0), 1.0), live)
    assert m.manual_live and m.adhoc_on_air
    m.command("scene", sig(at(1, 1), 2.0), "avant")  # closes the session record, the stream stays
    assert m.stream_on and not m.adhoc_on_air and m.manual_live
    m.command("auto", sig(at(1, 2), 3.0))
    m.tick(sig(at(1, 30), 4.0 + 4000.0))
    assert m.stream_on  # nothing automatic ended it
    f.step(m, sig(at(1, 31), 5.0 + 4000.0), studio_link.Announcement(live=False))  # the device stopped it
    assert m.state == State.ENDED and not m.manual_live


def test_the_day_roll_waits_for_a_manual_live():
    m = empty_day()
    m.command("start", sig(at(1, 0), 1.0))
    assert not m.new_day([at(13)], [{}], sig(at(1, 2), 3.0))  # engaged
    assert m.stream_on


def test_a_loss_beyond_the_grace_still_ends_a_manual_live():
    m = empty_day()
    m.command("start", sig(at(1, 0), 1.0))
    m.command("scene", sig(at(1, 1), 2.0), "avant")
    m.end_lost(sig(at(1, 12), 700.0), "signal perdu")
    assert not m.stream_on and not m.manual_live


def test_janaza_then_auto_returns_a_manual_live_to_its_own_screen():
    m = empty_day()
    m.command("start", sig(at(1, 0), 1.0))
    m.command("janaza", sig(at(1, 1), 2.0), "Untel")
    m.command("auto", sig(at(1, 2), 3.0))
    assert m.stream_on and m.state != State.ENDED and m.manual_live


def test_the_status_says_it():
    m = empty_day()
    assert m.status()["manual_live"] is False
    m.command("start", sig(at(1, 0), 1.0))
    assert m.status()["manual_live"] is True


def test_the_back_office_summary_carries_it_to_the_control_room():
    from sada.backoffice import live

    assert live.summarize({"manual_live": True})["manual_live"] is True
    assert live.summarize({})["manual_live"] is False
