"""Meal blocks for render2: the Harbour restaurant card and the staff-only placeholder."""
from __future__ import annotations

import re

from docx.enum.text import WD_ALIGN_PARAGRAPH as AL

from src.aigv2.guide.model import MarkerRef, MealBlock, PlaceholderMeal, Restaurant
from src.aigv2.render2 import kit as K
from src.aigv2.render2 import theme as T
from src.aigv2.render2.styles import PLACEHOLDER_STYLE, PLACEHOLDER_TABLE

PAD = (0.5, 0.75, 0.55, 0.75)  # top, left, bottom, right inside the card (cm)
STACK_W = 4.4
GAP_PT = 12
MAX_PLACEHOLDERS = 6
BAR = (T.ROYAL, 27)
_PT_CM = 1 / 28.35
_PER_PERSON = re.compile(r"\s*\b(per person|pp)\b\.?", re.I)
DASH = "–"


def _head(doc, eyebrow: str, heading: str) -> None:
    p = K.np(doc, before=10, after=2, align=AL.CENTER, keep=True)
    K.R(p, eyebrow, size=8, color=T.ROYAL, bold=True, caps=True, spacing=2.0)
    p = K.np(doc, after=0, align=AL.CENTER, keep=True, style="Heading 2")
    K.R(p, heading, font=T.HEAD, size=22, color=T.NAVY, bold=False)
    p = K.ornament(doc, before=3, after=12, w=2.4)
    p.paragraph_format.keep_with_next = True


def _nested(cell, W: float, n: int):
    lw = W - PAD[1] - PAD[3] - STACK_W
    t = K.tbl(cell, max(n, 1), [lw, STACK_W])
    for i, row in enumerate(t.rows):
        a, b = row.cells
        top = 14 if i else 2
        bot = 14 if i < n - 1 else 2
        K.cell_margins(a, top=top * _PT_CM, bottom=bot * _PT_CM, right=0.5)
        K.cell_margins(b, top=top * _PT_CM + 0.05, bottom=bot * _PT_CM)
        if i:
            for x in (a, b):
                K.borders(x, t=(T.HARBOUR_EDGE, 6))
    return t


def _stack(cell, label: str, value: str, *, big: bool = False, after: float = 5, color: str = T.ROYAL,
           style=None, italic=None, label_color: str = T.SLATE) -> None:
    p = K.np(cell, align=AL.RIGHT, style=style)
    K.R(p, label, size=6.5, color=label_color, bold=True, spacing=1.3, italic=italic)
    p = K.np(cell, align=AL.RIGHT, after=after, style=style)
    if big:
        K.R(p, value, font=T.HEAD, size=13.5, color=color, bold=True, italic=italic)
    else:
        K.R(p, value, size=9, color=color, italic=italic)


_APPROX = re.compile(r"(?<![A-Za-z])(approximately|approx\.?|about|around)(?![A-Za-z])|~", re.I)
_BASIS = (("PER PERSON", re.compile(r"(?<![A-Za-z])per\s+person(?![A-Za-z])|(?<![A-Za-z])p\.p\.|(?<![A-Za-z])pp(?![A-Za-z])|/\s*person", re.I)),
          ("FOR TWO", re.compile(r"(?<![A-Za-z])(for\s+(two|2|(a\s+)?couple)|per\s+couple)(?![A-Za-z])", re.I)),
          ("PER NIGHT", re.compile(r"(?<![A-Za-z])per\s+night(?![A-Za-z])", re.I)))


def _price(price) -> tuple[str, str]:
    """(label, value) for the price stack; the basis (person/two/night) and 'approx' come from the text."""
    if not isinstance(price, str) or not price.strip():
        return "PER PERSON", DASH
    text = price.strip()
    label = "PER PERSON"  # the library's default basis
    for name, rx in _BASIS:
        if rx.search(text):
            label = name
            text = rx.sub(" ", text)
            break
    if _APPROX.search(text):
        label += ", APPROX."
        text = _APPROX.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.")
    return label, (text or DASH)


def _left(cell, r: Restaurant) -> None:
    """Left cell; one VERIFY staff marker per missing field (price, hours, travel)."""
    p = K.np(cell, after=5, line=1.0)
    if r.maps_url:
        K.link(p, r.maps_url, r.name, size=18, color=T.NAVY, bold=False, ul=T.ROYAL)
    else:
        K.R(p, r.name, font=T.HEAD, size=18, color=T.NAVY)
    labels = list(r.cuisines) + (["Veg-friendly"] if r.veg else [])
    if labels:
        K.chips(K.np(cell, after=7), labels, size=7.5)
    if r.text:
        K.R(K.np(cell, after=5, line=1.45), r.text, size=10)
    if isinstance(r.price, MarkerRef):
        K.review_marker(cell, r.price.kind, r.price.text)
    if r.must_try:
        p = K.np(cell, after=0, line=1.4)
        K.R(p, "Must try  ", font=T.HEAD, size=12, italic=True, bold=True, color=T.ROYAL)
        K.R(p, r.must_try, size=9.5)
    for missing, what in ((r.price is None, "price"), (not r.hours, "opening hours"), (not r.travel, "travel time")):
        if missing:
            K.review_marker(cell, "VERIFY", f"{r.name}: {what}")


def render_meal_block(doc, W: float, block: MealBlock) -> None:
    if not block.restaurants:  # never a blank card: fall back to the staff placeholder
        render_placeholder_meal(doc, W, PlaceholderMeal(meal=block.meal, eyebrow=block.eyebrow,
                                                        heading=block.heading, count=3))
        return
    _head(doc, block.eyebrow, block.heading)
    t = K.tbl(doc, 1, [W], margins=PAD)
    K.row_keep(t.rows[0])
    c = t.rows[0].cells[0]
    K.cell_shade(c, T.HARBOUR_FILL)
    K.borders(c, l=BAR, t=(T.HARBOUR_EDGE, 4), b=(T.HARBOUR_EDGE, 6), r=(T.HARBOUR_EDGE, 4))
    rs = block.restaurants
    nt = _nested(c, W, len(rs))
    for row, r in zip(nt.rows, rs):
        a, b = row.cells
        _left(a, r)
        label, value = _price(r.price)
        _stack(b, label, value, big=True)
        _stack(b, "OPEN", r.hours or DASH)
        _stack(b, "FROM HERE", r.travel or DASH, after=0)
        K.close(a, 1)
        K.close(b, 1)
    K.close(c, 1)
    K.spacer(doc, GAP_PT)


def render_placeholder_meal(doc, W: float, block: PlaceholderMeal) -> None:
    _head(doc, block.eyebrow, block.heading)
    K.review_marker(doc, "ADD_RESTAURANT", block.heading).paragraph_format.keep_with_next = True
    t = K.tbl(doc, 1, [W], margins=PAD)
    t.style = doc.styles[PLACEHOLDER_TABLE]
    K.row_keep(t.rows[0])
    c = t.rows[0].cells[0]
    K.cell_shade(c, T.FROST)
    K.cell_borders(c, left=(T.ROYAL, 12, "dashed"), top=(T.POWDER, 8, "dashed"), bottom=(T.POWDER, 8, "dashed"),
                   right=(T.POWDER, 8, "dashed"))
    n = min(max(block.count, 1), MAX_PLACEHOLDERS)  # count is clamped to 1..6
    nt = _nested(c, W, n)
    S = PLACEHOLDER_STYLE
    for i, row in enumerate(nt.rows):
        a, b = row.cells
        if i:
            for x in (a, b):
                K.cell_borders(x, top=(T.POWDER, 6, "dashed"))
        K.R(K.np(a, after=3, style=S), f"ADD RESTAURANT {i + 1}", size=7.5, color=T.ROYAL, bold=True, italic=False,
            spacing=1.8)
        K.R(K.np(a, after=5, line=1.0, style=S), "Restaurant name (Maps link)", font=T.HEAD, size=18, italic=True,
            color=T.SLATE)
        K.R(K.np(a, after=7, style=S), "Cuisine · Veg-friendly?", size=7.5, italic=True, color=T.SLATE)
        K.R(K.np(a, after=0, line=1.45, style=S),
            "Two lines on the setting and why it suits this family, in the guide's voice.", size=10, italic=True,
            color=T.SLATE)
        _stack(b, "PER PERSON", "INR –", big=True, style=S, italic=True, color=T.SLATE)
        _stack(b, "OPEN", "– : –", style=S, italic=True, color=T.SLATE)
        _stack(b, "FROM HERE", "– min", after=0, style=S, italic=True, color=T.SLATE)
        K.close(a, 1)
        K.close(b, 1)
    K.close(c, 1)
    K.spacer(doc, GAP_PT)
