"""Day-page components for render2: opener, "Your day" label, journey strip."""
from __future__ import annotations

from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
from docx.oxml.ns import qn

from src.aigv2.guide.model import (ChecklistCard, Fact, JourneyStrip, Link, MarkerRef, Opener, SightseeingCard,
                                   SimpleCard, YourDay)
from src.aigv2.render2 import kit as K
from src.aigv2.render2 import theme as T

LEG_CM = 2.5
LEG_ORN_CM = 2.1
EYEBROW_STYLE = "Day Eyebrow"


def _eyebrow_text(c: Opener) -> str:
    return f"DAY {c.number} {K.DOT.strip()} {c.weekday.upper()}, {c.date.upper()}".replace("  ", " ")


def render_opener(doc, W: float, c: Opener) -> None:
    p = K.np(doc, after=8, align=AL.CENTER)
    K.picture(p, T.asset("logo_v1.png"), 2.7)

    p = K.np(doc, after=6, align=AL.CENTER, keep=True, style=EYEBROW_STYLE)
    K.R(p, K.DIAMOND_GLYPH + K.NB, size=7, color=T.AMBER)
    p.add_run(_eyebrow_text(c))
    K.R(p, K.NB + K.DIAMOND_GLYPH, size=7, color=T.AMBER)

    p = K.np(doc, after=4, align=AL.CENTER, line=1.0, keep=True, style="Heading 1")
    for i, line in enumerate(c.title):
        if i:
            p.add_run().add_break()
        K.R(p, line, font=T.HEAD, size=26, color=T.NAVY, bold=False)
    K.bookmark(p, f"day_{c.number}")

    K.ornament(doc, before=8, after=14, w=2.6)

    if c.intro:
        p = K.np(doc, after=16, align=AL.LEFT, line=1.5)
        K.R(p, c.intro, size=10.5)


def render_your_day(doc, W: float, c: YourDay) -> None:
    p = K.np(doc, after=10, keep=True)
    K.eyebrow(p, "YOUR DAY", size=12, spacing=3)
    K.hairline(p)


def _stop_cell(cell, stop) -> None:
    p = K.np(cell, align=AL.CENTER)
    K.eyebrow(p, stop.label, size=7.5)
    p = K.np(cell, align=AL.CENTER)
    if stop.name.url:
        K.link(p, stop.name.url, stop.name.text, size=13.5, color=T.NAVY, bold=False)
    else:
        K.R(p, stop.name.text, font=T.HEAD, size=13.5, color=T.NAVY)
    if stop.time:
        p = K.np(cell, align=AL.CENTER)
        K.R(p, stop.time, size=8.5, color=T.SLATE)


def _leg_cell(cell, text: str) -> None:
    p = K.np(cell, align=AL.CENTER)
    K.picture(p, K.ASSET_ORN, LEG_ORN_CM)
    if text:
        p = K.np(cell, align=AL.CENTER)
        K.R(p, text, font=T.HEAD, size=11, color=T.SLATE, italic=True)


def render_journey_strip(doc, W: float, c: JourneyStrip) -> None:
    n = len(c.stops)
    if not n:
        return
    legs = n - 1
    stop_w = (W - LEG_CM * legs) / n
    widths = [stop_w if i % 2 == 0 else LEG_CM for i in range(n + legs)]
    t = K.tbl(doc, 1, widths)
    K.row_keep(t.rows[0])
    for i, cell in enumerate(t.rows[0].cells):
        edge = (T.POWDER, 4)
        K.cell_borders(cell, top=edge, bottom=edge)
        K.cell_margins(cell, top=0.25, bottom=0.25, left=0.1, right=0.1)
        K.cell_valign(cell, "center")
        if i % 2 == 0:
            _stop_cell(cell, c.stops[i // 2])
        else:
            k = i // 2
            _leg_cell(cell, c.legs[k] if k < len(c.legs) else "")
        K.close(cell)
    K.spacer(doc, 16)


# ---------- cards (shared helpers are reused by the booking cards) ----------
CARD_PAD = (0.5, 0.75, 0.55, 0.75)  # top, left, bottom, right inside a card (cm)
CARD_BAR = (T.AMBER, 27)
CARD_GAP_PT = 12


def _card(doc, W: float):
    """One-cell white card: amber left bar, pale top/right edges, powder bottom edge; never splits."""
    t = K.tbl(doc, 1, [W], margins=CARD_PAD)
    K.row_keep(t.rows[0])
    cell = t.rows[0].cells[0]
    K.cell_shade(cell, T.WHITE)
    K.borders(cell, l=CARD_BAR, t=(T.CARD_EDGE, 4), b=(T.POWDER, 6), r=(T.CARD_EDGE, 4))
    return t, cell


def _end_card(doc, cell, gap: float = CARD_GAP_PT) -> None:
    K.close(cell, 1)
    K.spacer(doc, gap)


def _inner_w(W: float) -> float:
    return W - CARD_PAD[1] - CARD_PAD[3]


def _eyebrow_line(cell, when: str, part: str | None = None) -> None:
    p = K.np(cell, after=4, keep=True, style="Eyebrow")
    K.R(p, when.upper(), size=8, color=T.GOLD_INK, bold=True, spacing=1.6)
    if part:
        K.R(p, " ", size=8)
        K.R(p, K.DIAMOND_GLYPH, size=5.5, color=T.AMBER)
        K.R(p, " ", size=8)
        K.R(p, part.upper(), size=7.5, color=T.SLATE, bold=True, spacing=1.6)


def _title(cell, name: Link | str, size: float = 20, has_sub: bool = False) -> None:
    link = name if isinstance(name, Link) else Link(text=name)
    p = K.np(cell, after=2 if has_sub else 10, keep=True, line=1.0, style="Heading 3")
    if link.url:
        K.link(p, link.url, link.text, size=size, color=T.NAVY, bold=False)
    else:
        K.R(p, link.text, font=T.HEAD, size=size, color=T.NAVY, bold=False)


def _subtitle(cell, text: str | None) -> None:
    if text:
        K.R(K.np(cell, after=10, keep=True), text, font=T.HEAD, size=13, italic=True, color=T.SLATE)


def _body(cell, text: str, after: float = 2) -> None:
    if text:
        K.R(K.np(cell, after=after, line=1.45), text, size=10)


def _glance(cell, inner_w: float, facts: list[Fact]) -> None:
    """Two-column label-over-value grid with powder hairlines; odd count leaves the last cell empty."""
    if not facts:
        return
    gap = 0.8
    cw = (inner_w - gap) / 2
    t = K.tbl(cell, -(-len(facts) // 2), [cw, gap, cw], margins=(0.13, 0, 0.13, 0))
    for i, f in enumerate(facts):
        r, c = divmod(i, 2)
        fc = t.rows[r].cells[c * 2]
        K.borders(fc, t=(T.POWDER, 4) if r == 0 else None, b=(T.POWDER, 4))
        K.R(K.np(fc, after=2), f.label.upper(), size=7, color=T.SLATE, bold=True, spacing=1.4)
        vp = K.np(fc)
        if f.link and f.link.url:
            K.link(vp, f.link.url, f.value, size=13, color=T.NAVY, bold=False)
        else:
            K.R(vp, f.value, font=T.HEAD, size=13, color=T.NAVY)
    if len(facts) % 2:
        K.borders(t.rows[-1].cells[2], t=None, b=None)
    K.spacer(cell, 10)


def _tips(cell, tips: list[str]) -> None:
    if not tips:
        return
    p = K.np(cell, before=8, after=5, keep=True)
    K.R(p, "GOOD TO KNOW", size=7.5, color=T.ROYAL, bold=True, spacing=1.8)
    for tip in tips:
        p = K.diamond_item(cell, tip, size=9.5, after=3)
        p.paragraph_format.line_spacing = 1.38


def _markers(cell, markers: list[MarkerRef]) -> None:
    for m in markers:
        K.review_marker(cell, m.kind, m.text)


def render_sightseeing_card(doc, W: float, c: SightseeingCard) -> None:
    _, cell = _card(doc, W)
    _eyebrow_line(cell, c.when, c.part)
    _title(cell, c.name, has_sub=bool(c.subtitle))
    _subtitle(cell, c.subtitle)
    _glance(cell, _inner_w(W), c.facts)
    _markers(cell, c.markers)
    _body(cell, c.text)
    _tips(cell, c.tips)
    _end_card(doc, cell)


def render_simple_card(doc, W: float, c: SimpleCard) -> None:
    _, cell = _card(doc, W)
    _eyebrow_line(cell, c.when, c.part)
    _title(cell, c.heading)
    _body(cell, c.text, after=0)
    _end_card(doc, cell)


def render_checklist_card(doc, W: float, c: ChecklistCard) -> None:
    _, cell = _card(doc, W)
    _eyebrow_line(cell, c.when, c.kind)
    _title(cell, c.title)
    _body(cell, c.lead, after=6)
    if c.items:
        half = -(-len(c.items) // 2)
        gap = 0.6
        cw = (_inner_w(W) - gap) / 2
        nt = K.tbl(cell, 1, [cw, gap, cw])
        for ci, chunk in ((0, c.items[:half]), (2, c.items[half:])):
            cc = nt.rows[0].cells[ci]
            for item in chunk:
                p = K.diamond_item(cc, item, size=10, after=3)
                p.paragraph_format.line_spacing = 1.35
            K.close(cc, 1)
    _end_card(doc, cell)
