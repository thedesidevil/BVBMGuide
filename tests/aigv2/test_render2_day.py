import io
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document
from docx.oxml.ns import qn
from src.aigv2.render2 import theme as _T

T_POWDER, T_FROST = _T.POWDER, _T.FROST
from docx.shared import Cm

from src.aigv2.guide.model import (ChecklistCard, Fact, JourneyStop, JourneyStrip, Link, MarkerRef, Opener,
                                   OptionCards, Option, Page, ReviewMarkerBlock, SightseeingCard, SimpleCard, YourDay)
from src.aigv2.render2 import day_components as D
from src.aigv2.guide.build import build_day_page
from src.aigv2.models import HotelStay, Marker, TransportLeg
from src.aigv2.render.document import GuideData
from src.aigv2.render2 import frame as F
from src.aigv2.render2 import render as RN

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


def test_qc_reader_sees_card_title_and_facts():
    m = _qc_model()
    v = (m.section_venues or m.days[0].slots[0].venues)[0]
    assert v.name == "Tegalalang Terraces"
    assert v.url == "https://m.example/t"
    assert v.facts.get("GETTING THERE") == "30 min by car"
    assert (3, "Tegalalang Terraces") in m.headings


def _checklist(items):
    return ChecklistCard(when="10:00 AM", kind="Check-out", title=Link(text="Hotel"), lead="Before", items=items)


def reopen(doc):
    import io
    from docx import Document
    b = io.BytesIO()
    doc.save(b)
    b.seek(0)
    return Document(b)


def test_checklist_zero_items_has_no_nested_table():
    doc = _rendered(_checklist([]), D.render_checklist_card)
    assert not doc.tables[0].rows[0].cells[0].tables
    assert len(reopen(doc).tables) == 1


def test_checklist_one_item_right_cell_empty():
    doc = _rendered(_checklist(["only"]), D.render_checklist_card)
    nt = reopen(doc).tables[0].rows[0].cells[0].tables[0]
    assert [p.text for p in nt.rows[0].cells[0].paragraphs if p.text.startswith("◆")] == ["◆ only"] or \
        len([p for p in nt.rows[0].cells[0].paragraphs if "only" in p.text]) == 1
    assert [p.text for p in nt.rows[0].cells[2].paragraphs] == [""]


def test_sightseeing_minimal_card():
    c = SightseeingCard(when="9:00 AM", name=Link(text="Spot"))
    doc = _rendered(c)
    cell = doc.tables[0].rows[0].cells[0]
    assert not cell.tables
    assert [p.text for p in cell.paragraphs if p.text] == ["9:00 AM", "Spot"]


# ---------- booking cards ----------
def _booking(**kw):
    from src.aigv2.guide.model import BookingCard
    d = dict(when="Arrival", kind="Flight", title=Link(text="Flight to Bali"),
             facts=[Fact(label="Flight", value="QR 960"), Fact(label="From", value="Doha"),
                    Fact(label="To", value="Denpasar"), Fact(label="Lands", value="00:10")],
             text="", ref="ABC123", note="Flight details as on your booking")
    d.update(kw)
    return BookingCard(**d)


def _bk(c):
    return _rendered(c, D.render_booking_card)


def _edge(tc, side):
    return tc.find(qn("w:tcPr")).find(qn("w:tcBorders")).find(qn("w:" + side))


def test_booking_card_without_strip_is_one_row():
    t = _bk(_booking(ref=None, note=None)).tables[0]
    assert len(t.rows) == 1
    assert _edge(t.rows[0].cells[0]._tc, "bottom").get(qn("w:color")) == T_POWDER


def test_booking_card_with_strip_two_rows():
    t = _bk(_booking()).tables[0]
    assert len(t.rows) == 2
    assert _edge(t.rows[0].cells[0]._tc, "bottom").get(qn("w:val")) == "nil"
    s = t.rows[1].cells[0]._tc
    assert s.find(qn("w:tcPr")).find(qn("w:shd")).get(qn("w:fill")) == T_FROST
    assert _edge(s, "bottom").get(qn("w:color")) == T_POWDER
    txt = t.rows[1].cells[0].text
    assert txt.startswith("BOOKING REFERENCE") and "ABC123" in txt and "Flight details as on your booking" in txt
    assert txt.index("ABC123") < txt.index("\t") < txt.index("Flight details")
    assert s.find(".//" + qn("w:tab")) is not None


def test_strip_only_note():
    t = _bk(_booking(ref=None)).tables[0]
    assert "BOOKING REFERENCE" not in t.rows[1].cells[0].text
    assert "Flight details as on your booking" in t.rows[1].cells[0].text


def test_strip_only_ref():
    t = _bk(_booking(note=None)).tables[0]
    assert len(t.rows) == 2 and "ABC123" in t.rows[1].cells[0].text


def test_title_prefix_and_link():
    c = _booking(prefix="Return to ", title=Link(text="Hotel X", url="https://m.example/h"))
    p = next(p for p in _bk(c).tables[0].rows[0].cells[0].paragraphs if p.style.name == "Heading 3")
    assert p.text == "Return to Hotel X"
    hl = p._p.findall(qn("w:hyperlink"))
    assert len(hl) == 1 and "".join(t.text for t in hl[0].iter(qn("w:t"))) == "Hotel X"
    c = _booking(prefix="Return to ", title=Link(text="Hotel X"))
    p = next(p for p in _bk(c).tables[0].rows[0].cells[0].paragraphs if p.style.name == "Heading 3")
    assert p.text == "Return to Hotel X" and not p._p.findall(qn("w:hyperlink"))


def _glance_texts(doc):
    g = doc.tables[0].rows[0].cells[0].tables[0]
    return [p.text for r in g.rows for c in r.cells for p in c.paragraphs]


def test_fact_labels_uppercase_and_separate_paragraphs():
    c = _booking(facts=[Fact(label="Meeting point", value="Bali Airport")])
    t = _glance_texts(_bk(c))
    assert "MEETING POINT" in t and "Bali Airport" in t


def test_flight_transport_labels_preserved_for_qc():
    facts = [Fact(label=l, value="x") for l in ("Departs", "Arrives", "Service", "Operator")]
    t = _glance_texts(_bk(_booking(facts=facts)))
    for l in ("DEPARTS", "ARRIVES", "SERVICE", "OPERATOR"):
        assert l in t


def _all_paras(el):
    return el.findall(".//" + qn("w:p"))


def test_all_paragraphs_keep_with_next_in_row1():
    row = _bk(_booking(text="Some text.")).tables[0].rows[0]
    ps = _all_paras(row._tr)
    assert ps and all(p.find(qn("w:pPr")) is not None and p.find(qn("w:pPr")).find(qn("w:keepNext")) is not None
                      for p in ps)


def test_rows_cant_split():
    for r in _bk(_booking()).tables[0].rows:
        assert r._tr.trPr.find(qn("w:cantSplit")) is not None


def test_booking_card_followed_by_gap():
    doc = _bk(_booking())
    assert doc.paragraphs[-1].text == "" and doc.paragraphs[-1]._p.getprevious() is doc.tables[0]._tbl


def test_hotel_card_has_no_strip():
    c = _booking(kind="Check-in", ref=None, note=None, facts=[Fact(label="Room", value="Villa")])
    assert len(_bk(c).tables[0].rows) == 1


def test_booking_card_from_guide_build_output():
    import io
    import docx
    from tests.aigv2.test_guide_build import load, day, SETTINGS
    from src.aigv2.guide.build import build_day_page
    data = load()
    cards = []
    for i in (1, 5):
        cards += [c for c in build_day_page(day(data, i), data, SETTINGS).components if c.type == "BookingCard"]
    assert cards
    doc, W = _doc()
    for c in cards:
        D.render_booking_card(doc, W, c)
    buf = io.BytesIO()
    doc.save(buf)
    docx.Document(io.BytesIO(buf.getvalue()))
    flight = next(c for c in cards if c.kind == "Flight")
    txt = " ".join(_glance_texts(_bk(flight)))
    assert "ARRIVES" in txt and "Lands 00:10" in txt  # real data carries "Lands" in the value


# ---------------- Task 19: option cards, marker block, day assembler ----------------
_FIX = Path(__file__).parent / "fixtures" / "bali_guide" / "guide_data.json"
_SET = SimpleNamespace(walk_max_min=10)


def _data():
    return GuideData.model_validate(json.loads(_FIX.read_text(encoding="utf-8")))


def _dpage(index, data=None):
    data = data or _data()
    rd = next(d for d in data.days if d.index == index)
    return build_day_page(rd, data, _SET)


def _opt(n, note=None):
    return Option(label=f"OPTION {n}", name=Link(text=f"Place {n}", url=f"https://m.example/{n}"),
                  facts=[Fact(label="Time", value="2 hours"), Fact(label="Price", value="USD 20")],
                  text=f"Body {n}", note=note)


def _oc(n=2, **kw):
    d = dict(eyebrow="CHOOSE ONE", heading="Two ways to spend the evening", chip="At your own expense",
             options=[_opt(i + 1) for i in range(n)])
    d.update(kw)
    return OptionCards(**d)


def _body_tables(doc):
    return doc.element.body.findall(qn("w:tbl"))


def _tbl_text(t):
    return "".join(x.text or "" for x in t.iter(qn("w:t")))


def test_option_cards_two_side_by_side():
    doc, W = _doc()
    D.render_option_cards(doc, W, _oc(2))
    ts = doc.tables
    assert len(ts) == 1 and len(ts[0].rows) == 1 and len(ts[0].rows[0].cells) == 3
    assert ts[0].rows[0].cells[1].text.strip() == "or"
    txt = _tbl_text(ts[0]._tbl)
    assert "OPTION 1" in txt and "OPTION 2" in txt
    links = ts[0]._tbl.findall(".//" + qn("w:hyperlink"))
    assert len(links) == 2


def test_option_cards_chip_and_heading():
    doc, W = _doc()
    D.render_option_cards(doc, W, _oc(2, chip=None, own_expense=True))
    ps = doc.paragraphs
    chip = next(p for p in ps if "At your own expense" in p.text)
    assert not any(r.bold for r in chip.runs if "own expense" in r.text)
    assert chip.text.strip().startswith("◆") and chip.text.strip().endswith("◆")
    head = next(p for p in ps if p.text == "Two ways to spend the evening")
    assert head.style.name == "Heading 2"
    assert any(p.text.upper() == "CHOOSE ONE" for p in ps)


def test_option_cards_three_options_stacked():
    doc, W = _doc()
    D.render_option_cards(doc, W, _oc(3))
    ts = doc.tables
    assert len(ts) == 3 and all(len(t.rows[0].cells) == 1 for t in ts)
    assert "or" not in [c.text.strip() for t in ts for c in t.rows[0].cells]


def test_option_cards_single_option_full_width():
    doc, W = _doc()
    D.render_option_cards(doc, W, _oc(1))
    assert len(doc.tables) == 1 and len(doc.tables[0].rows[0].cells) == 1


def test_option_note_rendered_only_when_present():
    doc, W = _doc()
    oc = _oc(2)
    oc.options[1].note = "Book ahead"
    D.render_option_cards(doc, W, oc)
    txt = _tbl_text(doc.tables[0]._tbl)
    assert "Book ahead" in txt
    doc2, W2 = _doc()
    D.render_option_cards(doc2, W2, _oc(2))
    assert "Book ahead" not in _tbl_text(doc2.tables[0]._tbl)


def test_marker_block_renders_each_marker_in_order():
    doc, W = _doc()
    ms = [MarkerRef(kind="VERIFY", text="tour booking"), MarkerRef(kind="CHECK", text="hours")]
    D.render_marker_block(doc, W, ReviewMarkerBlock(markers=ms))
    ps = doc.paragraphs
    assert [p.style.name for p in ps] == ["Review Marker (internal)"] * 2
    assert [p.text for p in ps] == [Marker(kind=m.kind, text=m.text).render() + "  ·  staff only" for m in ms]


def test_render_day_page_dispatch_unknown_component_raises():
    from src.aigv2.guide.model import Page

    class Weird:
        pass

    doc, W = _doc()
    pg = Page.model_construct(kind="day", title="t", bookmark="b", components=[Weird()])
    with pytest.raises(TypeError, match="no renderer for Weird"):
        RN.render_day_page(doc, W, pg)


def _render_page(pg):
    doc = F.new_guide_doc("Dilna K", "Bali")
    _, W = F.add_guide_section(doc, "day", F.guide_label("Dilna K", "Bali"), first=True)
    RN.render_day_page(doc, W, pg)
    return doc


def reopen(doc):
    buf = io.BytesIO()
    doc.save(buf)
    return Document(io.BytesIO(buf.getvalue()))


def _flow_paras(doc):
    """Paragraph texts in document order, including those inside tables."""
    return ["".join(t.text or "" for t in p.iter(qn("w:t"))) for p in doc.element.body.iter(qn("w:p"))]


def test_bali_days_render_without_exception_andreopen():
    data = _data()
    for d in data.days:
        doc = _render_page(_dpage(d.index, data))
        assert reopen(doc).paragraphs


def _idx(texts_, needle, start=0):
    for i in range(start, len(texts_)):
        if needle in texts_[i]:
            return i
    raise AssertionError(f"{needle!r} not found after {start}")


def test_every_component_type_of_guide_model_day_pages_has_a_renderer():
    data = _data()
    seen = {type(c).__name__ for d in data.days for c in _dpage(d.index, data).components}
    assert seen and seen <= set(RN.RENDERERS_BY_NAME)


def test_option_padding_identical_for_1_2_3_options():
    def pads(n):
        doc, W = _doc()
        D.render_option_cards(doc, W, _oc(n))
        out = set()
        for tb in doc.tables:
            for c in tb.rows[0].cells:
                if "OPTION" in c.text:
                    mar = c._tc.tcPr.find(qn("w:tcMar"))
                    out.add(tuple(int(mar.find(qn(f"w:{s}")).get(qn("w:w"))) for s in ("top", "left", "bottom", "right")))
        return out
    assert pads(1) == pads(2) == pads(3) and len(pads(2)) == 1


def test_linked_fact_in_option_card_uses_cormorant():
    doc, W = _doc()
    oc = _oc(2)
    oc.options[0].facts = [Fact(label="Site", value="Visit", link=Link(text="Visit", url="https://x.example"))]
    D.render_option_cards(doc, W, oc)
    fonts = {rf.get(qn("w:ascii")) for h in doc.tables[0]._tbl.iter(qn("w:hyperlink")) for rf in h.iter(qn("w:rFonts"))}
    assert fonts == {"Cormorant Garamond"} or all("Cormorant" in f for f in fonts)


# ---- position-based order over body elements ----
def body_order(doc):
    """[(kind, text, title)] for each top-level paragraph ('p') and table ('t'); for a table, text is its first
    non-empty paragraph and title is its first Heading 3 paragraph text (else '')."""
    out = []
    for e in doc.element.body:
        if e.tag == qn("w:p"):
            out.append(("p", "".join(x.text or "" for x in e.iter(qn("w:t"))), ""))
        elif e.tag == qn("w:tbl"):
            paras = ["".join(x.text or "" for x in p.iter(qn("w:t"))) for p in e.iter(qn("w:p"))]
            first = next((x for x in paras if x.strip()), "")
            title = ""
            for p in e.iter(qn("w:p")):
                st = p.find(qn("w:pPr") + "/" + qn("w:pStyle"))
                if st is not None and st.get(qn("w:val")) in ("Heading3", "Heading 3"):
                    title = "".join(x.text or "" for x in p.iter(qn("w:t")))
                    break
            out.append(("t", first, title))
    return out


def first_index(order, needle, start=0, kind=None, title=False):
    for i in range(start, len(order)):
        k, text, ttl = order[i]
        if kind and k != kind:
            continue
        if needle in (ttl if title else text):
            return i
    raise AssertionError(f"{needle!r} not found after element {start}")


def _rendered_order(pg):
    return body_order(reopen(_render_page(pg)))


def test_day2_text_order():
    pg = _dpage(2)
    order = _rendered_order(pg)
    op = pg.components[0]
    sights = [c for c in pg.components if c.type == "SightseeingCard"]
    bf = pg.components[2]
    idx = [first_index(order, f"DAY {op.number}")]
    for needle in (op.title[0], "YOUR DAY"):
        idx.append(first_index(order, needle, idx[-1] + 1, kind="p"))
    idx.append(first_index(order, bf.heading, idx[-1] + 1, title=True))
    idx.append(first_index(order, sights[0].name.text, idx[-1] + 1, title=True))
    idx.append(first_index(order, "Lunch near", idx[-1] + 1, kind="p"))
    idx.append(first_index(order, sights[-1].name.text, idx[-1] + 1, title=True))
    idx.append(first_index(order, "Dinner near", idx[-1] + 1, kind="p"))
    assert idx == sorted(set(idx))


def test_day5_has_journey_strip_before_first_card():
    pg = _dpage(5)
    assert pg.components[2].type == "JourneyStrip"
    order = _rendered_order(pg)
    yd = first_index(order, "YOUR DAY", kind="p")
    strip = first_index([(k, x.upper(), t) for k, x, t in order], pg.components[2].stops[0].label.upper(), yd + 1, kind="t")
    first_card = next(i for i in range(yd + 1, len(order)) if order[i][0] == "t" and order[i][2])
    assert yd < strip < first_card


def _day7_order_ok(order, boat, opts_heading):
    b = first_index(order, boat, title=True)
    ck = first_index(order, "TAKSU SANUR HOTEL", b + 1, title=True)
    oh = first_index(order, opts_heading, ck + 1, kind="p")
    o1 = first_index(order, "OPTION 1", oh + 1, kind="t")
    dn = first_index(order, "Dinner near", o1 + 1, kind="p")
    assert b < ck < oh < o1 < dn


def test_day7_option_cards_before_dinner():
    pg = _dpage(7)
    boats = [c for c in pg.components if c.type == "BookingCard" and "Harbour" in c.title.text]
    assert boats, "fixture changed: Day 7 has no boat card"
    oc = next(c for c in pg.components if c.type == "OptionCards")
    order = _rendered_order(pg)
    _day7_order_ok(order, boats[0].title.text, oc.heading)
    comps = list(pg.components)
    i, j = comps.index(boats[0]), comps.index(oc)
    comps[i], comps[j] = comps[j], comps[i]
    mutated = Page.model_construct(kind=pg.kind, title=pg.title, bookmark=pg.bookmark, components=comps)
    with pytest.raises(AssertionError):
        _day7_order_ok(_rendered_order(mutated), boats[0].title.text, oc.heading)


def _day8_order_ok(order, ck_title, transfer_title, flight_title):
    yd = first_index(order, "YOUR DAY", kind="p")
    a = first_index(order, ck_title, yd + 1, title=True)
    b = first_index(order, transfer_title, a + 1, title=True)
    c = first_index(order, flight_title, b + 1, title=True)
    assert yd < a < b < c


def test_day8_checklist_then_airport_transfer():
    pg = _dpage(8)
    ck = next(c for c in pg.components if c.type == "ChecklistCard")
    bks = [c for c in pg.components if c.type == "BookingCard"]
    assert len(bks) >= 2, "fixture changed: expected airport transfer + flight"
    ck_t = ck.title.text if hasattr(ck.title, "text") else ck.title
    args = (ck_t, bks[0].title.text, bks[-1].title.text)
    _day8_order_ok(_rendered_order(pg), *args)
    comps = list(pg.components)
    i, j = comps.index(ck), comps.index(bks[0])
    comps[i], comps[j] = comps[j], comps[i]
    mutated = Page.model_construct(kind=pg.kind, title=pg.title, bookmark=pg.bookmark, components=comps)
    with pytest.raises(AssertionError):
        _day8_order_ok(_rendered_order(mutated), *args)


def _check_rendered(data):
    pg = _dpage(2, data)
    order = _rendered_order(pg)
    op = pg.components[0]
    assert first_index(order, f"DAY {op.number}") >= 0
    first_sched = next(c for c in pg.components if c.type in ("SimpleCard", "SightseeingCard"))
    ttl = first_sched.heading if first_sched.type == "SimpleCard" else first_sched.name.text
    first_index(order, ttl, title=True)


def test_cruise_day_and_domestic_one_day_trip_render():
    data = _data()
    data.trip.hotels = [HotelStay(city="Ubud", hotel="Ship One", check_in=date(2026, 9, 24),
                                  check_out=date(2026, 9, 28), source="voucher", kind="cruise")]
    rd = next(d for d in data.days if d.index == 2)
    rd.arrival = TransportLeg(kind="boat", from_place="A", to_place="Benoa", arrive=datetime(2026, 9, 25, 8, 0),
                              source="t")
    _check_rendered(data)
    data2 = _data()
    next(d for d in data2.days if d.index == 2).places = {}
    _check_rendered(data2)
