import io
import re

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from src.aigv2.models import Finding, Marker
from src.aigv2.render.blocks import add_marker


def _text(p) -> str:
    return " ".join("".join(t.text or "" for t in p.iter(qn("w:t"))).split())


def _internal_link(p) -> bool:
    return any(h.get(qn("w:anchor")) for h in p.iter(qn("w:hyperlink")))


def _style_id(p) -> str:
    ppr = p.find(qn("w:pPr"))
    st = ppr.find(qn("w:pStyle")) if ppr is not None else None
    return (st.get(qn("w:val")) if st is not None else "").casefold().replace(" ", "")


def _find(paras, needle: str):
    if not needle:
        return None
    hits = [p for p in paras if needle in _text(p)]
    return next((p for p in hits if not _internal_link(p)), hits[0] if hits else None)


def _day_header(paras, day):
    if day is None:
        return None
    rx = re.compile(rf"^Day\s*{day}\s*[–—:\-|,]")
    hits = [p for p in paras if rx.match(_text(p)) and not _internal_link(p)]
    return next((p for p in hits if _style_id(p).startswith("heading")), hits[0] if hits else None)


def annotate(docx_bytes: bytes, findings: list[Finding]) -> bytes:
    doc = Document(io.BytesIO(docx_bytes))
    body = doc.element.body
    paras = list(body.iter(qn("w:p")))
    tail: dict[int, object] = {}
    at_start = 0
    for f in findings:
        target = _find(paras, " ".join(f.anchor_text.split()))
        if target is None:
            target = _day_header(paras, f.day)
        new_p = OxmlElement("w:p")
        if target is None:
            body.insert(at_start, new_p)
            at_start += 1
        else:
            (tail.get(id(target)) if id(target) in tail else target).addnext(new_p)
            tail[id(target)] = new_p
        add_marker(Paragraph(new_p, doc._body), Marker(kind="CHECK", text=f.message))
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
