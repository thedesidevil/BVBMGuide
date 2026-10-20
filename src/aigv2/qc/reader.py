import io
import re
from typing import Optional

from docx import Document
from docx.oxml.ns import qn
from pydantic import BaseModel, Field

from src.aigv2.render.document import BEFORE_YOU_GO, WHILE_THERE

THANK_YOU = "Thank You"
SECTION_TITLES = [t for _, t in BEFORE_YOU_GO + WHILE_THERE] + [THANK_YOU]
_KNOWN_H1 = {t.casefold() for t in SECTION_TITLES}
MARKER_RE = re.compile(r"⚠ [^⚠]*?(?=\s+·\s|\s*⚠|\s*$)")
DAY_RE = re.compile(r"^Day\s*(\d+)\s*[–—:\-|,]")
MEAL_SLOT_RE = re.compile(r"^(Breakfast|Lunch|Dinner)\s+(?:near\b|[—–-]\s*Included\b)", re.I)
_MEAL_LINE = re.compile(r"^(Breakfast|Lunch|Dinner)\s+(?:near\s+[^.!?]{1,70}|[—–-]\s*Included in your package)$", re.I)
_FALLBACK_MAX = 80
_TRAVEL_LINE = re.compile(r"^Getting there:")
_TRANSPORT_FACTS = {"DEPARTS", "ARRIVES", "SERVICE", "OPERATOR"}
_TRANSPORT_TITLE = re.compile(r"^(Flight|Train|Boat|Bus|Transfer)(: .+)?$")
_SLOT_WORDS = {"morning", "afternoon", "evening"}
_SLOT_CLOSE = re.compile(r"^(Leave for the airport by|Reach the (station|harbor|harbour) by|Leave by|Overnight (in|on board))")
_HEADING_STYLE = re.compile(r"^heading\s*([1-3])$", re.I)
_SUBTITLE = re.compile(r"^All[\s-]*Inclusive Guide\b", re.I)
_KICKER = "your all-inclusive guide"
MAPS_RE = re.compile(r"^https?://(www\.)?(google\.[a-z.]+/maps|maps\.google\.|goo\.gl/maps|maps\.app\.goo\.gl)", re.I)


class DocVenue(BaseModel):
    name: str
    url: Optional[str] = None
    facts: dict[str, str] = Field(default_factory=dict)
    body: str = ""
    travel: str = ""
    kind: str = "venue"


class DocSlot(BaseModel):
    heading: str
    venues: list[DocVenue] = Field(default_factory=list)
    markers: list[str] = Field(default_factory=list)


class DocDay(BaseModel):
    header: str
    slots: list[DocSlot] = Field(default_factory=list)
    index: Optional[int] = None


class DocPara(BaseModel):
    text: str
    day: Optional[int] = None
    section: Optional[str] = None
    venue: Optional[str] = None


class DocModel(BaseModel):
    headings: list[tuple[int, str]]
    days: list[DocDay]
    sections: dict[str, list[str]]
    markers: list[str]
    links: list[tuple[str, str]]
    text: str
    title: str = ""
    subtitle: str = ""
    section_venues: list[DocVenue] = Field(default_factory=list)
    paragraphs: list[DocPara] = Field(default_factory=list)


def _ptext(p) -> str:
    out = []
    for el in p.iter(qn("w:t"), qn("w:tab"), qn("w:br")):
        out.append((el.text or "") if el.tag == qn("w:t") else " ")
    return "".join(out).strip()


def _children(container):
    for el in container:
        if el.tag in (qn("w:p"), qn("w:tbl")):
            yield el
        elif el.tag == qn("w:sdt"):
            content = el.find(qn("w:sdtContent"))
            if content is not None:
                yield from _children(content)


def _cells(tbl):
    return [tc for tr in tbl.findall(qn("w:tr")) for tc in tr.findall(qn("w:tc"))]


def _all_paras(el):
    if el.tag == qn("w:tbl"):
        for tc in _cells(el):
            yield from _all_paras(tc)
        return
    for child in _children(el):
        if child.tag == qn("w:p"):
            yield child
        else:
            for tc in _cells(child):
                yield from _all_paras(tc)


class _Reader:
    def __init__(self, data: bytes):
        self.doc = Document(io.BytesIO(data))
        self.rels = self.doc.part.rels
        self.styles = {}
        for s in self.doc.styles.element.findall(qn("w:style")):
            name = s.find(qn("w:name"))
            ppr = s.find(qn("w:pPr"))
            lvl = ppr.find(qn("w:outlineLvl")) if ppr is not None else None
            self.styles[s.get(qn("w:styleId"))] = (
                name.get(qn("w:val")) if name is not None else "", lvl.get(qn("w:val")) if lvl is not None else None)
        self.headings: list[tuple[int, str]] = []
        self.days: list[DocDay] = []
        self.sections: dict[str, list[str]] = {"": []}
        self.section_venues: list[DocVenue] = []
        self.paras: list[DocPara] = []
        self.links: list[tuple[str, str]] = []
        self.title = self.subtitle = ""
        self.day: Optional[DocDay] = None
        self.section = ""
        self.slot: Optional[DocSlot] = None
        self.travel: Optional[DocPara] = None

    def _links(self, p) -> list[tuple[str, str]]:
        out = []
        for h in p.iter(qn("w:hyperlink")):
            rid = h.get(qn("r:id"))
            if not rid or rid not in self.rels or not self.rels[rid].is_external:
                continue
            url = self.rels[rid].target_ref
            if url.startswith("#") or "#heading=" in url or "#bookmark=" in url:
                continue
            out.append(("".join(t.text or "" for t in h.iter(qn("w:t"))).strip(), url))
        return out

    def _internal_only(self, p) -> bool:
        hs = list(p.iter(qn("w:hyperlink")))
        if not hs:
            return False
        for h in hs:
            rid = h.get(qn("r:id"))
            url = self.rels[rid].target_ref if rid and rid in self.rels else ""
            if not (h.get(qn("w:anchor")) or url.startswith("#") or "#heading=" in url or "#bookmark=" in url):
                return False
        return True

    def _style_level(self, p) -> Optional[int]:
        ppr = p.pPr
        if ppr is None:
            return None
        lvl = ppr.find(qn("w:outlineLvl"))
        if lvl is not None and lvl.get(qn("w:val")) in ("0", "1", "2"):
            return int(lvl.get(qn("w:val"))) + 1
        ps = ppr.find(qn("w:pStyle"))
        if ps is None:
            return None
        sid = ps.get(qn("w:val")) or ""
        name, outline = self.styles.get(sid, ("", None))
        if name.casefold() == "title" or sid.casefold() == "title":
            return 0
        m = _HEADING_STYLE.match(name) or _HEADING_STYLE.match(sid.replace("Heading", "Heading "))
        if m:
            return int(m.group(1))
        if outline in ("0", "1", "2"):
            return int(outline) + 1
        return None

    def _level(self, p, text: str) -> Optional[int]:
        lvl = self._style_level(p)
        if lvl is not None or not text or not self._fallback_ok(p, text):
            return lvl
        if DAY_RE.match(text) or text.casefold() in _KNOWN_H1:
            return 1
        if text.casefold() in _SLOT_WORDS or _MEAL_LINE.match(text):
            return 2
        return None

    def _fallback_ok(self, p, text: str) -> bool:
        if len(text) > _FALLBACK_MAX or self._internal_only(p):
            return False
        ppr = p.pPr
        if ppr is not None:
            if ppr.find(qn("w:numPr")) is not None:
                return False
            ps = ppr.find(qn("w:pStyle"))
            sid = (ps.get(qn("w:val")) or "") if ps is not None else ""
            if "list" in sid.casefold() or "list" in self.styles.get(sid, ("", None))[0].casefold():
                return False
            if ppr.find(qn("w:keepNext")) is not None or ppr.find(qn("w:pageBreakBefore")) is not None:
                return True
        runs = [r for r in p.iter(qn("w:r")) if "".join(t.text or "" for t in r.iter(qn("w:t"))).strip()]
        return bool(runs) and all(_bold(r) or _big(r) for r in runs)

    def _record(self, text: str, venue: Optional[str] = None) -> Optional[DocPara]:
        if not text:
            return None
        para = DocPara(text=text, day=self.day.index if self.day else None,
                       section=None if self.day else self.section, venue=venue)
        self.paras.append(para)
        if self.day is None:
            self.sections.setdefault(self.section, []).append(text)
        elif self.slot is not None:
            self.slot.markers.extend(MARKER_RE.findall(text))
        return para

    def _current_slot(self) -> DocSlot:
        if self.slot is None:
            self.slot = DocSlot(heading="")
            self.day.slots.append(self.slot)
        return self.slot

    def _add_venue(self, v: DocVenue) -> None:
        if self.day is not None:
            if self.travel is not None:
                v.travel, self.travel.venue = self.travel.text, v.name
                self.travel = None
            self._current_slot().venues.append(v)
        elif self.section:
            self.section_venues.append(v)

    def run(self) -> DocModel:
        for el in _children(self.doc.element.body):
            if el.tag == qn("w:p"):
                self._paragraph(el)
            else:
                self._table(el)
        if not self.title:
            self._title_fallback()
        text = "\n".join(p.text for p in self.paras)
        return DocModel(headings=self.headings, days=self.days, sections=self.sections,
                        markers=[m for p in self.paras for m in MARKER_RE.findall(p.text)], links=self.links, text=text, title=self.title,
                        subtitle=self.subtitle, section_venues=self.section_venues, paragraphs=self.paras)

    def _title_fallback(self) -> None:
        front = [t for t in self.sections.get("", []) if t.casefold() != _KICKER]
        for i, t in enumerate(front):
            if _SUBTITLE.match(t):
                self.title = front[i - 1] if i and not front[i - 1].startswith("Dear ") and "⚠" not in front[i - 1] else ""
                return

    def _paragraph(self, p) -> None:
        text = _ptext(p)
        links = self._links(p)
        self.links.extend(links)
        level = self._level(p, text)
        if level == 0 and not self.title:
            self.title = text
        if level in (1, 2) or _SLOT_CLOSE.match(text):
            self.travel = None
        if level == 1 and text:
            self.headings.append((1, text))
            self.slot = None
            m = DAY_RE.match(text)
            if m:
                self.day = DocDay(header=text, index=int(m.group(1)))
                self.days.append(self.day)
            else:
                self.day, self.section = None, text
                self.sections.setdefault(text, [])
            self._record(text)
            return
        if level in (2, 3) and text:
            self.headings.append((level, text))
        if self.day is None and not self.subtitle and self.section == "" and _SUBTITLE.match(text):
            self.subtitle = text
        if self.day is not None and level == 2 and text:
            self.slot = DocSlot(heading=text)
            self.day.slots.append(self.slot)
            self._record(text)
            return
        if self.day is not None and _SLOT_CLOSE.match(text):
            self.slot = None
            self._record(text)
            return
        venue = None
        if self.day is not None and text:
            maps = [(t, u) for t, u in links if MAPS_RE.match(u)]
            if level == 3:
                venue = DocVenue(name=text, url=links[0][1] if links else None)
            elif maps and self.slot is not None and MEAL_SLOT_RE.match(self.slot.heading):
                venue = DocVenue(name=maps[0][0] or text, url=maps[0][1])
        if venue is not None:
            self._add_venue(venue)
        para = self._record(text, venue.name if venue else None)
        if para is not None and self.day is not None and venue is None and _TRAVEL_LINE.match(text):
            self.travel = para

    def _table(self, tbl) -> None:
        cells = _cells(tbl)
        if len(cells) == 1:
            self._card(cells[0])
            return
        for p in _all_paras(tbl):
            self.links.extend(self._links(p))
            self._record(_ptext(p))

    def _card(self, tc) -> None:
        title, url, facts, body, paras = None, None, {}, [], []
        for el in _children(tc):
            if el.tag == qn("w:tbl"):
                for p in _all_paras(el):
                    self.links.extend(self._links(p))
                    paras.append(self._record(_ptext(p)))
                for cell in _cells(el):
                    lines = [t for t in (_ptext(p) for p in _all_paras(cell)) if t]
                    if len(lines) >= 2 and _is_label(lines[0]):
                        facts[lines[0]] = " ".join(lines[1:])
                continue
            text = _ptext(el)
            links = self._links(el)
            self.links.extend(links)
            if title is None and text:
                title, url = text, (links[0][1] if links else None)
                if self._style_level(el) == 3:
                    self.headings.append((3, text))
            elif text:
                body.append(text)
            paras.append(self._record(text))
        if title:
            for para in paras:
                if para is not None:
                    para.venue = title
            self._add_venue(DocVenue(name=title, url=url, facts=facts, body="\n".join(body),
                                     kind=_card_kind(title, facts)))


def _card_kind(title: str, facts: dict[str, str]) -> str:
    if _TRANSPORT_FACTS & facts.keys() or _TRANSPORT_TITLE.match(title):
        return "transport"
    if "TRANSFER" in facts:
        return "transfer"
    if "CHECK-IN" in facts:
        return "hotel"
    return "venue"


def _rpr_on(r, tag: str):
    rpr = r.find(qn("w:rPr"))
    return rpr.find(qn(tag)) if rpr is not None else None


def _bold(r) -> bool:
    b = _rpr_on(r, "w:b")
    return b is not None and b.get(qn("w:val")) not in ("0", "false")


def _big(r) -> bool:
    sz = _rpr_on(r, "w:sz")
    try:
        return sz is not None and int(sz.get(qn("w:val"))) >= 24
    except (TypeError, ValueError):
        return False


def _is_label(s: str) -> bool:
    return any(c.isalpha() for c in s) and s == s.upper() and len(s) <= 40


def read_docx(data: bytes) -> DocModel:
    return _Reader(data).run()
