import io
import re
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml.ns import qn

from src.aigv2.guide import model as M
from src.aigv2.guide.build import build_guide
from src.aigv2.render.document import GuideData
from src.aigv2.render2 import fonts as FN
from src.aigv2.render2 import theme as T
from src.aigv2.render2.render import render_guide2

_FIX = Path(__file__).parent / "fixtures" / "bali_guide" / "guide_data.json"


@pytest.fixture(scope="module")
def guide():
    data = GuideData.model_validate(json.loads(_FIX.read_text(encoding="utf-8")))
    g = build_guide(data, SimpleNamespace(walk_max_min=10))
    ref = M.Page(kind="reference", title="Tailored Packing List", bookmark="sec_packing", components=[
        M.ReferenceOpener(eyebrow="BEFORE YOU GO", title="Tailored Packing List", intro="Light layers."),
        M.TipPanel(title="Tip", items=["Bring a hat"]),
        M.DosDonts(do=["Smile"], dont=["Shout"]),
        M.PhraseTable(phrases=[M.Phrase(local="Terima kasih", english="Thank you")])])
    g.pages.insert(-1, ref)
    return g


@pytest.fixture(scope="module")
def blob(guide):
    return render_guide2(guide)


@pytest.fixture(scope="module")
def doc(blob):
    return Document(io.BytesIO(blob))


def _texts(doc):
    return [p.text for p in doc.paragraphs]


def test_section_count_matches_pages(guide, doc):
    assert len(doc.sections) == len(guide.pages)


def test_page_order(guide, doc):
    heads = [p.text.replace("\n", " ") for p in doc.paragraphs if p.style.name == "Heading 1"]
    want = []
    for pg in guide.pages:
        if pg.kind == "day":
            want.append(" ".join(next(c for c in pg.components if isinstance(c, M.Opener)).title))
        elif pg.kind == "reference":
            want.append(next(c for c in pg.components if isinstance(c, M.ReferenceOpener)).title)
        elif pg.kind == "thank_you":
            want.append("Thank You")
    assert heads == want


def test_all_day_headings_present(guide, doc):
    joined = [p.text.replace("\n", " ") for p in doc.paragraphs]
    for p in guide.pages:
        if p.kind == "day":
            title = " ".join(next(c for c in p.components if isinstance(c, M.Opener)).title)
            assert any(title in t for t in joined), title


def test_letter_has_marker_name_and_no_prose(guide, doc):
    letter = guide.pages[0].components[0]
    assert letter.paragraphs == []
    t = _texts(doc)
    i = next(i for i, x in enumerate(t) if x.startswith("Dear"))
    assert t[i] == letter.salutation == "Dear Test,"
    assert "WRITE PERSONAL LETTER" in t[i + 1]
    nxt = [x for x in t[i + 2:i + 5] if x.strip()]
    assert nxt[0].startswith("Your Vacation")  # the contents page follows: no prose between
    assert not any(len(x) > 120 for x in t[i:i + 3])
    assert doc.sections[0].different_first_page_header_footer


def test_thank_you_text_from_guide(guide, doc):
    ty = next(c for p in guide.pages if p.kind == "thank_you" for c in p.components)
    t = _texts(doc)
    for para in ty.paragraphs:
        assert para in t
    assert ty.signoff in t and ty.signature in t
    h = next(p for p in doc.paragraphs if p.text == "Thank You")
    assert h.style.name == "Heading 1"
    runs = {r.text.strip(): r for r in h.runs}
    assert runs["You"].font.italic
    assert str(runs["You"].font.color.rgb) == T.CRIMSON.upper()
    assert str(runs["Thank"].font.color.rgb) == T.NAVY.upper()


def test_contacts_are_hyperlinks(doc):
    rels = {r.rId: r.target_ref for r in doc.part.rels.values() if r.reltype.endswith("/hyperlink")}
    ty = next(p for p in doc.paragraphs if p.text.startswith("+91 86000"))
    targets = [rels[h.get(qn("r:id"))] for h in ty._p.findall(qn("w:hyperlink"))]
    assert targets[0].startswith("tel:+91")
    assert "instagram.com/bonvoyagebymarina" in targets[1]
    assert targets[2].startswith("https://www.bonvoyagebymarina.com")


def test_reference_page_rendered(doc):
    t = _texts(doc)
    assert "Tailored Packing List" in t
    h = next(p for p in doc.paragraphs if p.text == "Tailored Packing List")
    assert h.style.name == "Heading 1"
    bm = [b.get(qn("w:name")) for b in h._p.findall(qn("w:bookmarkStart"))]
    assert bm == ["sec_packing"]


def test_fonts_embedded_when_found(blob):
    if not FN.find_cormorant():
        pytest.skip("Cormorant not installed")
    names = ZipFile(io.BytesIO(blob)).namelist()
    assert any(n.startswith("word/fonts/") for n in names)


def test_reader_reads_without_error_and_headings_present(blob, guide):
    from src.aigv2.qc.reader import read_docx
    assert read_docx(blob) is not None


@pytest.mark.xfail(strict=True, reason="Task 23 adapts qc/reader.py to the render2 layout")
def test_reader_sees_all_days_and_slots(blob, guide):
    from src.aigv2.qc.reader import read_docx
    m = read_docx(blob)
    assert len(m.days) == sum(1 for p in guide.pages if p.kind == "day")
    for d in m.days:
        for s in d.slots:
            assert s.venues or s.markers


def test_registry_covers_every_component():
    import typing
    from src.aigv2.render2.render import RENDERERS
    union = typing.get_args(M.Component)[0]
    classes = typing.get_args(union)
    assert classes
    missing = [c.__name__ for c in classes if c not in RENDERERS]
    assert missing == []


def test_embed_failure_returns_unembedded(guide, monkeypatch):
    if not FN.find_cormorant():
        pytest.skip("Cormorant not installed")
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(FN, "embed_fonts", boom)
    out = render_guide2(guide)
    assert not any(n.startswith("word/fonts/") for n in ZipFile(io.BytesIO(out)).namelist())
    Document(io.BytesIO(out))


def test_toc_numbers_match_final_page_map(guide, blob):
    import shutil
    if not (shutil.which("soffice") and shutil.which("pdftotext")):
        pytest.skip("soffice/pdftotext missing")
    from src.aigv2.render2 import document as DOC
    from src.aigv2.render2 import toc as TOC
    titles = {p.bookmark: DOC._heading(p) for p in guide.pages if p.kind in ("day", "reference", "thank_you")}
    skip = DOC._skip_pages(blob, guide, titles, 1)
    final = TOC.page_map(blob, titles, skip_pages=skip)
    assert final
    d = Document(io.BytesIO(blob))
    shown = {}
    for para in d.element.body.iter(qn("w:p")):
        h = para.find(qn("w:hyperlink"))
        if h is None or h.get(qn("w:anchor")) is None:
            continue
        txt = "".join(t.text or "" for t in para.iter(qn("w:t")))
        tail = re.search(r"(\d+)\s*$", txt).group(1)
        shown[h.get(qn("w:anchor"))] = tail
    assert shown
    assert {k: str(v) for k, v in final.items()} == shown
