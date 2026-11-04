"""Full-document assembler for render2: Guide -> .docx bytes with measured TOC page numbers."""
from __future__ import annotations

import io

from src.aigv2.guide import model as M
from src.aigv2.render2 import frame as F
from src.aigv2.render2 import fonts as FN
from src.aigv2.render2 import render as RN
from src.aigv2.render2 import toc as TOC

_KIND = {"letter": "letter", "toc": "toc", "day": "day", "reference": "reference", "thank_you": "thank_you"}


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
        _, W = F.add_guide_section(doc, _KIND[page.kind], label, first=(i == 0), start_page=start_page)
        if page.kind == "toc":
            TOC.render_toc(doc, guide, pages)
        else:
            RN.render_day_page(doc, W, page)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def render_guide2(guide: M.Guide, *, start_page: int = 1) -> bytes:
    data = _build(guide, None, start_page)
    titles = {p.bookmark: _heading(p) for p in guide.pages if p.kind in ("day", "reference", "thank_you")}
    # the letter is one page and the contents normally one more; if the first matched page is later than
    # that the contents ran long, so re-measure skipping everything before it.
    pages = TOC.page_map(data, titles, skip_pages=2, start_page=start_page)
    if pages:
        first = min(pages.values()) - start_page  # 0-based index of the first content page
        if first > 2:
            pages = TOC.page_map(data, titles, skip_pages=first, start_page=start_page)
    if pages:
        data = _build(guide, pages, start_page)
    fonts = FN.find_cormorant()
    return FN.embed_fonts(data, fonts) if fonts else data
