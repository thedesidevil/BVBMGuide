import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

from docx import Document
from docx.oxml.ns import qn

from src.aigv2.guide.build import build_day_page
from src.aigv2.guide.model import MarkerRef, MealBlock, Opener, PlaceholderMeal, Restaurant
from src.aigv2.qc.reader import MEAL_SLOT_RE, read_docx
from src.aigv2.render.document import GuideData
from src.aigv2.render2 import frame as F
from src.aigv2.render2 import meals as M

FIX = Path(__file__).parent / "fixtures" / "bali_guide" / "guide_data.json"


def _doc():
    doc = F.new_guide_doc("Dilna K", "Bali")
    _, W = F.add_guide_section(doc, "day", F.guide_label("Dilna K", "Bali"), first=True)
    return doc, W


def _r(i, **kw):
    d = dict(name=f"Warung {i}", maps_url=f"https://maps.example/{i}", cuisines=["Balinese", "Seafood"],
             text="A calm spot overlooking the paddies.", must_try="Bebek betutu, sate lilit",
             hours="9:00 AM – 9:00 PM", price="INR 800–1,500 per person", travel="8 min by car")
    d.update(kw)
    return Restaurant(**d)


def _block(rs=None):
    return MealBlock(meal="lunch", eyebrow="LUNCH", heading="Lunch near Ubud Palace",
                     restaurants=rs or [_r(1), _r(2), _r(3)])


def _render(block=None):
    doc, W = _doc()
    M.render_meal_block(doc, W, block or _block())
    return doc


def _card(doc):
    return doc.tables[0]


def _nested(doc):
    return _card(doc).rows[0].cells[0].tables[0]


def _paras(cell):
    return [p for p in cell.paragraphs]


def _sz(tc, side):
    return tc.tcPr.find(qn("w:tcBorders")).find(qn("w:" + side))


def test_heading_is_heading2_and_matches_slot_regex():
    doc = _render()
    h = [p for p in doc.paragraphs if p.style.name == "Heading 2"]
    assert len(h) == 1 and h[0].text == "Lunch near Ubud Palace"
    assert MEAL_SLOT_RE.match(h[0].text)
    body = doc.element.body
    kids = list(body)
    tbl_idx = kids.index(_card(doc)._tbl)
    hi = kids.index(h[0]._p)
    for e in kids[hi + 1:tbl_idx]:
        if e.tag == qn("w:p"):
            assert not e.findall(".//" + qn("w:i"))
            assert "".join(t.text or "" for t in e.iter(qn("w:t"))) == ""


def test_card_look():
    c = _card(_render()).rows[0].cells[0]._tc
    assert c.tcPr.find(qn("w:shd")).get(qn("w:fill")) == "EDF3FB"
    assert _sz(c, "left").get(qn("w:color")) == "3A6CB5" and _sz(c, "left").get(qn("w:sz")) == "27"
    for s in ("top", "right", "bottom"):
        assert _sz(c, s).get(qn("w:color")) == "BCD0EA"
    assert _card(_render()).rows[0]._tr.trPr.find(qn("w:cantSplit")) is not None
    n = _nested(_render())
    for row in n.rows[1:]:
        for cell in row.cells:
            b = _sz(cell._tc, "top")
            assert b.get(qn("w:color")) == "BCD0EA" and b.get(qn("w:sz")) == "6"


def test_three_rows_with_links_chips_and_stack():
    doc = _render()
    n = _nested(doc)
    assert len(n.rows) == 3
    for i, row in enumerate(n.rows, 1):
        a, b = row.cells
        links = a._tc.findall(".//" + qn("w:hyperlink"))
        assert len(links) == 1
        rid = links[0].get(qn("r:id"))
        assert doc.part.rels[rid].target_ref == f"https://maps.example/{i}"
        txt = [p.text for p in a.paragraphs]
        assert any("Balinese" in t and "Seafood" in t for t in txt)
        assert any(t.startswith("Must try") and "Bebek" in t for t in txt)
        bt = [p.text for p in b.paragraphs]
        assert bt[0] == "PER PERSON" and bt[1] == "INR 800–1,500"
        assert bt[2] == "OPEN" and bt[3] == "9:00 AM – 9:00 PM"
        assert bt[4] == "FROM HERE" and bt[5] == "8 min by car"


def test_approx_price_moves_to_label():
    doc = _render(_block([_r(1, price="Approx. INR 800–1,500 pp")]))
    bt = [p.text for p in _nested(doc).rows[0].cells[1].paragraphs]
    assert bt[0] == "PER PERSON, APPROX." and bt[1] == "INR 800–1,500"


def test_price_marker_rendered():
    doc = _render(_block([_r(1, price=MarkerRef(kind="PRICE_UNKNOWN", text="x"))]))
    a, b = _nested(doc).rows[0].cells
    assert any(p.style.name == "Review Marker (internal)" and "PRICE UNKNOWN" in p.text for p in a.paragraphs)
    assert [p.text for p in b.paragraphs][1] == "–"


def test_missing_hours_and_travel_show_dash():
    doc = _render(_block([_r(1, hours=None, travel=None)]))
    bt = [p.text for p in _nested(doc).rows[0].cells[1].paragraphs]
    assert bt[3] == "–" and bt[5] == "–"


def test_long_name_wraps_inside_card():
    doc = _render(_block([_r(1, name="N" * 90, text="word " * 120)]))
    assert len(doc.tables) == 1 and len(_card(doc).rows) == 1
    n = _nested(doc)
    grid = [int(g.get(qn("w:w"))) for g in n._tbl.tblGrid.findall(qn("w:gridCol"))]
    assert len(grid) == 2 and grid[1] == int(4.4 * 567)


def test_veg_friendly_chip():
    doc = _render(_block([_r(1, veg=True), _r(2)]))
    n = _nested(doc)
    assert any("Veg-friendly" in p.text for p in n.rows[0].cells[0].paragraphs)
    assert not any("Veg-friendly" in p.text for p in n.rows[1].cells[0].paragraphs)


def test_no_maps_url_plain_name():
    doc = _render(_block([_r(1, maps_url=None)]))
    a = _nested(doc).rows[0].cells[0]
    assert not a._tc.findall(".//" + qn("w:hyperlink"))
    assert a.paragraphs[0].text == "Warung 1"


def _ph(count=3):
    doc, W = _doc()
    M.render_placeholder_meal(doc, W, PlaceholderMeal(meal="lunch", eyebrow="LUNCH", heading="Lunch near Ubud Palace",
                                                      count=count))
    return doc


def test_placeholder_footprint_matches_harbour():
    h, p = _render(), _ph()
    gh = [g.get(qn("w:w")) for g in _nested(h)._tbl.tblGrid.findall(qn("w:gridCol"))]
    gp = [g.get(qn("w:w")) for g in _nested(p)._tbl.tblGrid.findall(qn("w:gridCol"))]
    assert gh == gp
    mar = lambda d: _card(d).rows[0].cells[0]._tc.tcPr.find(qn("w:tcMar"))
    assert (mar(h) is None) == (mar(p) is None)
    ph = _card(p)._tbl.tblPr.find(qn("w:tblCellMar"))
    hh = _card(h)._tbl.tblPr.find(qn("w:tblCellMar"))
    from lxml import etree
    assert etree.tostring(ph) == etree.tostring(hh)
    assert _card(p).style.name == "Placeholder Card (internal)"
    labels = [x.text for r in _nested(p).rows for x in r.cells[0].paragraphs if x.text.startswith("ADD RESTAURANT")]
    assert labels == ["ADD RESTAURANT 1", "ADD RESTAURANT 2", "ADD RESTAURANT 3"]
    kids = list(p.element.body)
    prev = kids[kids.index(_card(p)._tbl) - 1]
    mk = [x for x in p.paragraphs if x._p is prev][0]
    assert mk.style.name == "Review Marker (internal)"
    assert mk.text == "⚠ ADD RESTAURANT – Lunch near Ubud Palace  ·  staff only"


def test_placeholder_rows_use_placeholder_paragraph_style():
    for row in _nested(_ph()).rows:
        for c in row.cells:
            assert all(p.style.name == "Placeholder (internal)" for p in c.paragraphs)


def test_removing_internal_styles_leaves_no_placeholder_text():
    doc = _ph()
    for p in list(doc.paragraphs):
        if p.style.name == "Review Marker (internal)":
            p._p.getparent().remove(p._p)
    for t in list(doc.tables):
        if t.style is not None and t.style.name == "Placeholder Card (internal)":
            t._tbl.getparent().remove(t._tbl)
    text = "\n".join(p.text for p in doc.paragraphs) + "".join(
        t.text or "" for t in doc.element.body.iter(qn("w:t")))
    assert "ADD RESTAURANT" not in text.upper()


def test_meal_blocks_from_bali_fixture():
    data = GuideData.model_validate(json.loads(FIX.read_text(encoding="utf-8")))
    d = next(x for x in data.days if x.index == 2)
    page = build_day_page(d, data, SimpleNamespace(walk_max_min=10))
    blocks = [c for c in page.components if c.type == "MealBlock"]
    assert len(blocks) == 2
    doc, W = _doc()
    for b in blocks:
        M.render_meal_block(doc, W, b)
    buf = io.BytesIO()
    doc.save(buf)
    re_doc = Document(io.BytesIO(buf.getvalue()))
    assert len(re_doc.tables) == 2
    for t, b in zip(re_doc.tables, blocks):
        assert len(t.rows[0].cells[0].tables[0].rows) == len(b.restaurants) == 3


def test_qc_reader_meal_slot():
    doc, W = _doc()
    from src.aigv2.render2 import day_components as D
    D.render_opener(doc, W, Opener(number=1, weekday="Friday", date="25 September", title=["Ubud"], intro=""))
    M.render_meal_block(doc, W, _block())
    buf = io.BytesIO()
    doc.save(buf)
    m = read_docx(buf.getvalue())
    assert (2, "Lunch near Ubud Palace") in m.headings


import pytest


@pytest.mark.parametrize("raw,expected", [
    ("Approx. INR 800–1,500 pp", ("PER PERSON, APPROX.", "INR 800–1,500")),
    ("INR 800–1,800 per person", ("PER PERSON", "INR 800–1,800")),
    ("₹1,500–2,800 for two", ("FOR TWO", "₹1,500–2,800")),
    ("Approx INR 500 per person", ("PER PERSON, APPROX.", "INR 500")),
    ("~INR 500 pp", ("PER PERSON, APPROX.", "INR 500")),
    ("INR 1,000–2,200", ("PER PERSON", "INR 1,000–2,200")),
    ("approx. ₹900 for 2", ("FOR TWO, APPROX.", "₹900")),
    ("INR 6,000 per night", ("PER NIGHT", "INR 6,000")),
])
def test_price_basis(raw, expected):
    assert M._price(raw) == expected


def _markers(cell):
    return [p.text for p in cell.paragraphs if p.style.name == "Review Marker (internal)"]


def test_missing_fields_get_verify_markers():
    a = _nested(_render(_block([_r(1, name="Casa", price=None)]))).rows[0].cells[0]
    assert len(_markers(a)) == 1 and "VERIFY: Casa: price" in _markers(a)[0]
    a = _nested(_render(_block([_r(1, name="Casa", hours=None, travel=None)]))).rows[0].cells[0]
    ms = _markers(a)
    assert len(ms) == 2 and any("Casa: opening hours" in m for m in ms) and any("Casa: travel time" in m for m in ms)


def test_complete_restaurant_has_no_markers():
    for row in _nested(_render()).rows:
        assert _markers(row.cells[0]) == []


def test_marker_price_not_duplicated():
    a = _nested(_render(_block([_r(1, price=MarkerRef(kind="PRICE_UNKNOWN", text="x"))]))).rows[0].cells[0]
    assert len(_markers(a)) == 1


def test_empty_restaurants_fall_back_to_placeholder():
    doc = _render(MealBlock(meal="lunch", eyebrow="LUNCH", heading="Lunch near Ubud Palace", restaurants=[]))
    assert _card(doc).style.name == "Placeholder Card (internal)" and len(_nested(doc).rows) == 3


def test_placeholder_count_clamped():
    assert len(_nested(_ph(0)).rows) == 1
    assert len(_nested(_ph(20)).rows) == 6


def test_zero_minute_walk_reads_at_your_hotel():
    from src.aigv2.render2.meals import travel_text
    assert travel_text("Walk · 0 min") == "At your hotel"
    assert travel_text("Walk · 5 min") == "Walk · 5 min"
