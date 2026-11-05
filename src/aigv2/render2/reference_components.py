"""Reference-section components for render2 (first half): opener, fact row, titled paras, panels, app grid,
checklist groups. Google-Docs-safe: tables, paragraph borders and diamond glyphs only (no boxes, no run borders)."""
from __future__ import annotations

import re
from typing import Callable, Optional, Sequence

from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from src.aigv2.guide.model import (AppGrid, ChecklistGroups, ContactCards, DishGrid, DosDonts, EmergencyStrip,
                                   FactRowBlock, Link, NotePanel, PhraseTable, PlaceGroups, ReferenceOpener,
                                   SouvenirGrid, TipPanel, TitledParas)
from src.aigv2.render2 import kit as K
from src.aigv2.render2.day_components import _card, _end_card, _inner_w
from src.aigv2.render2 import theme as T

PANEL_PAD = (0.32, 0.5, 0.36, 0.5)  # top, left, bottom, right (cm)
PANEL_GAP_PT = 10
_PT_CM = 28.35


def _grid(doc, W: float, items: Sequence, render: Callable, ncols: int = 2, gap: float = 1.0,
          after_row: float = 14, split_long: Callable = None):
    """Airy grid of independent blocks; rows can't split; an odd count leaves the last cell empty."""
    if not items:
        return None
    ncols = 1 if len(items) == 1 else ncols
    cw = (W - gap * (ncols - 1)) / ncols
    widths: list[float] = []
    for i in range(ncols):
        widths += [cw] + ([gap] if i < ncols - 1 else [])
    rows = -(-len(items) // ncols)
    t = K.tbl(doc, rows, widths)
    for i, it in enumerate(items):
        r, c = divmod(i, ncols)
        cell = t.rows[r].cells[c * 2]
        if r < rows - 1:
            K.cell_margins(cell, bottom=after_row / _PT_CM)
        render(cell, cw, it)
        K.close(cell, 1)
    for r, row in enumerate(t.rows):  # a long item may break across pages; short ones stay whole
        long_row = split_long and any(split_long(it) for it in items[r * ncols:(r + 1) * ncols])
        trPr = row._tr.get_or_add_trPr()
        if long_row:
            for e in trPr.findall(qn("w:cantSplit")):  # K.tbl marks every row unsplittable
                trPr.remove(e)
        else:
            K.row_keep(row)
    for row in t.rows:  # empty cells (gutters, padding) must end in a paragraph
        for cell in row.cells:
            K.close(cell, 1)
    K.spacer(doc, 10)
    return t


def render_reference_opener(doc, W: float, c: ReferenceOpener, *, bookmark: Optional[str] = None) -> None:
    p = K.diamond_eyebrow(doc, c.eyebrow, color=T.GOLD_INK, before=0, after=6)
    p.alignment = AL.CENTER
    K.R(p, K.NB + K.DIAMOND_GLYPH, size=6, color=T.AMBER)
    for r in p.runs:
        if r.font.size is not None and r.font.size.pt == 7.5:
            r.font.size = Pt(8)
    p = K.np(doc, after=0, align=AL.CENTER, keep=True, line=1.0, style="Heading 1")
    K.R(p, c.title, font=T.HEAD, size=26, color=T.NAVY, bold=False)
    if bookmark:
        K.bookmark(p, bookmark)
    p = K.ornament(doc, before=8, after=10, w=2.6)
    p.paragraph_format.keep_with_next = True
    if c.intro:
        p = K.np(doc, after=18, align=AL.CENTER, line=1.25, indent=1.2)
        p.paragraph_format.right_indent = Cm(1.2)
        K.R(p, c.intro, font=T.HEAD, size=13.5, italic=True, color=T.SLATE)
        p.paragraph_format.keep_with_next = True  # the title block never sits alone at the foot of a page


def render_fact_row(doc, W: float, c: FactRowBlock) -> None:
    n = len(c.facts)
    if not n:
        return
    t = K.tbl(doc, 1, [W / n] * n, margins=(0.22, 0.3, 0.24, 0.3))
    K.row_keep(t.rows[0])
    for i, f in enumerate(c.facts):
        cell = t.rows[0].cells[i]
        K.borders(cell, t=(T.POWDER, 4), b=(T.POWDER, 4), l=(T.POWDER, 4) if i else None)
        p = K.np(cell, after=3, align=AL.CENTER, style="Fact Label")
        K.R(p, f.label.upper(), size=7, color=T.SLATE, bold=True, spacing=1.4)
        p = K.np(cell, align=AL.CENTER, line=1.0)
        if f.link and f.link.url:
            K.link(p, f.link.url, f.value, size=17, color=T.ROYAL, bold=True)
        else:
            K.R(p, f.value, font=T.HEAD, size=17, bold=True, color=T.ROYAL)
        K.close(cell, 1)
    K.spacer(doc, 16)


_ABBREV = ("e.g", "i.e", "etc", "approx", "St", "No", "Mr", "Mrs", "Ms", "Dr", "vs", "Rp", "Rs", "Mt", "Jl", "Ave",
           "Inc", "Ltd", "a.m", "p.m", "min", "max", "approx", "est", "cf")
_MIN_ITEM = 25
_LONG_PART = 90


def _sentences(text: str) -> list[str]:
    """Split on sentence ends ('. ', '! ', '? ') that do not follow an abbreviation or a single capital/number."""
    out, start = [], 0
    for m in re.finditer(r"([.!?])(?:[\"\u201d')]*)\s+(?=[A-Z0-9\u201c\"(])", text):
        word = re.search(r"(\S+)$", text[start:m.start() + 1])
        w = word.group(1).rstrip(".!?") if word else ""
        if m.group(1) == "." and (w in _ABBREV or w.lower() in {a.lower() for a in _ABBREV}
                                  or re.fullmatch(r"[A-Za-z]|\d+", w.split("(")[-1])):
            continue
        out.append(text[start:m.end()].strip())
        start = m.end()
    out.append(text[start:].strip())
    return [x for x in out if x]


def _merge_fragments(parts: list[str]) -> list[str]:
    items: list[str] = []
    for part in parts:
        if items and len(part) < _MIN_ITEM:
            items[-1] += " " + part
        else:
            items.append(part)
    if len(items) > 1 and len(items[0]) < _MIN_ITEM:  # a short leading fragment joins the next item
        items[1] = items[0] + " " + items[1]
        items = items[1:]
    return items


def bullet_items(body: str) -> list[str]:
    """Body text -> short readable bullet items. Each line stays its own item; within a line, split on sentence
    ends (and on ';' in long sentences); fragments under 25 chars are merged into a neighbour."""
    out: list[str] = []
    for line in (x.strip() for x in body.split("\n")):
        if not line:
            continue
        parts: list[str] = []
        for sent in _sentences(line):
            if ";" in sent and len(sent) > _LONG_PART:
                pieces = [x.strip() for x in re.split(r";\s+", sent) if x.strip()]
                pieces = [(x if x.endswith((".", "!", "?")) else x + ".") for x in pieces]
                parts += [x[0].upper() + x[1:] for x in pieces]
            else:
                parts.append(sent)
        out += _merge_fragments(parts)
    return out


def _titled_para(cell, w: float, item) -> None:
    p = K.np(cell, after=6, keep=True, line=1.0)
    K.R(p, item.heading, font=T.HEAD, size=16, color=T.NAVY)
    K.hairline(p, T.POWDER, space=2)
    for ln in bullet_items(item.body) or [item.body]:
        q = K.diamond_item(cell, ln, indent=0.62, after=4, size=10)
        q.paragraph_format.line_spacing = 1.32


def render_titled_paras(doc, W: float, c: TitledParas) -> None:
    _grid(doc, W, c.items, _titled_para, ncols=2, gap=1.0, after_row=14,
          split_long=lambda it: len(it.body.split("\n")) > 6 or len(it.body) > 600)


def _panel(doc, W: float, fill: str, bar: str):
    t = K.tbl(doc, 1, [W], margins=PANEL_PAD)
    K.row_keep(t.rows[0])
    cell = t.rows[0].cells[0]
    K.cell_shade(cell, fill)
    K.borders(cell, l=(bar, 18), t=None, b=None, r=None)
    return cell


def _panel_title(cell, text: str, color: str) -> None:
    p = K.np(cell, after=6, keep=True, style="Eyebrow")
    K.R(p, text, size=7.5, color=color, bold=True, caps=True, spacing=1.8)


def _panel_items(cell, inner_w: float, items: list[str], columns: int) -> None:
    def put(c, its):
        for it in its:
            p = K.diamond_item(c, it, indent=0.55, after=3, size=9.5)
            p.paragraph_format.line_spacing = 1.38
    if not items:
        return
    if columns >= 2 and len(items) > 1:
        gap = 0.6
        cw = (inner_w - gap) / 2
        half = -(-len(items) // 2)
        t = K.tbl(cell, 1, [cw, gap, cw])
        put(t.rows[0].cells[0], items[:half])
        put(t.rows[0].cells[2], items[half:])
        for c in t.rows[0].cells:
            K.close(c, 1)
    else:
        put(cell, items)


def _end_panel(doc, cell) -> None:
    K.close(cell, 1)
    K.spacer(doc, PANEL_GAP_PT)


def render_tip_panel(doc, W: float, c: TipPanel) -> None:
    cell = _panel(doc, W, T.HARBOUR_FILL, T.ROYAL)
    _panel_title(cell, c.title, T.ROYAL)
    _panel_items(cell, W - PANEL_PAD[1] - PANEL_PAD[3], c.items, c.columns)  # checks=True still uses diamonds
    _end_panel(doc, cell)


def render_note_panel(doc, W: float, c: NotePanel) -> None:
    cell = _panel(doc, W, T.TAUPE_TINT, T.TAUPE)
    _panel_title(cell, c.title, T.GOLD_INK)
    if c.text:
        K.R(K.np(cell, after=4 if c.items else 0, line=1.45, style="Body"), c.text, size=10)
    _panel_items(cell, W - PANEL_PAD[1] - PANEL_PAD[3], c.items, 1)
    _end_panel(doc, cell)


def _app(cell, w: float, app) -> None:
    p = K.np(cell, after=3, line=1.0)
    K.R(p, app.name, font=T.HEAD, size=15, color=T.NAVY)
    K.hairline(p, T.POWDER, space=2)
    K.R(K.np(cell, line=1.3), app.use, size=9.5, color=T.SLATE)


def render_app_grid(doc, W: float, c: AppGrid) -> None:
    _grid(doc, W, c.apps, _app, ncols=3, gap=0.7, after_row=10)


def _group(cell, w: float, g) -> None:
    p = K.np(cell, after=6, keep=True, line=1.0)
    K.R(p, g.title, font=T.HEAD, size=15, color=T.NAVY)
    K.hairline(p, T.POWDER, space=2)
    for it in g.items:
        p = K.diamond_item(cell, it, indent=0.62, after=4, size=10)
        p.paragraph_format.line_spacing = 1.32


def render_checklist_groups(doc, W: float, c: ChecklistGroups) -> None:
    _grid(doc, W, c.groups, _group, ncols=2, gap=1.0, after_row=14)


# ---------- second half: place groups, dishes, souvenirs, do/don't, phrases, emergency, contacts ----------
def _label(cell, text: str, color: str, size: float = 7, after: float = 2, bold: bool = True):
    p = K.np(cell, after=after, keep=True, line=1.0)
    K.R(p, text, size=size, color=color, bold=bold, caps=True, spacing=1.2)
    return p


def _links_line(cell, links: Sequence[Link], size: float = 9.5, after: float = 0, lead: Optional[str] = None) -> None:
    p = K.np(cell, after=after, line=1.35)
    if lead:
        K.R(p, lead + "  ", size=7, color=T.GOLD_INK, bold=True, caps=True, spacing=1.2)
    for i, l in enumerate(links):
        if i:
            K.R(p, "  ·  ", size=size, color=T.SLATE)
        if l.url:
            K.link(p, l.url, l.text, font=T.BODYF, size=size, color=T.NAVY, bold=False)
        else:
            K.R(p, l.text, size=size, color=T.NAVY)


def _travel_text(walk: Optional[int], drive: Optional[int]) -> str:
    parts = ([f"Walk {walk} min"] if walk is not None else []) + ([f"By car {drive} min"] if drive is not None else [])
    return " · ".join(parts) if parts else "Travel time not confirmed"


def _place(cell, pl, first: bool) -> None:
    p = K.np(cell, before=0 if first else 7, after=1, keep=True, line=1.0)
    if pl.name.url:
        K.link(p, pl.name.url, pl.name.text, size=13.5, color=T.NAVY, bold=False)
    else:
        K.R(p, pl.name.text, font=T.HEAD, size=13.5, color=T.NAVY)
    if pl.address and pl.address.strip():
        K.R(K.np(cell, after=2, line=1.25), pl.address.strip(), size=8, color=T.SLATE)
    K.R(K.np(cell, after=1, line=1.25), _travel_text(pl.walk_min, pl.drive_min), size=9, color=T.SLATE)
    p = K.np(cell, after=1, line=1.25)
    if pl.hours_text and pl.hours_text.strip():
        K.R(p, pl.hours_text, size=9)
    else:
        K.R(p, "Hours not listed", size=9, color=T.SLATE, italic=True)
    if pl.phone:
        K.R(K.np(cell, after=1, line=1.25), pl.phone, size=9)
    for m in pl.markers:
        K.review_marker(cell, m.kind, m.text)


def _place_column(cell, header: str, places) -> None:
    p = K.np(cell, after=5, keep=True, line=1.0)
    K.R(p, header, size=7.5, color=T.ROYAL, bold=True, caps=True, spacing=1.4)
    K.hairline(p, T.POWDER, space=2)
    if not places:
        K.R(K.np(cell, line=1.25), "None listed nearby.", size=9.5, color=T.SLATE, italic=True)
    for i, pl in enumerate(places):
        _place(cell, pl, i == 0)
    K.close(cell, 1)


def render_place_groups(doc, W: float, c: PlaceGroups) -> None:
    gap = 0.55
    cw = (_inner_w(W) - 2 * gap) / 3
    for h in c.hotels:
        _, cell = _card(doc, W)
        p = K.np(cell, after=2, keep=True, style="Eyebrow")
        K.R(p, h.city.upper(), size=8, color=T.GOLD_INK, bold=True, spacing=1.6)
        K.R(p, " ", size=8)
        K.R(p, K.DIAMOND_GLYPH, size=5.5, color=T.AMBER)
        K.R(p, " ", size=8)
        K.R(p, h.dates.upper(), size=7.5, color=T.SLATE, bold=True, spacing=1.6)
        p = K.np(cell, after=8, keep=True, line=1.0, style="Heading 3")
        K.R(p, "Near ", font=T.HEAD, size=20, color=T.NAVY, bold=False)
        if h.hotel.url:
            K.link(p, h.hotel.url, h.hotel.text, size=20, color=T.NAVY, bold=False)
        else:
            K.R(p, h.hotel.text, font=T.HEAD, size=20, color=T.NAVY, bold=False)
        for m in h.markers:
            K.review_marker(cell, m.kind, m.text)
        t = K.tbl(cell, 1, [cw, gap, cw, gap, cw])
        K.row_keep(t.rows[0])
        cells = t.rows[0].cells
        _place_column(cells[0], "Pharmacies", h.pharmacies)
        _place_column(cells[2], "Groceries", h.groceries)
        _place_column(cells[4], "Hospital", h.hospitals)
        K.close(cells[1], 1)
        K.close(cells[3], 1)
        _end_card(doc, cell)


def _heading(cell, text: str, size: float = 16, after: float = 6) -> None:
    p = K.np(cell, after=after, keep=True, line=1.0)
    K.R(p, text, font=T.HEAD, size=size, color=T.NAVY)
    K.hairline(p, T.POWDER, space=2)


def _link_runs(p, links: Sequence[Link], size: float, sep: str = "  ·  ") -> None:
    for i, l in enumerate(links):
        if i:
            K.R(p, sep, size=size, color=T.SLATE)
        if l.url:
            K.link(p, l.url, l.text, font=T.BODYF, size=size, color=T.NAVY, bold=False)
        else:
            K.R(p, l.text, size=size, color=T.NAVY)


def _dish(cell, w: float, d) -> None:
    _heading(cell, d.name, size=18)
    for ln in (bullet_items(d.desc) or [d.desc]) if d.desc.strip() else []:
        K.diamond_item(cell, ln, indent=0.62, after=4, size=10).paragraph_format.line_spacing = 1.32
    if d.where:
        def runs(p):
            K.R(p, "Where to try  ", size=7, color=T.GOLD_INK, bold=True, caps=True, spacing=1.2)
            _link_runs(p, d.where, 9.5)
        K.diamond_item(cell, runs, indent=0.62, after=0, size=9.5).paragraph_format.line_spacing = 1.32


def render_dish_grid(doc, W: float, c: DishGrid) -> None:
    _grid(doc, W, c.dishes, _dish, ncols=2, gap=1.0, after_row=14)


PLACES_PER_LINE = 2  # beyond this many places, bullets carry two links each
PLACES_ONE_PER_BULLET = 5


def _souvenir(cell, w: float, s) -> None:
    from src.aigv2.guide.dedupe import souvenir_items
    _heading(cell, s.title)
    _label(cell, "What to buy", T.SLATE)
    for it in souvenir_items(s.what) or [s.what]:
        K.diamond_item(cell, it, indent=0.62, after=3, size=9.5).paragraph_format.line_spacing = 1.3
    if s.places:
        p = _label(cell, "Best places to buy", T.GOLD_INK)
        p.paragraph_format.space_before = Pt(5)
        per = 1 if len(s.places) <= PLACES_ONE_PER_BULLET else PLACES_PER_LINE
        for i in range(0, len(s.places), per):
            chunk = s.places[i:i + per]
            K.diamond_item(cell, lambda p, ch=chunk: _link_runs(p, ch, 9.5), indent=0.62, after=3,
                           size=9.5).paragraph_format.line_spacing = 1.3


def render_souvenir_grid(doc, W: float, c: SouvenirGrid) -> None:
    _grid(doc, W, c.categories, _souvenir, ncols=2, gap=1.0, after_row=14)


def _do_dont_side(cell, heading: str, items: list[str], good: bool) -> None:
    p = K.np(cell, after=6, keep=True, line=1.0)
    K.R(p, heading, font=T.HEAD, size=18, color=T.NAVY)
    K.hairline(p, T.POWDER, space=2)
    for it in items:
        if good:
            p = K.diamond_item(cell, it, indent=0.55, after=4, size=10)
        else:
            p = K.np(cell, after=4, indent=0.55, hanging=0.55)
            K.tabs(p, [("left", 0.55, None)])
            K.R(p, "×", size=11, color=T.CRIMSON, bold=True)
            K.R(p, "\t" + it, size=10)
        p.paragraph_format.line_spacing = 1.35
    K.close(cell, 1)


def render_dos_donts(doc, W: float, c: DosDonts) -> None:
    gap = 1.0
    cw = (W - gap) / 2
    t = K.tbl(doc, 1, [cw, gap, cw])
    K.row_keep(t.rows[0])
    cells = t.rows[0].cells
    _do_dont_side(cells[0], "Do", c.do, True)
    _do_dont_side(cells[2], "Don\u2019t", c.dont, False)
    K.close(cells[1], 1)
    K.spacer(doc, 14)


def render_phrase_table(doc, W: float, c: PhraseTable) -> None:
    n = len(c.phrases)
    if not n:
        return
    gap, pw = 0.8, 4.3
    mw = (W - gap) / 2 - pw
    rows = -(-n // 2)
    t = K.tbl(doc, rows, [pw, mw, gap, pw, mw], margins=(0.14, 0.0, 0.14, 0.15))
    edge = (T.POWDER, 4)
    for r in range(rows):
        row = t.rows[r]
        K.row_keep(row)
        for side in (0, 1):
            k = r + side * rows
            cells = row.cells[side * 3: side * 3 + 2]
            if k >= n:
                for cell in cells:
                    K.close(cell, 1)
                continue
            ph = c.phrases[k]
            K.R(K.np(cells[0], line=1.0), ph.local, font=T.HEAD, size=14, italic=True, color=T.NAVY)
            K.R(K.np(cells[1], line=1.25), ph.english, size=9.5, color=T.SLATE)
            for cell in cells:
                K.cell_borders(cell, top=edge if r == 0 else None, bottom=edge)
                K.cell_valign(cell, "center")
                K.close(cell, 1)
        K.close(row.cells[2], 1)
    K.spacer(doc, 14)


def render_emergency_strip(doc, W: float, c: EmergencyStrip) -> None:
    n = len(c.numbers)
    if not n:
        return
    t = K.tbl(doc, 1, [W / n] * n, margins=(0.35, 0.15, 0.35, 0.15))
    K.row_keep(t.rows[0])
    for i, e in enumerate(c.numbers):
        cell = t.rows[0].cells[i]
        K.cell_shade(cell, T.WHITE)
        K.cell_borders(cell, top=(T.ROYAL, 12), bottom=(T.POWDER, 6),
                       left=(T.CARD_EDGE if i == 0 else T.POWDER, 4),
                       right=(T.CARD_EDGE, 4) if i == n - 1 else None)
        size = 26 if len(e.number) <= 10 else 20 if len(e.number) <= 14 else 17  # keep long strings on one line
        K.R(K.np(cell, after=2, align=AL.CENTER, line=1.0), e.number, font=T.HEAD, size=size, bold=True, color=T.ROYAL)
        p = K.np(cell, align=AL.CENTER, line=1.0)
        K.R(p, e.service, size=7, color=T.SLATE, caps=True, spacing=1.2)
        K.close(cell, 1)
    if c.dial:
        K.R(K.np(doc, before=6, after=0, align=AL.CENTER, line=1.0), c.dial, font=T.HEAD, size=12.5, italic=True,
            color=T.SLATE)
    K.spacer(doc, 14)


def render_contact_cards(doc, W: float, c: ContactCards) -> None:
    n = len(c.cards)
    if not n:
        return
    t = K.tbl(doc, 1, [W / n] * n, margins=(0.42, 0.6, 0.45, 0.6))
    K.row_keep(t.rows[0])
    for i, k in enumerate(c.cards):
        cell = t.rows[0].cells[i]
        K.cell_shade(cell, T.WHITE)
        K.borders(cell, l=(T.AMBER, 27) if i == 0 else (T.POWDER, 4), t=(T.CARD_EDGE, 4), b=(T.POWDER, 6),
                  r=(T.CARD_EDGE, 4))
        K.R(K.np(cell, after=3, keep=True, line=1.0), k.eyebrow.upper(), size=7.5, color=T.GOLD_INK, bold=True,
            spacing=1.4)
        p = K.np(cell, after=3 if (k.phone or k.note) else 0, keep=True, line=1.0)
        if k.name.url:
            K.link(p, k.name.url, k.name.text, size=16, color=T.NAVY, bold=False)
        else:
            K.R(p, k.name.text, font=T.HEAD, size=16, color=T.NAVY)
        if k.phone:
            K.R(K.np(cell, after=3 if k.note else 0, keep=bool(k.note), line=1.0), k.phone, font=T.HEAD, size=17,
                bold=True, color=T.ROYAL)
        if k.note:
            K.R(K.np(cell, line=1.3), k.note, size=9.5, color=T.SLATE)
        K.close(cell, 1)
    K.spacer(doc, 14)
