"""DOCX assembler for AIG documents.

Reads all stored JSONs from input/days/ and input/sections/, applies AIG
named styles, and writes the final DOCX in mandatory section order.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from src.aig.styles import ensure_styles

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load(path: Path) -> dict:
    """Load a JSON file, returning {} on missing file or parse error."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        log.warning("Failed to load %s", path)
        return {}


def _is_empty(data: dict) -> bool:
    """Return True if data is {} or {"cities": []} (nothing to render)."""
    if not data:
        return True
    if list(data.keys()) == ["cities"] and not data["cities"]:
        return True
    return False


def _add(doc: Document, text: str, style: str) -> None:
    """Add a paragraph with the given AIG style."""
    doc.add_paragraph(text, style=style)


def _remove_initial_empty_paragraphs(doc: Document) -> None:
    """Remove the default empty paragraph python-docx adds to new documents."""
    for p in list(doc.paragraphs):
        if p.text.strip() == "":
            p._element.getparent().remove(p._element)
        else:
            break


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _render_cover(doc: Document, data: dict) -> None:
    title = data.get("title", "")
    subtitle = data.get("subtitle", "")
    if title:
        _add(doc, title, "AIG Title")
    if subtitle:
        _add(doc, subtitle, "AIG Subtitle")


def _render_client_info(doc: Document, data: dict) -> None:
    _add(doc, "Client Information", "AIG Section Heading")

    names = data.get("client_names") or []
    if names:
        _add(doc, "Travellers: " + ", ".join(names), "AIG Body")

    num_guests = data.get("num_guests")
    if num_guests:
        _add(doc, f"Guests: {num_guests}", "AIG Body")

    departure = data.get("departure_city")
    if departure:
        _add(doc, f"Departing from: {departure}", "AIG Body")

    dietary = data.get("dietary_preferences")
    if dietary:
        _add(doc, f"Dietary preferences: {dietary}", "AIG Body")

    trip_summary = data.get("trip_summary") or []
    if trip_summary:
        _add(doc, "Trip Summary", "AIG Subsection")
        for row in trip_summary:
            city = row.get("city", "")
            dates = row.get("dates", "")
            hotel = row.get("hotel", "")
            hotel_link = row.get("hotel_maps_link", "")
            transport = row.get("transport", "")
            line_parts = [f"{city} | {dates}"]
            if hotel:
                hotel_text = f"Hotel: {hotel}"
                if hotel_link:
                    hotel_text += f" ({hotel_link})"
                line_parts.append(hotel_text)
            if transport:
                line_parts.append(f"Transport: {transport}")
            _add(doc, " | ".join(line_parts), "AIG Detail")


def _render_day(doc: Document, data: dict) -> None:
    day_number = data.get("day_number", "?")
    date = data.get("date", "")
    title = data.get("title", "")

    heading_parts = [f"Day {day_number}"]
    if date:
        heading_parts.append(date)
    if title:
        heading_parts.append(title)
    heading = ": ".join(heading_parts[:2]) + (" — " + title if title else "")
    # Simpler: Day N: date — title
    if date and title:
        heading = f"Day {day_number}: {date} — {title}"
    elif date:
        heading = f"Day {day_number}: {date}"
    elif title:
        heading = f"Day {day_number}: {title}"
    else:
        heading = f"Day {day_number}"

    _add(doc, heading, "AIG Day Heading")

    is_cruise = data.get("is_cruise_day", False)
    if is_cruise:
        _add(doc, "At Sea — enjoy the cruise amenities and relax on board.", "AIG Body")
    else:
        activities = data.get("activities") or []
        for act in activities:
            travel_leg = act.get("travel_leg")
            if travel_leg:
                from_loc = travel_leg.get("from_location", "")
                mode = travel_leg.get("mode", "")
                duration = travel_leg.get("duration", "")
                tip = travel_leg.get("tip")
                leg_parts = []
                if from_loc:
                    leg_parts.append(f"From {from_loc}")
                if mode:
                    leg_parts.append(f"by {mode}")
                if duration:
                    leg_parts.append(f"({duration})")
                if tip:
                    leg_parts.append(f"— {tip}")
                if leg_parts:
                    _add(doc, " ".join(leg_parts), "AIG Detail")

            name = act.get("name", "")
            if name:
                _add(doc, name, "AIG Subsection")

            desc = act.get("vivid_description", "")
            if desc:
                _add(doc, desc, "AIG Body")

            hours = act.get("hours")
            entry_fee = act.get("entry_fee")
            duration_str = act.get("recommended_duration")
            maps_url = act.get("maps_url")

            if hours:
                _add(doc, f"Hours: {hours}", "AIG Detail")
            if entry_fee:
                _add(doc, f"Entry fee: {entry_fee}", "AIG Detail")
            if duration_str:
                _add(doc, f"Recommended duration: {duration_str}", "AIG Detail")
            if maps_url:
                _add(doc, f"Map: {maps_url}", "AIG Detail")

            source = act.get("source", "")
            if source == "ai_estimated":
                _add(doc, "Note: Details are AI-estimated and should be verified locally.", "AIG Note")

        # Restaurants
        lunch = data.get("lunch") or []
        if lunch:
            _add(doc, "Lunch Options", "AIG Subsection")
            for r in lunch:
                _render_restaurant(doc, r)

        dinner = data.get("dinner") or []
        if dinner:
            _add(doc, "Dinner Options", "AIG Subsection")
            for r in dinner:
                _render_restaurant(doc, r)

    transport_note = data.get("transport_note")
    if transport_note:
        _add(doc, f"Transport: {transport_note}", "AIG Detail")

    overnight_city = data.get("overnight_city", "")
    overnight_hotel = data.get("overnight_hotel", "")
    overnight_label = overnight_hotel or overnight_city
    if overnight_label:
        _add(doc, f"✅ Overnight in {overnight_label}", "AIG Overnight")


def _render_restaurant(doc: Document, r: dict) -> None:
    name = r.get("name", "")
    if name:
        _add(doc, name, "AIG Restaurant Name")
    must_try = r.get("must_try_dishes") or r.get("must_try") or []
    if must_try:
        if isinstance(must_try, list):
            _add(doc, "Must try: " + ", ".join(str(d) for d in must_try), "AIG Detail")
        else:
            _add(doc, f"Must try: {must_try}", "AIG Detail")
    hours = r.get("hours")
    if hours:
        _add(doc, f"Hours: {hours}", "AIG Detail")
    travel_note = r.get("travel_note")
    if travel_note:
        _add(doc, f"Getting there: {travel_note}", "AIG Detail")
    maps_url = r.get("maps_url")
    if maps_url:
        _add(doc, f"Map: {maps_url}", "AIG Detail")


def _render_list_section(doc: Document, heading: str, data: dict) -> None:
    """Render a 'cities' list section: heading + per-city subsections with bullet items."""
    _add(doc, heading, "AIG Section Heading")
    cities = data.get("cities") or []
    for city_block in cities:
        city_name = city_block.get("city", "")
        if city_name:
            _add(doc, city_name, "AIG Subsection")
        items = city_block.get("items") or city_block.get("dishes") or []
        for item in items:
            if isinstance(item, dict):
                label = item.get("name") or item.get("dish") or str(item)
                detail = item.get("description") or item.get("detail") or ""
                _add(doc, f"• {label}", "AIG Bullet")
                if detail:
                    _add(doc, detail, "AIG Detail")
            else:
                _add(doc, f"• {item}", "AIG Bullet")


def _render_packing_list(doc: Document, data: dict) -> None:
    """Render packing list: heading + bullet items (no city grouping)."""
    _add(doc, "Tailored Packing List", "AIG Section Heading")
    # Accept either top-level 'items' list or 'cities' grouped structure
    items = data.get("items") or []
    if not items:
        # Try cities grouping as fallback
        cities = data.get("cities") or []
        for city_block in cities:
            city_name = city_block.get("city", "")
            if city_name:
                _add(doc, city_name, "AIG Subsection")
            city_items = city_block.get("items") or []
            for item in city_items:
                if isinstance(item, dict):
                    label = item.get("name") or str(item)
                    _add(doc, f"• {label}", "AIG Bullet")
                else:
                    _add(doc, f"• {item}", "AIG Bullet")
    else:
        for item in items:
            if isinstance(item, dict):
                label = item.get("name") or str(item)
                _add(doc, f"• {label}", "AIG Bullet")
            else:
                _add(doc, f"• {item}", "AIG Bullet")


def _render_important_places(doc: Document, data: dict) -> None:
    _add(doc, "Important Places Around Your Stay", "AIG Section Heading")
    cities = data.get("cities") or []
    for city_block in cities:
        city_name = city_block.get("city", "")
        if city_name:
            _add(doc, city_name, "AIG Subsection")
        places = city_block.get("places") or city_block.get("items") or []
        for place in places:
            if isinstance(place, dict):
                name = place.get("name", "")
                desc = place.get("description") or place.get("detail") or ""
                maps_url = place.get("maps_url") or ""
                if name:
                    _add(doc, f"• {name}", "AIG Bullet")
                if desc:
                    _add(doc, desc, "AIG Detail")
                if maps_url:
                    _add(doc, f"Map: {maps_url}", "AIG Detail")
            else:
                _add(doc, f"• {place}", "AIG Bullet")


def _render_thank_you(doc: Document, data: dict) -> None:
    _add(doc, "Thank You", "AIG Section Heading")
    text = data.get("text", "")
    if text:
        _add(doc, text, "AIG Body")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assemble(input_dir: Path, output_path: Path) -> None:
    """Assemble the final AIG DOCX from stored JSON files.

    Args:
        input_dir: Directory containing days/ and sections/ subdirectories.
        output_path: Destination path for the output .docx file.
    """
    input_dir = Path(input_dir)
    days_dir = input_dir / "days"
    sections_dir = input_dir / "sections"

    doc = Document()
    ensure_styles(doc)
    _remove_initial_empty_paragraphs(doc)

    # ------------------------------------------------------------------
    # 1. Cover
    # ------------------------------------------------------------------
    cover = _load(sections_dir / "cover.json")
    if not _is_empty(cover):
        _render_cover(doc, cover)
        doc.add_page_break()

    # ------------------------------------------------------------------
    # 2. Client Information
    # ------------------------------------------------------------------
    client_info = _load(sections_dir / "client_info.json")
    if not _is_empty(client_info):
        _render_client_info(doc, client_info)
        doc.add_page_break()

    # ------------------------------------------------------------------
    # 3. Day-wise Itinerary
    # ------------------------------------------------------------------
    if days_dir.exists():
        day_files = sorted(days_dir.glob("day_*.json"))
        for day_file in day_files:
            day_data = _load(day_file)
            if day_data:
                _render_day(doc, day_data)
                doc.add_page_break()

    # ------------------------------------------------------------------
    # 4. Important Places Around Your Stay
    # ------------------------------------------------------------------
    important_places = _load(sections_dir / "important_places.json")
    if not _is_empty(important_places):
        _render_important_places(doc, important_places)
        doc.add_page_break()

    # ------------------------------------------------------------------
    # 5. Souvenir Shopping Guide
    # ------------------------------------------------------------------
    souvenir = _load(sections_dir / "souvenir_guide.json")
    if not _is_empty(souvenir):
        _render_list_section(doc, "Souvenir Shopping Guide", souvenir)
        doc.add_page_break()

    # ------------------------------------------------------------------
    # 6. Must-Try Local Dishes
    # ------------------------------------------------------------------
    must_try = _load(sections_dir / "must_try_dishes.json")
    if not _is_empty(must_try):
        _render_list_section(doc, "Must-Try Local Dishes", must_try)
        doc.add_page_break()

    # ------------------------------------------------------------------
    # 7. Getting Around
    # ------------------------------------------------------------------
    getting_around = _load(sections_dir / "getting_around.json")
    if not _is_empty(getting_around):
        _render_list_section(doc, "Getting Around", getting_around)
        doc.add_page_break()

    # ------------------------------------------------------------------
    # 8. Cultural Etiquette & Local Phrases
    # ------------------------------------------------------------------
    etiquette = _load(sections_dir / "cultural_etiquette.json")
    if not _is_empty(etiquette):
        _render_list_section(doc, "Cultural Etiquette & Local Phrases", etiquette)
        doc.add_page_break()

    # ------------------------------------------------------------------
    # 9. Packing List
    # ------------------------------------------------------------------
    packing = _load(sections_dir / "packing_list.json")
    if not _is_empty(packing):
        _render_packing_list(doc, packing)
        doc.add_page_break()

    # ------------------------------------------------------------------
    # 10. Mobile Connectivity
    # ------------------------------------------------------------------
    connectivity = _load(sections_dir / "mobile_connectivity.json")
    if not _is_empty(connectivity):
        _render_list_section(doc, "Mobile Connectivity Guide", connectivity)
        doc.add_page_break()

    # ------------------------------------------------------------------
    # 11. Safety & Emergency Contacts
    # ------------------------------------------------------------------
    safety = _load(sections_dir / "safety_contacts.json")
    if not _is_empty(safety):
        _render_list_section(doc, "Safety & Emergency Contacts", safety)
        doc.add_page_break()

    # ------------------------------------------------------------------
    # 12. Health & Vaccination Guidance
    # ------------------------------------------------------------------
    health = _load(sections_dir / "health_vaccination.json")
    if not _is_empty(health):
        _render_list_section(doc, "Health & Vaccination Guidance", health)
        doc.add_page_break()

    # ------------------------------------------------------------------
    # 13. Thank You (always last — NO page break after)
    # ------------------------------------------------------------------
    thank_you = _load(sections_dir / "thank_you.json")
    if not _is_empty(thank_you):
        _render_thank_you(doc, thank_you)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    log.info("Assembled DOCX saved to %s", output_path)
