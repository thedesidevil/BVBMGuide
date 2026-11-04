"""Document styles for render2. Heading 1/2/3 are the semantic anchors read by qc/reader.py."""
from __future__ import annotations

from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
from docx.oxml.ns import qn

from src.aigv2.render2 import theme as T
from src.aigv2.render2.kit import PPR_ORDER, REVIEW_STYLE, el, insert_ordered, style

PLACEHOLDER_TABLE = "Placeholder Card (internal)"
STYLE_NAMES = ("Normal", "Heading 1", "Heading 2", "Heading 3", "Eyebrow", "Body", "BodyLead", "CardLabel",
               "Fact Label", "Fact Value", REVIEW_STYLE)


def _outline(st, level: int) -> None:
    insert_ordered(st.element.get_or_add_pPr(), el("w:outlineLvl", val=level), PPR_ORDER)


def _heading(doc, name: str, level: int, size: float, align) -> None:
    st = style(doc, name, font=T.HEAD, size=size, color=T.NAVY, bold=True, italic=False, before=0, after=4,
               keep_next=True, align=align)
    _outline(st, level)


def _dashed_box(st, side_val: str, color: str, sz: int, space: int, fill: str) -> None:
    ppr = st.element.get_or_add_pPr()
    b = el("w:pBdr")
    for side in ("top", "left", "bottom", "right"):
        b.append(el(f"w:{side}", val=side_val, sz=sz, space=space, color=color))
    insert_ordered(ppr, b, PPR_ORDER)
    insert_ordered(ppr, el("w:shd", val="clear", color="auto", fill=fill), PPR_ORDER)


def _review_marker_style(doc) -> None:
    st = style(doc, REVIEW_STYLE, font="Courier New", size=8, color="7A0019", bold=True, before=4, after=6,
               base="Normal")
    _dashed_box(st, "dashed", "D6006E", 8, 3, "FFF2A8")


def _placeholder_table_style(doc) -> None:
    if PLACEHOLDER_TABLE in [s.name for s in doc.styles]:
        return
    st = doc.styles.add_style(PLACEHOLDER_TABLE, WD_STYLE_TYPE.TABLE)
    e = st.element
    tbl_pr = el("w:tblPr")
    b = el("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b.append(el(f"w:{side}", val="dashed", sz=6, space=0, color=T.POWDER))
    tbl_pr.append(b)
    e.append(tbl_pr)
    tc_pr = el("w:tcPr")
    tc_pr.append(el("w:shd", val="clear", color="auto", fill=T.FROST))
    e.append(tc_pr)


def install_styles(doc) -> None:
    """Create/refresh all render2 styles. Safe to call twice."""
    n = style(doc, "Normal", font=T.BODYF, size=9.5, color=T.INK, after=0, line=1.12)
    insert_ordered(n.element.get_or_add_pPr(), el("w:widowControl"), PPR_ORDER)
    _heading(doc, "Heading 1", 0, 26, AL.CENTER)
    _heading(doc, "Heading 2", 1, 22, AL.CENTER)
    _heading(doc, "Heading 3", 2, 20, AL.LEFT)
    style(doc, "Eyebrow", font=T.BODYF, size=7.5, color=T.ROYAL, bold=True, caps=True, spacing=1.5, base="Normal")
    style(doc, "Body", font=T.BODYF, size=10, color=T.INK, line=1.45, after=4, base="Normal")
    style(doc, "BodyLead", font=T.BODYF, size=10.5, color=T.INK, line=1.5, after=6, base="Normal")
    style(doc, "CardLabel", font=T.BODYF, size=7.5, color=T.GOLD_INK, bold=True, caps=True, spacing=1.0,
          after=2, base="Normal")
    style(doc, "Fact Label", font=T.BODYF, size=7.5, color=T.SLATE, bold=True, caps=True, spacing=1.0,
          base="Normal")
    style(doc, "Fact Value", font=T.HEAD, size=13, color=T.INK, base="Normal")
    _review_marker_style(doc)
    _placeholder_table_style(doc)
