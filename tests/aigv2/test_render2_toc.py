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
    assert len(doc.tables) == 1 + 3 + 1  # 3 day cards + the two-column table + the Thank You entry
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


def test_known_numbers_are_plain_runs_unknown_are_pageref():
    doc = _build(pages={"day_1": 5, "sec_packing": 25, "thank_you": 38})
    f = dict(_fields(doc))
    assert "day_1" not in f and "sec_packing" not in f and "thank_you" not in f
    assert f["day_2"] == "–"
    txt = _text(doc)
    assert "p." + TOC.NB + "5" in txt and "25" in txt and "38" in txt
    assert not list(doc.element.body.iter(qn("w:fldSimple")))
    assert len(_fields(_build())) == 3 + 5 + 1
    assert all(c == "–" for _, c in _fields(_build()))


def test_numbers_share_one_right_tab_per_block():
    doc = _build()
    for p in doc.element.body.iter(qn("w:p")):
        if any("PAGEREF" in (i.text or "") for i in p.iter(qn("w:instrText"))):
            tabs = p.findall(".//" + qn("w:tab") + "[@" + qn("w:val") + "='right']")
            assert len(tabs) <= 1  # day cards: one right tab; section entries: a right-aligned number cell
    full = _build(pages={f"day_{i}": i for i in (1, 2, 3)})
    for p in full.element.body.iter(qn("w:p")):
        if "p." + TOC.NB in "".join(t.text or "" for t in p.iter(qn("w:t"))):
            assert len(p.findall(".//" + qn("w:tab") + "[@" + qn("w:val") + "='right']")) == 1
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
    assert len(doc.tables) == 5


def test_toc_in_full_document():
    doc = _build()
    buf = io.BytesIO()
    doc.save(buf)
    assert Document(io.BytesIO(buf.getvalue())).paragraphs


def test_page_map_graceful_without_soffice(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda *_: None)
    assert TOC.page_map(b"x", {"a": "A"}, skip_pages=0) == {}


@pytest.mark.skipif(shutil.which("soffice") is None or shutil.which("pdftotext") is None, reason="no soffice")
def test_page_map_finds_titles():
    doc = Document()
    for i, t in enumerate(["Alpha Title", "Bravo Title", "Charlie Title"]):
        if i:
            doc.add_page_break()
        doc.add_paragraph(t)
    buf = io.BytesIO()
    doc.save(buf)
    got = TOC.page_map(buf.getvalue(), {"a": "Alpha Title", "c": "Charlie Title", "x": "Nope"}, skip_pages=0, start_page=4)
    assert got == {"a": 4, "c": 6}
    assert TOC.page_map(buf.getvalue(), {"a": "Alpha Title"}, skip_pages=1) == {}


@pytest.mark.parametrize("title,expect", [
    ("Day 1 – Tue, 1 Sept | X", (1, "Tue", "1 Sep", "X")),
    ("Day 12 — Wed, 30 Sep | A | B", (12, "Wed", "30 Sep", "A | B")),
    ("Day 3 - Mon, 3 Mar | Y", (3, "Mon", "3 Mar", "Y")),
    ("Day 4 – Tues, 4 Sept | Z", (4, "Tue", "4 Sep", "Z")),
])
def test_day_title_regex_tolerant(title, expect):
    assert TOC._parse_day(title) == expect


def test_day_title_nonsense_falls_back():
    assert TOC._parse_day("Welcome to Bali") is None


@pytest.mark.skipif(shutil.which("soffice") is None or shutil.which("pdftotext") is None, reason="no soffice")
def test_page_map_matches_headings_only_after_skipped_pages():
    doc = Document()
    doc.add_paragraph("Contents")
    for t in ("Getting Around", "Money", "Missing Thing"):
        doc.add_paragraph(t)
    for head, body in (("Getting Around", "Taxis are easy."), ("Money", "see Getting Around and Missing Thing"),
                       ("Other", "Money matters here")):
        doc.add_page_break()
        doc.add_paragraph(head)
        for _ in range(6):
            doc.add_paragraph("filler line")
        doc.add_paragraph(body)
    buf = io.BytesIO()
    doc.save(buf)
    got = TOC.page_map(buf.getvalue(), {"g": "Getting Around", "m": "Money", "x": "Missing Thing"}, skip_pages=1)
    assert got == {"g": 2, "m": 3}


def _entry_tables(doc):
    return [t for t in doc.element.body.iter(qn("w:tbl"))
            if len(t.find(qn("w:tr")).findall(qn("w:tc"))) == 3 and t.find(".//" + qn("w:tbl") ) is None
            and t.getparent().tag == qn("w:body") or t.getparent().tag == qn("w:tc") and
            len(t.find(qn("w:tr")).findall(qn("w:tc"))) == 3]


def _tcw(tc):
    return int(tc.find(qn("w:tcPr")).find(qn("w:tcW")).get(qn("w:w")))


def test_entries_are_three_cell_rows_with_dotted_filler():
    doc = _build(pages={"sec_packing": 25, "thank_you": 38})
    tabs = _entry_tables(doc)
    assert len(tabs) == 5 + 1  # 5 sections + thank you
    for t in tabs:
        tr = t.find(qn("w:tr"))
        assert tr.find(qn("w:trPr")).find(qn("w:cantSplit")) is not None
        title, fill, num = tr.findall(qn("w:tc"))
        b = fill.find(qn("w:tcPr")).find(qn("w:tcBorders")).find(qn("w:bottom"))
        assert b.get(qn("w:val")) == "dotted"
        for tc in (title, fill, num):
            assert tc.find(qn("w:tcPr")).find(qn("w:vAlign")).get(qn("w:val")) == "bottom"
        assert num.find(qn("w:p")).find(qn("w:pPr")).find(qn("w:jc")).get(qn("w:val")) == "right"
        assert "." * 3 not in "".join(x.text or "" for x in t.iter(qn("w:t")))  # no text dots
    txt = _text(doc)
    assert "25" in txt and "38" in txt


def test_title_cell_has_slack_over_measured_width_even_when_font_is_wider():
    for title in ("Tailored Packing List", "Safety & Emergency Contacts", "Mobile Connectivity & SIM Guide",
                  "Thank You", "Souvenir Shopping Guide"):
        for width in (8.4, 18.2):
            tw, fw, nw = TOC.entry_widths(title, width)
            assert tw + fw + nw == pytest.approx(width)
            assert nw >= 0.9 and fw > 0
            need = 1.1 * TOC.measure_cm(title) + 0.6  # 10% wider title text + bullet glyph and gap
            # titles that fill the column are capped (number cell keeps >= 0.9 cm) and may wrap inside their own cell
            assert tw >= need or fw <= TOC.MIN_FILLER_CM + 1e-6
            assert tw >= 1.04 * TOC.measure_cm(title) + 0.6


def test_overlong_title_degrades_gracefully():
    tw, fw, nw = TOC.entry_widths("A very long title " * 6, 8.8)
    assert tw + fw + nw == pytest.approx(8.8) and nw >= 0.9 and fw >= 0.3
