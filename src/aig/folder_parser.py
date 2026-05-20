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
        files: list[Path] = []
        for ext in self.SUPPORTED_EXTENSIONS:
            files.extend(folder.glob(f"*{ext}"))
        return sorted(files)

    def _extract_text(self, file: Path) -> Optional[str]:
        try:
            if file.suffix.lower() == ".pdf":
                return self._extract_pdf_text(file)
            if file.suffix.lower() == ".docx":
                return self._extract_docx_text(file)
        except Exception:
            pass
        return None

    def _extract_pdf_text(self, file: Path) -> str:
        with pdfplumber.open(file) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)

    def _extract_docx_text(self, file: Path) -> str:
        doc = DocxDocument(str(file))
        return "\n".join(p.text for p in doc.paragraphs)
