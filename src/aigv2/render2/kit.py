"""Low-level python-docx / OOXML helpers for the render2 renderer (adapted from the design prototype).

Everything here is Google-Docs-safe: no run borders, no dotted-leader dependence, no inline-picture bullets,
solid page background by default.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Sequence, Union

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from src.aigv2.render2 import theme as T
from src.aigv2.render2.theme import BODYF, GOLD_INK, HEAD, INK, POWDER, ROYAL, SLATE, WHITE

RPR_ORDER = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline",
             "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
             "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText",
             "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout", "specVanish", "oMath"]
PPR_ORDER = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
             "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
             "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
             "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc",
             "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr",
             "sectPr", "pPrChange"]
TCPR_ORDER = ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap", "tcMar",
              "textDirection", "tcFitText", "vAlign", "hideMark"]
TBLPR_ORDER = ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize", "tblStyleColBandSize",
               "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook"]
SECT_ORDER = ["headerReference", "footerReference", "footnotePr", "endnotePr", "type", "pgSz", "pgMar", "paperSrc",
              "pgBorders", "lnNumType", "pgNumType", "cols", "formProt", "vAlign", "noEndnote", "titlePg",
              "textDirection", "bidi", "rtlGutter", "docGrid", "printerSettings"]

TWIP_PER_CM = 567
NB = " "  # non-breaking space
DOT = " · "
REVIEW_STYLE = "Review Marker (internal)"
DIAMOND_GLYPH = "◆"
ASSET_ORN = T.asset("ornament.png")
Container = object  # Document, _Cell, header/footer: anything with add_paragraph


def el(tag: str, **attrs):
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn("w:" + k), str(v))
    return e


def insert_ordered(parent, child, order: Sequence[str]):
    """Insert child into parent at its schema position, replacing a same-tag sibling."""
    name = child.tag.split("}")[1]
    for old in parent.findall(child.tag):
        parent.remove(old)
    idx = order.index(name)
    for i, sib in enumerate(list(parent)):
        sn = sib.tag.split("}")[1]
        if sn in order and order.index(sn) > idx:
            parent.insert(i, child)
            return child
    parent.append(child)
    return child


# ---------- document ----------
def new_doc(margins_cm=(2.0, 1.4, 1.7, 1.4), header_cm: float = 0.7, footer_cm: float = 0.6,
            gradient: Optional[str] = None, background: str = T.FROST):
    """A4 document with a SOLID page background (VML gradient only if `gradient` is passed)."""
    doc = Document()
    s = doc.sections[0]
    s.page_width, s.page_height = Cm(21.0), Cm(29.7)
    s.top_margin, s.right_margin, s.bottom_margin, s.left_margin = [Cm(x) for x in margins_cm]
    s.header_distance, s.footer_distance = Cm(header_cm), Cm(footer_cm)
    bg = parse_xml(
        '<w:background xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" '
        f'w:color="{background}">{gradient or ""}</w:background>')
    doc.element.insert(0, bg)
    _settings_flags(doc)
    return doc


def _settings_flags(doc) -> None:
    st = doc.settings.element
    zoom = st.find(qn("w:zoom"))
    anchor = zoom
    for tag in ("displayBackgroundShape", "hideSpellingErrors", "hideGrammaticalErrors"):
        if st.find(qn("w:" + tag)) is not None:
            continue
        e = el("w:" + tag)
        if anchor is None:
            st.insert(0, e)
        else:
            anchor.addnext(e)
        anchor = e


def text_width_cm(doc) -> float:
    s = doc.sections[0]
    return (s.page_width - s.left_margin - s.right_margin) / 360000


def no_proof(r):
    """Suppress proofing squiggles on a run (header/footer runs)."""
    insert_ordered(r._r.get_or_add_rPr(), el("w:noProof"), RPR_ORDER)
    return r


# ---------- sections / page numbers ----------
def set_page_start(section, n: int) -> None:
    """Restart page numbering at n for THIS section only."""
    insert_ordered(section._sectPr, el("w:pgNumType", start=n), SECT_ORDER)


def strip_page_start(section) -> None:
    for e in section._sectPr.findall(qn("w:pgNumType")):
        section._sectPr.remove(e)


_SECTION_KINDS = {"new_page": WD_SECTION.NEW_PAGE, "continuous": WD_SECTION.CONTINUOUS,
                  "odd": WD_SECTION.ODD_PAGE, "even": WD_SECTION.EVEN_PAGE}


def add_section(doc, kind: str = "new_page"):
    """New section; add_section copies the previous sectPr so its page-number restart is always stripped."""
    s = doc.add_section(_SECTION_KINDS[kind])
    strip_page_start(s)
    return s


# ---------- styles / runs ----------
def set_rfonts(rpr, name: str) -> None:
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = insert_ordered(rpr, el("w:rFonts"), RPR_ORDER)
    for a in ("ascii", "hAnsi", "cs", "eastAsia"):
        rf.set(qn("w:" + a), name)
    for a in ("asciiTheme", "hAnsiTheme", "cstheme", "eastAsiaTheme"):
        if rf.get(qn("w:" + a)) is not None:
            del rf.attrib[qn("w:" + a)]


def style(doc, name: str, *, font=None, size=None, color=None, bold=None, italic=None, before=None, after=None,
          line=None, base=None, caps=None, spacing=None, keep_next=None, align=None):
    """Get or create a paragraph style and apply the given properties."""
    styles = doc.styles
    try:
        st = styles[name]
    except KeyError:
        st = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        if base:
            st.base_style = styles[base]
    if font:
        set_rfonts(st.element.get_or_add_rPr(), font)
    if size is not None:
        st.font.size = Pt(size)
    if color:
        st.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        st.font.bold = bold
    if italic is not None:
        st.font.italic = italic
    if caps is not None:
        st.font.all_caps = caps
    if spacing is not None:
        insert_ordered(st.element.get_or_add_rPr(), el("w:spacing", val=int(spacing * 20)), RPR_ORDER)
    pf = st.paragraph_format
    if before is not None:
        pf.space_before = Pt(before)
    if after is not None:
        pf.space_after = Pt(after)
    if line is not None:
        pf.line_spacing = line
    if keep_next is not None:
        pf.keep_with_next = keep_next
    if align is not None:
        pf.alignment = align
    return st


def fmt(r, *, font=None, size=None, color=None, bold=None, italic=None, caps=None, spacing=None, shade=None,
        underline=None):
    if font:
        set_rfonts(r._r.get_or_add_rPr(), font)
    if size is not None:
        r.font.size = Pt(size)
    if color:
        r.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        r.font.bold = bold
    if italic is not None:
        r.font.italic = italic
    if caps:
        r.font.all_caps = True
    rpr = r._r.get_or_add_rPr()
    if spacing is not None:
        insert_ordered(rpr, el("w:spacing", val=int(spacing * 20)), RPR_ORDER)
    if shade:
        insert_ordered(rpr, el("w:shd", val="clear", color="auto", fill=shade), RPR_ORDER)
    if underline:  # hex colour for a thin single underline
        insert_ordered(rpr, el("w:u", val="single", color=underline), RPR_ORDER)
    return r


def run(p, text: str, *, style=None, **kw):
    r = p.add_run(text, style=style)
    return fmt(r, **kw)


def hyperlink(p, url: str, text: str, **kw):
    rid = p.part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                           is_external=True)
    h = el("w:hyperlink")
    h.set(qn("r:id"), rid)
    h.set(qn("w:history"), "1")
    r = p.add_run(text)
    fmt(r, **kw)
    h.append(r._r)
    p._p.append(h)
    return r


def anchor_link(p, bookmark_name: str, text: str, **kw):
    h = el("w:hyperlink", anchor=bookmark_name, history=1)
    r = p.add_run(text)
    fmt(r, **kw)
    h.append(r._r)
    p._p.append(h)
    return r


def _next_bookmark_id(p) -> int:
    root = p._p.getroottree().getroot()
    ids = [int(b.get(qn("w:id"))) for b in root.iter(qn("w:bookmarkStart")) if (b.get(qn("w:id")) or "").isdigit()]
    return max(ids, default=100) + 1


def bookmark(p, name: str) -> int:
    """Wrap the paragraph in a bookmark; the id is unique within the document. Returns the id."""
    bid = _next_bookmark_id(p)
    ppr = p._p.pPr
    idx = 0 if ppr is None else list(p._p).index(ppr) + 1
    p._p.insert(idx, el("w:bookmarkStart", id=bid, name=name))
    p._p.append(el("w:bookmarkEnd", id=bid))
    return bid


def field(p, instr: str, placeholder: str = "1", **kw) -> None:
    for kind in ("begin", "instr", "separate", "text", "end"):
        r = p.add_run()
        fmt(r, **kw)
        if kind == "instr":
            t = OxmlElement("w:instrText")
            t.set(qn("xml:space"), "preserve")
            t.text = f" {instr} "
            r._r.append(t)
        elif kind == "text":
            r.text = placeholder
        else:
            r._r.append(el("w:fldChar", fldCharType=kind))


# ---------- paragraphs ----------
def para(container, text=None, *, style=None, before=None, after=None, line=None, align=None, keep_next=None,
         keep_lines=None, indent_cm=None, hanging_cm=None, **runkw):
    p = container.add_paragraph(style=style)
    pf = p.paragraph_format
    if before is not None:
        pf.space_before = Pt(before)
    if after is not None:
        pf.space_after = Pt(after)
    if line is not None:
        pf.line_spacing = line
    if align is not None:
        pf.alignment = align
    if keep_next is not None:
        pf.keep_with_next = keep_next
    if keep_lines is not None:
        pf.keep_together = keep_lines
    if indent_cm is not None:
        pf.left_indent = Cm(indent_cm)
    if hanging_cm is not None:
        pf.first_line_indent = Cm(-hanging_cm)
    if text:
        run(p, text, **runkw)
    return p


def tabs(p, stops) -> None:
    """stops: list of (kind, pos_cm, leader|None). Never rely on a dotted leader for meaning."""
    ppr = p._p.get_or_add_pPr()
    t = el("w:tabs")
    for kind, pos, leader in stops:
        a = {"val": kind, "pos": int(pos * TWIP_PER_CM)}
        if leader:
            a["leader"] = leader
        t.append(el("w:tab", **a))
    insert_ordered(ppr, t, PPR_ORDER)


def p_border(p, side: str = "bottom", color: str = "000000", sz: int = 4, space: int = 4, val: str = "single") -> None:
    ppr = p._p.get_or_add_pPr()
    b = ppr.find(qn("w:pBdr"))
    if b is None:
        b = insert_ordered(ppr, el("w:pBdr"), PPR_ORDER)
    b.append(el(f"w:{side}", val=val, sz=sz, space=space, color=color))


def p_shade(p, fill: str) -> None:
    insert_ordered(p._p.get_or_add_pPr(), el("w:shd", val="clear", color="auto", fill=fill), PPR_ORDER)


def hairline(p, color: str = POWDER, side: str = "bottom", sz: int = 4, space: int = 3) -> None:
    p_border(p, side, color, sz, space)


def shrink_para(p, pt: float = 2):
    """Make an empty spacer paragraph tiny: paragraph-mark font size + exact line height."""
    ppr = p._p.get_or_add_pPr()
    rpr = ppr.find(qn("w:rPr"))
    if rpr is None:
        rpr = insert_ordered(ppr, OxmlElement("w:rPr"), PPR_ORDER)
    for tag in ("w:sz", "w:szCs"):
        rpr.append(el(tag, val=int(pt * 2)))
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = Pt(pt)
    return p


# ---------- tables ----------
def table(container, rows: int, widths_cm: Sequence[float], *, cell_margins_cm=(0.1, 0.15, 0.1, 0.15),
          indent_cm: float = 0):
    t = container.add_table(rows=rows, cols=len(widths_cm))
    # _Cell.add_table appends an empty paragraph after the table; drop it (callers use close()).
    nxt = t._tbl.getnext()
    if nxt is not None and nxt.tag == qn("w:p") and len(nxt) == 0 and hasattr(container, "_tc"):
        nxt.getparent().remove(nxt)
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    t.autofit = False
    tblPr = t._tbl.tblPr
    insert_ordered(tblPr, el("w:tblW", w=int(sum(widths_cm) * TWIP_PER_CM), type="dxa"), TBLPR_ORDER)
    insert_ordered(tblPr, el("w:tblInd", w=int(indent_cm * TWIP_PER_CM), type="dxa"), TBLPR_ORDER)
    b = el("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b.append(el(f"w:{side}", val="nil"))
    insert_ordered(tblPr, b, TBLPR_ORDER)
    insert_ordered(tblPr, el("w:tblLayout", type="fixed"), TBLPR_ORDER)
    m = el("w:tblCellMar")
    for side, v in zip(("top", "left", "bottom", "right"), cell_margins_cm):
        m.append(el(f"w:{side}", w=int(v * TWIP_PER_CM), type="dxa"))
    insert_ordered(tblPr, m, TBLPR_ORDER)
    for s in tblPr.findall(qn("w:tblStyle")):
        tblPr.remove(s)
    for gc, w in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), widths_cm):
        gc.set(qn("w:w"), str(int(w * TWIP_PER_CM)))
    for row in t.rows:
        for c, w in zip(row.cells, widths_cm):
            c.width = Cm(w)
    return t


def cell_shade(c, fill: str) -> None:
    insert_ordered(c._tc.get_or_add_tcPr(), el("w:shd", val="clear", color="auto", fill=fill), TCPR_ORDER)


def cell_borders(c, **sides) -> None:
    """sides: top/left/bottom/right = (hex, eighths-pt[, val]) or None for nil."""
    b = el("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        if side in sides:
            v = sides[side]
            if v is None:
                b.append(el(f"w:{side}", val="nil"))
            else:
                b.append(el(f"w:{side}", val=v[2] if len(v) > 2 else "single", sz=v[1], space=0, color=v[0]))
    insert_ordered(c._tc.get_or_add_tcPr(), b, TCPR_ORDER)


def cell_margins(c, top=None, left=None, bottom=None, right=None) -> None:
    m = el("w:tcMar")
    for side, v in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        if v is not None:
            m.append(el(f"w:{side}", w=int(v * TWIP_PER_CM), type="dxa"))
    insert_ordered(c._tc.get_or_add_tcPr(), m, TCPR_ORDER)


def cell_valign(c, v: str = "center") -> None:
    insert_ordered(c._tc.get_or_add_tcPr(), el("w:vAlign", val=v), TCPR_ORDER)


def row_keep(row, cant_split: bool = True, height_cm: Optional[float] = None, exact: bool = False) -> None:
    trPr = row._tr.get_or_add_trPr()
    if cant_split and trPr.find(qn("w:cantSplit")) is None:
        trPr.append(el("w:cantSplit"))
    if height_cm is not None:
        trPr.append(el("w:trHeight", val=int(height_cm * TWIP_PER_CM), hRule="exact" if exact else "atLeast"))


def borders(cell, *, l=None, t=None, b=None, r=None) -> None:
    """each: (hex, eighths-pt) or None -> nil"""
    cell_borders(cell, left=l, top=t, bottom=b, right=r)


def _fresh(cell) -> bool:
    blocks = [c for c in cell._tc if c.tag in (qn("w:p"), qn("w:tbl"))]
    if len(blocks) != 1 or blocks[0].tag != qn("w:p"):
        return False
    return not blocks[0].findall(".//" + qn("w:r")) and not blocks[0].findall(".//" + qn("w:hyperlink"))


def np(cont, *, before=None, after=None, align=None, line=None, keep=None, indent=None, hanging=None, style=None):
    """Next paragraph of a cell/document; reuses a cell's untouched first paragraph."""
    if hasattr(cont, "_tc") and _fresh(cont):
        p = cont.paragraphs[0]
        if style:
            p.style = style
        pf = p.paragraph_format
        pf.space_before = Pt(0 if before is None else before)
        pf.space_after = Pt(0 if after is None else after)
        if line is not None:
            pf.line_spacing = line
        if align is not None:
            pf.alignment = align
        if keep is not None:
            pf.keep_with_next = keep
        if indent is not None:
            pf.left_indent = Cm(indent)
        if hanging is not None:
            pf.first_line_indent = Cm(-hanging)
        return p
    return para(cont, None, style=style, before=0 if before is None else before, after=0 if after is None else after,
                line=line, align=align, keep_next=keep, indent_cm=indent, hanging_cm=hanging)


def tbl(cont, rows: int, widths: Sequence[float], *, margins=(0, 0, 0, 0), indent: float = 0):
    """Layout table whose edge aligns with the surrounding text; every row can't split across pages."""
    if hasattr(cont, "_tc") and _fresh(cont):
        cont._tc.remove(cont.paragraphs[0]._p)
    t = table(cont, rows, widths, cell_margins_cm=margins, indent_cm=indent + margins[1])
    for r in t.rows:
        row_keep(r)
    return t


def spacer(cont, pt: float = 4):
    return shrink_para(para(cont, "", before=0, after=0), pt)


def close(cell, pt: float = 1) -> None:
    """A cell must end in a paragraph (e.g. after a nested table)."""
    if cell._tc[-1].tag != qn("w:p"):
        spacer(cell, pt)


# ---------- text primitives ----------
def R(p, text: str, font: str = BODYF, size: float = 9.5, color: str = INK, **kw):
    return run(p, text, font=font, size=size, color=color, **kw)


def eyebrow(p, text: str, color: str = ROYAL, size: float = 7.5, spacing: Optional[float] = 1.5):
    """Small caps-bold label; letter spacing is an optional enhancement (lost in Google Docs)."""
    return R(p, text, size=size, color=color, bold=True, caps=True, spacing=spacing)


def link(p, url: str, text: str, font: str = HEAD, size: float = 15, color: str = INK, bold: bool = True,
         ul: str = T.AMBER, italic=None):
    return hyperlink(p, url, text, font=font, size=size, color=color, bold=bold, underline=ul, italic=italic)


def chips(p, labels: Sequence[str], size: float = 8, color: str = GOLD_INK, sep: str = DOT) -> None:
    """Tags as plain small text joined by a middle dot (no run border or shading: Google Docs drops them)."""
    if labels:
        R(p, sep.join(labels), size=size, color=color)


def picture(p, path: Union[str, Path], w_cm: float, raise_pt: Optional[float] = None):
    r = p.add_run()
    r.add_picture(str(path), width=Cm(w_cm))
    if raise_pt is not None:
        insert_ordered(r._r.get_or_add_rPr(), el("w:position", val=int(raise_pt * 2)), RPR_ORDER)
    return r


def ornament(cont, after: float = 6, before: float = 2, w: float = 3.2):
    p = np(cont, before=before, after=after, align=AL.CENTER)
    picture(p, ASSET_ORN, w)
    return p


def _glyph(p, size: float = 6) -> None:
    R(p, DIAMOND_GLYPH, size=size, color=T.AMBER)


def diamond_item(cont, text_runs: Union[str, Callable], indent: float = 0.6, after: float = 2, size: float = 9.5):
    """Bullet paragraph: text glyph + tab with a hanging indent (no inline picture)."""
    p = np(cont, after=after, indent=indent, hanging=indent)
    tabs(p, [("left", indent, None)])
    _glyph(p)
    R(p, "\t", size=size)
    if callable(text_runs):
        text_runs(p)
    else:
        R(p, text_runs, size=size)
    return p


def diamond_eyebrow(cont, text: str, *, color: str = GOLD_INK, before: float = 6, after: float = 3,
                    keep: bool = True):
    """Section label led by the gold diamond glyph."""
    p = np(cont, before=before, after=after, keep=keep)
    _glyph(p, 7)
    R(p, NB, size=7.5)
    eyebrow(p, text, color=color)
    return p


# ---------- review marker ----------
def review_marker(container, kind: str, text: str):
    """Staff-only marker paragraph (style 'Review Marker (internal)'); style defined in styles.py."""
    p = container.add_paragraph(style=REVIEW_STYLE)
    label = kind.replace("_", " ")
    p.add_run(f"⚠ {label}: {text}" + DOT.replace(" · ", "  ·  ") + "staff only")
    return p
