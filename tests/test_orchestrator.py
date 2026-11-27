"""Back office unreachable at start: the day is not left on the default times.

The orchestrator retries the times and the programme in the background and replans the sessions
still to come as soon as the back office answers (see Orchestrator._retry_plan / Machine.replan).
"""

import datetime as dt
from types import SimpleNamespace

from sada import events as events_mod
from sada import orchestrator as orch
from sada.state import Machine, MachineParams, Signals, State

D = dt.date(2026, 11, 14)  # Saturday
STATE_DIR = "/tmp/sada-test-state-unused"
TIMES = ["06:00", "13:00", "15:30", "17:12", "18:45"]  # fajr, dhuhr, asr, maghrib, isha


def at(h, m=0, s=0):
    return dt.datetime.combine(D, dt.time(h, m, s))


def sig(now, t=1000.0, voice=0.0):
    return Signals(now, t, voice, 0.0)


def dars(title="Tafsir Al-Kahf"):
    """Dars of the day, after maghrib: its start only exists with the real (Mawaqit) times."""
    return events_mod.parse(
        {
            "kind": "dars",
            "title": title,
            "speaker": "Imam Abdallah",
            "series": title,
            "session": 7,
            "recurrence": {"weekday": "samedi", "after": "maghrib"},
        }
    )


def dars_event(title="Tafsir Al-Kahf"):
    """Same dars, in the shape the machine expects (event of a session)."""
    return events_mod.instances_on([dars(title)], D, {"maghrib": "17:12"})[0].as_event()


def orchestrator(down):
    """Orchestrator stripped to the schedule, as it stands after a start on the fallback."""
    o = object.__new__(orch.Orchestrator)
    o.cfg = SimpleNamespace(
        backoffice_url="http://127.0.0.1:8090", api_port=8088, jumua_times_override=[], sim_start="12:00",
        state_dir=STATE_DIR,
    )  # fmt: skip
    # simulated start: the khutba times apply on this Saturday too
    o.times, o.program, o.times_data, o.instances = ["12:30", "13:30"], [], None, []
    o._plan_day, o._rolled = D, False
    o._stale, o._times_fallback, o._program_remote = True, True, False
    o._retry_delay, o._retry_at = orch.RETRY_DELAY_S, 0.0
    o._retry_thread, o._fetched = None, None
    sessions, extras = o.day_plan(D)
    o.machine = Machine(sessions, MachineParams(), extras=extras)

    def fake_times(url, port, fetch=None, log=None):
        if down[0]:
            return None
        return {
            "name": "Test",
            "jumua": "13:00",
            "jumua_list": ["13:00"],
            "origin": "live",
            "times": TIMES,
        }

    def fake_program(url, port, fetch=None, log=None):
        return None if down[0] else [dars()]

    o.fetched_times, o.fetched_program = fake_times, fake_program
    # what a new day touches besides the plan: the run (sessions file, recordings)
    o.encoder = SimpleNamespace(recordings=[], wanted=False)
    o.run_id, o._saved = "20261114_090000", None
    o.saved_runs = []
    o._save_sessions = lambda: o.saved_runs.append(o.run_id)
    return o


def test_back_office_down_then_up_replans_the_day(monkeypatch):
    down = [True]
    o = orchestrator(down)
    monkeypatch.setattr(orch.prayers, "from_backoffice", lambda *a, **k: o.fetched_times(*a, **k))
    monkeypatch.setattr(orch.events_mod, "from_backoffice", lambda *a, **k: o.fetched_program(*a, **k))
    assert o.machine.sessions == [at(12, 30), at(13, 30)]  # the fallback, until tomorrow

    # first attempt: the back office is still down, nothing moves
    o._retry_plan(sig(at(12, 5)))
    o._retry_thread.join(10)
    assert o._fetched is None
    assert o.machine.sessions == [at(12, 30), at(13, 30)]
    assert o._stale  # still to be retried

    # 30 s later the back office answers: times and programme arrive together
    down[0] = False
    o._retry_at = 0.0
    o._retry_plan(sig(at(12, 6)))
    o._retry_thread.join(10)
    o._retry_plan(sig(at(12, 7)))  # the loop applies the result it just collected

    assert o.times == ["13:00"]
    assert o.times_data["times"] == TIMES
    assert o.machine.sessions == [at(13, 0), at(17, 12)]  # khutba 13:00 + dars after maghrib
    assert o.machine.records[1].kind == "dars"
    assert o.machine.records[1].title == "Tafsir Al-Kahf"
    assert not o._stale  # the plan is the real one: no more retries

    o._retry_plan(sig(at(12, 8)))
    assert o._retry_thread is None or not o._retry_thread.is_alive()


def test_replan_keeps_the_session_in_progress():
    """A session is playing when the real timetable arrives: it is never restarted nor cut."""
    logs = []
    m = Machine([at(12, 30), at(13, 30)], MachineParams(), log=logs.append)
    m.tick(sig(at(12, 20), 0.0))  # armed
    m.tick(sig(at(12, 30), 30.0, 25.0))  # sustained voice: the khutba is under way
    assert m.state == State.KHUTBA and m.live.planned == "12:30"

    added = m.replan([at(12, 45), at(17, 12)], [{}, dars_event()], sig(at(12, 35), 400.0))

    assert added == 2
    assert m.live is not None and m.live.planned == "12:30"  # in progress, untouched
    assert m.sessions == [at(12, 30), at(12, 45), at(17, 12)]  # 13:30 (never started) replaced
    assert m.idx == 1
    assert m.rec.kind == "khutba"


def test_replan_reopens_a_day_already_closed():
    """The day ended on the fallback hours; a session arrives for tonight: the live resumes."""
    m = Machine([at(12, 30)], MachineParams())
    m.tick(sig(at(13, 30), 0.0))  # armed, then the window is closed: skipped, nothing left
    m.tick(sig(at(13, 31), 1.0))
    assert m.state == State.STOPPED

    added = m.replan([at(17, 12)], [dars_event()], sig(at(16, 0), 100.0))

    assert added == 1
    assert m.state == State.IDLE
    assert m.session == at(17, 12)
    assert m.rec.kind == "dars"


def test_replan_ignores_sessions_whose_window_is_closed():
    """Arriving too late must not start a session in the past."""
    m = Machine([at(12, 30)], MachineParams())
    m.tick(sig(at(12, 31), 0.0))
    assert m.replan([at(12, 0)], [{}], sig(at(14, 0), 100.0)) == 0


def test_khutbas_only_on_friday():
    """Mawaqit's jumua times are not a daily plan: outside Friday only the programme remains."""
    o = object.__new__(orch.Orchestrator)
    o.cfg = SimpleNamespace(jumua_times_override=[], sim_start=None)
    o.times, o.program, o.times_data = ["12:30", "13:30"], [], {"times": TIMES}
    assert o.day_plan(dt.date(2026, 11, 17)) == ([], [])  # Tuesday
    assert [s.strftime("%H:%M") for s in o.day_plan(dt.date(2026, 11, 20))[0]] == ["12:30", "13:30"]
    o.program = [dars()]
    assert [s.strftime("%H:%M") for s in o.day_plan(D)[0]] == ["17:12"]  # Saturday: the dars alone
    o.cfg.jumua_times_override = ["12:30"]  # forced by hand: any day
    o.program = []
    assert len(o.day_plan(dt.date(2026, 11, 17))[0]) == 2


def test_midnight_plans_the_new_day_then_refreshes_its_times(monkeypatch):
    """The process runs for days: at midnight the plan of the new day replaces yesterday's."""
    down = [False]
    o = orchestrator(down)
    o._stale = False
    monkeypatch.setattr(orch.prayers, "from_backoffice", lambda *a, **k: o.fetched_times(*a, **k))
    monkeypatch.setattr(orch.events_mod, "from_backoffice", lambda *a, **k: o.fetched_program(*a, **k))
    o._plan_day = D - dt.timedelta(days=1)
    o.machine.records[0].status = "done"  # yesterday's session, played

    o._roll_day(sig(at(0, 1)))
    assert o._plan_day == D and o._stale and o._rolled
    assert o.machine.sessions == [at(12, 30), at(13, 30)]  # at once, with what is known
    assert all(r.status == "pending" for r in o.machine.records)

    o._retry_plan(sig(at(0, 2)))
    o._retry_thread.join(10)
    o._retry_plan(sig(at(0, 3)))
    assert o.machine.sessions == [at(13, 0), at(17, 12)]  # today's times, the day planned whole
    assert not o._stale and not o._rolled


def test_new_day_waits_for_a_session_running_over_midnight():
    m = Machine([at(23, 0)], MachineParams())
    m.state = State.DARS
    assert not m.new_day([at(13, 0)], None, sig(at(0, 1)))
    m.state = State.ENDED
    assert m.new_day([at(13, 0)], None, sig(at(0, 2)))
    assert m.state == State.IDLE and m.sessions == [at(13, 0)]


def test_start_waits_for_the_back_office_then_gives_up():
    """Deployed together, the back office often boots second: the start waits for it, bounded."""
    t = [0.0]
    answers = iter([False, False, True])
    assert orch.wait_for_backoffice(
        "http://bo", 90, probe=lambda: next(answers), sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0]
    )
    assert t[0] == 3.0  # 1 s, then 2 s

    t[0] = 0.0
    assert not orch.wait_for_backoffice(
        "http://bo", 30, probe=lambda: False, sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0]
    )
    assert t[0] == 30.0  # never beyond the limit
    assert not orch.wait_for_backoffice("", 90, probe=lambda: 1 / 0)  # no back office: no wait


def live_orchestrator(up, fetches):
    o = object.__new__(orch.Orchestrator)
    o.cfg = SimpleNamespace(
        backoffice_url="http://bo", api_port=8088, rtmp_urls=[], camera_url="rtsp://local/cam", screen_texts=None
    )
    o.vad = o.presence = o.faces = None
    o.gabarit = object()
    o.uploader = None
    o._live_stale, o._live_delay, o._live_at = True, orch.RETRY_DELAY_S, 0.0
    o._live_thread, o._live_ready, o._live_fetched = None, False, None
    o._read_live_config = lambda: (
        fetches.append(1)
        or {
            "rtmp_urls": ["rtmp://a/k"],
            "camera_url": "srt://in",
            "screen_texts": None,
            "storage": None,
        }
    )
    return o


def test_live_config_is_fetched_once_the_back_office_answers(monkeypatch):
    up, fetches = [False], []
    o = live_orchestrator(up, fetches)
    monkeypatch.setattr(orch, "backoffice_up", lambda url: up[0])
    o._retry_live_config()
    o._live_thread.join(10)
    assert not o._live_ready and o.cfg.rtmp_urls == []  # still down: nothing applied, still stale
    o._live_at = 0.0
    o._retry_live_config()
    o._live_thread.join(10)
    o._retry_live_config()
    assert o._live_stale and fetches == [] and o._live_delay == 4 * orch.RETRY_DELAY_S
    up[0] = True
    o._live_at = 0.0
    o._retry_live_config()
    o._live_thread.join(10)
    o._retry_live_config()  # the loop applies what the thread fetched
    assert not o._live_stale and fetches == [1]
    assert o.cfg.rtmp_urls == ["rtmp://a/k"] and o.cfg.camera_url == "srt://in"
    o._retry_live_config()  # done: nothing more is fetched
    assert fetches == [1]


def test_live_config_retry_is_off_when_the_back_office_was_reached():
    o = live_orchestrator([True], [])
    o._live_stale = False
    o._retry_live_config()
    assert o._live_thread is None


def _midnight(monkeypatch, tmp_path, recordings, status):
    monkeypatch.setattr(orch.prayers, "from_backoffice", lambda *a, **k: None)
    monkeypatch.setattr(orch.events_mod, "from_backoffice", lambda *a, **k: None)
    o = orchestrator([True])
    o.cfg.state_dir = str(tmp_path)
    o._stale = False
    o._plan_day = D - dt.timedelta(days=1)
    o.run_dir = tmp_path / o.run_id
    o.encoder.recordings = list(recordings)
    o.machine.records[0].status = status
    return o


def test_a_new_day_is_a_new_run_so_that_yesterdays_sessions_are_kept(monkeypatch, tmp_path):
    """A process that runs for a whole Ramadan: tonight's session must not take the number of last night's."""
    o = _midnight(monkeypatch, tmp_path, [("/r/night1.mkv", None)], "done")
    first = o.run_id
    o._roll_day(sig(at(0, 1)))
    assert o.saved_runs == [first]  # yesterday's sessions were written to yesterday's run, before the plan changed
    assert o.run_id == "20261114_000100" != first and o.run_dir == tmp_path / o.run_id
    assert o.run_dir.is_dir() and o.encoder.recordings == []  # numbered from the first recording again
    assert o._saved is None  # the new run's sessions file is written at the next pass


def test_a_quiet_day_of_the_same_date_keeps_its_run(monkeypatch, tmp_path):
    o = _midnight(monkeypatch, tmp_path, [], "pending")
    o.run_id = "20261114_000500"  # started today, nothing happened yet
    first = o.run_id
    o._roll_day(sig(at(0, 1)))
    assert o.run_id == first and o.saved_runs == []


def test_a_run_of_another_day_is_left_behind_even_when_nothing_was_played(monkeypatch, tmp_path):
    o = _midnight(monkeypatch, tmp_path, [], "pending")
    o.run_id = "20261113_090000"  # started yesterday, a quiet day
    o._roll_day(sig(at(0, 1)))
    assert o.run_id == "20261114_000100"
    assert runs_date(o.run_id) == "2026-11-14"  # a session of today is dated today


def runs_date(run_id):
    from sada import runs

    return runs.run_date(run_id)


def test_the_new_day_waits_for_the_night_to_end_and_the_run_with_it(monkeypatch, tmp_path):
    o = _midnight(monkeypatch, tmp_path, [("/r/night.mkv", None)], "live")
    o.machine.state = State.TARAWIH  # the night runs over midnight
    first = o.run_id
    o._roll_day(sig(at(0, 1)))
    assert o.run_id == first and o.encoder.recordings  # nothing moves while it is on air
    o.machine.state = State.STOPPED
    o.machine.records[0].status = "done"
    o._roll_day(sig(at(0, 40)))
    assert o.run_id != first and o.encoder.recordings == []
