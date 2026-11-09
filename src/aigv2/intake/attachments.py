import hashlib
import io
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Literal

import fitz
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pydantic import BaseModel

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".heic", ".webp"}
MIN_TEXT_CHARS = 40
ZIP_MAX_FILES = 50
ZIP_MAX_BYTES = 50 * 1024 * 1024

_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE_RE = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\b(?:,?\s+\d{{4}})?"
    rf"|\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:,?\s+\d{{4}})?"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    re.IGNORECASE,
)


class Attachment(BaseModel):
    name: str
    kind: Literal["pdf", "docx", "image", "other"]
    text: str
    image_only: bool
    has_images: bool
    text_dates: list[str] = []
    duplicate_of: str | None = None
    error: str | None = None
    skipped_files: list[str] = []


def _find_dates(text: str) -> list[str]:
    seen: list[str] = []
    for m in _DATE_RE.finditer(text):
        s = m.group(0).strip()
        if s not in seen:
            seen.append(s)
    return seen


def _read_pdf(data: bytes) -> tuple[str, bool]:
    with fitz.open(stream=data, filetype="pdf") as doc:
        text = "\n".join(page.get_text() for page in doc)
        has_images = any(page.get_images() for page in doc)
    return text, has_images


def _read_docx(data: bytes) -> tuple[str, bool]:
    doc = Document(io.BytesIO(data))
    parts: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            parts.append(Paragraph(child, doc).text)
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                seen: set[int] = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    parts.append(cell.text)
    has_images = bool(doc.element.body.xpath(".//pic:pic"))
    return "\n".join(parts), has_images


def _build(name: str, data: bytes) -> Attachment:
    ext = PurePosixPath(name).suffix.lower()
    if ext in IMAGE_EXTS:
        return Attachment(name=name, kind="image", text="", image_only=True, has_images=True)
    if ext == ".pdf":
        kind, (text, has_images) = "pdf", _read_pdf(data)
    elif ext == ".docx":
        kind, (text, has_images) = "docx", _read_docx(data)
    else:
        return Attachment(name=name, kind="other", text="", image_only=False, has_images=False)
    image_only = len(text.strip()) < MIN_TEXT_CHARS and has_images
    return Attachment(
        name=name,
        kind=kind,
        text=text,
        image_only=image_only,
        has_images=has_images,
        text_dates=_find_dates(text),
    )


def _failed(name: str, exc: Exception) -> Attachment:
    return Attachment(
        name=name,
        kind="other",
        text="",
        image_only=False,
        has_images=False,
        error=f"{type(exc).__name__}: {exc}",
    )


def _safe_build(name: str, data: bytes) -> Attachment:
    try:
        return _build(name, data)
    except Exception as exc:
        return _failed(name, exc)


def read_attachment(path: Path) -> Attachment:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return _failed(path.name, exc)
    return _safe_build(path.name, data)


def _safe_zip_name(name: str) -> bool:
    p = PurePosixPath(name.replace("\\", "/"))
    return not p.is_absolute() and ".." not in p.parts and not re.match(r"^[A-Za-z]:", name)


def _expand_zip(path: Path) -> list[tuple[str, bytes | Attachment]]:
    out: list[tuple[str, bytes | Attachment]] = []
    total = 0
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        return [(path.name, _failed(path.name, exc))]
    skipped: list[str] = []
    with zf:
        for info in zf.infolist():
            base = PurePosixPath(info.filename.replace("\\", "/"))
            if info.is_dir() or not _safe_zip_name(info.filename):
                continue
            if "__MACOSX" in base.parts or base.name.startswith("._"):
                continue
            if len(out) >= ZIP_MAX_FILES or total + info.file_size > ZIP_MAX_BYTES:
                skipped.append(info.filename)
                continue
            inner = f"{path.name}/{info.filename}"
            try:
                data = zf.read(info)
            except Exception as exc:
                out.append((inner, _failed(inner, exc)))
                continue
            total += len(data)
            out.append((inner, data))
    if skipped:
        out.append((path.name, Attachment(name=path.name, kind="other", text="", image_only=False, has_images=False,
                                          skipped_files=skipped)))
    return out


def read_attachments(paths: list[Path]) -> list[Attachment]:
    items: list[tuple[str, bytes | Attachment]] = []
    for p in paths:
        if p.suffix.lower() == ".zip":
            items.extend(_expand_zip(p))
        else:
            try:
                items.append((p.name, p.read_bytes()))
            except OSError as exc:
                items.append((p.name, _failed(p.name, exc)))
    first_seen: dict[str, str] = {}
    result: list[Attachment] = []
    for name, data in items:
        if isinstance(data, Attachment):
            result.append(data)
            continue
        att = _safe_build(name, data)
        digest = hashlib.sha256(data).hexdigest()
        if digest in first_seen:
            att.duplicate_of = first_seen[digest]
        else:
            first_seen[digest] = name
        result.append(att)
    return result
