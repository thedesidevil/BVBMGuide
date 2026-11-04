from docx.oxml.ns import qn
from docx.shared import Cm

from src.aigv2.guide.model import (ChecklistCard, Fact, JourneyStop, JourneyStrip, Link, MarkerRef, Opener,
                                   SightseeingCard, SimpleCard, YourDay)
from src.aigv2.render2 import day_components as D
from src.aigv2.render2 import frame as F

W_SEEN = {}


def _doc():
    doc = F.new_guide_doc("Dilna K", "Bali")
    _, W = F.add_guide_section(doc, "day", F.guide_label("Dilna K", "Bali"), first=True)
    return doc, W


def _opener(**kw):
    d = dict(number=2, weekday="Friday", date="25 September", title=["Ubud", "and the Rice Terraces"],
             intro="A slow morning, then the terraces.")
    d.update(kw)
    return Opener(**d)


def _strip(names=("A", "B", "C"), legs=("Approx. 60 min", "")):
    stops = [JourneyStop(label=f"L{i}", name=Link(text=n, url=f"https://m.example/{n}"),
                         time="9:00" if i == 0 else None) for i, n in enumerate(names)]
    return JourneyStrip(stops=stops, legs=list(legs))


def texts(doc):
    return [p.text for p in doc.paragraphs]


def _opened(**kw):
    doc, W = _doc()
    D.render_opener(doc, W, _opener(**kw))
    return doc


def test_opener_text_order():
    t = [x for x in texts(_opened()) if x]
    joined = "\n".join(t)
    assert joined.index("DAY 2") < joined.index("Ubud") < joined.index("A slow morning")
    for bad in ("Prepared for", "At a glance", "Hour by hour"):
        assert bad not in joined


def test_opener_title_is_heading1_with_bookmark():
    doc = _opened()
    p = next(p for p in doc.paragraphs if p.text.startswith("Ubud"))
    assert p.style.name == "Heading 1"
    assert p._p.findall(".//" + qn("w:br"))
    names = [b.get(qn("w:name")) for b in p._p.findall(qn("w:bookmarkStart"))]
    assert names == ["day_2"]
    assert p._p.find(qn("w:bookmarkEnd")) is not None


def test_eyebrow_uses_day_eyebrow_style_and_text():
    doc = _opened()
    p = next(p for p in doc.paragraphs if p.style.name == "Day Eyebrow")
    assert p.text.strip("◆  ") == "DAY 2 · FRIDAY, 25 SEPTEMBER"


def test_your_day_label():
    doc, W = _doc()
    D.render_your_day(doc, W, YourDay())
    p = doc.paragraphs[-1]
    assert p.text == "YOUR DAY"
    assert p.runs[0].font.size.pt == 12
    assert p._p.find(".//" + qn("w:pBdr") + "/" + qn("w:bottom")) is not None


def test_journey_strip_counts():
    doc, W = _doc()
    D.render_journey_strip(doc, W, _strip())
    t = doc.tables[0]
    assert len(t.rows) == 1 and len(t.rows[0].cells) == 5
    assert len(t._tbl.findall(".//" + qn("w:hyperlink"))) == 3
    leg2 = t.rows[0].cells[3]
    assert leg2.text == ""
    assert t.rows[0].cells[1].text.strip() == "Approx. 60 min"


def test_journey_strip_widths():
    doc, W = _doc()
    D.render_journey_strip(doc, W, _strip())
    cells = doc.tables[0].rows[0].cells
    stops = [cells[i].width for i in (0, 2, 4)]
    assert len(set(stops)) == 1
    assert cells[1].width == cells[3].width and abs(cells[1].width - Cm(2.5)) < 1000
    assert sum(c.width for c in cells) <= Cm(W) + 5


def test_journey_strip_single_stop():
    doc, W = _doc()
    D.render_journey_strip(doc, W, _strip(names=("A",), legs=()))
    cells = doc.tables[0].rows[0].cells
    assert len(cells) == 1 and "A" in cells[0].text


def test_strip_row_cant_split():
    doc, W = _doc()
    D.render_journey_strip(doc, W, _strip())
    assert doc.tables[0].rows[0]._tr.trPr.find(qn("w:cantSplit")) is not None


def test_no_dotted_leaders_or_run_borders_in_day_components():
    doc, W = _doc()
    D.render_opener(doc, W, _opener())
    D.render_your_day(doc, W, YourDay())
    D.render_journey_strip(doc, W, _strip())
    x = doc.element.xml
    assert "<w:bdr" not in x
    for tab in doc.element.iter(qn("w:tab")):
        assert tab.get(qn("w:leader")) in (None, "none")


def test_opener_without_intro():
    doc = _opened(intro="")
    assert not any("A slow" in t for t in texts(doc))
    assert any(t.startswith("Ubud") for t in texts(doc))


# ---------- cards (Task 16) ----------
from src.aigv2.models import Marker  # noqa: E402
from src.aigv2.render2 import theme as _T  # noqa: E402


def _sight(**kw):
    d = dict(when="1:00 PM", part="Afternoon", name=Link(text="Tegalalang Terraces", url="https://m.example/t"),
             subtitle="Rice terraces", facts=[Fact(label="Getting there", value="30 min by car"),
                                              Fact(label="Hours", value="8 am - 6 pm"),
                                              Fact(label="Entry", value="IDR 20,000",
                                                   link=Link(text="x", url="https://m.example/e"))],
             text="Walk the terraces.", tips=["Wear shoes", "Bring water"],
             markers=[MarkerRef(kind="VERIFY", text="opening hours")])
    d.update(kw)
    return SightseeingCard(**d)


def _rendered(c, fn=None):
    doc, W = _doc()
    (fn or D.render_sightseeing_card)(doc, W, c)
    return doc


def _tc(doc):
    return doc.tables[0]._tbl.find(".//" + qn("w:tc"))


def _cell_paras(doc):
    return doc.tables[0].rows[0].cells[0].paragraphs


def test_card_is_single_cell_table_with_cant_split():
    doc = _rendered(_sight())
    t = doc.tables[0]
    assert len(t.rows) == 1 and len(t.rows[0].cells) == 1
    assert t.rows[0]._tr.trPr.find(qn("w:cantSplit")) is not None


def test_card_bar_and_edges():
    b = _tc(_rendered(_sight())).find(qn("w:tcPr")).find(qn("w:tcBorders"))
    def g(side):
        e = b.find(qn("w:" + side))
        return e.get(qn("w:color")), e.get(qn("w:sz"))
    assert g("left") == (_T.AMBER, "27")
    assert g("bottom") == (_T.POWDER, "6")
    assert g("top") == (_T.CARD_EDGE, "4") and g("right") == (_T.CARD_EDGE, "4")
    assert _tc(_rendered(_sight())).find(qn("w:tcPr")).find(qn("w:shd")).get(qn("w:fill")) == _T.WHITE


def test_sightseeing_title_is_hyperlink_in_heading3():
    doc = _rendered(_sight())
    p = next(p for p in _cell_paras(doc) if p.style.name == "Heading 3")
    h = p._p.find(qn("w:hyperlink"))
    assert h is not None and p.text == "Tegalalang Terraces"
    assert doc.part.rels[h.get(qn("r:id"))].target_ref == "https://m.example/t"
    doc = _rendered(_sight(name=Link(text="Plain")))
    p = next(p for p in _cell_paras(doc) if p.style.name == "Heading 3")
    assert p._p.find(qn("w:hyperlink")) is None and p.text == "Plain"


def test_eyebrow_text_and_style():
    p = _cell_paras(_rendered(_sight()))[0]
    assert p.style.name == "Eyebrow" and p.text == "1:00 PM ◆ AFTERNOON"
    p = _cell_paras(_rendered(_sight(part=None)))[0]
    assert p.text == "1:00 PM"


def test_glance_two_columns_and_odd_fact():
    doc = _rendered(_sight())
    g = doc.tables[0].rows[0].cells[0].tables[0]
    assert len(g.rows) == 2
    assert g.rows[1].cells[2].text.strip() == ""
    first = g.rows[0].cells[0]
    assert [p.text for p in first.paragraphs] == ["GETTING THERE", "30 min by car"]
    assert g.rows[1].cells[0]._tc.findall(".//" + qn("w:hyperlink"))


def test_getting_there_label_present_for_qc():
    doc = _rendered(_sight())
    texts_ = [p.text for p in doc.tables[0].rows[0].cells[0].tables[0].rows[0].cells[0].paragraphs]
    assert "GETTING THERE" in texts_ and "30 min by car" in texts_


def test_good_to_know_is_diamond_list():
    ps = [p.text for p in _cell_paras(_rendered(_sight()))]
    i = ps.index("GOOD TO KNOW")
    assert ps[i + 1].startswith("◆") and ps[i + 1].endswith("Wear shoes")
    assert ps[i + 2].startswith("◆") and "Bring water" in ps[i + 2]
    assert "GOOD TO KNOW" not in [p.text for p in _cell_paras(_rendered(_sight(tips=[])))]


def test_markers_use_review_style_inside_card():
    doc = _rendered(_sight())
    ms = [p for p in _cell_paras(doc) if p.style.name == "Review Marker (internal)"]
    assert [m.text for m in ms] == [Marker(kind="VERIFY", text="opening hours").render() + "  ·  staff only"]


def test_simple_card_has_no_glance_or_tips():
    doc = _rendered(SimpleCard(when="9:00 AM", part="Morning", heading="Breakfast", text="Slow start."),
                    D.render_simple_card)
    cell = doc.tables[0].rows[0].cells[0]
    assert not cell.tables
    assert "GOOD TO KNOW" not in cell.text
    h = next(p for p in cell.paragraphs if p.style.name == "Heading 3")
    assert h.text == "Breakfast" and h._p.find(qn("w:hyperlink")) is None


def test_checklist_card_two_columns():
    c = ChecklistCard(when="10:00 AM", kind="Check-out", title=Link(text="Hotel", url="https://m.example/h"),
                      lead="Before you go", items=[f"item{i}" for i in range(7)])
    doc = _rendered(c, D.render_checklist_card)
    cell = doc.tables[0].rows[0].cells[0]
    nt = cell.tables[0]
    assert len(nt.rows) == 1 and len(nt.rows[0].cells) == 3
    left = [p for p in nt.rows[0].cells[0].paragraphs if p.text.startswith("◆")]
    right = [p for p in nt.rows[0].cells[2].paragraphs if p.text.startswith("◆")]
    assert (len(left), len(right)) == (4, 3)
    assert nt.rows[0]._tr.trPr.find(qn("w:cantSplit")) is not None
    assert cell._tc.index(cell.paragraphs[[p.text for p in cell.paragraphs].index("Before you go")]._p) < \
        cell._tc.index(nt._tbl)


def test_long_text_card_does_not_split():
    doc = _rendered(_sight(text="word " * 120, name=Link(text="T" * 90, url="https://m.example/t")))
    assert len(doc.tables[0].rows) == 1
    assert doc.tables[0].rows[0]._tr.trPr.find(qn("w:cantSplit")) is not None


def test_cards_end_with_gap_spacer():
    doc = _rendered(_sight())
    last = doc.paragraphs[-1]
    assert last.text == "" and last._p.getprevious() is doc.tables[0]._tbl


def _qc_model():
    import io
    from src.aigv2.qc.reader import read_docx
    doc, W = _doc()
    D.render_opener(doc, W, _opener())
    D.render_sightseeing_card(doc, W, _sight())
    buf = io.BytesIO()
    doc.save(buf)
    return read_docx(buf.getvalue())


def test_card_title_and_facts_are_reader_independent():
    doc = _rendered(_sight())
    cell = doc.tables[0].rows[0].cells[0]
    h = [p for p in cell.paragraphs if p.style.name == "Heading 3"]
    assert [p.text for p in h] == ["Tegalalang Terraces"]
    assert h[0]._p.find(qn("w:hyperlink")) is not None
    first = cell.tables[0].rows[0].cells[0]
    assert [p.text for p in first.paragraphs] == ["GETTING THERE", "30 min by car"]


import pytest  # noqa: E402


@pytest.mark.xfail(strict=True, reason="Task 23 adapts qc/reader.py _card to skip Eyebrow paragraphs")
def test_qc_reader_sees_card_title_and_facts():
    m = _qc_model()
    v = m.section_venues[0]
    assert v.name == "Tegalalang Terraces"
    assert v.url == "https://m.example/t"
    assert v.facts.get("GETTING THERE") == "30 min by car"
    assert (3, "Tegalalang Terraces") in m.headings


def _checklist(items):
    return ChecklistCard(when="10:00 AM", kind="Check-out", title=Link(text="Hotel"), lead="Before", items=items)


def _reopen(doc):
    import io
    from docx import Document
    b = io.BytesIO()
    doc.save(b)
    b.seek(0)
    return Document(b)


def test_checklist_zero_items_has_no_nested_table():
    doc = _rendered(_checklist([]), D.render_checklist_card)
    assert not doc.tables[0].rows[0].cells[0].tables
    assert len(_reopen(doc).tables) == 1


def test_checklist_one_item_right_cell_empty():
    doc = _rendered(_checklist(["only"]), D.render_checklist_card)
    nt = _reopen(doc).tables[0].rows[0].cells[0].tables[0]
    assert [p.text for p in nt.rows[0].cells[0].paragraphs if p.text.startswith("◆")] == ["◆ only"] or \
        len([p for p in nt.rows[0].cells[0].paragraphs if "only" in p.text]) == 1
    assert [p.text for p in nt.rows[0].cells[2].paragraphs] == [""]


def test_sightseeing_minimal_card():
    c = SightseeingCard(when="9:00 AM", name=Link(text="Spot"))
    doc = _rendered(c)
    cell = doc.tables[0].rows[0].cells[0]
    assert not cell.tables
    assert [p.text for p in cell.paragraphs if p.text] == ["9:00 AM", "Spot"]
