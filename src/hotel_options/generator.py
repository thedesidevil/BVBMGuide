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


def _thin_rule(doc: Document, before: float = 4, after: float = 4,
               color: str = _RULE_COLOR) -> None:
    """Table-based horizontal rule — survives copy-paste into Google Docs."""
    def _spacer(pts: float) -> None:
        p = doc.add_paragraph()
        fmt = p.paragraph_format
        fmt.space_before      = Pt(0)
        fmt.space_after       = Pt(pts)
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        fmt.line_spacing      = Pt(1)

    if before > 0:
        _spacer(before)

    table = doc.add_table(rows=1, cols=1)
    table.autofit = False
    _no_borders(table)

    # Minimal row height
    trPr = table.rows[0]._tr.get_or_add_trPr()
    trh = OxmlElement("w:trHeight")
    trh.set(qn("w:val"), "1")
    trh.set(qn("w:hRule"), "exact")
    trPr.append(trh)

    cell = table.rows[0].cells[0]
    cell.width = Inches(7.0)

    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()

    # Zero cell margins
    tcMar = OxmlElement("w:tcMar")
    for side in ("top", "left", "bottom", "right"):
        m = OxmlElement(f"w:{side}")
        m.set(qn("w:w"), "0")
        m.set(qn("w:type"), "dxa")
        tcMar.append(m)
    tcPr.append(tcMar)

    # Only bottom border visible
    tcBorders = OxmlElement("w:tcBorders")
    for side in ("top", "left", "right"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "none")
        el.set(qn("w:sz"), "0")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "auto")
        tcBorders.append(el)
    b = OxmlElement("w:bottom")
    b.set(qn("w:val"), "single")
    b.set(qn("w:sz"), "4")
    b.set(qn("w:space"), "0")
    b.set(qn("w:color"), color)
    tcBorders.append(b)
    tcPr.append(tcBorders)

    # Minimal paragraph inside cell
    cp = cell.paragraphs[0]
    fmt = cp.paragraph_format
    fmt.space_before      = Pt(0)
    fmt.space_after       = Pt(0)
    fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    fmt.line_spacing      = Pt(1)

    if after > 0:
        _spacer(after)


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



# ── Cover page helpers ────────────────────────────────────────────────────────

def _georgia(para, text: str, size: float, bold=False, italic=False,
             color: RGBColor = _CHARCOAL) -> None:
    r = para.add_run(text)
    r.bold           = bold
    r.italic         = italic
    r.font.name      = "Georgia"
    r.font.size      = Pt(size)
    r.font.color.rgb = color


def _add_trip_snapshot(doc: Document, destination: str, requirements: str,
                       stay_requirements: str = "") -> None:
    import re as _re
    req_lines  = [r.strip() for r in _re.split(r'[\n,]+', requirements) if r.strip()]
    travellers = next((l for l in req_lines if _re.search(r'\d+\s+adult', l, _re.I)), "")

    rows: list[tuple[str, str]] = [("Destination", destination)]
    if travellers:
        rows.append(("Travellers", travellers))
    if stay_requirements:
        rows.append(("Stay Requirements", stay_requirements))

    table = doc.add_table(rows=1 + len(rows), cols=2)
    _no_borders(table)

    # Header row — merged, "TRIP SNAPSHOT"
    hdr = table.rows[0].cells[0].merge(table.rows[0].cells[1])
    hp = hdr.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(hp, 8, 6)
    _body_run(hp, "TRIP SNAPSHOT", bold=True, size=9, color=_CHARCOAL)

    for i, (label, value) in enumerate(rows):
        lc = table.rows[i + 1].cells[0]
        vc = table.rows[i + 1].cells[1]
        lp = lc.paragraphs[0]
        _spacing(lp, 3, 3)
        _body_run(lp, label, bold=True, size=9, color=_GREY)
        vp = vc.paragraphs[0]
        _spacing(vp, 3, 3)
        _body_run(vp, value, size=9, color=_CHARCOAL)

    _thin_borders(table)


def _add_advisor_note(doc: Document, destination: str) -> None:
    p = doc.add_paragraph()
    _spacing(p, 14, 6)
    _georgia(p, "A NOTE FROM BON VOYAGE BY MARINA", size=12, bold=True)

    note = (
        f"Thank you for giving us the opportunity to assist with your "
        f"{destination} journey. "
        f"The options in this document have been carefully reviewed and shortlisted "
        f"based on your preferences, location requirements, flexibility, and overall value. "
        f"We hope this guide helps you choose the stay that is right for you."
    )
    p = doc.add_paragraph()
    _spacing(p, 0, 8)
    _body_run(p, note, size=10.5, color=_CHARCOAL)


# ── Cover page ────────────────────────────────────────────────────────────────

def _build_cover_page(doc: Document, destination: str, client_name: str,
                      requirements: str, stay_requirements: str = "",
                      destination_photo: bytes | None = None) -> None:
    def blank(n: int = 1) -> None:
        for _ in range(n):
            p = doc.add_paragraph()
            _spacing(p, 0, 0)

    # 1. Destination image — full width, ~2.25" tall
    if destination_photo:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 0, 0)
        p.add_run().add_picture(io.BytesIO(destination_photo), width=Inches(6.5))
    else:
        blank(4)

    blank(2)

    # 2. Title — Georgia 26pt Bold Centered
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 0, 8)
    _georgia(p, f"{destination.upper()} ACCOMMODATION RECOMMENDATIONS",
             size=26, bold=True)

    # 3. Subtitle — Georgia 12pt Italic Centered
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 0, 20)
    _georgia(p, "Curated by Bon Voyage By Marina", size=12, italic=True, color=_GREY)

    # 4. Personalization
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 0, 6)
    _georgia(p, "Prepared Exclusively For", size=14, color=_GREY)

    if client_name:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 0, 20)
        _georgia(p, client_name.upper(), size=14, bold=True)

    # 5. Trip Snapshot box
    _add_trip_snapshot(doc, destination, requirements, stay_requirements)

    # 6. Advisor Note — starts on its own page
    _page_break(doc)
    _add_advisor_note(doc, destination)

    # 7. Bottom branding
    blank(1)
    _thin_rule(doc, before=4, after=6, color=_HDR_BG)

    # Replicate BVBM Company Letterhead exactly: Arial 11pt, centered
    # Line 1: bold
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 12, 12)
    _body_run(p, "Bon Voyage By Marina", bold=True, size=11, color=_CHARCOAL)

    # Line 2: italic tagline
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 12, 12)
    _body_run(p, "Bespoke Travel Planning • Premium Stays • Seamless Experiences",
              italic=True, size=11, color=_CHARCOAL)

    # Line 3: contact info
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 12, 12)
    _body_run(p, "\U0001f4de +91 86000 15316 | \U0001f4f8 @bonvoyagebymarina | \U0001f310 www.bonvoyagebymarina.com",
              size=11, color=_CHARCOAL)

    # Line 4: emoji (plain) + italic tagline
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 12, 12)
    _body_run(p, "✈️ ", size=11, color=_CHARCOAL)
    _body_run(p, "Crafting unforgettable journeys, one trip at a time.",
              italic=True, size=11, color=_CHARCOAL)


# ── Executive Summary ─────────────────────────────────────────────────────────

def _build_executive_summary(doc: Document, plans: list[Plan],
                              enriched_map: dict[str, EnrichedHotel],
                              grouped_by_sections: bool = False) -> None:
    if not plans:
        return
    _heading(doc, "Executive Summary", level=1)

    p = doc.add_paragraph()
    _spacing(p, 0, 12)
    _body_run(p, "Compare all accommodation options at a glance.", color=_GREY)

    if grouped_by_sections:
        _build_exec_summary_by_hotel(doc, plans)
    else:
        _build_exec_summary_by_plan(doc, plans)

    _thin_borders(doc.tables[-1])


def _build_exec_summary_by_hotel(doc: Document, plans: list[Plan]) -> None:
    """One row per hotel. Used when the file has section headers instead of PLAN markers."""
    # Flatten to (section_label, hotel) pairs
    hotel_rows = [(plan.label, hotel) for plan in plans for hotel in plan.hotels]

    col_labels = ["City / Dates", "Hotel", "Online Price", "Our Price", "You Save"]
    col_widths = [Inches(1.55), Inches(2.55), Inches(0.9), Inches(0.9), Inches(1.1)]

    table = doc.add_table(rows=1 + len(hotel_rows), cols=len(col_labels))
    table.autofit = False
    for i, w in enumerate(col_widths):
        for row in table.rows:
            row.cells[i].width = w

    for i, label in enumerate(col_labels):
        cell = table.rows[0].cells[i]
        _shade_cell(cell, _HDR_BG)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 0, 0)
        _body_run(p, label, bold=True, size=9, color=_WHITE)

    # Per-section: track cheapest hotel for BEST PRICE badge
    section_cheapest: dict[str, float] = {}
    for label, hotel in hotel_rows:
        price = hotel.discounted_price if hotel.discounted_price > 0 else hotel.online_price
        if label not in section_cheapest or price < section_cheapest[label]:
            section_cheapest[label] = price

    # Alternate shading by section group, not by row index
    section_colors: dict[str, str] = {}
    _palette = ["FFFFFF", _ROW_ALT]
    for label, _ in hotel_rows:
        if label not in section_colors:
            section_colors[label] = _palette[len(section_colors) % 2]

    for row_idx, (section_label, hotel) in enumerate(hotel_rows):
        row = table.rows[row_idx + 1]
        bg = section_colors[section_label]
        our_price = hotel.discounted_price if hotel.discounted_price > 0 else hotel.online_price
        is_cheapest = abs(our_price - section_cheapest[section_label]) < 0.01

        you_save_amount = (
            format_indian_number(hotel.customer_discount)
            if hotel.customer_discount > 0 else "—"
        )
        you_save_pct = (
            f"({hotel.discount_pct:.1f}% off)"
            if hotel.customer_discount > 0 else None
        )

        col_configs = [
            (section_label,                             WD_ALIGN_PARAGRAPH.LEFT,   _CHARCOAL, False),
            (hotel.name,                                WD_ALIGN_PARAGRAPH.LEFT,   _CHARCOAL, False),
            (format_indian_number(hotel.online_price),  WD_ALIGN_PARAGRAPH.CENTER, _CHARCOAL, False),
            (format_indian_number(our_price),           WD_ALIGN_PARAGRAPH.CENTER, _CHARCOAL, True),
            (you_save_amount,                           WD_ALIGN_PARAGRAPH.CENTER, _GREEN,    True),
        ]

        for col_idx, (text, align, color, bold) in enumerate(col_configs):
            cell = row.cells[col_idx]
            _shade_cell(cell, bg)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            p.alignment = align
            _spacing(p, 2, 2)
            _body_run(p, text, bold=bold, size=9, color=color)
            if col_idx == 4 and you_save_pct:
                p2 = cell.add_paragraph()
                p2.alignment = align
                _spacing(p2, 0, 2)
                _body_run(p2, you_save_pct, bold=False, size=8, color=color)
            if col_idx == 3 and is_cheapest:
                p2 = cell.add_paragraph()
                p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _spacing(p2, 1, 1)
                _body_run(p2, "BEST PRICE", bold=True, size=7.5, color=_GREEN)


def _build_exec_summary_by_plan(doc: Document, plans: list[Plan]) -> None:
    """One row per plan. Used when the file has explicit PLAN A / PLAN B markers."""
    prices  = [pl.pricing.discounted_price for pl in plans]
    savings = [pl.pricing.customer_discount for pl in plans]
    pcts    = [pl.pricing.discount_pct for pl in plans]
    min_price_idx   = prices.index(min(prices))
    max_savings_idx = savings.index(max(savings))
    best_value_idx  = pcts.index(max(pcts)) if max(pcts) > 0 else -1

    col_labels = ["Plan", "Hotels", "Best Online Price", "Our Price", "You Save"]
    col_widths = [Inches(0.65), Inches(3.0), Inches(1.05), Inches(1.05), Inches(1.25)]
    table = doc.add_table(rows=1 + len(plans), cols=len(col_labels))
    table.autofit = False
    for i, w in enumerate(col_widths):
        for row in table.rows:
            row.cells[i].width = w

    for i, label in enumerate(col_labels):
        cell = table.rows[0].cells[i]
        _shade_cell(cell, _HDR_BG)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 0, 0)
        _body_run(p, label, bold=True, size=9, color=_WHITE)

    for row_idx, plan in enumerate(plans):
        row = table.rows[row_idx + 1]
        bg = "FFFFFF" if row_idx % 2 == 0 else _ROW_ALT

        badges: list[str] = []
        if row_idx == min_price_idx:
            badges.append("LOWEST COST")
        if row_idx == max_savings_idx and row_idx != min_price_idx:
            badges.append("HIGHEST SAVINGS")
        if best_value_idx >= 0 and row_idx == best_value_idx \
                and row_idx not in (min_price_idx, max_savings_idx):
            badges.append("BEST VALUE")

        you_save_amount = (
            format_indian_number(plan.pricing.customer_discount)
            if plan.pricing.customer_discount > 0 else "—"
        )
        you_save_pct = (
            f"({plan.pricing.discount_pct:.1f}% off)"
            if plan.pricing.customer_discount > 0 else None
        )

        col_configs = [
            (plan.label,                                             WD_ALIGN_PARAGRAPH.CENTER, _CHARCOAL, True),
            (None,                                                   WD_ALIGN_PARAGRAPH.LEFT,   _CHARCOAL, False),
            (format_indian_number(plan.pricing.total_online_price),  WD_ALIGN_PARAGRAPH.CENTER, _CHARCOAL, False),
            (format_indian_number(plan.pricing.discounted_price),    WD_ALIGN_PARAGRAPH.CENTER, _CHARCOAL, True),
            (you_save_amount,                                        WD_ALIGN_PARAGRAPH.CENTER, _GREEN,    True),
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

            if col_idx == 4 and you_save_pct:
                p2 = cell.add_paragraph()
                p2.alignment = align
                _spacing(p2, 0, 2)
                _body_run(p2, you_save_pct, bold=False, size=8, color=color)

            if col_idx == 0 and badges:
                for badge in badges:
                    p2 = cell.add_paragraph()
                    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    _spacing(p2, 1, 1)
                    _body_run(p2, badge, bold=True, size=7.5, color=_GREEN)


# ── Hotel card ────────────────────────────────────────────────────────────────

def _add_key_facts(doc: Document, enriched: EnrichedHotel) -> None:
    facts: list[tuple[str, str]] = []
    if enriched.address:
        facts.append(("📍 Location", enriched.address))
    if enriched.phone:
        facts.append(("📞 Phone", enriched.phone))
    if enriched.rating:
        facts.append(("⭐ Guest Rating",
                       f"{enriched.rating}/5 ({enriched.rating_count:,} reviews)"))
    if enriched.dates:
        facts.append(("📅 Check-in / Check-out", enriched.dates))
    if enriched.cancellation:
        facts.append(("🔄 Cancellation", enriched.cancellation))
    if enriched.meal_type:
        facts.append(("🍳 Breakfast", enriched.meal_type))

    for label, value in facts:
        p = doc.add_paragraph()
        _spacing(p, 1, 2)
        _body_run(p, f"{label}: ", size=11, color=_GREY)
        _body_run(p, value, size=11, color=_CHARCOAL)


def _add_hotel_card(doc: Document, enriched: EnrichedHotel) -> None:
    """Image → Heading 2 name → Key Facts → Description."""
    if enriched.photo_bytes:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 8, 6)
        p.add_run().add_picture(io.BytesIO(enriched.photo_bytes), width=Inches(5.0))
    else:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 8, 6)
        _body_run(p, "[ Image not available ]", size=9, color=_GREY)

    # Hotel name — Georgia 16pt Bold, 12pt above, thin divider below
    name_para = doc.add_paragraph()
    _spacing(name_para, 12, 0)
    r = name_para.add_run(enriched.official_name or enriched.address or "Hotel")
    r.bold           = True
    r.font.name      = "Georgia"
    r.font.size      = Pt(16)
    r.font.color.rgb = _CHARCOAL
    _thin_rule(doc, before=0, after=6)

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
         f"{format_indian_number(pr.customer_discount)} ({pr.discount_pct:.1f}% off best online prices)",
         True, _GREY, _GREEN, 11),
    ]

    for i, (label, value, bold, lbl_color, val_color, val_size) in enumerate(rows_data):
        lp = table.rows[i].cells[0].paragraphs[0]
        _body_run(lp, label, size=11, color=lbl_color)
        vp = table.rows[i].cells[1].paragraphs[0]
        vp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _body_run(vp, value, bold=bold, size=val_size, color=val_color)


def _add_hotel_pricing_block(doc: Document, hotel) -> None:
    """Per-hotel pricing table using HotelRow discount fields."""
    our_price = hotel.discounted_price if hotel.discounted_price > 0 else hotel.online_price
    if hotel.customer_discount > 0:
        save_str = (f"{format_indian_number(hotel.customer_discount)}"
                    f" ({hotel.discount_pct:.1f}% off best online prices)")
        save_color = _GREEN
    else:
        save_str = "—"
        save_color = _GREY

    table = doc.add_table(rows=3, cols=2)
    _no_borders(table)
    rows_data = [
        ("Online Price", format_indian_number(hotel.online_price), False, _GREY, _CHARCOAL, 11),
        ("Our Price",    format_indian_number(our_price),          True,  _GREY, _CHARCOAL, 13),
        ("You Save",     save_str,                                 True,  _GREY, save_color, 11),
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
    destination_photo: bytes | None = None,
    stay_requirements: str = "",
    grouped_by_sections: bool = False,
) -> bytes:
    doc = Document()
    _set_margins(doc)
    _configure_styles(doc)

    # Cover page
    _build_cover_page(doc, destination, client_name, requirements,
                      stay_requirements=stay_requirements,
                      destination_photo=destination_photo)
    _page_break(doc)

    # Executive Summary
    _build_executive_summary(doc, plans, enriched_map, grouped_by_sections=grouped_by_sections)
    _page_break(doc)

    # Detail sections
    if grouped_by_sections:
        # Section = city/dates group. Each hotel within a section gets its own
        # card + individual pricing block. One page break between sections.
        for plan_idx, plan in enumerate(plans):
            if plan_idx > 0:
                _page_break(doc)

            _heading(doc, plan.label.upper(), level=1)
            _thin_rule(doc, before=2, after=8, color=_HDR_BG)

            for i, hotel in enumerate(plan.hotels):
                if i > 0:
                    _thin_rule(doc, before=8, after=4)
                enriched = enriched_map.get(hotel.name)
                if enriched:
                    _add_hotel_card(doc, enriched)
                else:
                    p = doc.add_paragraph()
                    _spacing(p, 8, 4)
                    _body_run(p, hotel.name, bold=True, size=13, color=_CHARCOAL)
                    _thin_rule(doc, before=0, after=6)

                _thin_rule(doc, before=12, after=8)
                _add_hotel_pricing_block(doc, hotel)
    else:
        # Original plan-based layout — one page per plan, shared pricing block.
        for plan_idx, plan in enumerate(plans):
            if plan_idx > 0:
                _page_break(doc)

            _heading(doc, plan.label.upper(), level=1)
            _thin_rule(doc, before=2, after=8, color=_HDR_BG)

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

            _thin_rule(doc, before=12, after=8)
            _add_pricing_block(doc, plan)

    # Final thank you page
    _page_break(doc)
    _build_thank_you_page(doc, destination, destination_photo)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── Thank You page ────────────────────────────────────────────────────────────

def _build_thank_you_page(doc: Document, destination: str,
                          destination_photo: bytes | None = None) -> None:
    def blank(n: int = 1) -> None:
        for _ in range(n):
            p = doc.add_paragraph()
            _spacing(p, 0, 0)

    # Generous whitespace to push content toward middle of page
    blank(6)

    # Heading — Arial 20pt Bold, left-aligned
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _spacing(p, 0, 28)
    r = p.add_run("Thank You")
    r.bold           = True
    r.font.name      = _FONT
    r.font.size      = Pt(20)
    r.font.color.rgb = _CHARCOAL

    # Body — lines 1 and 2 in same paragraph, line 3 separate
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _spacing(p, 0, 6)
    _body_run(p, (
        f"Thank you for giving Bon Voyage By Marina the opportunity to assist with your {destination} journey. "
        f"We hope the accommodation options in this document help you find the stay that best matches your travel style, preferences, and budget."
    ), size=11, color=_CHARCOAL)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _spacing(p, 0, 6)
    _body_run(p, "Should you wish to explore additional options, alternative locations, upgraded room categories, or other travel arrangements, we would be delighted to assist.",
              size=11, color=_CHARCOAL)

    # Closing — regular (not italic)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _spacing(p, 18, 24)
    _body_run(p, f"We look forward to helping create an unforgettable {destination} experience for you.",
              size=11, color=_CHARCOAL)

    # Signature — "Warm regards," directly followed by letterhead block, no gap
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _spacing(p, 0, 4)
    _body_run(p, "Warm regards,", size=11, color=_CHARCOAL)

    # Full letterhead block — compact spacing matching the letterhead document
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _spacing(p, 4, 2)
    _body_run(p, "Bon Voyage By Marina", bold=True, size=11, color=_CHARCOAL)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _spacing(p, 0, 2)
    _body_run(p, "Bespoke Travel Planning • Premium Stays • Seamless Experiences",
              italic=True, size=11, color=_CHARCOAL)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _spacing(p, 0, 2)
    _body_run(p, "\U0001f4de +91 86000 15316 | \U0001f4f8 @bonvoyagebymarina | \U0001f310 www.bonvoyagebymarina.com",
              size=11, color=_CHARCOAL)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _spacing(p, 0, 2)
    _body_run(p, "✈️ ", size=11, color=_CHARCOAL)
    _body_run(p, "Crafting unforgettable journeys, one trip at a time.",
              italic=True, size=11, color=_CHARCOAL)
