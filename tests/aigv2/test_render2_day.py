from docx.oxml.ns import qn
from docx.shared import Cm

from src.aigv2.guide.model import JourneyStop, JourneyStrip, Link, Opener, YourDay
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
