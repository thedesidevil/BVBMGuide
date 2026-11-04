import io
import shutil

import pytest
from docx import Document
from docx.oxml.ns import qn

from src.aigv2.guide.model import Guide, Page
from src.aigv2.render2 import frame as F
from src.aigv2.render2 import theme as T
from src.aigv2.render2 import toc as TOC


def _guide(title="Ubud, Nusa Lembongan, Sanur Magic", day_titles=None):
    day_titles = day_titles or ["Day 1 – Thu, 24 Sep | Arrival in Bali", "Day 2 – Fri, 25 Sep | Rice Terraces",
                                "Day 3 – Sat, 26 Sep | Departure"]
    pages = [Page(kind="toc", title="Contents", bookmark="toc")]
    pages += [Page(kind="day", title=t, bookmark=f"day_{i + 1}") for i, t in enumerate(day_titles)]
    for k, t in (("packing", "Tailored Packing List"), ("health", "Health & Vaccination"),
                 ("important", "Important Places"), ("getting_around", "Getting Around"),
                 ("safety", "Safety & Emergency Contacts")):
        pages.append(Page(kind="reference", title=t, bookmark=f"sec_{k}"))
    pages.append(Page(kind="thank_you", title="Thank You", bookmark="thank_you"))
    return Guide(client="Dilna Kallalthil", destination="Bali", title=title, subtitle="s", pages=pages)


def _build(guide=None, pages=None):
    guide = guide or _guide()
    doc = F.new_guide_doc(guide.client, guide.destination)
    F.add_guide_section(doc, "toc", F.guide_label(guide.client, guide.destination), first=True)
    TOC.render_toc(doc, guide, pages)
    return doc


def _text(doc):
    return "".join(t.text or "" for t in doc.element.body.iter(qn("w:t")))


def _links(doc):
    return {h.get(qn("w:anchor")): "".join(t.text for t in h.iter(qn("w:t")))
            for h in doc.element.body.iter(qn("w:hyperlink")) if h.get(qn("w:anchor"))}


def test_rows_are_days_plus_sections():
    doc = _build()
    assert len(doc.tables) == 1 + 3  # 3 day cards + the two-column table
    links = _links(doc)
    assert {"day_1", "day_2", "day_3"} <= set(links)
    assert len([k for k in links if k.startswith("sec_")]) == 5
    assert "thank_you" in links


def test_day_rows_are_internal_links():
    links = _links(_build())
    assert links["day_1"] == "Arrival in Bali"
    assert links["sec_packing"] == "Tailored Packing List"
    assert links["thank_you"] == "Thank You"


def _fields(doc):
    out = []
    for p in doc.element.body.iter(qn("w:p")):
        runs = list(p.iter(qn("w:r")))
        for i, r in enumerate(runs):
            it = r.find(qn("w:instrText"))
            if it is not None and "PAGEREF" in it.text:
                cached = runs[i + 2].find(qn("w:t")).text
                out.append((it.text.split()[1], cached))
    return out


def test_page_numbers_use_pageref_fields_with_cached_values():
    f = dict(_fields(_build(pages={"day_1": 5, "sec_packing": 25, "thank_you": 38})))
    assert f["day_1"] == "5" and f["sec_packing"] == "25" and f["thank_you"] == "38"
    assert f["day_2"] == "–"
    assert len(_fields(_build())) == 3 + 5 + 1


def test_numbers_share_one_right_tab_per_block():
    doc = _build()
    for p in doc.element.body.iter(qn("w:p")):
        if any("PAGEREF" in (i.text or "") for i in p.iter(qn("w:instrText"))):
            tabs = p.findall(".//" + qn("w:tab") + "[@" + qn("w:val") + "='right']")
            assert len(tabs) == 1
    assert all(t.get(qn("w:leader")) in (None, "none") for t in doc.element.body.iter(qn("w:tab")))


def test_no_removed_headings():
    txt = _text(_build())
    assert "YOUR ALL-INCLUSIVE GUIDE" not in txt.upper()
    assert "What your guide includes" not in txt


def _crimson_runs(doc):
    return [r for r in doc.element.body.iter(qn("w:r"))
            if r.find(qn("w:rPr")) is not None and r.find(qn("w:rPr")).find(qn("w:color")) is not None
            and r.find(qn("w:rPr")).find(qn("w:color")).get(qn("w:val")) == T.CRIMSON]


def test_crimson_last_word_when_three_or_more_words():
    runs = _crimson_runs(_build())
    assert len(runs) == 1
    assert "".join(t.text for t in runs[0].iter(qn("w:t"))) == "Magic"
    assert runs[0].find(qn("w:rPr")).find(qn("w:i")) is not None
    assert _crimson_runs(_build(_guide(title="Bali Magic"))) == []


def test_prepared_for_line_uses_first_name_and_dates():
    txt = _text(_build())
    assert "Prepared for Dilna" in txt and "Kallalthil" not in txt
    assert "24 September – 26 September" in txt
    g = _guide(day_titles=["Arrival", "Middle", "End"])
    t2 = _text(_build(g))
    assert "Prepared for Dilna" in t2 and "September" not in t2


def test_day_title_parsing_falls_back():
    doc = _build(_guide(day_titles=["Arrival", "Day 2 – Fri, 25 Sep | Rice", "End"]))
    links = _links(doc)
    assert links["day_1"] == "Arrival" and links["day_2"] == "Rice"
    assert len(doc.tables) == 4


def test_toc_in_full_document():
    doc = _build()
    buf = io.BytesIO()
    doc.save(buf)
    assert Document(io.BytesIO(buf.getvalue())).paragraphs


def test_page_map_graceful_without_soffice(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda *_: None)
    assert TOC.page_map(b"x", {"a": "A"}) == {}


@pytest.mark.skipif(shutil.which("soffice") is None or shutil.which("pdftotext") is None, reason="no soffice")
def test_page_map_finds_titles():
    doc = Document()
    for i, t in enumerate(["Alpha Title", "Bravo Title", "Charlie Title"]):
        if i:
            doc.add_page_break()
        doc.add_paragraph(t)
    buf = io.BytesIO()
    doc.save(buf)
    got = TOC.page_map(buf.getvalue(), {"a": "Alpha Title", "c": "Charlie Title", "x": "Nope"}, start_page=4)
    assert got == {"a": 4, "c": 6}
    assert TOC.page_map(buf.getvalue(), {"a": "Alpha Title"}, skip_pages=1) == {}
