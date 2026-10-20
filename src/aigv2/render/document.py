import io
import re
from datetime import date
from typing import Optional

from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor
from pydantic import BaseModel, Field

from src.aigv2.models import Booking, Marker, Place, TransportLeg, TripPlan
from src.aigv2.planning.important_places import ImportantPlaces
from src.aigv2.planning.meals import MealPick
from src.aigv2.planning.slots import DayResult
from src.aigv2.planning.travel import Leg
from src.aigv2.render.blocks import add_eyebrow, add_internal_link, add_marker, add_page_break, add_rule
from src.aigv2.render.day_render import DayRenderer, day_header, sunset_time
from src.aigv2.render.sections_render import render_important, render_section, render_thank_you
from src.aigv2.render.theme import ASSETS, GOLD, PPR_ORDER, new_document, ordered_insert
from src.aigv2.writing.days import DayText
from src.aigv2.writing.sections import SectionContent

__all__ = ["GuideData", "RenderDay", "day_header", "output_filename", "render_guide", "sunset_time"]

BEFORE_YOU_GO = [("packing", "Tailored Packing List"), ("money", "Money & Payments"),
                 ("connectivity", "Mobile Connectivity & SIM Guide"), ("health", "Health & Vaccination")]
WHILE_THERE = [("important", "Important Places Around Your Stays"), ("getting_around", "Getting Around"),
               ("dishes", "Must-Try Local Dishes"), ("souvenirs", "Souvenir Shopping Guide"),
               ("etiquette", "Cultural Etiquette & Local Phrases"), ("safety", "Safety & Emergency Contacts")]
_BAD_FILE_CHARS = re.compile(r'[\\/:*?"<>|]')


class RenderDay(BaseModel):
    index: int
    date: date
    city: str
    text: DayText
    result: DayResult
    meals: list[MealPick] = Field(default_factory=list)
    legs: dict[str, Leg] = Field(default_factory=dict)
    places: dict[str, Optional[Place]] = Field(default_factory=dict)
    booking_by_item: dict[str, Booking] = Field(default_factory=dict)
    price_by_restaurant: dict[str, str | Marker] = Field(default_factory=dict)
    arrival: Optional[TransportLeg] = None
    departure: Optional[TransportLeg] = None
    prev_city: Optional[str] = None
    utc_offset_hours: Optional[float] = None
    library_attractions: dict[str, dict] = Field(default_factory=dict)


class GuideData(BaseModel):
    trip: TripPlan
    title: str
    days: list[RenderDay]
    sections: dict[str, Optional[SectionContent]]
    important: list[ImportantPlaces]
    trip_scope: str
    modes: list[str]
    domestic: bool


def destinations(trip: TripPlan) -> list[str]:
    return list(dict.fromkeys([h.city for h in trip.hotels] or [d.city for d in trip.days]))


def output_filename(trip: TripPlan) -> str:
    client = trip.client_names[0] if trip.client_names else "Client"
    name = f"All Inclusive Guide - {client} - {', '.join(destinations(trip))}"
    return _BAD_FILE_CHARS.sub("-", name) + ".docx"


def _present(data: GuideData, key: str) -> bool:
    if key == "important":
        return bool(data.important)
    s = data.sections.get(key)
    return s is not None and bool(s.items or s.by_country)


def _cover(doc) -> None:
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Cm(0)
    sec.header_distance = sec.footer_distance = Cm(0)
    sec.different_first_page_header_footer = True
    p = doc.add_paragraph()
    p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(0)
    p.add_run().add_picture(str(ASSETS / "cover_a4.png"), width=Cm(21.0), height=Cm(29.7))
    new = doc.add_section(WD_SECTION.NEW_PAGE)
    holder = doc.paragraphs[-1]._p
    sect = holder.pPr.sectPr
    ordered_insert(p._p.get_or_add_pPr(), sect, PPR_ORDER)
    holder.getparent().remove(holder)
    new.left_margin = new.right_margin = new.top_margin = new.bottom_margin = Cm(2.0)
    new.header_distance = new.footer_distance = Cm(1.0)
    new.different_first_page_header_footer = False


def _title_page(doc, data: GuideData, dest: str, toc: list[tuple[str, list[tuple[str, str]]]]) -> None:
    lp = doc.add_paragraph()
    lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    lp.add_run().add_picture(str(ASSETS / "logo.png"), width=Cm(6))
    kicker = add_eyebrow(doc, "Your All-Inclusive Guide")
    for run in kicker.runs:
        run.font.color.rgb = RGBColor.from_string(GOLD)
        run.font.italic = True
    doc.add_paragraph(data.title, style="Title")
    doc.add_paragraph(f"All Inclusive Guide – {dest}")
    add_rule(doc)
    for group, entries in toc:
        if not entries:
            continue
        add_eyebrow(doc, group)
        for text, bookmark in entries:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)
            add_internal_link(p, text, bookmark)


def render_guide(data: GuideData, settings) -> bytes:
    doc = new_document()
    dest = ", ".join(destinations(data.trip))
    _cover(doc)
    names = [n for n in data.trip.client_names if n.strip()]
    first = names[0].split()[0] if names else "Guest"
    doc.add_paragraph(f"Dear {first},")
    p = doc.add_paragraph()
    add_marker(p, Marker(kind="WRITE_LETTER", text=""))
    add_page_break(doc)

    before = [(k, t) for k, t in BEFORE_YOU_GO if _present(data, k)]
    while_ = [(k, t) for k, t in WHILE_THERE if _present(data, k)]
    toc = [("DAY BY DAY", [(day_header(d.index, d.date, d.text.title), f"day_{d.index}") for d in data.days]),
           ("BEFORE YOU GO", [(t, f"sec_{k}") for k, t in before]),
           ("WHILE YOU'RE THERE", [(t, f"sec_{k}") for k, t in while_])]
    _title_page(doc, data, dest, toc)

    for rd in data.days:
        DayRenderer(doc, data, rd, settings.walk_max_min).render()
    for key, title in before + while_:
        if key == "important":
            render_important(doc, title, f"sec_{key}", data.important)
        else:
            render_section(doc, title, f"sec_{key}", data.sections[key])
    render_thank_you(doc, dest)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
