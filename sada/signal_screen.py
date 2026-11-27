"""The reconnection screen: what the destinations receive while the picture of the live is gone.

A fixed Sada screen — the Sadā logo, "Reconnexion en cours…" in French and in Arabic, on a plain dark background. It
is not one of the mosque's screens (nothing in `screens.py`, no template, no customisation): whoever watches only
needs to know that the broadcast is still there and will come back. Drawn once, at the size of the programme, and
looped by the encoder (see `Encoder.fallback_cmd`).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .paths import ASSETS, FONTS
from .text import RAQM, shaped

BACKGROUND = (0x12, 0x26, 0x1E)  # the night green of the Sada logo kit (assets/logo/sada-nuit.svg)
GOLD = (0xE2, 0xC2, 0x7A)
IVORY = (0xF7, 0xF3, 0xEA)
LOGO = ASSETS / "logo" / "sada-transparent.png"  # the mark, rendered from sada-transparent.svg (gold + ivory)

TEXT_FR = "Reconnexion en cours…"
TEXT_AR = "إعادة الاتصال جارية…"


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    layout = ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC
    return ImageFont.truetype(str(path), size, layout_engine=layout)


def _centred(draw: ImageDraw.ImageDraw, text: str, font, fill, cx: int, top: int) -> int:
    """Draws `text` centred on `cx`, its top at `top`; returns its height."""
    shown, opts = shaped(text)
    left, up, right, down = draw.textbbox((0, 0), shown, font=font, **opts)
    draw.text((cx - (left + right) / 2, top - up), shown, font=font, fill=fill, **opts)
    return down - up


def render(width: int, height: int) -> Image.Image:
    """The screen at `width` x `height` (RGB)."""
    img = Image.new("RGB", (width, height), BACKGROUND)
    unit = height / 720  # everything is laid out for 720 lines and scaled
    cx = width // 2
    logo = Image.open(LOGO).convert("RGBA")
    logo_w = min(int(width * 0.42), int(520 * unit * 1.2))
    logo = logo.resize((logo_w, round(logo.height * logo_w / logo.width)), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(img)
    fr = _font(FONTS / "SourceSans3-Semibold.ttf", max(12, round(40 * unit)))
    ar = _font(FONTS / "Amiri-Regular.ttf", max(12, round(46 * unit)))
    gap = round(34 * unit)
    # heights first, so that the whole block (mark, rule, two lines) sits on the vertical centre
    h_fr = draw.textbbox((0, 0), TEXT_FR, font=fr)[3] - draw.textbbox((0, 0), TEXT_FR, font=fr)[1]
    shown_ar, opts = shaped(TEXT_AR)
    box_ar = draw.textbbox((0, 0), shown_ar, font=ar, **opts)
    h_ar = box_ar[3] - box_ar[1]
    block = logo.height + gap + h_fr + round(18 * unit) + h_ar
    y = max(0, (height - block) // 2)
    img.paste(logo, (cx - logo.width // 2, y), logo)
    y += logo.height + gap
    y += _centred(draw, TEXT_FR, fr, IVORY, cx, y) + round(18 * unit)
    _centred(draw, TEXT_AR, ar, GOLD, cx, y)
    return img


def write(path: str | Path, width: int, height: int) -> str:
    """Renders the screen into `path` (PNG, atomically) and returns the path."""
    path = str(path)
    tmp = f"{path}.tmp.png"
    render(width, height).save(tmp, "PNG", compress_level=6)
    Path(tmp).replace(path)
    return path
