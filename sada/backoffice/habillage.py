"""Habillage d'une vidéo de session, côté back-office : réglages, aperçu, rendu en tâche de fond.

Le rendu lui-même est dans `sada.pipeline.habillage`. Ici : d'où vient la source, où va le résultat
(`<dossier de la session>/habillage/`, jamais à côté de l'original), quels champs on préremplit
(titre, intervenant, série, date de la session) et ce que la mosquée garde d'une fois sur l'autre
(positions, durées, message de fin : son identité, pas le contenu d'un dars précis).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import traceback
from pathlib import Path

from sqlalchemy import update

from ..i18n import _
from ..pipeline import clips as clipmod
from ..pipeline import habillage as rendu
from ..pipeline import subtitles as sous_titres
from . import db, orm, states, traduction
from .jobs import DbRowStore, Job, JobStatus
from .models import Habillage, Khutba, Mosque, User

#: réglages qui décrivent la mosquée et pas une vidéo : retenus pour la prochaine fois
IDENTITE = (
    "intro_on",
    "lower_on",
    "logo_on",
    "bar_on",
    "outro_on",
    "intro_s",
    "lower_at",
    "lower_s",
    "outro_s",
    "logo_pos",
    "logo_size",
    "logo_opacity",
    "outro_text",
    "outro_link",
)

MOIS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


# ------------------------------------------------------------------ source et fichiers


MARGE_PAROLE = 1.0  # s gardées avant la première parole
COUPE_MIN = 2.0  # silence plus court au début : rien n'est coupé


def silence_initial(k: dict) -> float:
    """Secondes coupées au début de la séance : ce qui précède la première parole de la transcription
    (Whisper avec détection de voix, hallucinations déjà écartées), moins une seconde de marge.

    Le direct démarre sur la présence au minbar, souvent avant la première parole : la vidéo habillée
    commence, elle, quand l'imam parle. 0 sans transcription."""
    from ..pipeline.output import SessionOutput

    if not k.get("output_dir"):
        return 0.0
    tr = SessionOutput(k["output_dir"]).read(SessionOutput(k["output_dir"]).transcript, {})
    debuts = [float(x["start"]) for x in tr.get("segments") or [] if str(x.get("text") or "").strip()]
    if not debuts:
        return 0.0
    coupe = min(debuts) - MARGE_PAROLE
    duree = float(tr.get("duration") or 0)
    if coupe < COUPE_MIN or (duree and duree - coupe < 10.0):
        return 0.0
    return round(coupe, 2)


def source(k: dict) -> tuple[str, float, float | None] | None:
    """(fichier, début, fin) de la vidéo à habiller : la vidéo de la session si elle a été extraite,
    sinon l'enregistrement complet coupé aux bornes de la session ; le silence d'avant la première
    parole est retiré du début. None : rien à habiller."""
    coupe = silence_initial(k)
    if k.get("video_path") and Path(k["video_path"]).exists():
        return k["video_path"], coupe, None
    rec = k.get("recording")
    if rec and Path(rec).exists():
        debut = float(k.get("start_pos") or 0.0)
        return rec, debut + coupe, (float(k["end_pos"]) if k.get("end_pos") else None)
    return None


def dossier(k: dict) -> Path:
    return Path(k["output_dir"]) / "habillage"


def fichier_video(k: dict) -> Path:
    return dossier(k) / "video-habillee.mp4"


def fichier_rendu_en_cours(k: dict) -> Path:
    """Le rendu s'écrit à part : la vidéo habillée précédente reste affichée jusqu'à ce qu'il aboutisse."""
    return dossier(k) / "video-habillee.en-cours.mp4"


def fichier_options_rendues(k: dict) -> Path:
    """Options de la vidéo habillée en place (celles du formulaire peuvent déjà avoir changé)."""
    return dossier(k) / "video-habillee.json"


def fichier_apercu(k: dict) -> Path:
    return dossier(k) / "apercu.jpg"


def nom_telechargement(k: dict) -> str:
    """Nom proposé au téléchargement : la date et le genre, jamais le chemin sur la machine."""
    return f"sada-{k.get('kind') or 'session'}-{(k.get('date') or '')[:10] or k['id']}-habillee.mp4"


def nom_sous_titres(k: dict, langue: str, brut: bool = False) -> str:
    """Nom du .srt téléchargé : date, genre, langue ; `-original` pour l'alignement sur la vidéo source."""
    base = f"sada-{k.get('kind') or 'session'}-{(k.get('date') or '')[:10] or k['id']}"
    return f"{base}-sous-titres-{langue}{'-original' if brut else ''}.srt"


def marque(m: dict) -> tuple[dict | None, str | None]:
    """Couleurs et logo de la mosquée, comme pour les clips (vides : charte des clips, sans logo)."""
    brand = {c: m[f"brand_{c}"] for c in ("green", "gold") if (m.get(f"brand_{c}") or "").strip()}
    logo = None
    if (m.get("logo_path") or "").strip():
        from . import branding

        p = branding.path_for(m)
        if p.exists() and p.suffix.lower() in clipmod.LOGO_EXT:
            logo = str(p)
    return brand or None, logo


# ------------------------------------------------------------------ préremplissage


def _date_fr(iso: str | None) -> str:
    try:
        d = dt.date.fromisoformat((iso or "")[:10])
    except ValueError:
        return ""
    return f"{d.day}{'er' if d.day == 1 else ''} {MOIS[d.month - 1]} {d.year}"


def prerempli(conn, k: dict, m: dict) -> dict:
    """Options d'une première ouverture : réglages retenus par la mosquée + métadonnées de la session."""
    base = _defauts_mosquee(m)
    imam = orm.first(conn, User, id=k["imam_id"]) if k.get("imam_id") else None
    speaker = (k.get("speaker") or "").strip() or ((imam or {}).get("display_name") or "").strip()
    titre = (k.get("title") or "").strip() or (k.get("theme") or "").strip() or (k.get("label") or "").strip()
    morceaux = []
    if (k.get("series") or "").strip():
        morceaux.append(k["series"].strip())
    if k.get("session_no"):
        morceaux.append(f"séance {k['session_no']}")
    if _date_fr(k.get("date")):
        morceaux.append(_date_fr(k.get("date")))
    champs = {
        "title": titre,
        "speaker": speaker,
        "subtitle": " · ".join(morceaux),
        "role": "Imam de la mosquée" if imam and not (k.get("speaker") or "").strip() else "",
    }
    o = rendu.normaliser(champs, base)
    if not o["speaker"]:
        o["lower_on"] = False
    if not o["title"]:
        o["intro_on"] = False
    return o


def _defauts_mosquee(m: dict) -> dict:
    try:
        d = json.loads(m.get("habillage_defaults") or "{}")
    except ValueError:
        d = {}
    try:
        return rendu.normaliser({k: v for k, v in d.items() if k in IDENTITE} if isinstance(d, dict) else {})
    except ValueError:
        return dict(rendu.DEFAUTS)


def retenir(conn, m: dict, o: dict) -> None:
    defauts = json.dumps({k: o[k] for k in IDENTITE}, ensure_ascii=False)
    conn.execute(update(Mosque).where(Mosque.id == m["id"]).values(habillage_defaults=defauts))
    orm.done(conn)


# ------------------------------------------------------------------ état


def ligne(conn, kid: int) -> dict | None:
    return orm.first(conn, Habillage, khutba_id=kid)


def _rendues(conn, k: dict) -> dict:
    h = ligne(conn, k["id"])
    rendues = fichier_options_rendues(k)
    try:
        brut = rendues.read_text(encoding="utf-8") if rendues.exists() else ((h or {}).get("options") or "{}")
        d = json.loads(brut)
        return d if isinstance(d, dict) else {}
    except (ValueError, OSError):
        return {}


def decalage_carton(conn, k: dict) -> float:
    """Durée du carton d'ouverture de la vidéo habillée en place (0 s sans rendu, ou sans carton)."""
    try:
        return rendu.chrono(rendu.normaliser(_rendues(conn, k), rendu.DEFAUTS), 0.0).i
    except (ValueError, TypeError):
        return 0.0


def coupe_rendue(conn, k: dict) -> float:
    """Silence coupé au début de la vidéo habillée en place (celui du rendu, pas celui d'aujourd'hui)."""
    try:
        return float((_rendues(conn, k).get("_rendu") or {}).get("coupe") or 0.0)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def decalage_habille(conn, k: dict) -> float:
    """Temps de la séance -> temps de la vidéo habillée : + carton d'ouverture, - silence coupé."""
    return decalage_carton(conn, k) - coupe_rendue(conn, k)


def version_habillee(conn, k: dict) -> dict | None:
    """La vidéo habillée prête, celle qu'on affiche : son décalage (carton, coupe) recale la transcription."""
    if not (ligne(conn, k["id"]) and fichier_video(k).exists()):
        return None
    return {"offset_s": decalage_habille(conn, k), "v": int(fichier_video(k).stat().st_mtime)}


def etat(conn, k: dict, m: dict) -> dict:
    """Ce que l'écran affiche : options (enregistrées ou préremplies), statut, fichiers prêts."""
    h = ligne(conn, k["id"])
    try:
        options = (
            rendu.normaliser(json.loads(h["options"]), rendu.DEFAUTS)
            if h and h["options"] not in ("", "{}")
            else prerempli(conn, k, m)
        )
    except ValueError:
        options = prerempli(conn, k, m)
    video = fichier_video(k)
    # Vidéo habillée en place : elle reste disponible pendant un nouveau rendu, ou après un échec.
    pret = bool(h and video.exists())
    apercu = fichier_apercu(k)
    brand, logo = marque(m)
    sous_titres_vue = langues(conn, k)
    return {
        "state": states.habillage_state(h, pret),
        "options": options,
        "status": (h or {}).get("status") or "",
        "progress": round(float((h or {}).get("progress") or 0), 3),
        "error": (h or {}).get("error") or "",
        "started_at": (h or {}).get("started_at") or "",
        "finished_at": (h or {}).get("finished_at") or "",
        "duration_s": (h or {}).get("duration_s"),
        "video_ready": pret,
        # Pistes téléchargeables : seulement quand la vidéo habillée existe (le .srt est calé sur elle).
        # La complétude de chaque langue, elle, se lit toujours : elle décide du bouton de traduction.
        "subtitles": list(sous_titres_vue["passages"]) if pret else [],
        "subtitles_state": sous_titres_vue["languages"],
        "translation": traduction.etat(k),
        "size_mb": round(video.stat().st_size / 1048576, 1) if pret else None,
        "video_v": int(video.stat().st_mtime) if pret else 0,
        "preview_ready": apercu.exists(),
        "preview_v": int(apercu.stat().st_mtime) if apercu.exists() else 0,
        "has_source": source(k) is not None,
        "silence_cut_s": silence_initial(k),
        "has_logo": logo is not None,
        "mosque": m.get("name") or "",
        "colors": {
            "green": "#{:02X}{:02X}{:02X}".format(*rendu.couleurs(brand)["green"]),
            "gold": "#{:02X}{:02X}{:02X}".format(*rendu.couleurs(brand)["gold"]),
        },
    }


def _enregistrer(conn, k: dict, o: dict, **champs) -> None:
    now = db.now_iso()
    if ligne(conn, k["id"]) is None:
        conn.add(Habillage(mosque_id=k["mosque_id"], khutba_id=k["id"], options="{}", updated_at=now))
        conn.flush()
    conn.execute(
        update(Habillage)
        .where(Habillage.khutba_id == k["id"])
        .values(options=json.dumps(o, ensure_ascii=False), **champs, updated_at=now)
    )
    orm.done(conn)


def sans_chemin(message: str) -> str:
    """Message d'erreur montrable : un chemin de la machine n'en garde que le nom du fichier."""
    return re.sub(r"(?:[A-Za-z]:)?[/\\][^\s:'\"]+", lambda x: Path(x.group(0)).name, message)


# ------------------------------------------------------------------ sous-titres (.srt, à part sur YouTube)


def langues(conn, k: dict, data: dict | None = None) -> dict:
    """Passages et complétude de chaque piste, en une lecture de la session (`data` évite de la relire)."""
    return traduction.plan(conn, k, data)


def pistes(conn, k: dict) -> dict[str, list[dict]]:
    """Passages par langue de la vidéo (corrections et sous-titres ajoutés compris), dans le temps de la session.

    Chaque piste couvre tout le sermon : paroles de la langue telles quelles + tout le reste traduit.
    """
    return langues(conn, k)["passages"]


def langues_disponibles(conn, k: dict) -> list[str]:
    """Langues servies par les .srt (téléchargés) et les .vtt (lus par le lecteur) : celles qui ont un passage.

    Une langue peut être servie avant d'être complète (traduction en cours) : `langues()` dit où elle en est.
    """
    return list(langues(conn, k)["passages"])


def alignements(conn, k: dict) -> dict[str, float]:
    """Décalage des temps de la séance (0 = son début) vers ceux de chaque vidéo : habillée (carton
    d'ouverture, silence coupé), d'origine (la vidéo de la séance, qui commence avec elle : aucun)."""
    return {"habille": decalage_habille(conn, k), "brut": 0.0}


def sous_titres_srt(conn, k: dict, langue: str, brut: bool = False, passages: dict | None = None) -> tuple[str, bytes]:
    """(nom du fichier, contenu UTF-8). Une langue sans sous-titre lève ValueError, avec un message montrable."""
    disponibles = passages if passages is not None else pistes(conn, k)
    if langue not in disponibles:
        raise ValueError(_("No subtitles in this language for this video."))
    texte = sous_titres.srt(sous_titres.cues(disponibles[langue], alignements(conn, k)["brut" if brut else "habille"]))
    if not texte.strip():
        raise ValueError(_("No subtitles in this language for this video."))
    return nom_sous_titres(k, langue, brut), texte.encode("utf-8")


def sous_titres_vtt(conn, k: dict, langue: str, brut: bool = False, passages: dict | None = None) -> bytes:
    """Le WebVTT d'une langue, lu sur place par le `<track>` du lecteur.

    Il ne dépend pas de la vidéo habillée : dès que la transcription existe, le lecteur peut afficher
    les sous-titres (`brut` : alignés sur la vidéo d'origine, sinon sur la vidéo habillée).
    Une langue sans sous-titre lève ValueError ; une langue connue dont plus rien ne tombe dans la
    vidéo rend un fichier vide valide, qu'un lecteur accepte sans erreur."""
    disponibles = passages if passages is not None else pistes(conn, k)
    if langue not in disponibles:
        raise ValueError(_("No subtitles in this language for this video."))
    return sous_titres.vtt(
        sous_titres.cues(disponibles[langue], alignements(conn, k)["brut" if brut else "habille"])
    ).encode("utf-8")


class _HabillageStore(DbRowStore):
    def ensure_row(self, conn, ref: dict) -> None:
        if ligne(conn, ref["id"]) is None:
            conn.add(Habillage(mosque_id=ref["mosque_id"], khutba_id=ref["id"], options="{}", updated_at=db.now_iso()))
            conn.flush()


JOB = Job(
    _HabillageStore(Habillage, "khutba_id", "status", "error"),
    busy_message=lambda: _("a render is already running for this video"),
    thread_name="habillage",
)


def recover_interrupted(conn) -> None:
    """Rendus en cours quand le serveur s'est arrêté : ils ne finiront jamais."""
    JOB.recover_interrupted(conn)


# ------------------------------------------------------------------ actions


def _options(conn, k: dict, brut: dict) -> dict:
    h = ligne(conn, k["id"])
    base = json.loads(h["options"]) if h and h["options"] not in ("", "{}") else rendu.DEFAUTS
    o = rendu.normaliser(brut, base)
    rendu.verifier(o)
    return o


def apercu(conn, k: dict, m: dict, brut: dict) -> dict:
    """Planche d'aperçu (quelques secondes) ; les options sont enregistrées avec."""
    o = _options(conn, k, brut)
    src = source(k)
    if not src:
        raise ValueError(_("source video not found: nothing to dress"))
    orm.done(conn)
    brand, logo = marque(m)
    rendu.apercu(o, src[0], str(fichier_apercu(k)), m.get("name") or "", brand, logo, debut=src[1], fin=src[2])
    _enregistrer(conn, k, o, preview_at=db.now_iso())
    retenir(conn, m, o)
    return o


def _fichier_empreinte(p: str | None) -> list | None:
    if not p:
        return None
    try:
        st = Path(p).stat()
    except OSError:
        return None
    return [str(Path(p).resolve()), st.st_size, int(st.st_mtime)]


def empreinte(k: dict, m: dict) -> dict | None:
    """Tout ce qui, hors options, change l'image rendue : source et ses bornes, nom, couleurs et logo."""
    src = source(k)
    if not src:
        return None
    brand, logo = marque(m)
    return {
        "source": _fichier_empreinte(src[0]),
        "debut": src[1],
        "fin": src[2],
        "coupe": silence_initial(k),
        "mosquee": m.get("name") or "",
        "brand": brand,
        "logo": _fichier_empreinte(logo),
    }


def a_jour(conn, k: dict, m: dict, o: dict) -> bool:
    """La vidéo habillée en place a déjà été rendue avec ces options, cette source et cette marque."""
    h = ligne(conn, k["id"])
    rendues = fichier_options_rendues(k)
    if not (h and h["status"] == JobStatus.READY and fichier_video(k).exists() and rendues.exists()):
        return False
    try:
        d = json.loads(rendues.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False
    vu = d.pop("_rendu", None)
    return vu is not None and vu == empreinte(k, m) and rendu.normaliser(d) == o


def lancer(conn, db_path: str, k: dict, m: dict, brut: dict, user: dict, ip=None, background: bool = True) -> dict:
    """Lance le rendu ; renvoie les options. Rien n'est relancé si la vidéo en place est déjà à jour
    (options, source et marque identiques au dernier rendu réussi) : la clé "_a_jour" le signale."""
    o = _options(conn, k, brut)
    JOB.ensure_idle(conn, k)
    if not source(k):
        raise ValueError(_("source video not found: nothing to dress"))
    if a_jour(conn, k, m, o):
        retenir(conn, m, o)
        return {**o, "_a_jour": True}
    JOB.start(
        conn,
        k,
        _rendre,
        (db_path, k["id"]),
        fields={
            "options": json.dumps(o, ensure_ascii=False),
            "progress": 0.0,
            "error": "",
            "started_at": db.now_iso(),
            "finished_at": "",
            "user_id": user["id"],
        },
        # `retenir` and the audit come right after the running state is recorded, before the render starts.
        before_spawn=lambda: _after_start(conn, k, m, o, user, ip),
        background=background,
    )
    return o


def _after_start(conn, k: dict, m: dict, o: dict, user: dict, ip) -> None:
    retenir(conn, m, o)
    db.audit(
        conn,
        m["id"],
        user["id"],
        "habillage.lance",
        "khutba",
        k["id"],
        ip=ip,
        elements=",".join(e for e in rendu.BOOLEENS if o[e]),
    )


def _rendre(db_path: str, kid: int, log=print) -> None:
    conn = db.connect(db_path)
    k = None
    try:
        h = ligne(conn, kid)
        k = orm.first(conn, Khutba, id=kid)
        assert k is not None
        m = orm.first(conn, Mosque, id=k["mosque_id"])
        o = rendu.normaliser(json.loads(h["options"]))
        src = source(k)
        if not src:
            raise RuntimeError(_("source video not found"))
        brand, logo = marque(m)
        vu = empreinte(k, m or {})  # avant le rendu : une source changée pendant le rendu sera re-rendue
        dernier = [0.0]

        def progres(f: float) -> None:
            if f - dernier[0] >= 0.01:
                dernier[0] = f
                conn.execute(
                    update(Habillage)
                    .where(Habillage.khutba_id == kid)
                    .values(progress=round(f, 3), updated_at=db.now_iso())
                )
                orm.done(conn)

        tmp = fichier_rendu_en_cours(k)
        out = rendu.rendre(
            o,
            src[0],
            str(tmp),
            m.get("name") or "",
            brand,
            logo,
            progres=progres,
            log=lambda msg: log("[habillage]", msg, flush=True),
            debut=src[1],
            fin=src[2],
        )
        duree = rendu.sonder(out).duree
        # Le nouveau rendu remplace l'ancien d'un coup : l'ancienne vidéo est supprimée à cet instant.
        final = fichier_video(k)
        Path(out).replace(final)
        fichier_options_rendues(k).write_text(json.dumps({**o, "_rendu": vu}, ensure_ascii=False), encoding="utf-8")
        out = str(final)
        JOB.mark_ready(conn, k, progress=1, file_path=out, duration_s=round(duree, 1), finished_at=db.now_iso())
        db.audit(conn, m["id"], None, "habillage.pret", "khutba", kid, duree=round(duree))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        if k:
            fichier_rendu_en_cours(k).unlink(missing_ok=True)
        JOB.mark_failed(conn, {"id": kid}, sans_chemin(str(e))[:400], finished_at=db.now_iso())
    finally:
        conn.close()
