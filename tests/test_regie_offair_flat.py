"""A scene picked from the control room while nothing is on air reaches the Sada Studio.

The studio reads the flat state (`regie.flat`) and composes `scene` only when `compositing` is "studio". Off air the
machine has no scene, so the picked one (`preview_scene`) must be what the flat state says, with its kind, and the
state must move (`rev`) so the studio reacts. In a rehearsal the rehearsal's own picture keeps the priority.
"""

from PIL import Image
from test_setup_mode import make, open_setup

from sada.backoffice import live
from sada.backoffice.api import regie


def summary(st: dict) -> dict:
    return {"ok": True, **live.summarize(st)}


def base(**kw) -> dict:
    return {"ok": True, "state": "STOPPED", "scene": None, "preview_scene": None, "stream_on": False, "rev": 7, **kw}


def test_off_air_without_a_picked_scene_nothing_changes():
    f = regie.flat(base())
    assert f["scene"] is None and f["scene_kind"] is None and f["preview_scene"] is None
    assert f["compositing"] == "server"


def test_off_air_the_picked_scene_is_the_scene_the_studio_composes():
    f = regie.flat(base(preview_scene="priere"))
    assert f["scene"] == "priere" and f["scene_kind"] == "full" and f["preview_scene"] == "priere"
    assert f["compositing"] == "studio"  # nobody else can show a picture-only scene
    assert regie.flat(base(preview_scene="khutba"))["scene_kind"] == "banner"
    assert regie.flat(base(preview_scene="custom:affiche"))["scene_kind"] == "full"


def test_in_a_live_the_machine_scene_stays():
    f = regie.flat(base(stream_on=True, state="KHUTBA", scene="khutba", preview_scene="priere"))
    assert f["scene"] == "khutba" and f["scene_kind"] == "banner" and f["preview_scene"] is None
    assert f["compositing"] == "server"
    f = regie.flat(base(stream_on=True, scene="dars", compositing="studio"))
    assert f["scene"] == "dars" and f["compositing"] == "studio"


def test_a_rehearsal_keeps_the_priority_for_a_caller_in_setup_mode():
    block = {"active": True, "live": False, "scene": "avant", "compositing": "studio", "rev": 3}
    st = base(preview_scene="priere", setup=block)
    f = regie.flat(st, setup=True)
    assert f["scene"] == "avant" and f["rev"] == 3  # the rehearsal's picture
    # the same status read by the live view (no setup): the picked scene
    assert regie.flat(st, setup=False)["scene"] == "priere"


def test_a_scene_command_off_air_answers_with_the_new_scene_and_a_new_rev(monkeypatch):
    o = make(monkeypatch)
    before = summary(o.status())
    out = o.manual("scene", "priere")
    after = regie.flat(summary(out["status"]))
    assert after["scene"] == "priere" and after["scene_kind"] == "full" and after["compositing"] == "studio"
    assert after["rev"] > before["rev"]  # the studio ignores a state that is not newer than its own
    assert out["rev"] == after["rev"] and out["compositing"] == "server"  # orchestrator's own fields are untouched
    # the immediate answer is the snapshot the next polls serve
    nxt = regie.flat(summary(o.status()))
    assert nxt["scene"] == "priere" and nxt["rev"] == after["rev"]


def test_a_custom_scene_command_off_air_answers_with_the_new_scene(monkeypatch):
    o = make(monkeypatch)
    o._custom_scenes["custom:affiche"] = Image.new("RGBA", (4, 4))
    out = o.set_custom_scene("custom:affiche", None)
    f = regie.flat(summary(out["status"]))
    assert f["scene"] == "custom:affiche" and f["scene_kind"] == "full" and f["compositing"] == "studio"


def test_a_live_taking_over_drops_the_picked_scene(monkeypatch):
    o = make(monkeypatch)
    o.manual("scene", "priere")
    o.manual("start")
    f = regie.flat(summary(o.status()))
    assert f["preview_scene"] is None and f["scene"] == o.machine.scene


def test_a_rehearsal_scene_in_setup_mode_beats_the_picked_one(monkeypatch, tmp_path):
    o = make(monkeypatch)
    open_setup(o, tmp_path)
    o.manual("scene", "priere")  # the live view's, off air: picture only
    st = summary(o.status())
    assert regie.flat(st, setup=True)["scene"] == o.rehearsal.machine.scene
    assert regie.flat(st, setup=False)["scene"] == "priere"
