"""AIG prep: generate library context and client profile companion documents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Country lookup: aig-library folder name → clean country/region label
# ---------------------------------------------------------------------------

FOLDER_TO_COUNTRY: dict[str, str] = {
    "Africa": "Africa",
    "Almaty Kazakhstan": "Kazakhstan",
    "Andamans": "India",
    "Australia": "Australia",
    "Austria": "Austria",
    "Azerbaijan and Georgia": "Azerbaijan / Georgia",
    "Bali Indonesia": "Indonesia",
    "Belgium": "Belgium",
    "Bhutan": "Bhutan",
    "China": "China",
    "Dubai and Abu Dhabi - UAE": "UAE",
    "England and Scotland": "United Kingdom",
    "France": "France",
    "French Polynesia": "French Polynesia",
    "Germany": "Germany",
    "Goa": "India",
    "Greece and Turkey": "Greece / Turkey",
    "Italy": "Italy",
    "Japan": "Japan",
    "Karnataka, Kerala and Tamil Nadu": "India",
    "Maldives": "Maldives",
    "Mauritius": "Mauritius",
    "Netherlands": "Netherlands",
    "North India": "India",
    "Northeast India": "India",
    "Philippines": "Philippines",
    "Qatar": "Qatar",
    "Rajasthan": "India",
    "Singapore and Malaysia": "Singapore / Malaysia",
    "South America": "South America",
    "South Korea": "South Korea",
    "Spain": "Spain",
    "Srilanka": "Sri Lanka",
    "Switzerland": "Switzerland",
    "Thailand": "Thailand",
    "USA": "USA",
    "Vietnam": "Vietnam",
}

# Sections from library JSON to include (order determines output order).
# Attractions and hotels are excluded per spec.
_LIBRARY_SECTIONS = [
    ("restaurants",        "Curated Restaurants"),
    ("local_dishes",       "Must-Try Local Dishes"),
    ("souvenirs",          "Souvenir Shopping"),
    ("transport_options",  "Getting Around"),
    ("safety_tips",        "Safety Tips"),
    ("connectivity_tips",  "Mobile Connectivity"),
    ("emergency_contacts", "Emergency Contacts"),
    ("health_tips",        "Health & Vaccination"),
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PrepContext:
    client_name: str
    destination_label: str    # e.g. "London" or "Lima, Cusco, Sacred Valley"
    cities: list[str]
    date_range: str           # e.g. "28 Jun 2026 – 4 Jul 2026" or ""
    hotels: dict[str, str]    # city → hotel name
    dietary_notes: str        # joined string, e.g. "vegetarian, chicken, seafood"
    transport_mode: str       # e.g. "Public Transport" or ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_iso_date(iso: Optional[str]) -> str:
    """Convert 'YYYY-MM-DD' to '28 Jun 2026', or return '' on failure."""
    if not iso:
        return ""
    try:
        from datetime import date
        d = date.fromisoformat(iso)
        return d.strftime("%-d %b %Y")
    except (ValueError, TypeError):
        return iso  # return as-is if unparseable


def _join_diet(restrictions: list[str], allergies: list[str], preferences: list[str]) -> str:
    combined = [x for x in restrictions + allergies + preferences if x]
    return ", ".join(combined)


def _build_prep_context_from_trip_facts(data: dict) -> PrepContext:
    """Build PrepContext from a trip_facts.json dict (TripFacts schema)."""
    client_names: list[str] = data.get("client_names") or []
    client_name = client_names[0] if client_names else ""

    cities: list[str] = data.get("destinations") or []
    destination_label = ", ".join(cities) if cities else ""

    start = _format_iso_date(data.get("trip_start_date"))
    end = _format_iso_date(data.get("trip_end_date"))
    date_range = f"{start} – {end}" if start and end else start or end

    hotels: dict[str, str] = {}
    for h in data.get("hotels") or []:
        city = h.get("city") or ""
        name = h.get("hotel_name") or ""
        if city and name:
            hotels[city] = name

    transport_mode = data.get("local_transport") or ""

    dietary_notes = _join_diet(
        data.get("dietary_restrictions") or [],
        data.get("food_allergies") or [],
        data.get("cuisine_preferences") or [],
    )

    return PrepContext(
        client_name=client_name,
        destination_label=destination_label,
        cities=cities,
        date_range=date_range,
        hotels=hotels,
        dietary_notes=dietary_notes,
        transport_mode=transport_mode,
    )


def _build_prep_context_from_itinerary_data(itinerary) -> PrepContext:
    """Build PrepContext from an ItineraryData object (single-file parser output)."""
    client_name = getattr(itinerary, "client_name", None) or ""

    cities: list[str] = list(getattr(itinerary, "destinations", None) or [])
    if not cities:
        dest = getattr(itinerary, "destination", None)
        if dest and dest != "Unknown":
            cities = [dest]
    destination_label = ", ".join(cities)

    start = _format_iso_date(getattr(itinerary, "trip_start_date", None))
    end = _format_iso_date(getattr(itinerary, "trip_end_date", None))
    date_range = f"{start} – {end}" if start and end else start or end

    hotels: dict[str, str] = {}
    for stay in getattr(itinerary, "hotel_stays", None) or []:
        city = getattr(stay, "city", None) or ""
        name = getattr(stay, "hotel_name", None) or ""
        if city and name:
            hotels[city] = name
    if not hotels:
        hotel_name = getattr(itinerary, "hotel_name", None)
        if hotel_name and cities:
            hotels[cities[0]] = hotel_name

    transport_mode = getattr(itinerary, "transport_mode", None) or ""

    dietary_notes = _join_diet(
        list(getattr(itinerary, "dietary_preferences", None) or []),
        list(getattr(itinerary, "food_allergies", None) or []),
        list(getattr(itinerary, "cuisine_preferences", None) or []),
    )

    return PrepContext(
        client_name=client_name,
        destination_label=destination_label,
        cities=cities,
        date_range=date_range,
        hotels=hotels,
        dietary_notes=dietary_notes,
        transport_mode=transport_mode,
    )


def extract_trip_context(input_path: Path, ai_client=None) -> PrepContext:
    """Extract trip context from a DOCX input file or its sibling trip_facts.json.

    If trip_facts.json exists in the same directory as input_path, it is
    loaded and used directly (no AI call needed).  Otherwise the DOCX is
    parsed with parse_itinerary (AI-assisted when ai_client is provided,
    regex-only otherwise).
    """
    facts_path = input_path.parent / "trip_facts.json"
    if facts_path.exists():
        data = json.loads(facts_path.read_text(encoding="utf-8"))
        return _build_prep_context_from_trip_facts(data)

    from .parser import parse_itinerary
    itinerary = parse_itinerary(input_path, ai_client=ai_client)
    return _build_prep_context_from_itinerary_data(itinerary)


# ---------------------------------------------------------------------------
# City → country lookup
# ---------------------------------------------------------------------------

def _city_to_country(city: str, db_path: Path) -> str:
    """Return a country/region label for city using _index.json folder coverage."""
    index_path = db_path / "_index.json"
    if not index_path.exists():
        return ""
    index = json.loads(index_path.read_text(encoding="utf-8"))
    folder_coverage: dict[str, list[str]] = index.get("_folder_coverage", {})
    for folder, cities in folder_coverage.items():
        if city in cities:
            return FOLDER_TO_COUNTRY.get(folder, folder)
    return ""


# ---------------------------------------------------------------------------
# Library section renderers
# ---------------------------------------------------------------------------

def _render_restaurants(items: list[dict]) -> str:
    if not items:
        return ""
    lines = [
        "### Curated Restaurants",
        "*Use these in Day-wise Itinerary restaurant recommendations.*\n",
        "| Name | Cuisine | Area | Hours | Veg-friendly | Must-Try Dishes |",
        "|------|---------|------|-------|:------------:|-----------------|",
    ]
    for r in items:
        name = r.get("name", "")
        cuisine = ", ".join(r.get("cuisine_type") or [])
        area = r.get("area", "")
        hours = r.get("hours", "")
        veg = "Yes" if r.get("vegetarian_friendly") else "No"
        must_try = ", ".join(r.get("must_try_dishes") or [])
        lines.append(f"| {name} | {cuisine} | {area} | {hours} | {veg} | {must_try} |")
    return "\n".join(lines)


def _render_local_dishes(items: list[dict]) -> str:
    if not items:
        return ""
    lines = [
        "### Must-Try Local Dishes",
        "*Use in the \"Must-Try Local Dishes\" section.*\n",
    ]
    for d in items:
        name = d.get("name", "")
        desc = d.get("description", "")
        where = d.get("where_to_try", "")
        where_str = f" Best at: {where}." if where else ""
        lines.append(f"- **{name}** — {desc}{where_str}")
    return "\n".join(lines)


def _render_souvenirs(items: list[dict]) -> str:
    if not items:
        return ""
    lines = [
        "### Souvenir Shopping",
        "*Use in the \"Souvenir Shopping Guide\" section.*\n",
    ]
    for s in items:
        item = s.get("item", "")
        where = ", ".join(s.get("where_to_buy") or [])
        where_str = f" — Where to buy: {where}" if where else ""
        lines.append(f"- **{item}**{where_str}")
    return "\n".join(lines)


def _render_transport(items: list[dict]) -> str:
    if not items:
        return ""
    lines = [
        "### Getting Around",
        "*Use in the \"Getting Around\" section.*\n",
    ]
    for t in items:
        mode = t.get("mode", "") or t.get("type", "")
        desc = t.get("description", "")
        cost = t.get("cost", "")
        cost_str = f" Cost: {cost}" if cost else ""
        lines.append(f"- **{mode}** — {desc}{cost_str}")
    return "\n".join(lines)


def _render_safety(items: list[dict]) -> str:
    if not items:
        return ""
    lines = [
        "### Safety Tips",
        "*Use in the \"Safety & Emergency Contacts\" section.*\n",
    ]
    for t in items:
        tip = t.get("tip", "") or t.get("description", "")
        if tip:
            lines.append(f"- {tip}")
    return "\n".join(lines)


def _render_connectivity(items: list[dict]) -> str:
    if not items:
        return ""
    lines = [
        "### Mobile Connectivity",
        "*Use in the \"Mobile Connectivity Guide\" section.*\n",
    ]
    for t in items:
        tip = t.get("tip", "") or t.get("description", "")
        if tip:
            lines.append(f"- {tip}")
    return "\n".join(lines)


def _render_emergency(items: list[dict]) -> str:
    if not items:
        return ""
    lines = [
        "### Emergency Contacts",
        "*Use in the \"Safety & Emergency Contacts\" section.*\n",
    ]
    for c in items:
        service = c.get("service", "")
        number = c.get("number", "") or c.get("contact", "")
        lines.append(f"- {service}: {number}")
    return "\n".join(lines)


def _render_health(items: list[dict]) -> str:
    if not items:
        return ""
    lines = [
        "### Health & Vaccination",
        "*Use in the \"Health & Vaccination Guidance\" section.*\n",
    ]
    for t in items:
        tip = t.get("tip", "") or t.get("description", "") or t.get("advice", "")
        if tip:
            lines.append(f"- {tip}")
    return "\n".join(lines)


_SECTION_RENDERERS = {
    "restaurants":        _render_restaurants,
    "local_dishes":       _render_local_dishes,
    "souvenirs":          _render_souvenirs,
    "transport_options":  _render_transport,
    "safety_tips":        _render_safety,
    "connectivity_tips":  _render_connectivity,
    "emergency_contacts": _render_emergency,
    "health_tips":        _render_health,
}


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def _render_city_block(city: str, db_path: Path) -> str:
    """Render the full markdown block for one city."""
    country = _city_to_country(city, db_path)
    heading = f"## {city}, {country}" if country else f"## {city}"

    city_file = db_path / f"{city}.json"
    if not city_file.exists():
        return (
            f"{heading}\n\n"
            f"*No BVM library data available for {city} — "
            f"ChatGPT will use general knowledge.*"
        )

    data: dict = json.loads(city_file.read_text(encoding="utf-8"))
    sections: list[str] = [heading]

    for key, _label in _LIBRARY_SECTIONS:
        items = data.get(key) or []
        renderer = _SECTION_RENDERERS.get(key)
        if renderer:
            rendered = renderer(items)
            if rendered:
                sections.append(rendered)

    return "\n\n".join(sections)


def generate_library_context(prep_context: PrepContext, db_path: Path) -> str:
    """Generate the BVM Library Context markdown document."""
    parts = [
        f"# BVM Library Context: {prep_context.destination_label}",
        (
            "> **Instructions for ChatGPT:** The sections below contain BVM's curated\n"
            "> recommendations for this trip. Prioritise these restaurants, dishes, and\n"
            "> facts when generating the guide. Use your own knowledge only to fill gaps\n"
            "> where BVM data is absent or insufficient (fewer than 3 restaurants for a\n"
            "> meal slot, missing a section entirely, etc.)."
        ),
    ]
    for city in prep_context.cities:
        parts.append("---")
        parts.append(_render_city_block(city, db_path))

    return "\n\n".join(parts) + "\n"


def generate_client_profile(prep_context: PrepContext) -> str:
    """Generate the client profile markdown template."""
    ctx = prep_context

    client_line = ctx.client_name if ctx.client_name else "[fill in: client name]"
    title = f"# Client Profile: {client_line} — {ctx.destination_label}"

    destinations_line = ctx.destination_label or "[fill in: destination(s)]"
    dates_line = ctx.date_range if ctx.date_range else "[fill in: travel dates]"

    hotel_lines: list[str] = []
    if ctx.hotels:
        for city, hotel in ctx.hotels.items():
            hotel_lines.append(f"  - {city}: {hotel}")
    else:
        hotel_lines.append("  - [fill in: city: hotel name]")

    diet_line = (
        f"{ctx.dietary_notes} *(extracted from input)*"
        if ctx.dietary_notes
        else "[fill in: e.g. vegetarian / halal / no restrictions]"
    )

    transport_line = (
        f"{ctx.transport_mode} *(noted in input)*"
        if ctx.transport_mode
        else "[fill in: e.g. Public Transport / Taxi / Private car]"
    )

    hotels_block = "\n".join(hotel_lines)

    return f"""{title}

> **Instructions for ChatGPT:** Use this profile to personalise the guide.
> Fields marked [fill in] were not found in the input file — please complete
> these before sending to ChatGPT.

## Trip Details
- **Client Name:** {client_line}
- **Destination(s):** {destinations_line}
- **Travel Dates:** {dates_line}
- **Hotels:**
{hotels_block}

## Dietary Preferences
- **Restrictions / Preferences:** {diet_line}

## Travel Profile
- **Travel Style:** [fill in: budget / mid-range / luxury]
- **Occasion:** [fill in: leisure / honeymoon / anniversary / family / business / other]
- **Group Composition:** [fill in: solo / couple / family with kids / group of friends / other]
- **Transport Mode:** {transport_line}

## Special Requirements
- [fill in: any specific requests, accessibility needs, must-see places, etc.]

---
*Generated automatically from input file. Review and complete [fill in] fields before sending to ChatGPT.*
"""


def _filename_base(prep_context: PrepContext) -> str:
    """Derive a safe filename base from the context, e.g. 'Bhushan_London'."""
    name_part = prep_context.client_name.replace(" ", "_") if prep_context.client_name else "client"
    dest_part = prep_context.cities[0].replace(" ", "_") if prep_context.cities else "trip"
    return f"{name_part}_{dest_part}"


def run_prep(
    input_path: Path,
    db_path: Path,
    output_dir: Optional[Path] = None,
    ai_client=None,
) -> tuple[Path, Path]:
    """Orchestrate prep: extract context, generate docs, write files.

    Returns (library_context_path, client_profile_path).
    """
    ctx = extract_trip_context(input_path, ai_client=ai_client)

    library_md = generate_library_context(ctx, db_path)
    profile_md = generate_client_profile(ctx)

    out_dir = output_dir if output_dir is not None else input_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    base = _filename_base(ctx)
    context_path = out_dir / f"{base}_library_context.md"
    profile_path = out_dir / f"{base}_client_profile.md"

    context_path.write_text(library_md, encoding="utf-8")
    profile_path.write_text(profile_md, encoding="utf-8")

    return context_path, profile_path
