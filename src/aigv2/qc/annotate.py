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


_DAY_RX = re.compile(r"^Day\s*(\d+)\s*[–—:\-|,]")


def _day_map(paras) -> dict[int, int | None]:
    out, current = {}, None
    for p in paras:
        if _style_id(p) in ("heading1", "heading 1"):
            m = _DAY_RX.match(_text(p))
            current = int(m.group(1)) if m else None
        out[id(p)] = current
    return out


def _find(paras, needle: str, day=None, days=None):
    if not needle:
        return None
    hits = [p for p in paras if needle in _text(p) and not _internal_link(p)]
    scoped = [p for p in hits if day is not None and days.get(id(p)) == day]
    pool = scoped or hits or [p for p in paras if needle in _text(p)]
    return pool[0] if pool else None


def _day_header(paras, day):
    if day is None:
        return None
    hits = [p for p in paras if _DAY_RX.match(_text(p)) and int(_DAY_RX.match(_text(p)).group(1)) == day
            and not _internal_link(p)]
    return next((p for p in hits if _style_id(p).startswith("heading")), hits[0] if hits else None)


def _outside_tables(p):
    top = p
    for a in p.iterancestors():
        if a.tag == qn("w:tbl"):
            top = a
    return top


def annotate(docx_bytes: bytes, findings: list[Finding]) -> bytes:
    doc = Document(io.BytesIO(docx_bytes))
    body = doc.element.body
    paras = list(body.iter(qn("w:p")))
    days = _day_map(paras)
    tail: dict[int, object] = {}
    at_start = 0
    for f in findings:
        target = _find(paras, " ".join(f.anchor_text.split()), f.day, days)
        if target is None:
            target = _day_header(paras, f.day)
        new_p = OxmlElement("w:p")
        if target is None:
            body.insert(at_start, new_p)
            at_start += 1
        else:
            top = _outside_tables(target)
            (tail[id(top)] if id(top) in tail else top).addnext(new_p)
            tail[id(top)] = new_p
        add_marker(Paragraph(new_p, doc._body), Marker(kind="CHECK", text=f.message))
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
