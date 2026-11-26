"""tools/migrate_mosque.py : plan des fichiers et reprise des textes d'écrans (idempotente, sans écraser)."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from conftest import count  # noqa: E402

from sada.backoffice import models  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "migrate_mosque", Path(__file__).parent.parent / "tools" / "migrate_mosque.py"
)
mm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mm)


def _data(tmp_path):
    d = tmp_path / "data"
    (d / "screens" / "exemple").mkdir(parents=True)
    (d / "screens" / "exemple" / "ecrans.html").write_text("<html>a</html>")
    (d / "screens" / "autre").mkdir(parents=True)
    (d / "screens" / "autre" / "ecrans.html").write_text("x")
    (d / "backoffice" / "exemple").mkdir(parents=True)
    (d / "backoffice" / "exemple" / "prefs.json").write_text("{}")
    (d / "backoffice" / "custom_scenes" / "exemple").mkdir(parents=True)
    (d / "backoffice" / "custom_scenes" / "exemple" / "manifest.json").write_text("{}")
    (d / "backoffice" / "custom_scenes" / "exemple" / ".lock").write_text("")
    (d / "backoffice" / "logos").mkdir(parents=True)
    (d / "backoffice" / "logos" / "exemple.jpg").write_bytes(b"jpg")
    (d / "backoffice" / "logos" / "autre.jpg").write_bytes(b"jpg")
    return d


def test_fichiers_de_la_mosquee_seulement(tmp_path):
    found = mm.local_files(_data(tmp_path), "exemple")
    assert sorted(found) == [
        "backoffice/custom_scenes/exemple/manifest.json",
        "backoffice/exemple/prefs.json",
        "backoffice/logos/exemple.jpg",
        "screens/exemple/ecrans.html",
    ]


def test_plan_sans_ecraser_sauf_force(tmp_path):
    local = mm.local_files(_data(tmp_path), "exemple")
    remote = {
        "screens/exemple/ecrans.html": "0" * 64,  # différent
        "backoffice/logos/exemple.jpg": mm.sha256(local["backoffice/logos/exemple.jpg"]),  # identique
    }
    p = mm.plan_files(local, remote, force=False)
    assert p["differ"] == ["screens/exemple/ecrans.html"] and p["replace"] == []
    assert p["same"] == ["backoffice/logos/exemple.jpg"]
    assert sorted(p["add"]) == ["backoffice/custom_scenes/exemple/manifest.json", "backoffice/exemple/prefs.json"]
    f = mm.plan_files(local, remote, force=True)
    assert f["replace"] == ["screens/exemple/ecrans.html"] and f["differ"] == []


def test_textes_lus_en_local(tmp_path):
    db = tmp_path / "l.db"
    c = sqlite3.connect(db)
    c.executescript(
        "create table mosques(id integer primary key, slug text);"
        "create table screen_texts(mosque_id int, screen text, slot text, text text, updated_at text);"
        "insert into mosques values (1,'exemple'),(2,'autre');"
        "insert into screen_texts values (1,'avant','foot','Bienvenue','t'),(2,'avant','foot','non','t');"
    )
    c.commit()
    c.close()
    assert mm.local_screen_texts(db, "exemple") == [
        {"screen": "avant", "slot": "foot", "text": "Bienvenue", "updated_at": "t"}
    ]
    assert mm.local_screen_texts(tmp_path / "absent.db", "exemple") == []


def test_textes_repris_idempotent_sans_ecraser(env):
    conn = env["conn"]
    slug = "ma-mosquee"
    rows = [
        {"screen": "avant", "slot": "foot", "text": "A", "updated_at": "t"},
        {"screen": "avant", "slot": "sub", "text": "B", "updated_at": "t"},
    ]
    assert mm.apply_screen_texts(conn, slug, rows, False, True)["add"] == 2
    assert count(conn, models.ScreenText) == 0  # dry run
    assert mm.apply_screen_texts(conn, slug, rows, False, False)["add"] == 2
    assert mm.apply_screen_texts(conn, slug, rows, False, False) == {"add": 0, "same": 2, "differ": 0, "replace": 0}
    changed = [{**rows[0], "text": "Z"}]
    assert mm.apply_screen_texts(conn, slug, changed, False, False)["differ"] == 1
    got = {r.slot: r.text for r in conn.execute(models.screen_texts.select())}
    assert got["foot"] == "A"  # gardé
    assert mm.apply_screen_texts(conn, slug, changed, True, False)["replace"] == 1
    got = {r.slot: r.text for r in conn.execute(models.screen_texts.select())}
    assert got["foot"] == "Z" and got["sub"] == "B"
    assert "error" in mm.apply_screen_texts(conn, "inconnue", rows, False, False)
