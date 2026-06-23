from __future__ import annotations
import io
from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from src.hotel_options.models import Plan, EnrichedHotel


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


def _add_hyperlink(paragraph, text: str, url: str) -> None:
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    run_elem = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    style_elem = OxmlElement("w:rStyle")
    style_elem.set(qn("w:val"), "Hyperlink")
    rpr.append(style_elem)
    bold_elem = OxmlElement("w:b")
    rpr.append(bold_elem)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "28")  # 14pt = 28 half-points
    rpr.append(sz)
    szCs = OxmlElement("w:szCs")
    szCs.set(qn("w:val"), "28")  # 14pt = 28 half-points
    rpr.append(szCs)
    run_elem.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    run_elem.append(t)
    hyperlink.append(run_elem)
    paragraph._p.append(hyperlink)


def _add_horizontal_rule(doc: Document) -> None:
    p = doc.add_paragraph()
    ppr = p._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "auto")
    pbdr.append(bottom)
    ppr.append(pbdr)


def _add_page_break(doc: Document) -> None:
    p = doc.add_paragraph()
    run = p.add_run()
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    run._r.append(br)


def _remove_table_borders(table) -> None:
    tbl = table._tbl
    tbl_pr = tbl.tblPr
    for existing in tbl_pr.findall(qn("w:tblBorders")):
        tbl_pr.remove(existing)
    tbl_borders = OxmlElement("w:tblBorders")
    for name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = OxmlElement(f"w:{name}")
        border.set(qn("w:val"), "none")
        tbl_borders.append(border)
    tbl_pr.append(tbl_borders)


def _copy_letterhead(doc: Document, letterhead_path: str | Path) -> None:
    path = Path(letterhead_path)
    if not path.exists():
        return
    src = Document(str(path))
    for src_para in src.paragraphs:
        if not src_para.text.strip() and not src_para.runs:
            continue
        dst_para = doc.add_paragraph()
        dst_para.alignment = src_para.alignment
        for src_run in src_para.runs:
            dst_run = dst_para.add_run(src_run.text)
            dst_run.bold = src_run.bold
            dst_run.italic = src_run.italic
            if src_run.font.name:
                dst_run.font.name = src_run.font.name
            if src_run.font.size:
                dst_run.font.size = src_run.font.size


def _add_hotel_card(doc: Document, enriched: EnrichedHotel) -> None:
    if enriched.photo_bytes:
        img_para = doc.add_paragraph()
        img_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = img_para.add_run()
        run.add_picture(io.BytesIO(enriched.photo_bytes), width=Inches(5.5))
    else:
        p = doc.add_paragraph("[Photo not available]")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    name_para = doc.add_paragraph()
    _add_hyperlink(name_para, enriched.official_name, enriched.maps_url)

    rating_para = doc.add_paragraph(f"⭐ {enriched.rating} · {enriched.rating_count:,} reviews")
    if rating_para.runs:
        rating_para.runs[0].font.size = Pt(11)

    addr_parts = []
    if enriched.address:
        addr_parts.append(f"📍 {enriched.address}")
    if enriched.phone:
        addr_parts.append(f"📞 {enriched.phone}")
    if addr_parts:
        addr_para = doc.add_paragraph("  ·  ".join(addr_parts))
        if addr_para.runs:
            addr_para.runs[0].font.size = Pt(11)

    info_parts = []
    if enriched.cancellation:
        info_parts.append(f"🗓 {enriched.cancellation}")
    if enriched.meal_type:
        info_parts.append(f"🍳 {enriched.meal_type}")
    if info_parts:
        info_para = doc.add_paragraph("  ·  ".join(info_parts))
        if info_para.runs:
            info_para.runs[0].font.size = Pt(11)

    desc_para = doc.add_paragraph(enriched.description)
    if desc_para.runs:
        desc_para.runs[0].font.size = Pt(11)


def _add_pricing_table(doc: Document, plan: Plan) -> None:
    p = plan.pricing
    table = doc.add_table(rows=3, cols=2)
    _remove_table_borders(table)

    table.rows[0].cells[0].text = "Best Online Price"
    table.rows[0].cells[1].text = format_indian_number(p.total_online_price)

    table.rows[1].cells[0].text = "Our Best Price"
    table.rows[1].cells[1].text = format_indian_number(p.discounted_price)
    for cell in table.rows[1].cells:
        for para in cell.paragraphs:
            for run in para.runs:
                run.bold = True

    savings = f"{format_indian_number(p.customer_discount)} · {p.discount_pct:.1f}% off"
    table.rows[2].cells[0].text = "Your Savings"
    table.rows[2].cells[1].text = savings


def build_document(
    plans: list[Plan],
    enriched_map: dict[str, EnrichedHotel],
    client_name: str,
    destination: str,
    letterhead_path: str | Path,
) -> bytes:
    doc = Document()

    _copy_letterhead(doc, letterhead_path)
    _add_horizontal_rule(doc)

    title = doc.add_paragraph()
    title_run = title.add_run(f"Accommodation Options — {destination}")
    title_run.bold = True
    title_run.font.size = Pt(16)

    if client_name:
        sub = doc.add_paragraph(f"Prepared for: {client_name}")
        if sub.runs:
            sub.runs[0].font.size = Pt(12)

    for plan in plans:
        _add_page_break(doc)

        heading = doc.add_paragraph()
        h_run = heading.add_run(plan.label)
        h_run.bold = True
        h_run.font.size = Pt(16)

        for i, hotel in enumerate(plan.hotels):
            if i > 0:
                _add_horizontal_rule(doc)
            enriched = enriched_map.get(hotel.name)
            if enriched:
                _add_hotel_card(doc, enriched)
            else:
                doc.add_paragraph(f"[{hotel.name} — enrichment not available]")

        _add_pricing_table(doc, plan)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
