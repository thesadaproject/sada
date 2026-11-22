"""The wording of the printed prayer-time calendar (PDF), one table per language.

The calendar is a printed document: its language is a choice of the mosque, not the one of the
person who downloads it. French is the default; a future country / language setting of the
mosque only has to pass its code to `labels()` (and to `prayer_export.pdf_bytes(..., lang=)`),
and a new language is one more entry of `LABELS` (`DEFAULT` fills the keys it does not translate).

The Arabic names of the prayers do not depend on the language: they are printed under each column.
"""

from __future__ import annotations

DEFAULT_LANG = "fr"

# Arabic names printed under the column titles, by column key.
PRAYER_AR = {
    "fajr": "الفجر",
    "sunrise": "الشروق",
    "dhuhr": "الظهر",
    "asr": "العصر",
    "maghrib": "المغرب",
    "isha": "العشاء",
}

LABELS: dict[str, dict] = {
    "fr": {
        "prayer_times": "Horaires de prière",
        "col": {
            "date": "Date",
            "hijri": "Hégire",
            "fajr": "Fajr",
            "sunrise": "Chourouk",
            "dhuhr": "Dhuhr",
            "asr": "Asr",
            "maghrib": "Maghrib",
            "isha": "Isha",
        },
        "weekdays": ("Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim."),
        "months": (
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
        ),  # fmt: skip
        "hijri_months": (
            "Mouharram",
            "Safar",
            "Rabi' al-awwal",
            "Rabi' ath-thani",
            "Joumada al-oula",
            "Joumada ath-thania",
            "Rajab",
            "Chaabane",
            "Ramadan",
            "Chawwal",
            "Dhou al-qa'da",
            "Dhou al-hijja",
        ),  # fmt: skip
        "jumua": "Jumu'a",
        "night": "Nuit {n}",
        "legend_friday": "Prière du vendredi (Jumu'a)",
        "legend_odd_nights": "Nuits impaires des dix derniers jours",
        # No single night is designated: opinions differ, so the legend only says where it is sought.
        "legend_note": "Laylat al-Qadr est recherchée dans les dix dernières nuits, notamment les nuits impaires.",
        "legend_maghrib": "Les nuits impaires commencent au Maghrib, la veille au soir.",
        "online": "Horaires en ligne, toujours à jour",
        "scan": "Scannez le code avec votre téléphone.",
        "computed": "Horaires calculés.",
        "manual": "Horaires fixés par la mosquée.",
        "first": "1er",
        # the public pages (month, refusals): Sada's night frame, in the mosque's language
        "page": {
            "missing_title": "Page introuvable",
            "missing_text": "Cette mosquée n'existe pas, ou elle ne publie pas ses horaires ici.",
            "mawaqit_title": "Horaires sur Mawaqit",
            "mawaqit_text": "Cette mosquée publie ses horaires sur Mawaqit.",
            "mawaqit_button": "Voir sur Mawaqit",
            "month_title": "Mois invalide",
            "month_text": "Un mois s'écrit ainsi : 2027-03 (l'année, un tiret, le mois).",
            "site": "Découvrir Sada",
            "kicker": "Horaires de prière",
            "screen": "Écran des horaires",
            "pdf": "Télécharger le PDF",
            "csv": "Télécharger le CSV",
            "ramadan": "Calendrier du Ramadan (PDF)",
            "empty": "Aucun horaire saisi pour ce mois.",
            "prev": "Mois précédent",
            "next": "Mois suivant",
            "today": "Aujourd'hui",
        },
    },
    "en": {
        "prayer_times": "Prayer times",
        "col": {
            "date": "Date",
            "hijri": "Hijri",
            "fajr": "Fajr",
            "sunrise": "Sunrise",
            "dhuhr": "Dhuhr",
            "asr": "Asr",
            "maghrib": "Maghrib",
            "isha": "Isha",
        },
        "weekdays": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
        "months": (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),  # fmt: skip
        "hijri_months": (
            "Muharram",
            "Safar",
            "Rabi' al-Awwal",
            "Rabi' al-Thani",
            "Jumada al-Ula",
            "Jumada al-Akhirah",
            "Rajab",
            "Sha'ban",
            "Ramadan",
            "Shawwal",
            "Dhu al-Qa'dah",
            "Dhu al-Hijjah",
        ),  # fmt: skip
        "jumua": "Jumu'a",
        "night": "Night {n}",
        "legend_friday": "Friday prayer",
        "legend_odd_nights": "Odd nights of the last ten days",
        "legend_note": "Laylat al-Qadr is sought in the last ten nights, especially the odd nights.",
        "legend_maghrib": "The odd nights begin at Maghrib, the evening before.",
        "online": "Times online, always up to date",
        "scan": "Scan the code with your phone.",
        "computed": "Calculated prayer times.",
        "manual": "Times set by the mosque.",
        "first": "1",
        "page": {
            "missing_title": "Page not found",
            "missing_text": "This mosque does not exist, or it does not publish its times here.",
            "mawaqit_title": "Times on Mawaqit",
            "mawaqit_text": "This mosque publishes its times on Mawaqit.",
            "mawaqit_button": "See on Mawaqit",
            "month_title": "Invalid month",
            "month_text": "A month looks like 2027-03 (the year, a dash, the month).",
            "site": "Discover Sada",
            "kicker": "Prayer times",
            "screen": "Times screen",
            "pdf": "Download the PDF",
            "csv": "Download the CSV",
            "ramadan": "Ramadan calendar (PDF)",
            "empty": "No prayer time entered for this month.",
            "prev": "Previous month",
            "next": "Next month",
            "today": "Today",
        },
    },
}


def labels(lang: str | None = None) -> dict:
    """The table of a language; an unknown code gives the default language (French)."""
    return LABELS.get((lang or "").split("-")[0].lower()) or LABELS[DEFAULT_LANG]
