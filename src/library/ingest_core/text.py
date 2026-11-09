"""Read text from DOCX/PDF library files, including DOCX tables."""

import hashlib
import re
from pathlib import Path


class UnreadableFile(Exception):
    """Raised when a file cannot be read as text."""


def _read_docx(path: Path) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    lines: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            lines.append(Paragraph(child, doc).text)
        elif tag == "tbl":
            table = Table(child, doc)
            for row in table.rows:
                cells: list[str] = []
                prev = None
                for cell in row.cells:
                    if prev is not None and cell._tc is prev:
                        continue
                    prev = cell._tc
                    cells.append(cell.text.strip())
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _read_pdf(path: Path) -> str:
    import fitz

    doc = fitz.open(str(path))
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def read_text(path: Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".docx":
            return _read_docx(path)
        if suffix == ".pdf":
            return _read_pdf(path)
    except Exception as e:
        raise UnreadableFile(f"{path}: {e}") from e
    raise UnreadableFile(f"{path}: unsupported file type '{suffix}'")


def text_hash(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha1(collapsed.encode("utf-8")).hexdigest()
