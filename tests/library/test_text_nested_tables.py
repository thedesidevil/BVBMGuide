from pathlib import Path

from docx import Document

from src.library.ingest_core.text import read_text


def _nested_docx(path: Path) -> Path:
    doc = Document()
    doc.add_paragraph("Intro line")
    outer = doc.add_table(rows=1, cols=1)
    cell = outer.rows[0].cells[0]
    inner = cell.add_table(rows=2, cols=2)
    inner.rows[0].cells[0].text = "Mathai's Restocafe"
    inner.rows[0].cells[1].text = "INR 200 - 600"
    inner.rows[1].cells[0].text = "Cuisine · Veg-friendly"
    inner.rows[1].cells[1].text = "11 AM : 10 PM"
    doc.add_paragraph("After the table")
    doc.save(str(path))
    return path


def test_tables_nested_in_a_cell_are_read(tmp_path):
    text = read_text(_nested_docx(tmp_path / "n.docx"))
    for needle in ("Intro line", "Mathai's Restocafe", "INR 200 - 600", "Cuisine · Veg-friendly", "11 AM : 10 PM",
                   "After the table"):
        assert needle in text
    assert text.index("Intro line") < text.index("Mathai's Restocafe") < text.index("After the table")


def test_plain_tables_read_exactly_as_before(tmp_path):
    doc = Document()
    doc.add_paragraph("Heading")
    t = doc.add_table(rows=2, cols=2)
    for r, row in enumerate([("a", "b"), ("c", "d")]):
        for c, v in enumerate(row):
            t.rows[r].cells[c].text = v
    p = tmp_path / "p.docx"
    doc.save(str(p))
    assert read_text(p) == "Heading\na | b\nc | d"
