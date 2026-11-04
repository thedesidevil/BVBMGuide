"""Full-document assembler for render2: Guide -> .docx bytes with measured TOC page numbers."""
from __future__ import annotations

import io

from src.aigv2.guide import model as M
from src.aigv2.render2 import frame as F
from src.aigv2.render2 import fonts as FN
from src.aigv2.render2 import render as RN
from src.aigv2.render2 import toc as TOC

MAX_PASSES = 3


def _heading(page: M.Page) -> str:
    """The visible heading text of a page (what page_map searches for)."""
    for c in page.components:
        if isinstance(c, M.Opener):
            return " ".join(c.title)
        if isinstance(c, M.ReferenceOpener):
            return c.title
    return "Thank You" if page.kind == "thank_you" else page.title


def _build(guide: M.Guide, pages, start_page: int) -> bytes:
    doc = F.new_guide_doc(guide.client, guide.destination)
    label = F.guide_label(guide.client, guide.destination)
    for i, page in enumerate(guide.pages):
        _, W = F.add_guide_section(doc, page.kind, label, first=(i == 0), start_page=start_page)
        if page.kind == "toc":
            TOC.render_toc(doc, guide, pages)
        else:
            RN.render_day_page(doc, W, page)
    buf = io.BytesIO()
    doc.save(buf)
    return _embed(buf.getvalue())


def _embed(data: bytes) -> bytes:
    """Embedded fonts change LibreOffice's layout, so pages are measured on the embedded bytes."""
    fonts = FN.find_cormorant()
    if not fonts:
        return data
    try:
        return FN.embed_fonts(data, fonts)
    except Exception:
        return data


def _skip_pages(data: bytes, guide: M.Guide, titles: dict[str, str], start_page: int) -> int:
    """Leading PDF pages (letter + contents) before the first page whose heading matches any title."""
    lead = sum(1 for p in guide.pages if p.kind in ("letter", "toc"))
    first = TOC.page_map(data, titles, skip_pages=0, start_page=start_page)
    if not first:
        return lead or 2
    return max(lead, min(v - start_page for v in first.values()))


def render_guide2(guide: M.Guide, *, start_page: int = 1) -> bytes:
    data = _build(guide, None, start_page)
    titles = {p.bookmark: _heading(p) for p in guide.pages if p.kind in ("day", "reference", "thank_you")}
    skip = _skip_pages(data, guide, titles, start_page)
    pages = TOC.page_map(data, titles, skip_pages=skip, start_page=start_page)
    if pages:
        # The numbers change the TOC text, which could move pages: rebuild until stable (bounded).
        for _ in range(MAX_PASSES - 1):
            data = _build(guide, pages, start_page)
            again = TOC.page_map(data, titles, skip_pages=skip, start_page=start_page)
            if again == pages or not again:
                break
            pages = again
        else:
            data = _build(guide, pages, start_page)
    return data
