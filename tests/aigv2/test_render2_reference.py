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


# ---------------- Task 20b ----------------
def _np(name, walk=None, drive=None, hours="Daily 8-9", phone=None, markers=(), url=True):
    return m.NearbyPlace(name=m.Link(text=name, url=f"https://maps.example/{name}" if url else None),
                         walk_min=walk, drive_min=drive, hours_text=hours, phone=phone, markers=list(markers))


def _hotel(name="Hotel One", **kw):
    return m.HotelPlaces(hotel=m.Link(text=name, url="https://maps.example/h"), city="Ubud",
                         dates="24 – 28 September", **kw)


def _hlinks(e):
    return [_text(h) for h in e.iter(qn("w:hyperlink"))]


def test_place_groups_one_card_per_hotel_with_cant_split():
    doc, W = _doc()
    RC.render_place_groups(doc, W, m.PlaceGroups(hotels=[_hotel(pharmacies=[_np("P1", 3, 1)]), _hotel("Hotel Two")]))
    ts = _tables(doc)
    assert len(ts) == 2
    for t in ts:
        assert t.find(qn("w:tr") + "/" + qn("w:trPr") + "/" + qn("w:cantSplit")) is not None
    assert "UBUD ◆ 24 – 28 SEPTEMBER" in _text(ts[0])
    assert "Near Hotel One" in _text(ts[0]) and "Hotel One" in _hlinks(ts[0])
    assert _border(_cells(ts[0])[0], "left").get(qn("w:color")) == T.AMBER


def test_place_columns_and_travel_text():
    doc, W = _doc()
    mk = m.MarkerRef(kind="VERIFY", text="check hours")
    RC.render_place_groups(doc, W, m.PlaceGroups(hotels=[_hotel(
        pharmacies=[_np("P1", 3, 1, phone="+62 1", markers=[mk]), _np("P2", None, 4, hours=None)],
        groceries=[_np("G1")], hospitals=[_np("H1", 5, None, hours="")])]))
    outer = _tables(doc)[0]
    inner = outer.find(".//" + qn("w:tc") + "/" + qn("w:tbl"))
    assert len(_cells(inner)) == 5
    txt = _text(inner)
    assert "PHARMACIES" in txt.upper() and "Walk 3 min · By car 1 min" in txt and "By car 4 min" in txt
    assert "Walk 5 min" in txt and "Travel time not confirmed" in txt and "+62 1" in txt
    assert txt.count("Hours not listed") == 2 and "Daily 8-9" in txt
    assert "VERIFY" in txt.upper() and "staff only" in txt
    mk_p = next(p for p in inner.iter(qn("w:p")) if "staff only" in _text(p))
    from docx.text.paragraph import Paragraph
    assert Paragraph(mk_p, doc._body).style.name == "Review Marker (internal)"


def test_place_empty_column_text():
    doc, W = _doc()
    RC.render_place_groups(doc, W, m.PlaceGroups(hotels=[_hotel(pharmacies=[_np("P1", 3)])]))
    assert _text(_tables(doc)[0]).count("None listed nearby.") == 2


def test_dish_grid_two_columns_and_where_links():
    doc, W = _doc()
    RC.render_dish_grid(doc, W, m.DishGrid(dishes=[
        m.Dish(name="Soto", desc="Soup.", where=[m.Link(text="Warung A", url="https://m/a"), m.Link(text="Plain")]),
        m.Dish(name="Satay", desc="Skewers.")]))
    t = _tables(doc)[0]
    assert len(t.findall(qn("w:tr"))) == 1 and len(_cells(t)) == 3
    c0, c2 = _cells(t)[0], _cells(t)[2]
    assert _hlinks(c0) == ["Warung A"] and "Plain" in _text(c0) and "  ·  " in _text(c0)
    assert "WHERE TO TRY" in _text(c0).upper()
    assert "WHERE TO TRY" not in _text(c2).upper() and "Satay" in _text(c2)


def test_souvenir_grid():
    doc, W = _doc()
    RC.render_souvenir_grid(doc, W, m.SouvenirGrid(categories=[
        m.Souvenir(title="Textiles", what="Woven.", places=[m.Link(text="Market", url="https://m/x")]),
        m.Souvenir(title="Coffee", what="Beans.")]))
    cells = _cells(_tables(doc)[0])
    assert "WHAT TO BUY" in _text(cells[0]).upper() and "BEST PLACES TO BUY" in _text(cells[0]).upper()
    assert _hlinks(cells[0]) == ["Market"]
    assert "BEST PLACES" not in _text(cells[2]).upper() and "WHAT TO BUY" in _text(cells[2]).upper()
    title = cells[0].findall(qn("w:p"))[0]
    assert title.find(qn("w:pPr") + "/" + qn("w:pBdr") + "/" + qn("w:bottom")).get(qn("w:color")) == T.POWDER


def test_dos_donts_markers_and_columns():
    doc, W = _doc()
    RC.render_dos_donts(doc, W, m.DosDonts(do=["Smile", "Bow"], dont=["Shout"]))
    t = _tables(doc)[0]
    assert len(t.findall(qn("w:tr"))) == 1 and len(_cells(t)) == 3
    do, dont = _cells(t)[0], _cells(t)[2]
    assert _text(do).count("◆") == 2 and "Do" in _text(do) and "Don’t" in _text(dont)
    diamond = next(r for r in do.iter(qn("w:r")) if "◆" in _text(r))
    assert diamond.find(".//" + qn("w:color")).get(qn("w:val")) == T.AMBER
    x = next(r for r in dont.iter(qn("w:r")) if "×" in _text(r))
    assert x.find(".//" + qn("w:color")).get(qn("w:val")) == T.CRIMSON and x.find(".//" + qn("w:b")) is not None
    assert "◆" not in _text(dont)


def test_phrase_table_two_sides():
    doc, W = _doc()
    RC.render_phrase_table(doc, W, m.PhraseTable(phrases=[m.Phrase(local=f"L{i}", english=f"E{i}") for i in range(5)]))
    t = _tables(doc)[0]
    rows = t.findall(qn("w:tr"))
    assert len(rows) == 3
    filled = [sum(1 for tc in r.findall(qn("w:tc")) if _text(tc).strip()) for r in rows]
    assert filled == [4, 4, 2]
    grid = [int(g.get(qn("w:w"))) for g in t.find(qn("w:tblGrid")).findall(qn("w:gridCol"))]
    assert grid[0] == int(4.3 * 567) and len(grid) == 5
    first = rows[0].findall(qn("w:tc"))[0]
    assert _border(first, "top").get(qn("w:color")) == T.POWDER and _border(first, "bottom") is not None
    assert _border(rows[1].findall(qn("w:tc"))[0], "top").get(qn("w:val")) == "nil"
    assert first.find(qn("w:tcPr") + "/" + qn("w:vAlign")).get(qn("w:val")) == "center"
    assert _text(rows[0].findall(qn("w:tc"))[3]) == "L3"


def test_emergency_strip_cells_top_rule_and_dial():
    doc, W = _doc()
    nums = [m.EmergencyNumber(service=s, number=n) for s, n in
            [("Police", "110"), ("Ambulance", "119"), ("Fire", "+81 119"), ("Tourist", "03-1234")]]
    RC.render_emergency_strip(doc, W, m.EmergencyStrip(numbers=nums, dial="International dial code: +81"))
    t = _tables(doc)[0]
    cells = _cells(t)
    assert len(cells) == 4
    for tc in cells:
        b = _border(tc, "top")
        assert b.get(qn("w:color")) == T.ROYAL and b.get(qn("w:sz")) == "12"
        assert _fill(tc) == T.WHITE
    assert [_text(tc.findall(qn("w:p"))[0]) for tc in cells] == ["110", "119", "+81 119", "03-1234"]
    assert _border(cells[1], "left").get(qn("w:color")) == T.POWDER
    assert _border(cells[0], "left").get(qn("w:color")) == T.CARD_EDGE
    assert any(p.text == "International dial code: +81" for p in doc.paragraphs)
    doc2, W = _doc()
    RC.render_emergency_strip(doc2, W, m.EmergencyStrip(numbers=nums[:1]))
    assert not any("dial" in p.text for p in doc2.paragraphs)


def test_contact_cards_amber_first_and_links():
    doc, W = _doc()
    RC.render_contact_cards(doc, W, m.ContactCards(cards=[
        m.Contact(eyebrow="TOURIST POLICE", name=m.Link(text="Desk", url="tel:999"), phone="999", note="English"),
        m.Contact(eyebrow="EMBASSY", name=m.Link(text="Consulate", url="https://m/c"), phone="+1 2")]))
    t = _tables(doc)[0]
    a, b = _cells(t)
    assert _border(a, "left").get(qn("w:color")) == T.AMBER and _border(b, "left").get(qn("w:color")) == T.POWDER
    assert _hlinks(a) == ["Desk"] and _hlinks(b) == ["Consulate"]
    assert "999" in _text(a) and "English" in _text(a)
    assert len([p for p in b.findall(qn("w:p")) if _text(p).strip()]) == 3  # eyebrow, name, phone; no note


def test_reference_components_cant_split_rows():
    doc, W = _doc()
    RC.render_place_groups(doc, W, m.PlaceGroups(hotels=[_hotel(pharmacies=[_np("P")])]))
    RC.render_dish_grid(doc, W, m.DishGrid(dishes=[m.Dish(name="a", desc="b")] * 3))
    RC.render_souvenir_grid(doc, W, m.SouvenirGrid(categories=[m.Souvenir(title="a", what="b")] * 3))
    RC.render_dos_donts(doc, W, m.DosDonts(do=["a"], dont=["b"]))
    RC.render_phrase_table(doc, W, m.PhraseTable(phrases=[m.Phrase(local="a", english="b")] * 4))
    RC.render_emergency_strip(doc, W, m.EmergencyStrip(numbers=[m.EmergencyNumber(service="a", number="1")]))
    RC.render_contact_cards(doc, W, m.ContactCards(cards=[m.Contact(eyebrow="e", name=m.Link(text="n"))]))
    n = 0
    for t in doc.element.body.iter(qn("w:tbl")):
        for tr in t.findall(qn("w:tr")):
            n += 1
            assert tr.find(qn("w:trPr") + "/" + qn("w:cantSplit")) is not None
    assert n > 10


def test_real_sections_render():
    from tests.aigv2.test_guide_build_sections import _near, _sec
    from src.aigv2.guide.build import build_important_page
    from src.aigv2.planning.important_places import ImportantPlaces
    from src.aigv2.writing.sections import Contact, Dish, EmergencyNumber, Phrase, Souvenir
    data = load()
    contents = {
        "dishes": SectionContent(key="dishes", items=[_it("D", "d")],
                                 dishes=[Dish(name="Soto", description="Soup", where_to_try=["Warung"])]),
        "souvenirs": SectionContent(key="souvenirs", items=[_it("S", "s")],
                                    souvenirs=[Souvenir(title="Textiles", what="Woven", places=["Market"])]),
        "etiquette": SectionContent(key="etiquette", dos=["Smile"], donts=["Shout"],
                                    phrases=[Phrase(local="Hi", english="Hello")], items=[_it("Tipping", "Opt.")]),
        "safety": SectionContent(key="safety", numbers=[EmergencyNumber(service="Police", number="110")],
                                 contacts=[Contact(name="Desk", phone="999", note="English", kind="tourist_police")],
                                 items=[_it("Scams", "Beware.")]),
    }
    pages = [build_reference_page(k, c, data) for k, c in contents.items()]
    e1 = ImportantPlaces(city="Ubud", hotel="Hotel One", pharmacies=[_near("P1")], hospital=_near("H1", walk=None, drive=12))
    pages.append(build_important_page([e1]))
    fns = {"ReferenceOpener": RC.render_reference_opener, "FactRowBlock": RC.render_fact_row,
           "TitledParas": RC.render_titled_paras, "TipPanel": RC.render_tip_panel,
           "NotePanel": RC.render_note_panel, "AppGrid": RC.render_app_grid,
           "ChecklistGroups": RC.render_checklist_groups, "PlaceGroups": RC.render_place_groups,
           "DishGrid": RC.render_dish_grid, "SouvenirGrid": RC.render_souvenir_grid, "DosDonts": RC.render_dos_donts,
           "PhraseTable": RC.render_phrase_table, "EmergencyStrip": RC.render_emergency_strip,
           "ContactCards": RC.render_contact_cards}
    doc, W = _doc()
    seen = set()
    for page in pages:
        for comp in page.components:
            fns[comp.type](doc, W, comp)
            seen.add(comp.type)
    assert {"PlaceGroups", "DishGrid", "SouvenirGrid", "DosDonts", "PhraseTable", "EmergencyStrip",
            "ContactCards"} <= seen
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    assert Document(buf).paragraphs


def test_emergency_strip_long_numbers_shrink():
    doc, W = _doc()
    nums = [m.EmergencyNumber(service=s, number=n) for s, n in
            [("a", "110"), ("b", "+62 118 / 119"), ("c", "+62 361 227 911 / 12")]]
    RC.render_emergency_strip(doc, W, m.EmergencyStrip(numbers=nums))
    sizes = [tc.findall(qn("w:p"))[0].find(".//" + qn("w:sz")).get(qn("w:val")) for tc in _cells(_tables(doc)[0])]
    assert sizes == ["52", "40", "34"]


def test_multiline_titled_para_gets_diamond_bullets():
    from docx import Document
    from src.aigv2.guide import model as m
    from src.aigv2.render2 import reference_components as RC
    from src.aigv2.render2 import kit as K
    doc = K.new_doc()
    RC.render_titled_paras(doc, 17.0, m.TitledParas(items=[m.TitledPara(heading="Clothing", body="One\nTwo\nThree")]))
    xml = doc.element.xml
    assert xml.count(K.DIAMOND_GLYPH) == 3 and "w:hanging" in xml


def test_do_item_uses_diamond_and_dont_cross():
    from src.aigv2.guide import model as m
    from src.aigv2.render2 import reference_components as RC
    from src.aigv2.render2 import kit as K
    doc = K.new_doc()
    RC.render_dos_donts(doc, 17.0, m.DosDonts(do=["a"], dont=["b"]))
    xml = doc.element.xml
    assert K.DIAMOND_GLYPH in xml and "×" in xml


def test_long_titled_para_can_split_and_opener_keeps_with_next():
    doc, W = _doc()
    RC.render_reference_opener(doc, W, m.ReferenceOpener(eyebrow="E", title="Tailored Packing List", intro="intro"))
    body = "\n".join(f"item {i}" for i in range(30))
    RC.render_titled_paras(doc, W, m.TitledParas(items=[m.TitledPara(heading="Packing", body=body)]))
    t = _tables(doc)[-1]
    assert t.find(".//" + qn("w:cantSplit")) is None
    assert t.find(".//" + qn("w:keepLines")) is None
    paras = t.findall(".//" + qn("w:p"))
    assert paras[0].find(".//" + qn("w:keepNext")) is not None  # heading stays with first line
    assert all(p.find(".//" + qn("w:keepNext")) is None for p in paras[2:])
    last_open = [p for p in doc.element.body.findall(qn("w:p")) if "intro" in _text(p)][0]
    assert last_open.find(".//" + qn("w:keepNext")) is not None


def test_short_titled_para_row_still_unsplittable():
    doc, W = _doc()
    RC.render_titled_paras(doc, W, m.TitledParas(items=[m.TitledPara(heading="h", body="short")]))
    assert _tables(doc)[0].find(".//" + qn("w:cantSplit")) is not None


def test_bullet_items_split_sentences_but_not_abbreviations():
    body = ("Cards are accepted in hotels, e.g. at the Ubud Palace gift shop. Small warungs take cash only. "
            "Carry small notes for St. Paul parking at gate No. 5, approx. Rp 20,000. OK.")
    items = RC.bullet_items(body)
    assert items[0].endswith("gift shop.")
    assert any("St. Paul" in i and "No. 5" in i and "approx. Rp" in i for i in items)
    assert all(len(i) >= 25 for i in items[:-1] + [items[-1]] if len(items) > 1)
    assert RC.bullet_items("Tip 10%.") == ["Tip 10%."]
    assert RC.bullet_items("One line here is fine\nSecond line is fine too") == [
        "One line here is fine", "Second line is fine too"]


def test_bullet_items_split_long_semicolon_parts():
    body = ("Use the airport ATM on arrival for small notes of rupiah and keep receipts; "
            "avoid street changers that offer rates far above the bank rate shown on screen.")
    assert len(RC.bullet_items(body)) == 2


def test_titled_para_is_heading_with_hairline_and_diamond_per_sentence():
    doc, W = _doc()
    RC.render_titled_paras(doc, W, m.TitledParas(items=[m.TitledPara(
        heading="Cards", body="Cards work in hotels and bigger shops. Warungs prefer cash and small notes.")]))
    xml = doc.element.body.xml
    assert xml.count(RC.K.DIAMOND_GLYPH) == 2
    assert "w:pBdr" in xml
    single = _doc()
    RC.render_titled_paras(single[0], single[1], m.TitledParas(items=[m.TitledPara(heading="Tip", body="Tip ten percent.")]))
    assert single[0].element.body.xml.count(RC.K.DIAMOND_GLYPH) == 1
