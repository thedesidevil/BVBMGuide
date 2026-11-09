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


def test_entries_are_three_cell_rows_with_dot_characters():
    doc = _build(pages={"sec_packing": 25, "thank_you": 38})
    tabs = _entry_tables(doc)
    assert len(tabs) == 5 + 1  # 5 sections + thank you
    for t in tabs:
        tr = t.find(qn("w:tr"))
        assert tr.find(qn("w:trPr")).find(qn("w:cantSplit")) is not None
        title, fill, num = tr.findall(qn("w:tc"))
        assert fill.find(qn("w:tcPr")).find(qn("w:tcBorders")) is None  # no dotted cell border any more
        assert fill.find(qn("w:tcPr")).find(qn("w:noWrap")) is not None
        for tc in (title, fill, num):
            assert tc.find(qn("w:tcPr")).find(qn("w:vAlign")).get(qn("w:val")) == "bottom"
            sp = tc.find(qn("w:p")).find(qn("w:pPr")).find(qn("w:spacing"))
            assert sp.get(qn("w:lineRule")) == "exact" and sp.get(qn("w:line")) == str(int(TOC.ENTRY_LINE_PT * 20))
        assert num.find(qn("w:p")).find(qn("w:pPr")).find(qn("w:jc")).get(qn("w:val")) == "right"
        assert "." * 3 not in "".join(x.text or "" for x in title.iter(qn("w:t")))
    # the full-width Thank You row has room for a dot run, in the DOT_RULE colour, right aligned
    ty = tabs[-1].find(qn("w:tr")).findall(qn("w:tc"))[1]
    run = ty.find(".//" + qn("w:r"))
    assert set("".join(x.text for x in run.iter(qn("w:t"))).replace("\u00a0", "")) == {"."}
    assert run.find(qn("w:rPr")).find(qn("w:color")).get(qn("w:val")) == T.DOT_RULE
    assert ty.find(qn("w:p")).find(qn("w:pPr")).find(qn("w:jc")).get(qn("w:val")) == "right"
    txt = _text(doc)
    assert "25" in txt and "38" in txt


def _guide_real():
    import json
    from pathlib import Path
    f = Path("aigv2_data/runs/20261105-gdocs-check6/guide.json")
    if not f.is_file():
        pytest.skip("saved guide not available")
    return Guide.model_validate_json(f.read_text())


def _txt(tc):
    return "".join(x.text or "" for x in tc.iter(qn("w:t")))


def test_real_guide_every_row_has_dots_wide_number_zero_margins_no_wrap():
    doc = _build(_guide_real(), pages={"sec_packing": 25, "sec_health": 34})
    rows = _entry_tables(doc)
    assert len(rows) >= 11
    for t in rows:
        title, fill, num = t.find(qn("w:tr")).findall(qn("w:tc"))
        dots = _txt(fill).replace("\u00a0", "")
        assert dots.count(".") >= 4 and set(dots) == {"."}, _txt(title)
        assert _tcw(num) >= 1.3 * 567 - 1
        assert _tcw(fill) >= 1.05 * 567 - 1
        for tc in (title, fill, num):
            mar = tc.find(qn("w:tcPr")).find(qn("w:tcMar"))
            assert mar.find(qn("w:left")).get(qn("w:w")) == "0" and mar.find(qn("w:right")).get(qn("w:w")) == "0"
            assert tc.find(qn("w:tcPr")).find(qn("w:noWrap")) is not None
        assert num.find(qn("w:p")).find(qn("w:pPr")).find(qn("w:jc")).get(qn("w:val")) == "right"
        for cm in t.find(qn("w:tblPr")).find(qn("w:tblCellMar")):
            assert cm.get(qn("w:w")) == "0"
        sz = title.findall(".//" + qn("w:sz"))[-1].get(qn("w:val"))
        assert int(sz) >= 22
        ttl = _txt(title).replace("\t", "").strip()
        ttl = ttl[ttl.index(" ") + 1:] if ttl and not ttl[0].isalnum() else ttl
        assert _tcw(title) >= TOC.measure_cm(ttl, int(sz) / 2) * 1.06 * 567 - 1
    assert "34" in _text(doc)


def test_real_guide_dots_fit_filler_at_1_0_and_1_2():
    g = _guide_real()
    before, while_ = TOC._split_refs(g)
    cw = (18.2 - TOC.COL_GUTTER_CM) / 2  # TOC page text width
    for items in (before, while_):
        titles = [p.title for p in items]
        sz = TOC.column_font_pt(titles, cw)
        assert 11 <= sz <= 12
        for ttl in titles:
            tw, fw, nw = TOC.entry_widths(ttl, cw, sz)
            assert tw + fw + nw == pytest.approx(cw) and fw >= TOC.MIN_FILLER_CM - 1e-6
            d = TOC.dots_for(fw)
            assert d.count(".") >= 4
            assert TOC.measure_cm(d, TOC.DOT_PT) <= 0.9 * fw
            assert TOC.measure_cm(d, TOC.DOT_PT) * 1.2 <= fw + 1e-6 or fw < 2.5  # 1.2x font still inside the filler
            assert tw >= TOC.measure_cm(ttl, sz) * 1.06 + TOC.BULLET_CM


def test_dot_run_at_most_75_percent_of_filler_when_roomy():
    for fill in (2.0, 2.5, 6.0, 12.0):
        d = TOC.dots_for(fill)
        assert d.count(".") >= 4
        w = TOC.measure_cm(d, TOC.DOT_PT)
        assert w <= 0.75 * fill + 1e-6
        assert w * 1.2 <= fill
    assert TOC.dots_for(0.5) == ""


def test_title_cell_has_slack_over_measured_width():
    for title in ("Tailored Packing List", "Safety & Emergency Contacts", "Mobile Connectivity & SIM Guide",
                  "Thank You", "Souvenir Shopping Guide"):
        for width in (8.4, 17.2):
            tw, fw, nw = TOC.entry_widths(title, width)
            assert tw + fw + nw == pytest.approx(width)
            assert nw >= 1.3
            assert tw >= TOC.measure_cm(title) * 1.06 + TOC.BULLET_CM - 1e-6 or fw <= 0


def test_overlong_title_degrades_gracefully():
    tw, fw, nw = TOC.entry_widths("A very long title " * 6, 8.8)
    assert tw + fw + nw == pytest.approx(8.8) and nw >= 1.3 and fw >= -1e-9
    assert TOC.dots_for(fw) == ""
