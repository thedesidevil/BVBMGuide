"""Contents page for the render2 renderer (locked design: day cards + Before/While two-column list)."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from docx.enum.text import WD_ALIGN_PARAGRAPH as AL

from src.aigv2.guide.model import Guide, Page
from src.aigv2.render import document as _legacy
from src.aigv2.render2 import kit as K
from src.aigv2.render2 import theme as T
from src.aigv2.render2.kit import NB, R, anchor_link, close, diamond_item, eyebrow, np, ornament, picture, spacer, tbl

BEFORE_YOU_GO = [f"sec_{k}" for k, _ in _legacy.BEFORE_YOU_GO]
WHILE_THERE = [f"sec_{k}" for k, _ in _legacy.WHILE_THERE]
GAP_BEFORE_SECOND_BLOCK_PT = 14
NUM_PAD = 0.35  # cm: right padding of the day cards
DASH = "–"
_DAY_RE = re.compile(r"^Day\s+(\d+)\s*[–-]\s*(\w{3}),\s*(\d{1,2}\s+\w{3})\s*\|\s*(.+)$")
_MONTHS = {"Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April", "May": "May", "Jun": "June",
           "Jul": "July", "Aug": "August", "Sep": "September", "Oct": "October", "Nov": "November",
           "Dec": "December"}


def _parse_day(title: str):
    m = _DAY_RE.match(title.strip())
    return (int(m.group(1)), m.group(2), m.group(3), m.group(4).strip()) if m else None


def _full_date(dm: str) -> str:
    d, mon = dm.split()
    return f"{d} {_MONTHS.get(mon, mon)}"


def date_range(guide: Guide) -> str:
    days = [_parse_day(p.title) for p in guide.pages if p.kind == "day"]
    days = [d for d in days if d]
    if not days:
        return ""
    a, b = _full_date(days[0][2]), _full_date(days[-1][2])
    return a if a == b else f"{a} {DASH} {b}"


def _number(p, bookmark_name: str, pages: Optional[dict], prefix: str = "", **kw) -> None:
    """Page number as a PAGEREF field; the cached result is the known number (or a dash)."""
    if prefix:
        R(p, prefix, **kw)
    n = (pages or {}).get(bookmark_name)
    K.field(p, f"PAGEREF {bookmark_name} \\h", str(n) if n is not None else DASH, **kw)


def _header(doc, guide: Guide) -> None:
    p = np(doc, before=0, after=2, align=AL.CENTER)
    picture(p, T.asset("logo_v1.png"), 2.6)
    p = np(doc, after=9, align=AL.CENTER)
    R(p, "Your Vacation  ·  Your Story  ·  Your Way", font=T.HEAD, size=12, italic=True, color=T.GOLD_INK)
    p = np(doc, after=1, align=AL.CENTER, line=0.95)
    words = guide.title.split()
    if len(words) >= 3:
        R(p, " ".join(words[:-1]) + " ", font=T.HEAD, size=25, color=T.NAVY)
        R(p, words[-1], font=T.HEAD, size=25, italic=True, color=T.CRIMSON)
    else:
        R(p, guide.title, font=T.HEAD, size=25, color=T.NAVY)
    first = guide.client.split()[0] if guide.client.strip() else ""
    bits = ([f"Prepared for {first}"] if first else []) + ([date_range(guide)] if date_range(guide) else [])
    if bits:
        p = np(doc, after=5, align=AL.CENTER)
        R(p, "  ·  ".join(bits), font=T.HEAD, size=13.5, italic=True, color=T.SLATE)
    ornament(doc, before=2, after=14, w=2.6)


def _day_card(doc, W: float, page: Page, pages) -> None:
    pad = (0.09, 0.4, 0.09, NUM_PAD)
    t = tbl(doc, 1, [W], margins=pad)
    c = t.rows[0].cells[0]
    K.cell_shade(c, T.WHITE)
    K.borders(c, l=(T.AMBER, 27), t=(T.CARD_EDGE, 4), r=(T.CARD_EDGE, 4), b=(T.POWDER, 6))
    K.cell_valign(c, "center")
    p = np(c, after=0)
    K.tabs(p, [("right", W - pad[1] - pad[3], None)])
    parsed = _parse_day(page.title)
    if parsed:
        n, wd, dm, title = parsed
        d, mon = dm.split()
        R(p, f"{wd} {d} {mon}", size=8, color=T.SLATE, italic=True)
        R(p, NB * 3)
        R(p, f"Day {n}", font=T.HEAD, size=12, bold=True, italic=True, color=T.GOLD_INK)
        R(p, NB * 2)
    else:
        title = page.title
    anchor_link(p, page.bookmark, title, font=T.HEAD, size=14, bold=True, color=T.INK)
    R(p, "\t")
    _number(p, page.bookmark, pages, prefix="p." + NB, font=T.HEAD, size=14, bold=True, color=T.ROYAL)
    close(c, 1)
    spacer(doc, 2)


def _entry(cont, page: Page, width: float, pages) -> None:
    def runs(p):
        anchor_link(p, page.bookmark, page.title, font=T.HEAD, size=13, bold=True, color=T.INK)
        R(p, "\t")
        _number(p, page.bookmark, pages, font=T.HEAD, size=13, bold=True, color=T.ROYAL)
    p = diamond_item(cont, runs, after=4)
    K.tabs(p, [("left", 0.6, None), ("right", width, None)])


def _section_title(doc) -> None:
    p = np(doc, before=5, after=0, align=AL.CENTER, keep=True)
    R(p, "Before you go & ", font=T.HEAD, size=19)
    R(p, "while you're there", font=T.HEAD, size=19, italic=True, color=T.GOLD_INK)
    ornament(doc, before=1, after=4)


def _split_refs(guide: Guide):
    refs = [p for p in guide.pages if p.kind == "reference"]
    by = {p.bookmark: p for p in refs}
    before = [by[b] for b in BEFORE_YOU_GO if b in by]
    while_ = [by[b] for b in WHILE_THERE if b in by]
    while_ += [p for p in refs if p.bookmark not in BEFORE_YOU_GO and p.bookmark not in WHILE_THERE]
    return before, while_


def render_toc(doc, guide: Guide, pages: Optional[dict] = None) -> None:
    s = doc.sections[-1]
    W = (s.page_width - s.left_margin - s.right_margin) / 360000
    _header(doc, guide)
    days = [p for p in guide.pages if p.kind == "day" and p.bookmark.startswith("day_")]
    if days:
        eyebrow(np(doc, after=3), "Day by day", color=T.GOLD_INK)
        for pg in days:
            _day_card(doc, W, pg, pages)
    np(doc, before=GAP_BEFORE_SECOND_BLOCK_PT, after=0)
    _section_title(doc)
    before, while_ = _split_refs(guide)
    cw = (W - 0.6) / 2
    t = tbl(doc, 1, [cw, 0.6, cw])
    for ci, (label, items) in zip((0, 2), (("Before you go", before), ("While you're there", while_))):
        c = t.rows[0].cells[ci]
        eyebrow(np(c, after=3), label, color=T.GOLD_INK)
        for pg in items:
            _entry(c, pg, cw, pages)
        close(c, 1)
    ty = next((p for p in guide.pages if p.kind == "thank_you"), None)
    if ty is not None:
        np(doc, before=6, after=0)
        _entry(doc, ty, W, pages)


def page_map(docx_bytes: bytes, titles: dict[str, str], skip_pages: int = 0, start_page: int = 1) -> dict[str, int]:
    """bookmark -> displayed page number, found by rendering to PDF and searching each page's text for the title.

    Returns {} when soffice or pdftotext is unavailable or conversion fails."""
    if not (shutil.which("soffice") and shutil.which("pdftotext")):
        return {}
    norm = lambda s: re.sub(r"\s+", " ", s).strip()
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "guide.docx"
        src.write_bytes(docx_bytes)
        try:
            subprocess.run(["soffice", f"-env:UserInstallation=file://{tmp}/profile", "--headless",
                            "--convert-to", "pdf", "--outdir", tmp, str(src)],
                           check=True, capture_output=True, timeout=300)
            pdf = Path(tmp) / "guide.pdf"
            n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(pdf)], check=True,
                                                                capture_output=True, text=True).stdout).group(1))
            texts = [norm(subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), str(pdf), "-"], check=True,
                                         capture_output=True, text=True).stdout) for i in range(1, n + 1)]
        except (subprocess.SubprocessError, OSError, AttributeError):
            return {}
    out: dict[str, int] = {}
    for bm, title in titles.items():
        needle = norm(title)
        for i in range(skip_pages, len(texts)):
            if needle and needle in texts[i]:
                out[bm] = i + 1 + start_page - 1
                break
    return out
