"""Characterization of Machine.tick(): seeded random days replayed against recorded digests.

The live broadcast is driven by this machine, so its refactors must not change a single transition,
log line or reason. Each scenario mixes session kinds (khutba, dars, conference, tarawih), noisy
signals and manual commands (pause/resume, janaza, extend, skip, scene, ...). Every step records the
state, scene, reason, session records, log lines and command answers; the digest of the whole trace
is compared to the one recorded before the refactor.

Two golden files:

* `state_trace_golden.json` is the one recorded BEFORE the control-room work (2ff5469): the scenes and commands that
  existed then must still trace identically. The only difference allowed is the status keys that work added
  (`NEW_STATUS_KEYS`), which are left out of that digest. Re-recorded once, for an intended change: an end screen
  picked by hand (scene `termine` / `dars_fin` in manual mode) now stays on air instead of stopping the stream; every
  trace that changed was checked to diverge at that very point and nowhere else.
* `state_trace_custom_golden.json` records the same days with the `custom:` scene commands mixed in (a custom
  scene is known to the machine), so the new behaviour is pinned without touching the old proof.

To re-record both after an INTENDED change (check first where the traces diverge): `python tests/test_state_trace.py`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import sys

import pytest

from sada.state import Machine, MachineParams, Signals, State

DAY = dt.date(2026, 3, 6)
COMMANDS = ("start", "pause", "resume", "auto", "extend", "skip", "scene", "janaza", "tarawih", "next_reciter", "stop")
SCENES = ("avant", "khutba", "priere", "entracte", "termine", "dars", "dars_fin", "tarawih", "bogus")
CUSTOM_SCENES = (*SCENES, "custom:attente")
NEW_STATUS_KEYS = ("overlays", "transition", "mic_muted")  # added to Machine.status() after the old golden
# added after both goldens: `rev` is a revision drawn from the wall clock, `playing_event` a derived view
LATER_STATUS_KEYS = ("rev", "playing_event")
# keys of each session record added after both goldens (the range of recordings a session spans)
LATER_SESSION_KEYS = ("end_recording", "end_file_pos")
PLANS = {
    "khutba2": [("12:30", {}), ("13:30", {})],
    "dars": [("12:30", {"kind": "dars", "title": "T"}), ("13:30", {"kind": "conference"})],
    "mixed": [("12:30", {}), ("14:00", {"kind": "dars"})],
    "tarawih": [
        (
            "12:30",
            {
                "kind": "tarawih",
                "mode": "audio",
                "offset_min": 5,
                "after_isha": False,
                "silence_end_min": 4,
                "night": 3,
                "reciters": ["A", "B"],
            },
        )
    ],
    "tarawih_video": [
        ("12:30", {"kind": "tarawih", "mode": "video", "after_isha": True, "max_min": 90, "reciters": ["A"]}),
        ("13:50", {}),
    ],
    "tarawih_then_khutba": [("12:30", {"kind": "tarawih", "offset_min": 10}), ("12:50", {})],
}


def _plan(name: str) -> tuple[list[dt.datetime], list[dict]]:
    rows = PLANS[name]
    return (
        [dt.datetime.combine(DAY, dt.time(int(t[:2]), int(t[3:]))) for t, _meta in rows],
        [dict(meta) for _t, meta in rows],
    )


def run_scenario(plan: str, seed: int, steps: int = 700, custom: bool = False) -> tuple[str, set[str]]:
    """Replay one random day; return (digest of the whole trace, names of the states visited).

    `custom`: the `custom:attente` scene is among the scene commands, and the machine knows it."""
    scenes = CUSTOM_SCENES if custom else SCENES
    rnd = random.Random(f"{plan}/{seed}")
    sessions, extras = _plan(plan)
    logs: list[str] = []
    m = Machine(sessions, MachineParams(), log=logs.append, extras=extras, pos_fn=lambda: (1, round(t - 1000.0, 1)))
    if custom:
        m.custom_known = {"custom:attente"}.__contains__
    now = dt.datetime.combine(DAY, dt.time(12, 0)) + dt.timedelta(minutes=rnd.choice((0, 5, 60, 100)))
    t = 1000.0
    voice = silence = 0.0
    voice_p = rnd.choice((0.2, 0.5, 0.8))
    trace: list = []
    visited: set[str] = set()
    for _step in range(steps):
        dsec = rnd.choice((1.0, 1.0, 5.0, 20.0, 60.0, 120.0))
        t += dsec
        now += dt.timedelta(seconds=dsec * rnd.choice((1, 1, 1, 5)))
        if rnd.random() < voice_p ** (1 + silence / 90):
            voice, silence = voice + dsec, 0.0
        else:
            voice, silence = 0.0, silence + dsec
        face = rnd.choice((None, None, 0.0, 2.0, 50.0, 200.0))
        presence = rnd.choice((None, True, False))
        sig = Signals(now, t, voice, silence, presence, face)
        answer = None
        if rnd.random() < 0.04:
            cmd = rnd.choice(COMMANDS)
            arg = {
                "scene": rnd.choice(scenes),
                "extend": rnd.choice(("5", "15", "x")),
                "janaza": rnd.choice(("Name|note", "", "N")),
            }.get(cmd)
            answer = m.command(cmd, sig, arg)
        elif rnd.random() < 0.003:
            answer = m.command("cancel", sig)
        else:
            m.tick(sig)
        visited.add(m.state.value)
        trace.append(
            [
                m.state.value,
                m.scene,
                m.override,
                m.last_reason,
                m.idx,
                m.grace_until,
                m.grace_reason,
                m.extend_until_t,
                m.paused_from.value if m.paused_from else None,
                m.kind,
                m.live.planned if m.live else None,
                answer,
            ]
        )
    status = {k: v for k, v in m.status().items() if k not in LATER_STATUS_KEYS}
    status["sessions"] = [{k: v for k, v in r.items() if k not in LATER_SESSION_KEYS} for r in status["sessions"]]
    if not custom:
        status = {k: v for k, v in status.items() if k not in NEW_STATUS_KEYS}
    final = {"status": status, "timing": m.timing().__dict__, "logs": logs, "trace": trace}
    blob = json.dumps(final, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest(), visited


SEEDS = range(40)


def _golden(name: str = "state_trace_golden.json") -> dict[str, str]:
    import pathlib

    return json.loads((pathlib.Path(__file__).parent / name).read_text())


@pytest.mark.parametrize("plan", sorted(PLANS))
def test_trace_unchanged(plan):
    golden = _golden()
    for seed in SEEDS:
        digest, _visited = run_scenario(plan, seed)
        assert digest == golden[f"{plan}/{seed}"], f"trace of {plan}/{seed} changed"


@pytest.mark.parametrize("plan", sorted(PLANS))
def test_trace_with_custom_scenes_unchanged(plan):
    golden = _golden("state_trace_custom_golden.json")
    for seed in SEEDS:
        digest, _visited = run_scenario(plan, seed, custom=True)
        assert digest == golden[f"{plan}/{seed}"], f"custom trace of {plan}/{seed} changed"


def test_a_custom_scene_the_machine_does_not_know_is_refused_in_every_day():
    """Without a known image the `custom:` commands never leave the planned states."""
    for plan in PLANS:
        _digest, visited = run_scenario(plan, 0)
        assert State.CUSTOM.value not in visited


def test_traces_cover_every_state():
    """The digests only guard what the scenarios reach: they must reach every state."""
    seen: set[str] = set()
    for plan in PLANS:
        for seed in SEEDS:
            seen |= run_scenario(plan, seed)[1] | run_scenario(plan, seed, custom=True)[1]
    assert seen == {s.value for s in State}


if __name__ == "__main__":
    import pathlib

    for name, custom in (("state_trace_golden.json", False), ("state_trace_custom_golden.json", True)):
        out = {f"{p}/{s}": run_scenario(p, s, custom=custom)[0] for p in sorted(PLANS) for s in SEEDS}
        pathlib.Path(__file__).with_name(name).write_text(json.dumps(out, indent=0, sort_keys=True) + "\n")
        print(name, len(out), "digests recorded", file=sys.stderr)
