from __future__ import annotations
import io

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from src.hotel_options.models import Plan, EnrichedHotel

# ── Design constants ──────────────────────────────────────────────────────────
_CHARCOAL = RGBColor(0x2D, 0x2D, 0x2D)
_GREY     = RGBColor(0x66, 0x66, 0x66)
_GREEN    = RGBColor(0x2E, 0x7D, 0x32)
_WHITE    = RGBColor(0xFF, 0xFF, 0xFF)

_SERIF = "Georgia"
_BODY  = "Calibri"       # Aptos with Calibri as fallback

_LIGHT_GREY = "F2F2F2"  # recommendation box background
_ROW_ALT    = "F7F7F7"  # alternate row in summary table
_RULE_COLOR = "CCCCCC"  # horizontal rules and thin borders
_HDR_BG     = "2D2D2D"  # summary table header background

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


def _spacing(para, before: float = 0, after: float = 8) -> None:
    fmt = para.paragraph_format
    fmt.space_before         = Pt(before)
    fmt.space_after          = Pt(after)
    fmt.line_spacing_rule    = WD_LINE_SPACING.MULTIPLE
    fmt.line_spacing         = 1.15


def _body_run(para, text: str, *, bold=False, italic=False,
              size: float = 10.5, font: str = _BODY,
              color: RGBColor = _CHARCOAL) -> None:
    r = para.add_run(text)
    r.bold        = bold
    r.italic      = italic
    r.font.name   = font
    r.font.size   = Pt(size)
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


def _add_hyperlink(para, text: str, url: str) -> None:
    """Hotel name as a charcoal Georgia hyperlink (no default blue)."""
    r_id = para.part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hl = OxmlElement("w:hyperlink")
    hl.set(qn("r:id"), r_id)
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    fonts.set(qn("w:ascii"), _SERIF)
    fonts.set(qn("w:hAnsi"), _SERIF)
    rpr.append(fonts)
    bold = OxmlElement("w:b")
    rpr.append(bold)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "28")   # 14 pt
    rpr.append(sz)
    szCs = OxmlElement("w:szCs")
    szCs.set(qn("w:val"), "28")
    rpr.append(szCs)
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "2D2D2D")
    rpr.append(color)
    # remove underline
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "none")
    rpr.append(u)
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    r.append(t)
    hl.append(r)
    para._p.append(hl)


def _fld_run(para, instruction: str, size_pt: float, color: RGBColor) -> None:
    """Append a PAGE / NUMPAGES field run to para._p."""
    hex_color = f"{color[0]:02X}{color[1]:02X}{color[2]:02X}"
    half_pt = str(int(size_pt * 2))

    def _rpr():
        rpr = OxmlElement("w:rPr")
        fonts = OxmlElement("w:rFonts")
        fonts.set(qn("w:ascii"), _BODY)
        fonts.set(qn("w:hAnsi"), _BODY)
        rpr.append(fonts)
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), half_pt)
        rpr.append(sz)
        col = OxmlElement("w:color")
        col.set(qn("w:val"), hex_color)
        rpr.append(col)
        return rpr

    r_begin = OxmlElement("w:r")
    r_begin.append(_rpr())
    fc = OxmlElement("w:fldChar")
    fc.set(qn("w:fldCharType"), "begin")
    r_begin.append(fc)

    r_instr = OxmlElement("w:r")
    r_instr.append(_rpr())
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    r_instr.append(instr)

    r_end = OxmlElement("w:r")
    r_end.append(_rpr())
    fc_end = OxmlElement("w:fldChar")
    fc_end.set(qn("w:fldCharType"), "end")
    r_end.append(fc_end)

    para._p.append(r_begin)
    para._p.append(r_instr)
    para._p.append(r_end)


# ── Footer ────────────────────────────────────────────────────────────────────

def _add_footer(doc: Document) -> None:
    """Footer on every page except the cover (first page)."""
    section = doc.sections[0]
    section.different_first_page_header_footer = True

    footer = section.footer
    footer.is_linked_to_previous = False

    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.clear()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Thin line above footer text
    ppr = p._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    top = OxmlElement("w:top")
    top.set(qn("w:val"), "single")
    top.set(qn("w:sz"), "4")
    top.set(qn("w:space"), "1")
    top.set(qn("w:color"), _RULE_COLOR)
    pbdr.append(top)
    ppr.append(pbdr)

    _body_run(p, "Bon Voyage By Marina  ·  Crafting Unforgettable Journeys  ·  Page ",
              size=8, color=_GREY)
    _fld_run(p, "PAGE", 8, _GREY)
    _body_run(p, " of ", size=8, color=_GREY)
    _fld_run(p, "NUMPAGES", 8, _GREY)


# ── Cover page ────────────────────────────────────────────────────────────────

def _build_cover_page(doc: Document, destination: str, client_name: str,
                      requirements: str) -> None:
    def blank(n: int = 1) -> None:
        for _ in range(n):
            p = doc.add_paragraph()
            _spacing(p, 0, 0)

    blank(8)

    # Title
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 0, 10)
    r = p.add_run(f"{destination.upper()} HOTEL OPTIONS")
    r.bold        = True
    r.font.name   = _SERIF
    r.font.size   = Pt(26)
    r.font.color.rgb = _CHARCOAL

    # Subtitle
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 0, 8)
    r = p.add_run("Curated Accommodation Recommendations")
    r.italic      = True
    r.font.name   = _SERIF
    r.font.size   = Pt(12)
    r.font.color.rgb = _GREY

    blank(4)

    # "Prepared Exclusively For"
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 0, 4)
    _body_run(p, "Prepared Exclusively For", size=10.5, color=_GREY)

    # Client name
    if client_name:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 0, 6)
        r = p.add_run(client_name.upper())
        r.bold        = True
        r.font.name   = _SERIF
        r.font.size   = Pt(14)
        r.font.color.rgb = _CHARCOAL

    # Requirements
    if requirements:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 2, 0)
        _body_run(p, requirements, size=10, color=_GREY)

    blank(7)
    _thin_rule(doc, before=2, after=8)

    for line, bold in [
        ("Bon Voyage By Marina", True),
        ("Crafting Unforgettable Journeys", False),
        ("+91 86000 15316", False),
        ("@bonvoyagebymarina", False),
    ]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 2, 2)
        _body_run(p, line, bold=bold, size=10,
                  color=_CHARCOAL if bold else _GREY)


# ── Executive Summary ─────────────────────────────────────────────────────────

def _build_executive_summary(doc: Document, plans: list[Plan],
                              enriched_map: dict[str, EnrichedHotel]) -> None:
    # Heading
    p = doc.add_paragraph()
    _spacing(p, 0, 6)
    r = p.add_run("Executive Summary")
    r.bold        = True
    r.font.name   = _SERIF
    r.font.size   = Pt(16)
    r.font.color.rgb = _CHARCOAL

    _thin_rule(doc, before=2, after=10)

    p = doc.add_paragraph()
    _spacing(p, 0, 12)
    _body_run(p, "Compare all accommodation options at a glance.",
              size=10.5, color=_GREY)

    # Determine highlight indices
    prices  = [pl.pricing.discounted_price for pl in plans]
    savings = [pl.pricing.customer_discount for pl in plans]
    pcts    = [pl.pricing.discount_pct for pl in plans]
    min_price_idx   = prices.index(min(prices))
    max_savings_idx = savings.index(max(savings))
    best_value_idx  = pcts.index(max(pcts)) if max(pcts) > 0 else -1

    col_labels = ["Plan", "Hotels", "Our Price", "You Save",
                  "Cancellation", "Breakfast"]
    table = doc.add_table(rows=1 + len(plans), cols=len(col_labels))

    # Header row
    for i, label in enumerate(col_labels):
        cell = table.rows[0].cells[i]
        _shade_cell(cell, _HDR_BG)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _body_run(p, label, bold=True, size=9, color=_WHITE)

    # Data rows
    for row_idx, plan in enumerate(plans):
        row = table.rows[row_idx + 1]
        bg = "FFFFFF" if row_idx % 2 == 0 else _ROW_ALT

        # Cancellation: prefer "free cancellation" entry, else first available
        cancel_raw = next(
            (h.cancellation for h in plan.hotels
             if h.cancellation and "free" in h.cancellation.lower()),
            next((h.cancellation for h in plan.hotels if h.cancellation), "—"),
        )
        cancellation = (cancel_raw[:27] + "…") if len(cancel_raw) > 30 else cancel_raw

        meal_types = [h.meal_type for h in plan.hotels if h.meal_type]
        breakfast  = "Included" if any("breakfast" in m.lower() for m in meal_types) else "Not included"

        hotels_str = "\n".join(h.name for h in plan.hotels)

        badges: list[str] = []
        if row_idx == min_price_idx:
            badges.append("LOWEST COST")
        if row_idx == max_savings_idx and row_idx != min_price_idx:
            badges.append("HIGHEST SAVINGS")
        if best_value_idx >= 0 and row_idx == best_value_idx \
                and row_idx not in (min_price_idx, max_savings_idx):
            badges.append("BEST VALUE")

        cells_data = [
            (plan.label, WD_ALIGN_PARAGRAPH.CENTER),
            (hotels_str, WD_ALIGN_PARAGRAPH.LEFT),
            (format_indian_number(plan.pricing.discounted_price), WD_ALIGN_PARAGRAPH.CENTER),
            (format_indian_number(plan.pricing.customer_discount), WD_ALIGN_PARAGRAPH.CENTER),
            (cancellation, WD_ALIGN_PARAGRAPH.CENTER),
            (breakfast, WD_ALIGN_PARAGRAPH.CENTER),
        ]

        for col_idx, (text, align) in enumerate(cells_data):
            cell = row.cells[col_idx]
            _shade_cell(cell, bg)
            p = cell.paragraphs[0]
            p.alignment = align
            color = _GREEN if col_idx == 3 else _CHARCOAL
            bold  = col_idx in (0, 3)
            _body_run(p, text, bold=bold, size=9, color=color)

            if col_idx == 0 and badges:
                for badge in badges:
                    p2 = cell.add_paragraph()
                    _spacing(p2, 1, 1)
                    _body_run(p2, badge, bold=True, size=7.5, color=_GREEN)

    _thin_borders(table)


# ── Hotel card ────────────────────────────────────────────────────────────────

def _add_key_facts(doc: Document, enriched: EnrichedHotel) -> None:
    """Key facts block — no emojis, clean label: value format."""
    facts: list[tuple[str, str]] = []
    if enriched.address:
        facts.append(("Location", enriched.address))
    if enriched.rating:
        facts.append(("Guest Rating",
                       f"{enriched.rating} / 5  ({enriched.rating_count:,} reviews)"))
    if enriched.dates:
        facts.append(("Check-in / Check-out", enriched.dates))
    if enriched.cancellation:
        label = "Cancellation"
        facts.append((label, enriched.cancellation))
    if enriched.meal_type:
        facts.append(("Breakfast", enriched.meal_type))

    for label, value in facts:
        p = doc.add_paragraph()
        _spacing(p, 1, 2)
        # Label in grey, value in charcoal on the same line
        _body_run(p, f"{label}:  ", bold=True, size=9, color=_GREY)
        _body_run(p, value, size=10.5, color=_CHARCOAL)


def _add_hotel_card(doc: Document, enriched: EnrichedHotel) -> None:
    """Image → Name (hyperlink) → Key Facts → Description."""
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

    # Hotel name
    name_para = doc.add_paragraph()
    _spacing(name_para, 4, 6)
    _add_hyperlink(name_para,
                   enriched.official_name or enriched.address or "Hotel",
                   enriched.maps_url)

    _add_key_facts(doc, enriched)

    if enriched.description:
        p = doc.add_paragraph()
        _spacing(p, 6, 8)
        _body_run(p, enriched.description, size=10.5)


# ── Pricing block ─────────────────────────────────────────────────────────────

def _add_pricing_block(doc: Document, plan: Plan) -> None:
    """Three-row pricing table: Online Price / Our Price / You Save."""
    p = plan.pricing
    table = doc.add_table(rows=3, cols=2)
    _no_borders(table)

    rows_data = [
        ("Online Price",
         format_indian_number(p.total_online_price),
         False, _GREY, _CHARCOAL, 10.5),
        ("Our Price",
         format_indian_number(p.discounted_price),
         True, _GREY, _CHARCOAL, 13),
        ("You Save",
         f"{format_indian_number(p.customer_discount)}  ({p.discount_pct:.1f}% off best online prices)",
         True, _GREY, _GREEN, 11),
    ]

    for i, (label, value, bold, lbl_color, val_color, val_size) in enumerate(rows_data):
        lp = table.rows[i].cells[0].paragraphs[0]
        _body_run(lp, label, size=10.5, color=lbl_color)
        vp = table.rows[i].cells[1].paragraphs[0]
        vp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _body_run(vp, value, bold=bold, size=val_size, color=val_color)


# ── Recommendation box ────────────────────────────────────────────────────────

def _recommendation_bullets(plan: Plan,
                             enriched_hotels: list[EnrichedHotel]) -> list[str]:
    bullets: list[str] = []

    high_rated = [h for h in enriched_hotels if h.rating and h.rating >= 4.3]
    if high_rated and len(high_rated) == len(enriched_hotels):
        bullets.append("Consistently well-rated hotels across the stay")
    elif high_rated:
        bullets.append("Includes a highly rated property")

    free_cancel = any(
        h.cancellation and "free" in h.cancellation.lower()
        for h in enriched_hotels
    )
    non_refund = any(
        h.cancellation and "non-refundable" in h.cancellation.lower()
        for h in enriched_hotels
    )
    if free_cancel:
        bullets.append("Flexible cancellation — peace of mind if plans change")
    elif non_refund:
        bullets.append("Non-refundable rate secures the best available price")

    has_breakfast = any(
        h.meal_type and "breakfast" in h.meal_type.lower()
        for h in enriched_hotels
    )
    if has_breakfast:
        bullets.append("Breakfast included — no daily add-on costs")

    if plan.pricing.discount_pct >= 7:
        bullets.append(
            f"Savings of {plan.pricing.discount_pct:.1f}% over best available online prices"
        )

    if len(plan.hotels) >= 2:
        bullets.append("Curated hotel mix to suit different legs of the trip")

    return (bullets or ["Thoughtfully curated for this itinerary"])[:5]


def _add_recommendation_box(doc: Document, plan: Plan,
                             enriched_hotels: list[EnrichedHotel]) -> None:
    bullets = _recommendation_bullets(plan, enriched_hotels)

    p = doc.add_paragraph()
    _spacing(p, 12, 4)

    table = doc.add_table(rows=1, cols=1)
    _no_borders(table)
    cell = table.rows[0].cells[0]
    _shade_cell(cell, _LIGHT_GREY)

    hp = cell.paragraphs[0]
    _spacing(hp, 8, 6)
    _body_run(hp, "WHY WE RECOMMEND THIS OPTION",
              bold=True, size=9, color=_CHARCOAL)

    for bullet in bullets:
        bp = cell.add_paragraph()
        _spacing(bp, 2, 2)
        _body_run(bp, f"•  {bullet}", size=10.5, color=_CHARCOAL)

    pp = cell.add_paragraph()
    _spacing(pp, 6, 2)


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
    _add_footer(doc)

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

        # Plan heading
        p = doc.add_paragraph()
        _spacing(p, 0, 4)
        r = p.add_run(plan.label.upper())
        r.bold        = True
        r.font.name   = _SERIF
        r.font.size   = Pt(16)
        r.font.color.rgb = _CHARCOAL
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
                          size=10.5, color=_GREY)

        # Pricing
        _thin_rule(doc, before=12, after=8)
        _add_pricing_block(doc, plan)

        # Recommendation box
        enriched_hotels = [enriched_map[h.name] for h in plan.hotels
                           if h.name in enriched_map]
        _add_recommendation_box(doc, plan, enriched_hotels)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
