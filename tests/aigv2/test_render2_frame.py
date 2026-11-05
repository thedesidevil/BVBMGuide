import io

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm

from src.aigv2.render2 import frame as F


def _reload(doc):
    buf = io.BytesIO()
    doc.save(buf)
    return Document(io.BytesIO(buf.getvalue()))


def _text(part):
    return "".join(t.text or "" for t in part._element.iter(qn("w:t")))


def _drawings(part):
    return len(list(part._element.iter(qn("w:drawing"))))


def _build():
    doc = F.new_guide_doc("Dilna Kallalthil", "Bali")
    label = F.guide_label("Dilna Kallalthil", "Bali")
    secs = {}
    for i, kind in enumerate(("toc", "day", "reference", "thank_you")):
        secs[kind] = F.add_guide_section(doc, kind, label, first=(i == 0))
    return doc, label, secs


def test_guide_label():
    assert F.guide_label("Dilna Kallalthil", "Bali") == "YOUR ALL-INCLUSIVE GUIDE · DILNA · BALI"
    assert F.guide_label("", "Bali") == "YOUR ALL-INCLUSIVE GUIDE · GUEST · BALI"
    assert F.guide_label("Dilna", "Bali, Ubud") .endswith("· BALI, UBUD")


def test_header_has_label_and_logo():
    doc, label, _ = _build()
    h = doc.sections[0].header
    assert label in _text(h)
    assert _drawings(h) == 1


def test_first_page_header_empty_for_day_but_not_for_reference():
    doc, _, secs = _build()
    day, ref = doc.sections[1], doc.sections[2]
    assert day.different_first_page_header_footer is True
    assert _text(day.first_page_header) == "" and _drawings(day.first_page_header) == 0
    assert ref.different_first_page_header_footer is False


def test_footer_carries_contact_and_page_field():
    doc, _, _ = _build()
    s = doc.sections[0]
    assert F.CONTACT in _text(s.footer)
    assert F.CONTACT in _text(s.first_page_footer)
    instr = "".join(t.text or "" for t in s.footer._element.iter(qn("w:instrText")))
    assert "PAGE" in instr


def test_margins_per_kind():
    doc, _, secs = _build()
    # index doc.sections: the Section returned for the first section goes stale once more are added
    for idx, want in ((0, (2.0, 1.4, 1.7, 1.4)), (1, (2.2, 1.9, 2.0, 1.9))):
        s = doc.sections[idx]
        got = tuple(x / 360000 for x in (s.top_margin, s.right_margin, s.bottom_margin, s.left_margin))
        assert all(abs(a - b) < 0.01 for a, b in zip(got, want)), idx
    assert F.MARGINS["toc"] == (2.0, 1.4, 1.7, 1.4)


def test_text_width_returned():
    _, _, secs = _build()
    assert abs(secs["toc"][1] - (21.0 - 1.4 - 1.4)) < 0.01
    assert abs(secs["day"][1] - (21.0 - 1.9 - 1.9)) < 0.01


def test_page_number_start_only_on_first_section():
    doc, _, _ = _build()
    els = list(doc.element.iter(qn("w:pgNumType")))
    assert len(els) == 1
    assert doc.sections[0]._sectPr.find(qn("w:pgNumType")) is not None
    assert len(doc.sections) == 4


def test_background_present_once_and_solid():
    doc, _, _ = _build()
    bgs = list(doc.element.iter(qn("w:background")))
    assert len(bgs) == 1 and bgs[0].get(qn("w:color")) == "FBFCFE"


def test_all_header_footer_runs_noproof():
    doc, _, _ = _build()
    for s in doc.sections:
        for part in (s.header, s.footer, s.first_page_footer):
            for r in part._element.iter(qn("w:r")):
                assert r.find(qn("w:rPr")) is not None and r.find(qn("w:rPr")).find(qn("w:noProof")) is not None


def test_doc_opens_with_python_docx_after_save():
    doc, label, _ = _build()
    d2 = _reload(doc)
    assert len(d2.sections) == 4 and label in _text(d2.sections[1].header)
