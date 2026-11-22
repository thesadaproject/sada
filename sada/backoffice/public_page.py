"""The public, read-only pages of a mosque's own timetable: one month (table, PDF / CSV downloads) and the
refusals (unknown or unpublished mosque, Mawaqit, malformed month).

Same frame as the screen (night ground, ivory ink, EB Garamond / Source Sans 3 / Amiri, the stylesheet of
`prayer_screen`), in the mosque's language (French by default, whatever the reader's browser says), with
the Arabic name of each prayer under its column like the PDF. Nothing to fetch but the stylesheet and the
fonts, no script. Everything written into the page is escaped.
"""

from __future__ import annotations

import datetime as dt
from html import escape
from urllib.parse import quote

from hijridate import Gregorian

from . import identity
from . import prayer_export as export
from .prayer_labels import DEFAULT_LANG, PRAYER_AR, labels
from .prayer_screen import SITE, WORDMARK, doc, logo_img


def _shift(month: str, n: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    m += n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def refused(body: dict, status: int, lang: str = DEFAULT_LANG) -> str:
    """The page of a refusal: an unknown or unpublished mosque (404), a Mawaqit mosque (404, linking to its
    page), a malformed month (422). Sada's night frame, the word-mark, a sentence in the mosque's language
    and a way out to sadakhutbah.org.

    Which of a missing and an unpublished mosque it is stays unsaid: the answer is the same."""
    L = labels(lang)["page"]
    url = body.get("mawaqit_url") or ""
    if status == 422:
        title, text, actions = L["month_title"], L["month_text"], ""
    elif status == 404 and url.startswith("https://"):
        title, text = L["mawaqit_title"], L["mawaqit_text"]
        actions = (
            f'<a class="btn main" href="{escape(url, quote=True)}" rel="noopener">{escape(L["mawaqit_button"])}</a>'
        )
    else:
        title, text, actions = L["missing_title"], L["missing_text"], ""
    site = f'<a class="btn{"" if actions else " main"}" href="https://{SITE}" rel="noopener">{SITE}</a>'
    body_html = (
        f'<main class="refuse" role="main"><header class="mark">{WORDMARK}</header>'
        f'<section class="card"><h1>{escape(title)}</h1><p>{escape(text)}</p>'
        f'<div class="actions">{actions}{site}</div></section></main>'
    )
    return doc(f"{title} · Sadā", body_html)


def render(
    slug: str, mosque: dict, month: str, rows: list[dict], st: dict, who: dict | None = None, lang: str = DEFAULT_LANG
) -> str:
    """The month. `who` is the mosque's identity ({accent, accent2, logo}); `st` the prayer settings."""
    L = labels(lang)
    P = L["page"]
    who = who or {}
    base = f"/api/v1/public/mosques/{quote(slug)}/prayer-times"
    first = dt.date.fromisoformat(month + "-01")
    title = f"{L['months'][first.month - 1].capitalize()} {first.year}"
    name = escape(mosque.get("name") or "")
    prev_m, next_m = _shift(month, -1), _shift(month, 1)
    cols = (
        ("date", "d"),
        ("hijri", "h"),
        ("fajr", ""),
        ("sunrise", "sun"),
        ("dhuhr", ""),
        ("asr", ""),
        ("maghrib", ""),
        ("isha", ""),
    )
    head = "".join(
        f'<th scope="col" class="{c}"><span class="fr">{escape(L["col"][k])}</span>'
        + (f'<span class="ar" lang="ar" dir="rtl">{PRAYER_AR[k]}</span>' if k in PRAYER_AR else "")
        + "</th>"
        for k, c in cols
    )
    today = dt.date.today()
    lines = []
    for r in rows:
        d = r["date"]
        h = Gregorian.fromdate(d).to_hijri()
        fri = d.weekday() == 4
        night = h.month == export.RAMADAN and h.day in export.ODD_NIGHT_EVES  # sober mark, no single night named
        t = r["times"]
        jum = [escape(x) for x in r["jumua"]] if fri and r["jumua"] else []
        # Jumu'a times on one line, never wrapped: a second line would stretch the row
        dhuhr = f'<span class="jm">{"<i>/</i>".join(jum)}</span>' if jum else escape(t["dhuhr"] or "-")
        hij_full = escape(export.hijri_text(d, lang))
        hij_short = escape(f"{h.day} {L['hijri_short'][h.month - 1]}")
        tag = f'<span class="tag">{escape(L["night"].format(n=h.day + 1))}</span>' if night else ""
        cls = " ".join(c for c in ("fri" if fri else "", "odd" if night else "", "today" if d == today else "") if c)
        cells = "".join(
            f'<td class="{"sun" if k == "sunrise" else ""}">{escape(v) if v else "-"}</td>' if k != "dhuhr" else f"<td>{dhuhr}</td>"
            for k, v in (("fajr", t["fajr"]), ("sunrise", t["sunrise"]), ("dhuhr", t["dhuhr"]), ("asr", t["asr"]),
                         ("maghrib", t["maghrib"]), ("isha", t["isha"]))
        )  # fmt: skip
        jumua = f' <span class="tag jt">{escape(L["jumua"])}</span>' if fri else ""
        lines.append(
            f'<tr class="{cls}"><th scope="row" class="d"><span class="gd">{escape(L["weekdays"][d.weekday()])} {d.day}</span>{jumua}'
            f'<span class="hj" aria-hidden="true">{hij_short}</span></th>'
            f'<td class="h">{hij_full}{tag}</td>{cells}</tr>'
        )
    table = (
        f'<div class="wrap"><table class="month"><thead><tr>{head}</tr></thead><tbody>{"".join(lines)}</tbody></table></div>'
        if rows
        else f'<p class="none" role="status">{escape(P["empty"])}</p>'
    )
    q = f"month={month}"
    # One discreet menu for the three downloads (no script: a <details>), the screen as a secondary link.
    buttons = (
        f'<div class="dl"><details class="dlmenu"><summary class="btn">{escape(P["download"])}</summary>'
        f'<div class="menu"><a href="{base}/export?format=pdf&amp;{q}" download>{escape(P["pdf"])}</a>'
        f'<a href="{base}/export?format=csv&amp;{q}" download>{escape(P["csv"])}</a>'
        f'<a href="{base}/export?format=pdf&amp;ramadan=1" download>{escape(P["ramadan"])}</a></div></details>'
        f'<a class="alt" href="{base}/page">{escape(P["screen"])}</a></div>'
    )
    nav = (
        f'<nav class="months" aria-label="{escape(title)}"><a class="btn" href="{base}/page?month={prev_m}" rel="prev" '
        f'aria-label="{escape(P["prev"])}">&larr;</a><strong>{escape(title)}</strong>'
        f'<a class="btn" href="{base}/page?month={next_m}" rel="next" aria-label="{escape(P["next"])}">&rarr;</a></nav>'
    )
    sub = escape(export.hijri_span(rows, lang)) if rows else ""
    body = (
        f'<div class="monthpage"><header class="mhead"><div class="who">{logo_img(slug, who)}<div>'
        f'<p class="kicker">{escape(P["kicker"])}</p><h1 class="mosque">{name}</h1><p class="sub">{sub}</p></div></div></header>'
        f"<main>{nav}{buttons}{table}</main>"
        f'<footer class="foot"><span class="brand">{WORDMARK}</span></footer></div>'
    )
    style = identity.css_vars(who.get("accent", ""), who.get("accent2", ""))
    return doc(f"{mosque.get('name') or ''} - {title}", body, "", style)
