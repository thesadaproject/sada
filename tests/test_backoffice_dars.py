"""Back-office and dars: labels, clip caption."""

from sada.backoffice import publish
from sada.backoffice.importer import khutba_label

MOSQUE = {"name": "Mosquée Exemple"}


def test_libelle_dars_et_khutba():
    assert (
        khutba_label({"index": 1, "kind": "dars", "title": "Tafsir Al-Kahf", "session_no": 7})
        == "Dars — Tafsir Al-Kahf · séance 7"
    )
    assert (
        khutba_label({"index": 0, "kind": "conference", "title": "Les droits des voisins"})
        == "Conférence — Les droits des voisins"
    )
    assert khutba_label({"index": 0, "planned": "13:30"}) == "Session 1 — 13 h 30"
    assert khutba_label({"index": 1, "kind": "dars"}) == "Session 2"


def test_legende_dun_clip_de_dars():
    khutba = {
        "kind": "dars",
        "title": "Tafsir Al-Kahf",
        "label": "Dars — Tafsir Al-Kahf · séance 7",
        "date": "2026-11-10",
    }
    cap = publish.default_caption(khutba, MOSQUE, ["65:3"])
    assert cap.splitlines()[0] == "Dars : Tafsir Al-Kahf — Mosquée Exemple"
    assert "65:3" in cap

    khutba = {"kind": "khutba", "title": "", "label": "Session 1 — 12 h 30", "date": "2026-11-06"}
    cap = publish.default_caption(khutba, MOSQUE, [])
    assert cap.splitlines()[0] == "Khutba du vendredi — Mosquée Exemple"
