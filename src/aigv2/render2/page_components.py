"""Letter placeholder and Thank You renderers for render2."""
from __future__ import annotations

from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
from docx.shared import Cm

from src.aigv2.guide import model as M
from src.aigv2.render2 import frame as F
from src.aigv2.render2 import kit as K
from src.aigv2.render2 import theme as T

TAGLINE = "Your Vacation  ·  Your Story  ·  Your Way"
SERVICES = "Bespoke Travel Planning  ·  Premium Stays  ·  Seamless Experiences"
CLOSING = "Crafting unforgettable journeys, one trip at a time."
LOGO_CM = 3.4


def _contacts() -> list[tuple[str, str]]:
    phone, insta, web = [s.strip() for s in F.CONTACT.split("·")]
    return [(phone, "tel:" + "".join(ch for ch in phone if ch.isdigit() or ch == "+")),
            (insta, "https://www.instagram.com/" + insta.lstrip("@")),
            (web, "https://" + web)]


def render_letter(doc, W: float, c: M.Letter) -> None:
    """Placeholder only: logo, tagline, salutation (first name). The body is written by staff."""
    p = K.np(doc, before=10, after=4, align=AL.CENTER)
    K.picture(p, T.asset("logo_v1.png"), 2.9)
    p = K.np(doc, after=6, align=AL.CENTER)
    K.R(p, TAGLINE, font=T.HEAD, size=12, italic=True, color=T.GOLD_INK)
    K.ornament(doc, before=2, after=26, w=2.6)
    p = K.np(doc, after=14, align=AL.LEFT)
    K.R(p, c.salutation, font=T.HEAD, size=20, color=T.NAVY)
    for t in c.paragraphs:
        p = K.np(doc, after=10, line=1.6)
        K.R(p, t, size=10.5)


def render_thank_you(doc, W: float, c: M.ThankYou, *, bookmark: str | None = None) -> None:
    p = K.np(doc, before=30, after=4, align=AL.CENTER)
    K.picture(p, T.asset("logo_v1.png"), LOGO_CM)
    p = K.np(doc, after=6, align=AL.CENTER)
    K.R(p, TAGLINE, font=T.HEAD, size=12, italic=True, color=T.GOLD_INK)
    K.ornament(doc, before=2, after=40, w=2.6)
    p = K.np(doc, after=4, align=AL.CENTER, line=1.0, style="Heading 1", keep=True)
    K.R(p, "Thank ", font=T.HEAD, size=40, color=T.NAVY, bold=False)
    K.R(p, "You", font=T.HEAD, size=40, italic=True, color=T.CRIMSON, bold=False)
    if bookmark:
        K.bookmark(p, bookmark)
    K.ornament(doc, before=8, after=22, w=2.6)
    for t in c.paragraphs:
        p = K.np(doc, after=10, align=AL.CENTER, line=1.6, indent=1.8)
        p.paragraph_format.right_indent = Cm(1.8)
        K.R(p, t, size=10.5)
    p = K.np(doc, before=16, after=0, align=AL.CENTER)
    K.R(p, c.signoff, font=T.HEAD, size=15, italic=True, color=T.SLATE)
    p = K.np(doc, before=2, after=36, align=AL.CENTER)
    K.R(p, c.signature, font=T.HEAD, size=22, color=T.NAVY)
    p = K.np(doc, after=10, align=AL.CENTER)
    K.eyebrow(p, SERVICES, color=T.ROYAL, spacing=1.6)
    p = K.np(doc, after=12, align=AL.CENTER)
    for i, (txt, url) in enumerate(_contacts()):
        if i:
            K.R(p, "   |   ", size=10, color=T.GOLD_INK)
        K.link(p, url, txt, font=T.BODYF, size=10, color=T.NAVY, bold=False, ul=T.AMBER)
    p = K.np(doc, before=2, after=0, align=AL.CENTER)
    K.R(p, CLOSING, font=T.HEAD, size=14, italic=True, color=T.GOLD_INK)
