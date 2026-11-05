import io

from docx import Document
from docx.oxml.ns import qn

from src.aigv2.qc.reader import read_docx
from src.aigv2.render2 import kit as K
from src.aigv2.render2 import theme as T
from src.aigv2.render2.styles import install_styles


def _save(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _reload(doc):
    return Document(io.BytesIO(_save(doc)))


def test_link_is_real_hyperlink():
    doc = K.new_doc()
    p = doc.add_paragraph()
    K.link(p, "https://maps.example/x", "Café Zero")
    d = _reload(doc)
    h = d.element.body.findall(".//" + qn("w:hyperlink"))[0]
    rid = h.get(qn("r:id"))
    assert d.part.rels[rid].target_ref == "https://maps.example/x" and d.part.rels[rid].is_external
    r = h.find(qn("w:r"))
    assert r.find(qn("w:rPr")).find(qn("w:u")) is not None
    assert r.find(qn("w:rPr")).find(qn("w:color")).get(qn("w:val")) == T.INK
    assert "".join(t.text for t in h.iter(qn("w:t"))) == "Café Zero"


def test_anchor_link_and_bookmark_pair():
    doc = K.new_doc()
    a, b = doc.add_paragraph("A"), doc.add_paragraph("B")
    i1, i2 = K.bookmark(a, "day_1"), K.bookmark(b, "day_2")
    K.anchor_link(doc.add_paragraph(), "day_1", "Go")
    body = doc.element.body
    assert i1 != i2
    names = [x.get(qn("w:name")) for x in body.iter(qn("w:bookmarkStart"))]
    assert names == ["day_1", "day_2"]
    assert body.find(".//" + qn("w:hyperlink")).get(qn("w:anchor")) == "day_1"
    assert len(list(body.iter(qn("w:bookmarkEnd")))) == 2


def test_card_row_cant_split():
    doc = K.new_doc()
    t = K.tbl(doc, 2, [5, 5])
    assert all(r._tr.trPr.find(qn("w:cantSplit")) is not None for r in t.rows)


def test_cell_shade_and_borders():
    doc = K.new_doc()
    t = K.tbl(doc, 1, [5])
    c = t.rows[0].cells[0]
    K.cell_shade(c, T.WHITE)
    K.cell_borders(c, left=(T.AMBER, 27), top=(T.CARD_EDGE, 4), bottom=None)
    tc = c._tc.tcPr
    assert tc.find(qn("w:shd")).get(qn("w:fill")) == T.WHITE
    b = tc.find(qn("w:tcBorders"))
    assert b.find(qn("w:left")).get(qn("w:sz")) == "27" and b.find(qn("w:left")).get(qn("w:color")) == T.AMBER
    assert b.find(qn("w:top")).get(qn("w:color")) == T.CARD_EDGE
    assert b.find(qn("w:bottom")).get(qn("w:val")) == "nil"
    assert b.find(qn("w:right")) is None


def test_review_marker_style_exists_and_removable():
    doc = K.new_doc()
    install_styles(doc)
    doc.add_paragraph("body one")
    K.review_marker(doc, "VERIFY", "hours")
    K.review_marker(doc, "WRITE_LETTER", "intro")
    doc.add_paragraph("body two")
    K.review_marker(doc, "CHECK", "x")
    d = _reload(doc)
    for p in list(d.paragraphs):
        if p.style.name == "Review Marker (internal)":
            p._p.getparent().remove(p._p)
    texts = [p.text for p in d.paragraphs]
    assert not any("⚠" in t for t in texts)
    assert [t for t in texts if t] == ["body one", "body two"]
    m = _reload(doc).paragraphs[1].text
    assert m == "⚠ VERIFY: hours  ·  staff only"


def test_headings_resolve_for_qc_reader():
    doc = K.new_doc()
    install_styles(doc)
    doc.add_paragraph("Page title", style="Heading 1")
    doc.add_paragraph("Part heading", style="Heading 2")
    doc.add_paragraph("Card title", style="Heading 3")
    m = read_docx(_save(doc))
    levels = {t: l for l, t in m.headings}
    assert levels == {"Page title": 1, "Part heading": 2, "Card title": 3}


def test_page_number_restart_only_first_section():
    doc = K.new_doc()
    K.set_page_start(doc.sections[0], 1)
    K.add_section(doc)
    K.add_section(doc, "continuous")
    assert len(list(doc.element.iter(qn("w:pgNumType")))) == 1
    K.strip_page_start(doc.sections[0])
    assert not list(doc.element.iter(qn("w:pgNumType")))


def test_background_is_solid_cream_by_default():
    doc = K.new_doc()
    bg = doc.element.find(qn("w:background"))
    assert bg.get(qn("w:color")) == "FDFBF7" and len(bg) == 0
    assert doc.element[0] is bg
    g = K.new_doc(gradient=T.GRAD)
    assert any(e.tag.endswith("}fill") for e in g.element.find(qn("w:background")).iter())
    assert not any(e.tag.endswith("}fill") for e in doc.element.find(qn("w:background")).iter())
    assert g.element.find(qn("w:background")).get(qn("w:color")) == "FDFBF7"


def test_chips_are_plain_text():
    doc = K.new_doc()
    p = doc.add_paragraph()
    K.chips(p, ["Vegetarian", "Rooftop", "Late"])
    assert p.text == "Vegetarian · Rooftop · Late"
    assert not list(p._p.iter(qn("w:bdr"))) and not list(p._p.iter(qn("w:shd")))


def test_bullet_uses_text_glyph():
    doc = K.new_doc()
    p = K.diamond_item(doc, "Pack layers")
    assert "◆" in p.text and p.text.endswith("Pack layers")
    assert not list(p._p.iter(qn("w:drawing")))
    assert p.paragraph_format.first_line_indent < 0


def test_no_proof_and_settings_flags():
    doc = K.new_doc()
    r = K.no_proof(doc.add_paragraph().add_run("x"))
    assert r._r.rPr.find(qn("w:noProof")) is not None
    st = doc.settings.element
    for tag in ("displayBackgroundShape", "hideSpellingErrors", "hideGrammaticalErrors"):
        assert st.find(qn("w:" + tag)) is not None


def test_install_styles_idempotent():
    doc = K.new_doc()
    install_styles(doc)
    n = len(doc.styles.element.findall(qn("w:style")))
    install_styles(doc)
    assert len(doc.styles.element.findall(qn("w:style"))) == n
    names = [s.name for s in doc.styles]
    assert names.count("Review Marker (internal)") == 1 and names.count("Placeholder Card (internal)") == 1


def test_review_marker_mirrors_marker_render():
    from src.aigv2.models import Marker
    from src.aigv2.qc.reader import MARKER_RE
    from src.aigv2.qc.rules import _MARKER_KIND
    doc = K.new_doc()
    install_styles(doc)
    for kind in K.MARKER_KINDS:
        p = K.review_marker(doc, kind, "some text")
        assert p.text == Marker(kind=kind, text="some text").render() + "  ·  staff only"
        found = MARKER_RE.findall(p.text)
        assert len(found) == 1 and _MARKER_KIND.match(found[0])
    assert K.review_marker(doc, "ADD_RESTAURANT", "x").text.startswith("⚠ ADD RESTAURANT – x")
    assert "WRITE PERSONAL LETTER" in K.review_marker(doc, "WRITE_LETTER", "x").text


def test_review_marker_guards_free_text():
    from src.aigv2.qc.reader import MARKER_RE
    from src.aigv2.qc.rules import _MARKER_KIND
    doc = K.new_doc()
    install_styles(doc)
    p = K.review_marker(doc, "VERIFY", "hours · check ⚠ twice")
    found = MARKER_RE.findall(p.text)
    assert len(found) == 1 and found[0] == "⚠ VERIFY: hours, check  twice"
    assert _MARKER_KIND.match(found[0]).group(1) == "VERIFY"


def test_review_marker_unknown_kind_raises():
    import pytest
    with pytest.raises(ValueError):
        K.review_marker(K.new_doc(), "NOPE", "x")
