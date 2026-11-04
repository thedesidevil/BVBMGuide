import io

from docx import Document
from docx.oxml.ns import qn

from src.aigv2.guide import model as m
from src.aigv2.guide.build import build_reference_page
from src.aigv2.render2 import frame as F
from src.aigv2.render2 import reference_components as RC
from src.aigv2.render2 import theme as T
from src.aigv2.writing.sections import SectionContent, SectionGroup, SectionItem
from src.aigv2.writing.structured import App
from tests.aigv2.test_guide_build import load


def _doc():
    doc = F.new_guide_doc("Dilna K", "Bali")
    _, W = F.add_guide_section(doc, "reference", F.guide_label("Dilna K", "Bali"), first=True)
    return doc, W


def _text(e):
    return "".join(t.text or "" for t in e.iter(qn("w:t")))


def _tables(doc):
    return doc.element.body.findall(qn("w:tbl"))


def _cells(tbl):
    return [tc for tr in tbl.findall(qn("w:tr")) for tc in tr.findall(qn("w:tc"))]


def _border(tc, side):
    b = tc.find(qn("w:tcPr") + "/" + qn("w:tcBorders") + "/" + qn("w:" + side))
    return b


def _fill(tc):
    s = tc.find(qn("w:tcPr") + "/" + qn("w:shd"))
    return None if s is None else s.get(qn("w:fill"))


def _paras(doc):
    return doc.paragraphs


def test_reference_opener_texts_and_styles():
    doc, W = _doc()
    RC.render_reference_opener(doc, W, m.ReferenceOpener(eyebrow="BEFORE YOU GO", title="Packing", intro="Pack well."),
                               bookmark="sec_packing")
    ps = doc.paragraphs
    assert "◆" in ps[0].text and "BEFORE YOU GO" in ps[0].text.upper()
    assert ps[0].alignment == 1 and ps[0].paragraph_format.keep_with_next
    assert ps[1].style.name == "Heading 1" and ps[1].text == "Packing"
    bs = ps[1]._p.find(qn("w:bookmarkStart"))
    assert bs is not None and bs.get(qn("w:name")) == "sec_packing" and ps[1]._p.find(qn("w:bookmarkEnd")) is not None
    intro = ps[3]
    assert intro.text == "Pack well." and intro.runs[0].font.italic and intro.alignment == 1
    doc2, W = _doc()
    RC.render_reference_opener(doc2, W, m.ReferenceOpener(eyebrow="X", title="T", intro=""))
    assert len(doc2.paragraphs) == 3


def test_fact_row_cells_and_borders():
    doc, W = _doc()
    RC.render_fact_row(doc, W, m.FactRowBlock(facts=[
        m.Fact(label="Currency", value="IDR"),
        m.Fact(label="Rate", value="1 = 0.005", link=m.Link(text="x", url="https://x.example")),
        m.Fact(label="Tipping", value="10%")]))
    t = _tables(doc)[0]
    cells = _cells(t)
    assert len(cells) == 3
    ps = cells[0].findall(qn("w:p"))
    assert [_text(x) for x in ps[:2]] == ["CURRENCY", "IDR"]
    assert _border(cells[0], "left").get(qn("w:val")) == "nil"
    for c in cells[1:]:
        assert _border(c, "left").get(qn("w:val")) == "single"
    for c in cells:
        assert _border(c, "top").get(qn("w:color")) == T.POWDER
        assert _border(c, "bottom").get(qn("w:color")) == T.POWDER
    assert cells[1].find(".//" + qn("w:hyperlink")) is not None
    assert cells[0].find(".//" + qn("w:hyperlink")) is None
    assert t.find(".//" + qn("w:cantSplit")) is not None


def test_titled_paras_two_columns_and_odd_item():
    doc, W = _doc()
    items = [m.TitledPara(heading=f"H{i}", body=f"B{i}") for i in range(3)]
    RC.render_titled_paras(doc, W, m.TitledParas(items=items))
    t = _tables(doc)[0]
    rows = t.findall(qn("w:tr"))
    assert len(rows) == 2 and len(rows[0].findall(qn("w:tc"))) == 3  # cell, gutter, cell
    assert _text(rows[1].findall(qn("w:tc"))[2]).strip() == ""
    assert "H2" in _text(rows[1].findall(qn("w:tc"))[0])
    doc, W = _doc()
    RC.render_titled_paras(doc, W, m.TitledParas(items=items[:1]))
    rows = _tables(doc)[0].findall(qn("w:tr"))
    assert len(rows) == 1 and len(rows[0].findall(qn("w:tc"))) == 1


def test_tip_panel_colours_and_columns():
    doc, W = _doc()
    RC.render_tip_panel(doc, W, m.TipPanel(title="For your little one", items=["a", "b", "c", "d"], columns=2))
    t = _tables(doc)[0]
    tc = _cells(t)[0]
    assert _fill(tc) == T.HARBOUR_FILL == "EDF3FB"
    left = _border(tc, "left")
    assert left.get(qn("w:color")) == T.ROYAL and left.get(qn("w:sz")) == "18"
    for side in ("top", "bottom", "right"):
        b = _border(tc, side)
        assert b is None or b.get(qn("w:val")) == "nil"
    inner = tc.findall(qn("w:tbl"))
    assert len(inner) == 1
    cols = _cells(inner[0])
    assert len(cols) == 3
    assert _text(cols[0]).count("◆") == 2 and _text(cols[2]).count("◆") == 2
    doc, W = _doc()
    RC.render_tip_panel(doc, W, m.TipPanel(title="T", items=["x", "y"], checks=True))
    xml = doc.element.xml
    assert xml.count("◆") == 2 and "w:bdr" not in xml
    assert "☐" not in xml and "□" not in xml


def test_note_panel_colours():
    doc, W = _doc()
    RC.render_note_panel(doc, W, m.NotePanel(title="PLEASE NOTE", text="Some text.", items=["i1", "i2"]))
    tc = _cells(_tables(doc)[0])[0]
    assert _fill(tc) == "F3EFEA"
    assert _border(tc, "left").get(qn("w:color")) == T.TAUPE
    txt = _text(tc)
    assert "Some text." in txt and txt.count("◆") == 2 and "PLEASE NOTE" in txt
    title = tc.findall(qn("w:p"))[0]
    assert title.find(".//" + qn("w:color")).get(qn("w:val")) == T.GOLD_INK
    assert title.find(".//" + qn("w:b")) is not None


def test_tip_vs_note_are_visibly_different_families():
    doc, W = _doc()
    RC.render_tip_panel(doc, W, m.TipPanel(title="T", items=["a"]))
    RC.render_note_panel(doc, W, m.NotePanel(title="N", text="x"))
    a, b = [_cells(t)[0] for t in _tables(doc)]
    assert _fill(a) != _fill(b)
    assert _border(a, "left").get(qn("w:color")) != _border(b, "left").get(qn("w:color"))


def test_app_grid_three_columns():
    doc, W = _doc()
    RC.render_app_grid(doc, W, m.AppGrid(apps=[m.App(name=f"App{i}", use="Rides") for i in range(5)]))
    t = _tables(doc)[0]
    rows = t.findall(qn("w:tr"))
    assert len(rows) == 2 and all(len(r.findall(qn("w:tc"))) == 5 for r in rows)  # 3 cells + 2 gutters
    name_p = rows[0].findall(qn("w:tc"))[0].findall(qn("w:p"))[0]
    assert name_p.find(".//" + qn("w:rFonts")).get(qn("w:ascii")) == T.HEAD
    assert name_p.find(qn("w:pPr") + "/" + qn("w:pBdr") + "/" + qn("w:bottom")).get(qn("w:color")) == T.POWDER
    assert _text(rows[1].findall(qn("w:tc"))[4]).strip() == ""


def test_checklist_groups_two_columns():
    doc, W = _doc()
    groups = [m.ChecklistGroup(title=f"G{i}", items=["one", "two"]) for i in range(5)]
    RC.render_checklist_groups(doc, W, m.ChecklistGroups(groups=groups))
    t = _tables(doc)[0]
    rows = t.findall(qn("w:tr"))
    assert len(rows) == 3
    first = rows[0].findall(qn("w:tc"))[0].findall(qn("w:p"))
    assert first[0].find(qn("w:pPr") + "/" + qn("w:pBdr") + "/" + qn("w:bottom")) is not None
    assert all("◆" in _text(p) for p in first[1:])
    assert len(first) == 3
    xml = doc.element.xml
    assert "w:bdr" not in xml and "☐" not in xml and "□" not in xml
    assert _text(rows[2].findall(qn("w:tc"))[2]).strip() == ""


def test_all_reference_components_cant_split_rows():
    doc, W = _doc()
    RC.render_fact_row(doc, W, m.FactRowBlock(facts=[m.Fact(label="a", value="b"), m.Fact(label="c", value="d")]))
    RC.render_titled_paras(doc, W, m.TitledParas(items=[m.TitledPara(heading="h", body="b")] * 3))
    RC.render_tip_panel(doc, W, m.TipPanel(title="t", items=["a", "b"], columns=2))
    RC.render_note_panel(doc, W, m.NotePanel(title="n", text="x"))
    RC.render_app_grid(doc, W, m.AppGrid(apps=[m.App(name="a", use="b")] * 4))
    RC.render_checklist_groups(doc, W, m.ChecklistGroups(groups=[m.ChecklistGroup(title="g", items=["i"])] * 3))
    for t in _tables(doc):
        for tr in t.findall(qn("w:tr")):
            assert tr.find(qn("w:trPr") + "/" + qn("w:cantSplit")) is not None


def _it(h, b=""):
    return SectionItem(heading=h, body=b, verify=False)


def test_reference_components_from_real_sections():
    data = load()
    fx = _it("Currency: XYZ", "1 XYZ = ₹2.00. Indicative rate (check before you travel).")
    contents = {
        "packing": SectionContent(key="packing", groups=[
            SectionGroup(title="Clothing", items=[_it("Linen shirts")]),
            SectionGroup(title="For your little one", items=[_it("Swim nappies"), _it("Hat")])]),
        "money": SectionContent(key="money", items=[fx, _it("Cards", "Widely accepted.")]),
        "connectivity": SectionContent(key="connectivity", items=[_it("eSIM", "Buy one.")],
                                       apps=[App(name="AppA", purpose="Rides")]),
        "health": SectionContent(key="health", items=[_it("Vaccines", "Check."),
                                                      _it("Boat crossings", "Seas can be rough. Ask.")]),
    }
    doc, W = _doc()
    seen = set()
    fns = {"ReferenceOpener": RC.render_reference_opener, "FactRowBlock": RC.render_fact_row,
           "TitledParas": RC.render_titled_paras, "TipPanel": RC.render_tip_panel,
           "NotePanel": RC.render_note_panel, "AppGrid": RC.render_app_grid,
           "ChecklistGroups": RC.render_checklist_groups}
    for key, c in contents.items():
        for comp in build_reference_page(key, c, data).components:
            if comp.type in fns:
                fns[comp.type](doc, W, comp)
                seen.add(comp.type)
    assert seen == set(fns)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    assert Document(buf).paragraphs
