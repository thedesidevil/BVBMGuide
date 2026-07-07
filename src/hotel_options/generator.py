from __future__ import annotations
import io
import re
import urllib.parse
from dataclasses import dataclass

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from src.hotel_options.models import Plan, EnrichedHotel


# ── Theme system ──────────────────────────────────────────────────────────────

@dataclass
class Theme:
    header_hex: str
    light_hex: str
    marinas_hex: str
    primary: RGBColor
    secondary: RGBColor
    accent: RGBColor


_THEME_NAVY = Theme(
    header_hex="1F3A5F",
    light_hex="F3F7FB",
    marinas_hex="F3F7FB",
    primary=RGBColor(0x1F, 0x3A, 0x5F),
    secondary=RGBColor(0x5E, 0x78, 0x9A),
    accent=RGBColor(0x2E, 0x86, 0xC1),
)

_THEME_GOLD = Theme(
    header_hex="8A6D2F",
    light_hex="FBF6EA",
    marinas_hex="FFFDF7",
    primary=RGBColor(0x8A, 0x6D, 0x2F),
    secondary=RGBColor(0xC7, 0x78, 0x00),
    accent=RGBColor(0xC7, 0x78, 0x00),
)


def _theme(index: int) -> Theme:
    return _THEME_NAVY if index % 2 == 0 else _THEME_GOLD


# ── Shared constants ──────────────────────────────────────────────────────────

_CHARCOAL     = RGBColor(0x2D, 0x2D, 0x2D)
_GREY         = RGBColor(0x66, 0x66, 0x66)
_GREEN        = RGBColor(0x2E, 0x7D, 0x32)
_WHITE        = RGBColor(0xFF, 0xFF, 0xFF)
_SAVINGS_BG   = "EAF4EA"
_REC_BANNER_BG = "FBF6EA"
_RULE_COLOR   = "CCCCCC"
_FONT         = "Arial"
_MARGIN       = Inches(0.75)


# ── Number formatting ─────────────────────────────────────────────────────────

def format_indian_number(amount: float) -> str:
    n = int(round(amount))
    s = str(n)
    if len(s) <= 3:
        return f"₹{s}"
    last3 = s[-3:]
    rest = s[:-3]
    groups: list[str] = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return f"₹{','.join(groups)},{last3}"


def _star_category(category: str) -> str:
    """'4-Star Hotel' → '4-star', '3 Star' → '3-star', else ''."""
    m = re.search(r'(\d)', category or "")
    return f"{m.group(1)}-star" if m else ""


# ── Document setup ────────────────────────────────────────────────────────────

def _set_margins(doc: Document) -> None:
    for section in doc.sections:
        section.top_margin    = _MARGIN
        section.bottom_margin = _MARGIN
        section.left_margin   = _MARGIN
        section.right_margin  = _MARGIN


def _configure_styles(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name  = _FONT
    normal.font.size  = Pt(11)
    normal.font.color.rgb = _CHARCOAL
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    normal.paragraph_format.line_spacing = 1.15

    h1 = doc.styles["Heading 1"]
    h1.font.name  = _FONT
    h1.font.size  = Pt(16)
    h1.font.bold  = True
    h1.font.color.rgb = _CHARCOAL
    h1.paragraph_format.space_before = Pt(0)
    h1.paragraph_format.space_after  = Pt(4)


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _blank(doc: Document, n: int = 1) -> None:
    for _ in range(n):
        p = doc.add_paragraph()
        _sp(p, 0, 0)


def _sp(para, before: float = 0, after: float = 0) -> None:
    fmt = para.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after  = Pt(after)


def _run(para, text: str, *, font: str = _FONT, size: float = 11,
         bold: bool = False, italic: bool = False,
         color: RGBColor = _CHARCOAL) -> None:
    r = para.add_run(text)
    r.bold           = bold
    r.italic         = italic
    r.font.name      = font
    r.font.size      = Pt(size)
    r.font.color.rgb = color


def _shade_cell(cell, hex_color: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _set_cell_margins(cell, top: float, left: float,
                      bottom: float, right: float) -> None:
    """Set cell padding in pt (converted to twips internally)."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement("w:tcMar")
    for side, val in [("top", top), ("left", left),
                      ("bottom", bottom), ("right", right)]:
        m = OxmlElement(f"w:{side}")
        m.set(qn("w:w"), str(int(val * 20)))
        m.set(qn("w:type"), "dxa")
        tcMar.append(m)
    tcPr.append(tcMar)


def _no_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    for existing in tbl_pr.findall(qn("w:tblBorders")):
        tbl_pr.remove(existing)
    tbl_borders = OxmlElement("w:tblBorders")
    for name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = OxmlElement(f"w:{name}")
        b.set(qn("w:val"), "none")
        tbl_borders.append(b)
    tbl_pr.append(tbl_borders)


def _thin_borders(table) -> None:
    for row in table.rows:
        for cell in row.cells:
            tcPr = cell._tc.get_or_add_tcPr()
            tcBorders = OxmlElement("w:tcBorders")
            for side in ("top", "left", "bottom", "right"):
                b = OxmlElement(f"w:{side}")
                b.set(qn("w:val"), "single")
                b.set(qn("w:sz"), "4")
                b.set(qn("w:color"), _RULE_COLOR)
                tcBorders.append(b)
            tcPr.append(tcBorders)


def _page_break(doc: Document) -> None:
    p = doc.add_paragraph()
    _sp(p, 0, 0)
    run = p.add_run()
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    run._r.append(br)


def _line_spacing_15(para) -> None:
    fmt = para.paragraph_format
    fmt.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    fmt.line_spacing = None


# ── Cover page helpers ────────────────────────────────────────────────────────

def _georgia(para, text: str, size: float, bold: bool = False,
             italic: bool = False, color: RGBColor = _CHARCOAL) -> None:
    _run(para, text, font="Georgia", size=size, bold=bold, italic=italic, color=color)


def _add_trip_snapshot(doc: Document, destination: str, requirements: str,
                       stay_requirements: str = "") -> None:
    import re as _re
    req_lines  = [r.strip() for r in _re.split(r'[\n,]+', requirements) if r.strip()]
    travellers = next((l for l in req_lines if _re.search(r'\d+\s+adult', l, _re.I)), "")
    rooms      = next((l for l in req_lines if _re.search(r'\d+\s+room', l, _re.I)), "")

    data = [
        ("DESTINATION", destination),
        ("TRAVELLERS",  travellers or "—"),
        ("ROOMS",       rooms or "—"),
        ("PREFERENCES", stay_requirements or "—"),
    ]

    _SNAP_HDR = "1F3A5F"
    _SNAP_ALT = "F7F3EA"
    _SNAP_LBL = RGBColor(0x8A, 0x6D, 0x2F)

    table = doc.add_table(rows=2, cols=4)
    _no_borders(table)

    hdr = table.rows[0].cells[0].merge(table.rows[0].cells[3])
    _shade_cell(hdr, _SNAP_HDR)
    _set_cell_margins(hdr, 7.2, 7.2, 7.2, 7.2)
    hp = hdr.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _sp(hp, 0, 0)
    _run(hp, "TRIP SNAPSHOT", size=10, color=_WHITE)

    for col_idx, (label, value) in enumerate(data):
        cell = table.rows[1].cells[col_idx]
        bg = _SNAP_ALT if col_idx % 2 == 0 else "FFFFFF"
        _shade_cell(cell, bg)
        lp = cell.paragraphs[0]
        _sp(lp, 0, 2)
        lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _run(lp, label, size=9, bold=True, color=_SNAP_LBL)
        vp = cell.add_paragraph()
        _sp(vp, 0, 2)
        vp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _run(vp, value, size=9, color=_CHARCOAL)


def _add_advisor_note(doc: Document, destination: str) -> None:
    p = doc.add_paragraph()
    _sp(p, 14, 6)
    _georgia(p, "A NOTE FROM BON VOYAGE BY MARINA", size=12, bold=True)

    note = (
        f"Thank you for giving us the opportunity to assist with your "
        f"{destination} journey. "
        f"The options in this document have been carefully reviewed and shortlisted "
        f"based on your preferences, location requirements, flexibility, and overall value. "
        f"We hope this guide helps you choose the stay that is right for you."
    )
    p = doc.add_paragraph()
    _sp(p, 0, 8)
    _run(p, note, size=10.5)


def _add_letterhead_footer(doc: Document, centered: bool = True) -> None:
    align = WD_ALIGN_PARAGRAPH.CENTER if centered else WD_ALIGN_PARAGRAPH.LEFT
    for text, bold, italic in [
        ("Bon Voyage By Marina", True, False),
        ("Bespoke Travel Planning • Premium Stays • Seamless Experiences", False, True),
        ("\U0001f4de +91 86000 15316 | \U0001f4f8 @bonvoyagebymarina | \U0001f310 www.bonvoyagebymarina.com", False, False),
    ]:
        p = doc.add_paragraph()
        p.alignment = align
        _sp(p, 4, 2)
        _run(p, text, size=11, bold=bold, italic=italic)
    p = doc.add_paragraph()
    p.alignment = align
    _sp(p, 0, 2)
    _run(p, "✈️ ", size=11)
    _run(p, "Crafting unforgettable journeys, one trip at a time.", size=11, italic=True)


def _build_cover_page(doc: Document, destination: str, client_name: str,
                      requirements: str, stay_requirements: str = "",
                      destination_photo: bytes | None = None) -> None:
    if destination_photo:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _sp(p, 0, 0)
        p.add_run().add_picture(io.BytesIO(destination_photo), width=Inches(7.0))
    else:
        _blank(doc, 4)

    _blank(doc, 2)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _sp(p, 0, 8)
    _georgia(p, f"{destination.upper()} ACCOMMODATION RECOMMENDATIONS", size=26, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _sp(p, 0, 20)
    _georgia(p, "Curated by Bon Voyage By Marina", size=12, italic=True, color=_GREY)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _sp(p, 0, 6)
    _georgia(p, "PREPARED EXCLUSIVELY FOR", size=14, color=_GREY)

    if client_name:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _sp(p, 0, 20)
        _georgia(p, client_name.upper(), size=14, bold=True)

    _add_trip_snapshot(doc, destination, requirements, stay_requirements)

    _page_break(doc)
    _add_advisor_note(doc, destination)
    _blank(doc, 1)
    _add_letterhead_footer(doc, centered=True)


# ── Thank-you page ────────────────────────────────────────────────────────────

def _build_thank_you_page(doc: Document, destination: str) -> None:
    _blank(doc, 6)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _sp(p, 0, 28)
    _run(p, "Thank You", size=20, bold=True)

    for text in [
        (
            f"Thank you for giving Bon Voyage By Marina the opportunity to assist with your {destination} journey. "
            f"We hope the accommodation options in this document help you find the stay that best matches your travel style, preferences, and budget."
        ),
        "Should you wish to explore additional options, alternative locations, upgraded room categories, or other travel arrangements, we would be delighted to assist.",
        f"We look forward to helping create an unforgettable {destination} experience for you.",
    ]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _sp(p, 0, 6)
        _run(p, text, size=11)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _sp(p, 18, 4)
    _run(p, "Warm regards,", size=11)
    _add_letterhead_footer(doc, centered=False)


# ── Stub (replaced in Task 6) ─────────────────────────────────────────────────

def build_document(
    plans: list[Plan],
    enriched_map: dict[str, EnrichedHotel],
    client_name: str,
    destination: str,
    requirements: str = "",
    destination_photo: bytes | None = None,
    stay_requirements: str = "",
    grouped_by_sections: bool = False,
) -> bytes:
    doc = Document()
    _set_margins(doc)
    _configure_styles(doc)
    _build_cover_page(doc, destination, client_name, requirements,
                      stay_requirements=stay_requirements,
                      destination_photo=destination_photo)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
