"""The visual identity of a mosque on its public prayer-time pages (screen, month, PDF).

Sada stays the frame (typeface, night-green ground, discreet emblem in the foot). The mosque brings
a logo and one or two accent colours; when it brings none, Sada's own gold and green apply.

Whatever colour a mosque picks, the text drawn with it has to be readable. This module therefore never
hands a raw colour to a page: it derives, from the colour, the variants each surface needs, and
checks them against the WCAG 2 contrast ratio.

- `on_dark(c)`   the colour as text / line on the night ground (lightened until 4.5:1).
- `on_light(c)`  the colour as text on white or paper (darkened until 4.5:1).
- `ink_on(c)`    the ink (dark or light) that reads best on a surface painted with `c`.
"""

from __future__ import annotations

import re

SADA_ACCENT = "#e2c27a"  # leaf gold
SADA_ACCENT2 = "#3d6b57"  # green
NIGHT = "#0b1a14"
DEEP = "#1c3a2e"  # panels of the dark pages
PAPER = "#f7f3ea"
WHITE = "#ffffff"
INK_DARK = "#12261e"
INK_LIGHT = "#f0ead9"
MIN_TEXT = 4.5  # WCAG AA, normal text

_HEX = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def normalize(value: str | None) -> str:
    """'#RRGGBB' lower case; '' stays ''. Anything else is refused (ValueError), never stored."""
    v = (value or "").strip()
    if not v:
        return ""
    m = _HEX.match(v)
    if not m:
        raise ValueError(v)
    h = m.group(1).lower()
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return "#" + h


def rgb(color: str) -> tuple[int, int, int]:
    c = normalize(color)
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def hexa(r: float, g: float, b: float) -> str:
    r, g, b = (max(0, min(255, round(v))) for v in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def luminance(color: str) -> float:
    def lin(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(v) for v in rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def mix(a: str, b: str, t: float) -> str:
    """a moved toward b by t (0..1)."""
    ra, rb = rgb(a), rgb(b)
    return hexa(*(x + (y - x) * t for x, y in zip(ra, rb, strict=True)))


def _shift_until(color: str, target: str, ground: str, minimum: float) -> str:
    """Move `color` toward `target` (white or black) in small steps until it reads on `ground`."""
    if contrast(color, ground) >= minimum:
        return color
    for i in range(1, 21):
        c = mix(color, target, i / 20)
        if contrast(c, ground) >= minimum:
            return c
    return target


def on_dark(color: str, ground: str = NIGHT, minimum: float = MIN_TEXT) -> str:
    return _shift_until(color, "#ffffff", ground, minimum)


def on_light(color: str, ground: str = WHITE, minimum: float = MIN_TEXT) -> str:
    return _shift_until(color, "#000000", ground, minimum)


def ink_on(color: str) -> str:
    """Dark or light ink, whichever reads better on `color`."""
    return INK_DARK if contrast(INK_DARK, color) >= contrast(INK_LIGHT, color) else INK_LIGHT


def surface(color: str, minimum: float = MIN_TEXT) -> tuple[str, str]:
    """(fill, ink) for a surface painted with `color` and written on. A middling colour may reach only
    about 3.6:1 with either ink; it is then moved toward white or black, as little as needed, so the
    text on it always reaches `minimum`."""
    toward = "#ffffff" if luminance(color) > 0.195 else "#000000"
    for i in range(21):
        c = mix(color, toward, i / 20)
        ink = ink_on(c)
        if contrast(ink, c) >= minimum:
            return c, ink
    return toward, ink_on(toward)


def palette(accent: str = "", accent2: str = "") -> dict[str, str]:
    """Every colour the public pages use, derived from the mosque's two (either may be empty).

    Keys: accent (as chosen), accent2, on_dark / on_dark2 (text on the night ground), on_deep (text on
    the dark panels), fill_ink (ink on a surface painted with the accent), on_light / on_light2 (text
    on white), light_fill_ink.
    """
    a = normalize(accent) or SADA_ACCENT
    b = normalize(accent2) or SADA_ACCENT2
    fill, fill_ink = surface(a)
    fill2, fill2_ink = surface(b)
    return {
        "accent": a,
        "accent2": b,
        "on_dark": on_dark(a, DEEP),  # DEEP is the lighter of the two grounds: passing there passes on night
        "on_dark2": on_dark(b, DEEP),
        "fill": fill,
        "fill_ink": fill_ink,
        "fill2": fill2,
        "fill2_ink": fill2_ink,
        "on_light": on_light(a, PAPER),
        "on_light2": on_light(b, PAPER),
    }


def css_vars(accent: str = "", accent2: str = "") -> str:
    """The custom properties the public pages read (`style` attribute of <body>); empty for Sada's own,
    whose values are the stylesheet's defaults."""
    if not (normalize(accent) or normalize(accent2)):
        return ""
    p = palette(accent, accent2)
    return (
        f"--accent:{p['on_dark']};--accent-fill:{p['fill']};--accent-ink:{p['fill_ink']};"
        f"--accent2:{p['on_dark2']};--accent2-fill:{p['fill2']};--accent2-ink:{p['fill2_ink']}"
    )
