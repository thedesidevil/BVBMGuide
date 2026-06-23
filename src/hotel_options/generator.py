from __future__ import annotations
import io

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from src.hotel_options.models import Plan, EnrichedHotel

# ── Design constants ──────────────────────────────────────────────────────────
_CHARCOAL = RGBColor(0x2D, 0x2D, 0x2D)
_GREY     = RGBColor(0x66, 0x66, 0x66)
_GREEN    = RGBColor(0x2E, 0x7D, 0x32)
_WHITE    = RGBColor(0xFF, 0xFF, 0xFF)

_FONT = "Arial"

_LIGHT_GREY = "F2F2F2"
_ROW_ALT    = "F7F7F7"
_RULE_COLOR = "CCCCCC"
_HDR_BG     = "1F497D"  # dark navy blue

_MARGIN = Inches(0.75)


# ── Low-level helpers ─────────────────────────────────────────────────────────

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


def _set_margins(doc: Document) -> None:
    for section in doc.sections:
        section.top_margin    = _MARGIN
        section.bottom_margin = _MARGIN
        section.left_margin   = _MARGIN
        section.right_margin  = _MARGIN


def _configure_styles(doc: Document) -> None:
    """Set Arial as the universal font and define heading hierarchy."""
    normal = doc.styles["Normal"]
    normal.font.name  = _FONT
    normal.font.size  = Pt(11)
    normal.font.color.rgb = _CHARCOAL
    normal.paragraph_format.space_after      = Pt(8)
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    normal.paragraph_format.line_spacing      = 1.15

    # Title — cover page title (26 pt bold centered)
    title = doc.styles["Title"]
    title.font.name  = _FONT
    title.font.size  = Pt(26)
    title.font.bold  = True
    title.font.color.rgb = _CHARCOAL
    title.paragraph_format.alignment   = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(10)

    # Heading 1 — major sections: Executive Summary, Plan A / B / C …
    h1 = doc.styles["Heading 1"]
    h1.font.name  = _FONT
    h1.font.size  = Pt(16)
    h1.font.bold  = True
    h1.font.color.rgb = _CHARCOAL
    h1.paragraph_format.space_before = Pt(0)
    h1.paragraph_format.space_after  = Pt(4)

    # Heading 2 — hotel names
    h2 = doc.styles["Heading 2"]
    h2.font.name  = _FONT
    h2.font.size  = Pt(14)
    h2.font.bold  = True
    h2.font.color.rgb = _CHARCOAL
    h2.paragraph_format.space_before = Pt(4)
    h2.paragraph_format.space_after  = Pt(6)

    # Heading 3 — sub-labels (cover subtitle, etc.)
    h3 = doc.styles["Heading 3"]
    h3.font.name   = _FONT
    h3.font.size   = Pt(12)
    h3.font.bold   = False
    h3.font.italic = True
    h3.font.color.rgb = _GREY
    h3.paragraph_format.alignment   = WD_ALIGN_PARAGRAPH.CENTER
    h3.paragraph_format.space_after = Pt(8)


def _fix_fonts(para) -> None:
    """Force Arial on every run — overrides Calibri theme font from template."""
    for run in para.runs:
        run.font.name = _FONT


def _heading(doc: Document, text: str, level: int,
             align: WD_ALIGN_PARAGRAPH | None = None):
    """Add a heading paragraph with guaranteed Arial font on all runs."""
    p = doc.add_heading(text, level=level)
    if align is not None:
        p.alignment = align
    _fix_fonts(p)
    return p


def _spacing(para, before: float = 0, after: float = 8) -> None:
    fmt = para.paragraph_format
    fmt.space_before      = Pt(before)
    fmt.space_after       = Pt(after)
    fmt.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    fmt.line_spacing      = 1.15


def _body_run(para, text: str, *, bold=False, italic=False,
              size: float = 11, color: RGBColor = _CHARCOAL) -> None:
    r = para.add_run(text)
    r.bold           = bold
    r.italic         = italic
    r.font.name      = _FONT
    r.font.size      = Pt(size)
    r.font.color.rgb = color


def _thin_rule(doc: Document, before: float = 4, after: float = 4) -> None:
    p = doc.add_paragraph()
    _spacing(p, before, after)
    ppr = p._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "4")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), _RULE_COLOR)
    pbdr.append(bottom)
    ppr.append(pbdr)


def _page_break(doc: Document) -> None:
    p = doc.add_paragraph()
    _spacing(p, 0, 0)
    run = p.add_run()
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    run._r.append(br)


def _shade_cell(cell, hex_color: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


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



# ── Cover page ────────────────────────────────────────────────────────────────

def _build_cover_page(doc: Document, destination: str, client_name: str,
                      requirements: str) -> None:
    def blank(n: int = 1) -> None:
        for _ in range(n):
            p = doc.add_paragraph()
            _spacing(p, 0, 0)

    blank(8)

    # Title — uses "Title" style (Arial 26pt bold centered)
    title_para = doc.add_paragraph(f"{destination.upper()} HOTEL OPTIONS",
                                   style="Title")
    _spacing(title_para, 0, 10)
    _fix_fonts(title_para)

    # Subtitle — uses "Heading 3" style (Arial 12pt italic centered grey)
    sub = doc.add_paragraph("Curated Accommodation Recommendations",
                            style="Heading 3")
    _spacing(sub, 0, 8)
    _fix_fonts(sub)

    blank(4)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 0, 4)
    _body_run(p, "Prepared Exclusively For", color=_GREY)

    if client_name:
        cp = doc.add_paragraph(client_name.upper(), style="Heading 1")
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(cp, 0, 6)
        _fix_fonts(cp)

    if requirements:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 2, 0)
        _body_run(p, requirements, size=10, color=_GREY)


# ── Executive Summary ─────────────────────────────────────────────────────────

def _build_executive_summary(doc: Document, plans: list[Plan],
                              enriched_map: dict[str, EnrichedHotel]) -> None:
    _heading(doc, "Executive Summary", level=1)

    p = doc.add_paragraph()
    _spacing(p, 0, 12)
    _body_run(p, "Compare all accommodation options at a glance.", color=_GREY)

    prices  = [pl.pricing.discounted_price for pl in plans]
    savings = [pl.pricing.customer_discount for pl in plans]
    pcts    = [pl.pricing.discount_pct for pl in plans]
    min_price_idx   = prices.index(min(prices))
    max_savings_idx = savings.index(max(savings))
    best_value_idx  = pcts.index(max(pcts)) if max(pcts) > 0 else -1

    col_labels = ["Plan", "Hotels", "Best Online Price", "Our Price", "You Save",
                  "Cancellation", "Breakfast"]
    table = doc.add_table(rows=1 + len(plans), cols=len(col_labels))

    for i, label in enumerate(col_labels):
        cell = table.rows[0].cells[i]
        _shade_cell(cell, _HDR_BG)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _body_run(p, label, bold=True, size=9, color=_WHITE)

    for row_idx, plan in enumerate(plans):
        row = table.rows[row_idx + 1]
        bg = "FFFFFF" if row_idx % 2 == 0 else _ROW_ALT

        cancel_raw = next(
            (h.cancellation for h in plan.hotels
             if h.cancellation and "free" in h.cancellation.lower()),
            next((h.cancellation for h in plan.hotels if h.cancellation), "—"),
        )
        cancellation = (cancel_raw[:27] + "…") if len(cancel_raw) > 30 else cancel_raw

        meal_types = [h.meal_type for h in plan.hotels if h.meal_type]
        breakfast  = "Included" if any("breakfast" in m.lower() for m in meal_types) else "Not included"

        badges: list[str] = []
        if row_idx == min_price_idx:
            badges.append("LOWEST COST")
        if row_idx == max_savings_idx and row_idx != min_price_idx:
            badges.append("HIGHEST SAVINGS")
        if best_value_idx >= 0 and row_idx == best_value_idx \
                and row_idx not in (min_price_idx, max_savings_idx):
            badges.append("BEST VALUE")

        you_save_str = (
            f"{format_indian_number(plan.pricing.customer_discount)}"
            f"  ({plan.pricing.discount_pct:.1f}% off)"
        )

        # col: 0=Plan 1=Hotels 2=BestOnline 3=OurPrice 4=YouSave 5=Cancel 6=Breakfast
        col_configs = [
            (plan.label,                                             WD_ALIGN_PARAGRAPH.CENTER, _CHARCOAL, True),
            (None,                                                   WD_ALIGN_PARAGRAPH.LEFT,   _CHARCOAL, False),
            (format_indian_number(plan.pricing.total_online_price),  WD_ALIGN_PARAGRAPH.CENTER, _CHARCOAL, False),
            (format_indian_number(plan.pricing.discounted_price),    WD_ALIGN_PARAGRAPH.CENTER, _CHARCOAL, True),
            (you_save_str,                                           WD_ALIGN_PARAGRAPH.CENTER, _GREEN,    True),
            (cancellation,                                           WD_ALIGN_PARAGRAPH.CENTER, _CHARCOAL, False),
            (breakfast,                                              WD_ALIGN_PARAGRAPH.CENTER, _CHARCOAL, False),
        ]

        for col_idx, (text, align, color, bold) in enumerate(col_configs):
            cell = row.cells[col_idx]
            _shade_cell(cell, bg)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            p.alignment = align

            if col_idx == 1:
                for h_idx, hotel in enumerate(plan.hotels):
                    bp = p if h_idx == 0 else cell.add_paragraph()
                    bp.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    _body_run(bp, f"• {hotel.name}", size=9, color=_CHARCOAL)
            else:
                _body_run(p, text, bold=bold, size=9, color=color)

            if col_idx == 0 and badges:
                for badge in badges:
                    p2 = cell.add_paragraph()
                    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    _spacing(p2, 1, 1)
                    _body_run(p2, badge, bold=True, size=7.5, color=_GREEN)

    _thin_borders(table)


# ── Hotel card ────────────────────────────────────────────────────────────────

def _add_key_facts(doc: Document, enriched: EnrichedHotel) -> None:
    facts: list[tuple[str, str]] = []
    if enriched.address:
        facts.append(("📍 Location", enriched.address))
    if enriched.phone:
        facts.append(("📞 Phone", enriched.phone))
    if enriched.rating:
        facts.append(("⭐ Guest Rating",
                       f"{enriched.rating} / 5  ({enriched.rating_count:,} reviews)"))
    if enriched.dates:
        facts.append(("📅 Check-in / Check-out", enriched.dates))
    if enriched.cancellation:
        facts.append(("🔄 Cancellation", enriched.cancellation))
    if enriched.meal_type:
        facts.append(("🍳 Breakfast", enriched.meal_type))

    for label, value in facts:
        p = doc.add_paragraph()
        _spacing(p, 1, 2)
        _body_run(p, f"{label}:  ", bold=True, size=11, color=_GREY)
        _body_run(p, value, size=11, color=_CHARCOAL)


def _add_hotel_card(doc: Document, enriched: EnrichedHotel) -> None:
    """Image → Heading 2 name → Key Facts → Description."""
    if enriched.photo_bytes:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 8, 6)
        p.add_run().add_picture(io.BytesIO(enriched.photo_bytes), width=Inches(5.5))
    else:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 8, 6)
        _body_run(p, "[ Image not available ]", size=9, color=_GREY)

    # Hotel name — Heading 2
    name_para = doc.add_paragraph(
        enriched.official_name or enriched.address or "Hotel",
        style="Heading 2",
    )
    _spacing(name_para, 4, 6)
    _fix_fonts(name_para)

    _add_key_facts(doc, enriched)

    if enriched.description:
        p = doc.add_paragraph()
        _spacing(p, 6, 8)
        _body_run(p, enriched.description)


# ── Pricing block ─────────────────────────────────────────────────────────────

def _add_pricing_block(doc: Document, plan: Plan) -> None:
    """Three-row pricing table: Online Price / Our Price / You Save."""
    pr = plan.pricing
    table = doc.add_table(rows=3, cols=2)
    _no_borders(table)

    rows_data = [
        ("Online Price", format_indian_number(pr.total_online_price),
         False, _GREY, _CHARCOAL, 11),
        ("Our Price",    format_indian_number(pr.discounted_price),
         True,  _GREY, _CHARCOAL, 13),
        ("You Save",
         f"{format_indian_number(pr.customer_discount)}  ({pr.discount_pct:.1f}% off best online prices)",
         True, _GREY, _GREEN, 11),
    ]

    for i, (label, value, bold, lbl_color, val_color, val_size) in enumerate(rows_data):
        lp = table.rows[i].cells[0].paragraphs[0]
        _body_run(lp, label, size=11, color=lbl_color)
        vp = table.rows[i].cells[1].paragraphs[0]
        vp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _body_run(vp, value, bold=bold, size=val_size, color=val_color)


# ── Main entry point ──────────────────────────────────────────────────────────

def build_document(
    plans: list[Plan],
    enriched_map: dict[str, EnrichedHotel],
    client_name: str,
    destination: str,
    requirements: str = "",
) -> bytes:
    doc = Document()
    _set_margins(doc)
    _configure_styles(doc)

    # Cover page
    _build_cover_page(doc, destination, client_name, requirements)
    _page_break(doc)

    # Executive Summary
    _build_executive_summary(doc, plans, enriched_map)
    _page_break(doc)

    # One page per plan
    for plan_idx, plan in enumerate(plans):
        if plan_idx > 0:
            _page_break(doc)

        # Plan heading — Heading 1
        _heading(doc, plan.label.upper(), level=1)
        _thin_rule(doc, before=2, after=8)

        # Hotel cards
        for i, hotel in enumerate(plan.hotels):
            if i > 0:
                _thin_rule(doc, before=8, after=4)
            enriched = enriched_map.get(hotel.name)
            if enriched:
                _add_hotel_card(doc, enriched)
            else:
                p = doc.add_paragraph()
                _spacing(p, 8, 8)
                _body_run(p, f"[ {hotel.name} — details not available ]",
                          color=_GREY)

        # Pricing
        _thin_rule(doc, before=12, after=8)
        _add_pricing_block(doc, plan)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
