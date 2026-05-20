"""Parse all documents in an input folder and extract trip facts via AI."""

from pathlib import Path
from typing import Optional

import pdfplumber
from docx import Document as DocxDocument

from src.common.ai_provider import get_ai_client


class FolderParser:
    """Parses all documents in a folder and returns consolidated TripFacts."""

    SUPPORTED_EXTENSIONS = {".pdf", ".docx"}

    def __init__(self, ai_client=None):
        self._ai = ai_client if ai_client is not None else get_ai_client()

    def _find_files(self, folder: Path) -> list[Path]:
        seen: set[Path] = set()
        for f in folder.iterdir():
            if f.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                seen.add(f)
        return sorted(seen)

    def _extract_text(self, file: Path) -> Optional[str]:
        try:
            if file.suffix.lower() == ".pdf":
                return self._extract_pdf_text(file)
            if file.suffix.lower() == ".docx":
                return self._extract_docx_text(file)
        except Exception:
            pass
        return None

    def _extract_pdf_text(self, file: Path) -> Optional[str]:
        with pdfplumber.open(file) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages).strip()
        return text if text else None

    def _extract_docx_text(self, file: Path) -> Optional[str]:
        doc = DocxDocument(str(file))
        text = "\n".join(p.text for p in doc.paragraphs).strip()
        return text if text else None
