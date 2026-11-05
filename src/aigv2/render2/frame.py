"""Page frame for the render2 renderer: sections, header, footer, page background."""
from __future__ import annotations

from typing import Literal

from docx.shared import Cm

from src.aigv2.render2 import kit as K
from src.aigv2.render2 import theme as T
from src.aigv2.render2.styles import install_styles

Kind = Literal["toc", "day", "reference", "letter", "thank_you"]

CONTACT = "+91 86000 15316 · @bonvoyagebymarina · www.bonvoyagebymarina.com"
# (top, right, bottom, left) in cm
MARGINS: dict[str, tuple[float, float, float, float]] = {
    "toc": (2.0, 1.4, 1.7, 1.4),
    "day": (2.2, 1.9, 2.0, 1.9),
    "reference": (2.2, 1.9, 2.0, 1.9),
    "letter": (2.2, 1.9, 2.0, 1.9),
    "thank_you": (2.2, 1.9, 2.0, 1.9),
}
HEADER_CM, FOOTER_CM = 0.7, 0.6
_OPENER_KINDS = ("toc", "day", "letter", "thank_you")
LOGO_CM = 3.3


def guide_label(client: str, destination: str) -> str:
    first = (client or "").split()[0] if (client or "").strip() else "GUEST"
    return f"YOUR ALL-INCLUSIVE GUIDE · {first.upper()} · {(destination or '').upper()}"


def new_guide_doc(client: str, destination: str):
    """A4 doc with the solid white background and render2 styles. The caller builds the label via
    guide_label(client, destination) and passes it to add_guide_section."""
    doc = K.new_doc()
    install_styles(doc)
    for p in list(doc.paragraphs):  # the first section is the TOC section; no stray paragraphs
        p._p.getparent().remove(p._p)
    return doc


def _footer_into(ftr, W: float) -> None:
    p = ftr.paragraphs[0]
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    K.p_border(p, "top", T.POWDER, 4, 5)
    K.tabs(p, [("right", W, None)])
    K.no_proof(K.run(p, CONTACT, font=T.BODYF, size=8, color=T.SLATE))
    K.no_proof(K.run(p, "\t"))
    K.no_proof(K.run(p, "Page ", font=T.BODYF, size=8, color=T.SLATE))
    n = len(p._p)
    K.field(p, "PAGE", "1", font=T.HEAD, size=11, bold=True, color=T.ROYAL)
    for r in list(p._p)[n:]:
        K.no_proof(_Run(r, p))


class _Run:
    """Minimal wrapper so kit.no_proof can edit a raw w:r."""
    def __init__(self, r, p):
        self._r = r
        self._parent = p


def _header_into(hdr, W: float, label: str) -> None:
    p = hdr.paragraphs[0]
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    K.tabs(p, [("right", W, None)])
    K.p_border(p, "bottom", T.POWDER, 4, 3)
    K.no_proof(K.run(p, label, font=T.BODYF, size=7.5, bold=True, color=T.ROYAL))
    K.no_proof(K.run(p, "\t"))
    K.no_proof(K.picture(p, T.asset("logo_h1.png"), LOGO_CM))


def header_footer(section, W: float, label: str, *, titlepg: bool) -> None:
    section.different_first_page_header_footer = titlepg
    for part in (section.header, section.footer, section.first_page_header, section.first_page_footer):
        part.is_linked_to_previous = False
    _header_into(section.header, W, label)
    _footer_into(section.footer, W)
    _footer_into(section.first_page_footer, W)  # first-page header stays empty


def add_guide_section(doc, kind: Kind, label: str, *, first: bool = False, start_page: int = 1):
    s = doc.sections[0] if first else K.add_section(doc, "new_page")
    s.top_margin, s.right_margin, s.bottom_margin, s.left_margin = [Cm(x) for x in MARGINS[kind]]
    s.header_distance, s.footer_distance = Cm(HEADER_CM), Cm(FOOTER_CM)
    W = (s.page_width - s.left_margin - s.right_margin) / 360000
    header_footer(s, W, label, titlepg=kind in _OPENER_KINDS)
    if first:
        K.set_page_start(s, start_page)
    return s, W
