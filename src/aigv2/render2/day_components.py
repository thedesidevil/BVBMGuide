"""Day-page components for render2: opener, "Your day" label, journey strip."""
from __future__ import annotations

from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
from docx.oxml.ns import qn

from src.aigv2.guide.model import JourneyStrip, Opener, YourDay
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
