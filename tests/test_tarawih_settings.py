"""Tarawih settings: audio by default, video refused without confirmation, nothing outside the period."""

import pytest

pytest.importorskip("fastapi")

from conftest import client  # noqa: E402

from sada.backoffice import models, orm, tarawih  # noqa: E402

FORM = {"mode": "audio", "start": "2027-02-08", "end": "2027-03-09", "offset_min": "20", "max_min": "180"}


def test_valeurs_par_defaut_en_son_seul(env):
    d = client(env, "admin").get("/api/v1/settings").json()["tarawih"]
    assert d["mode"] == "audio" and d["start"] == "" and d["offset_min"] == 20 and d["max_min"] is None  # no limit
    assert d["after_isha"] is False and d["silence_end_min"] == 6 and d["reciters"] == []
    assert tarawih.event(env["conn"], env["mid"]) is None  # no period: nothing planned


def test_video_refusee_sans_confirmation(env):
    c = client(env, "admin")
    r = c.ecrire("/settings/tarawih", {**FORM, "mode": "video"}, methode="PUT")
    assert r.status_code == 422
    assert tarawih.event(env["conn"], env["mid"]) is None
    r = c.ecrire("/settings/tarawih", {**FORM, "mode": "video", "confirm_video": "1"}, methode="PUT")
    assert r.status_code == 200, r.text
    assert r.json()["tarawih"]["video_confirmed_at"]
    assert tarawih.event(env["conn"], env["mid"])["mode"] == "video"
    log = orm.first(env["conn"], models.Audit, action="tarawih.configure")
    assert log and '"video"' in (log.get("details") or "")


def test_reglage_audio_donne_une_nuit_par_soir_dans_la_periode(env):
    c = client(env, "admin")
    form = {**FORM, "after_isha": True, "reciters": ["Imam A", " Imam  B ", "imam a"]}
    assert c.ecrire("/settings/tarawih", form, methode="PUT").status_code == 200
    raw = tarawih.event(env["conn"], env["mid"])
    assert raw["mode"] == "audio" and raw["reciters"] == ["Imam A", "Imam B"]  # ordered, deduplicated
    assert raw["recurrence"] == {"after": "isha", "offset_min": 20} and raw["after_isha"] is True
    assert raw["period"] == {"from": "2027-02-08", "until": "2027-03-09"}


def test_recitants_d_une_nuit_remplacent_la_liste(env):
    import datetime as dt

    from sada import events

    c = client(env, "admin")
    form = {**FORM, "reciters": ["Imam A", "Imam B"], "nights": {"2027-02-20": ["Imam C"]}}
    assert c.ecrire("/settings/tarawih", form, methode="PUT").status_code == 200
    e = events.parse(tarawih.event(env["conn"], env["mid"]))
    times = {"isha": "19:30"}
    night = events.instances_on([e], dt.date(2027, 2, 20), times)[0].as_event()
    other = events.instances_on([e], dt.date(2027, 2, 21), times)[0].as_event()
    assert night["reciters"] == ["Imam C"] and other["reciters"] == ["Imam A", "Imam B"]
    bad = {**FORM, "nights": {"2027-05-01": ["Imam C"]}}
    assert c.ecrire("/settings/tarawih", bad, methode="PUT").status_code == 422  # outside the period


@pytest.mark.parametrize(
    "patch",
    [
        {"end": "2027-02-01"},
        {"end": "2027-05-01"},
        {"end": ""},
        {"offset_min": "0"},
        {"max_min": "999"},
        {"silence_end_min": "1"},
        {"reciters": [f"Imam {i}" for i in range(9)]},
        {"mode": "always"},
    ],
)
def test_reglages_invalides_refuses(env, patch):
    r = client(env, "admin").ecrire("/settings/tarawih", {**FORM, **patch}, methode="PUT")
    assert r.status_code == 422


def test_mode_off_ne_planifie_rien(env):
    c = client(env, "admin")
    assert c.ecrire("/settings/tarawih", {**FORM, "mode": "off"}, methode="PUT").status_code == 200
    assert tarawih.event(env["conn"], env["mid"]) is None


def test_video_sans_confirmation_en_base_reste_en_son_seul(env):
    orm.upsert(
        env["conn"],
        models.Tarawih,
        ("mosque_id",),
        mosque_id=env["mid"],
        mode="video",
        start_date="2027-02-08",
        end_date="2027-03-09",
    )
    assert tarawih.event(env["conn"], env["mid"])["mode"] == "audio"


def test_sans_maximum_la_nuit_n_a_pas_de_limite_et_un_maximum_choisi_est_garde(env):
    c = client(env, "admin")
    assert c.ecrire("/settings/tarawih", {**FORM, "max_min": ""}, methode="PUT").status_code == 200
    raw = tarawih.event(env["conn"], env["mid"])
    assert "max_min" not in raw  # nothing imposed: the night ends on its own conditions
    assert c.get("/api/v1/settings").json()["tarawih"]["max_min"] is None
    assert c.ecrire("/settings/tarawih", {**FORM, "max_min": "150"}, methode="PUT").status_code == 200
    assert tarawih.event(env["conn"], env["mid"])["max_min"] == 150  # chosen by the mosque: kept
    assert c.get("/api/v1/settings").json()["tarawih"]["max_min"] == 150


QIYAM = {"qiyam_time": "02:30", "qiyam_start": "2027-03-01", "qiyam_end": "2027-03-09"}


def test_un_qiyam_a_heure_fixe_est_planifie_apres_minuit_sur_la_nuit_de_la_veille(env):
    import datetime as dt

    from sada import events

    c = client(env, "admin")
    r = c.ecrire("/settings/tarawih", {**FORM, **QIYAM, "reciters": ["Imam A"]}, methode="PUT")
    assert r.status_code == 200, r.text
    assert r.json()["tarawih"]["qiyam_time"] == "02:30" and r.json()["tarawih"]["qiyam_start"] == "2027-03-01"
    raws = tarawih.events(env["conn"], env["mid"])
    assert [e["uid"] for e in raws] == ["tarawih", "qiyam"]
    q = events.parse(raws[1])
    assert q.fixed is not None and q.kind == "tarawih" and q.title == "Qiyam"
    day = dt.date(2027, 3, 2)  # 02:30 on the 2nd is the end of the night of the 1st
    (i,) = events.instances_on([q], day, {})
    assert i.starts == dt.datetime(2027, 3, 2, 2, 30)
    assert i.tarawih["night_date"] == "2027-03-01" and i.tarawih["night"] == 22  # numbered like the tarawih
    assert events.instances_on([q], dt.date(2027, 3, 1), {}) == []  # nothing at 02:30 on the 1st: its night is 02-28
    assert events.instances_on([q], dt.date(2027, 3, 10), {})[0].tarawih["night_date"] == "2027-03-09"
    assert events.instances_on([q], dt.date(2027, 3, 11), {}) == []  # past the last night


def test_le_qiyam_prend_la_periode_du_tarawih_sans_dates_propres(env):
    c = client(env, "admin")
    r = c.ecrire("/settings/tarawih", {**FORM, "qiyam_time": "03:00"}, methode="PUT")
    assert r.status_code == 200 and r.json()["tarawih"]["qiyam_start"] == "2027-02-08"
    assert r.json()["tarawih"]["qiyam_end"] == "2027-03-09"


def test_une_heure_de_qiyam_sans_aucune_nuit_est_refusee(env):
    c = client(env, "admin")
    r = c.ecrire("/settings/tarawih", {"mode": "audio", "qiyam_time": "03:00"}, methode="PUT")
    assert r.status_code == 422


@pytest.mark.parametrize(
    "patch",
    [{"qiyam_time": "25:00"}, {"qiyam_time": "2h30"}, {"qiyam_end": ""}, {"qiyam_end": "2027-02-01"}],
)
def test_un_qiyam_invalide_est_refuse(env, patch):
    r = client(env, "admin").ecrire("/settings/tarawih", {**FORM, **QIYAM, **patch}, methode="PUT")
    assert r.status_code == 422


def test_mode_off_ne_planifie_pas_le_qiyam_non_plus(env):
    c = client(env, "admin")
    c.ecrire("/settings/tarawih", {**FORM, **QIYAM}, methode="PUT")
    c.ecrire("/settings/tarawih", {**FORM, **QIYAM, "mode": "off"}, methode="PUT")
    assert tarawih.events(env["conn"], env["mid"]) == []
    c.ecrire("/settings/tarawih", {**FORM, "mode": "audio"}, methode="PUT")  # the qiyam hour is dropped with the form
    assert [e["uid"] for e in tarawih.events(env["conn"], env["mid"])] == ["tarawih"]


def test_un_qiyam_peut_etre_une_seule_nuit(env):
    c = client(env, "admin")
    one = {"qiyam_time": "01:30", "qiyam_start": "2027-03-05", "qiyam_end": "2027-03-05"}
    assert c.ecrire("/settings/tarawih", {**FORM, **one}, methode="PUT").status_code == 200
    q = tarawih.qiyam_event(env["conn"], env["mid"])
    assert q["period"] == {"from": "2027-03-05", "until": "2027-03-05"}
