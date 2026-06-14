"""Build enriched day content from TripFacts + library and save to JSON."""

import json
import re as _re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from src.aig.context import AIGContext
from src.common.maps import maps_url
from src.common.models import TripDay


# ── Output models ────────────────────────────────────────────────────────────

class FlightSector(BaseModel):
    label: str               # "Sector 1"
    from_terminal: str
    to_terminal: str
    departure_time: str
    arrival_time: str
    duration: Optional[str] = None


class FlightDetails(BaseModel):
    airline: str
    sectors: list[FlightSector] = Field(default_factory=list)


class TransferInstructions(BaseModel):
    intro: str = ""
    headline_tip: str = ""
    route_steps: list[str] = Field(default_factory=list)
    total_travel_time: str = ""
    cost_inr: str = ""
    settle_in_note: str = ""


class DaySection(BaseModel):
    """One time-of-day activity block."""
    section_title: str       # e.g. "🌆 Evening- Amsterdam Canals Walk (Optional)"
    place_name: Optional[str] = None
    maps_url: str = ""
    travel_info: Optional[str] = None   # "⏱️ ~25 mins train from Almere Centrum → Amsterdam Centraal"
    hours: Optional[str] = None
    cost: Optional[str] = None
    description: str = ""


class ReturnInstructions(BaseModel):
    instructions: str = ""
    travel_note: str = ""


class RestaurantCard(BaseModel):
    name: str
    maps_url: str = ""
    ambience: Optional[str] = None
    must_try_dishes: list[str] = Field(default_factory=list)
    hours: Optional[str] = None
    price_inr: Optional[str] = None     # "₹1,200-1,800 per person"
    travel_note: Optional[str] = None   # "~20 mins walk from canals"
    source: str = "library"


class DayContent(BaseModel):
    day_number: int
    date: Optional[str] = None
    title: Optional[str] = None
    overnight_city: Optional[str] = None
    overnight_hotel: Optional[str] = None
    is_cruise_day: bool = False
    transport_note: Optional[str] = None

    # Structured sections
    flight_details: Optional[FlightDetails] = None
    transfer_instructions: Optional[TransferInstructions] = None
    sections: list[DaySection] = Field(default_factory=list)
    dinner_location: Optional[str] = None   # location hint for dinner section title
    lunch: list[RestaurantCard] = Field(default_factory=list)
    dinner: list[RestaurantCard] = Field(default_factory=list)
    return_instructions: Optional[ReturnInstructions] = None


# ── Helper functions ──────────────────────────────────────────────────────────

_ARRIVAL_SKIP_KEYWORDS = ["arrival", "check-in", "check in", "hotel check"]
_MEAL_KEYWORDS = ["dinner", "lunch", "breakfast"]


def _is_cruise_day(day: TripDay) -> bool:
    if day.overnight_city is None:
        return True
    combined = " ".join([day.title or ""] + day.activities).lower()
    return "at sea" in combined


def _city_matches(leg_city: str, city: str) -> bool:
    if not leg_city or not city:
        return False
    lc = leg_city.lower()
    cc = city.lower()
    return cc in lc or lc in cc


def _filter_sectionable(activities: list[str]) -> list[str]:
    """Return activities suitable for day sections — not arrival/check-in, not meals."""
    result = []
    for act in activities:
        a = act.lower()
        if any(kw in a for kw in _ARRIVAL_SKIP_KEYWORDS):
            continue
        if any(kw in a for kw in _MEAL_KEYWORDS):
            continue
        result.append(act)
    return result


def _extract_meal_location(activities: list[str]) -> Optional[str]:
    """Extract location hint from a meal activity like 'Early dinner near canals'."""
    for act in activities:
        if any(kw in act.lower() for kw in _MEAL_KEYWORDS):
            m = _re.search(r"near\s+(.+)", act, _re.IGNORECASE)
            if m:
                return m.group(1).strip()
    return None


def _match_attraction(activity_name: str, attractions: list[dict]) -> Optional[dict]:
    """Fuzzy-match an activity string to a library attraction record."""
    name_lower = activity_name.lower()
    for attr in attractions:
        if attr.get("name", "").lower() == name_lower:
            return attr
    for attr in attractions:
        attr_name = attr.get("name", "").lower()
        if attr_name and (attr_name in name_lower or name_lower in attr_name):
            return attr
    return None


def _parse_json_list(text: str) -> list:
    """Parse a JSON array from text, stripping markdown fences if present."""
    text = text.strip()
    text = _re.sub(r"^```(?:json)?\s*", "", text)
    text = _re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    match = _re.search(r"\[.*\]", text, _re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return []


def _parse_json_dict(text: str) -> dict:
    """Parse a JSON object from text, stripping markdown fences if present."""
    text = text.strip()
    text = _re.sub(r"^```(?:json)?\s*", "", text)
    text = _re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    match = _re.search(r"\{.*\}", text, _re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    return {}


# ── Flight details ────────────────────────────────────────────────────────────

def _build_flight_details(transport_modes: list, city: str) -> Optional[FlightDetails]:
    """Extract flight sectors for legs arriving at this city on this trip."""
    last_arrival = None
    for leg in transport_modes:
        if leg.mode == "flight" and _city_matches(leg.to_city, city):
            last_arrival = leg

    if not last_arrival:
        return None

    airline = last_arrival.operator or "Unknown"
    booking_ref = last_arrival.booking_reference

    # Collect all legs in the same booking (multi-sector journeys share booking reference)
    if booking_ref:
        chain = [
            leg for leg in transport_modes
            if leg.mode == "flight" and leg.booking_reference == booking_ref
        ]
    else:
        chain = [last_arrival]

    sectors = []
    for i, leg in enumerate(chain):
        sectors.append(FlightSector(
            label=f"Sector {i + 1}",
            from_terminal=leg.from_terminal or leg.from_city,
            to_terminal=leg.to_terminal or leg.to_city,
            departure_time=leg.departure_time or "",
            arrival_time=leg.arrival_time or "",
        ))

    return FlightDetails(airline=airline, sectors=sectors)


# ── AI enrichment ─────────────────────────────────────────────────────────────

def _enrich_activities_to_sections(
    activities: list[str],
    city: str,
    hotel_name: str,
    hotel_city: str,
    start_point: str,
    lib_attractions: list[dict],
    ai_client,
) -> list[DaySection]:
    """Call AI to convert raw activity strings into structured DaySection objects."""
    if not activities:
        return []

    act_data = []
    for act in activities:
        attr = _match_attraction(act, lib_attractions)
        act_data.append({
            "name": act,
            "hours": attr["hours"] if attr else None,
            "cost": attr.get("entry_fee") if attr else None,
        })

    activities_json = json.dumps(act_data, ensure_ascii=False, indent=2)
    n = len(activities)

    prompt = (
        f"You are building day sections for travellers in {city}.\n"
        f"Hotel: {hotel_name} in {hotel_city}.\n"
        f"Starting point for first activity: {start_point}\n\n"
        "Convert each activity into a day section. For each, return:\n"
        '- "section_title": time-of-day emoji + label. Examples:\n'
        '    "🌄 Morning- Van Gogh Museum"\n'
        '    "☀️ Afternoon- Anne Frank House (Timed Entry)"\n'
        '    "🌆 Evening- Amsterdam Canals Walk (Optional)"\n'
        "  Use emojis: 🌄 Morning, ☀️ Afternoon, 🌆 Evening, 🌙 Night.\n"
        '  Add "(Optional)" for casual/optional activities.\n'
        '- "place_name": canonical venue name for Google Maps, or null\n'
        '- "travel_info": "⏱️ ~XX mins MODE from PREVIOUS_LOCATION" — specific journey\n'
        '- "hours": opening hours string, or null\n'
        '- "cost": in INR (e.g. "₹1,500 per person") or "Free" or null\n'
        '- "description": 2-3 vivid, immersive sentences about the experience\n\n'
        f"Activities (process in order, one object per activity):\n{activities_json}\n\n"
        f"Return JSON array of exactly {n} objects. No markdown fences."
    )

    raw = ai_client.complete(prompt, max_tokens=4096, temperature=0.3)
    enriched = _parse_json_list(raw)

    sections = []
    for i, act in enumerate(activities):
        e = enriched[i] if i < len(enriched) and isinstance(enriched[i], dict) else {}
        place = e.get("place_name") or None
        lib_hours = act_data[i]["hours"] if i < len(act_data) else None
        sections.append(DaySection(
            section_title=e.get("section_title") or act,
            place_name=place,
            maps_url=maps_url(place, city) if place else "",
            travel_info=e.get("travel_info"),
            hours=e.get("hours") or lib_hours,
            cost=e.get("cost"),
            description=e.get("description", ""),
        ))
    return sections


def _generate_transfer_instructions(
    arrival_terminal: str,
    city: str,
    hotel_name: str,
    hotel_city: str,
    local_transport: str,
    ai_client,
) -> Optional[TransferInstructions]:
    """Ask AI to write step-by-step transfer instructions from airport to hotel."""
    prompt = (
        f'Write hotel transfer instructions for travellers arriving at "{arrival_terminal}"\n'
        f"heading to {hotel_name} in {hotel_city}, {city}.\n"
        f"Local transport: {local_transport}\n\n"
        "Return JSON object with these exact fields:\n"
        "{\n"
        '  "intro": "1 sentence: After arriving at 📍 [terminal], make your way to your hotel in [city].",\n'
        '  "headline_tip": "bold navigation tip with → arrows, e.g. follow signs for Trains → Schiphol Plaza",\n'
        '  "route_steps": ["step 1: specific train/bus names and ticket info", "step 2: duration + frequency", "step 3: last mile bus/taxi info"],\n'
        '  "total_travel_time": "~XX-YY mins",\n'
        '  "cost_inr": "₹XXX-X,XXX per person",\n'
        '  "settle_in_note": "1 encouraging sentence to rest before exploring"\n'
        "}\n\n"
        "Use real transport names, actual durations, costs in INR. No markdown fences."
    )

    raw = ai_client.complete(prompt, max_tokens=1024, temperature=0.3)
    d = _parse_json_dict(raw)
    if not d:
        return None

    return TransferInstructions(
        intro=d.get("intro", ""),
        headline_tip=d.get("headline_tip", ""),
        route_steps=d.get("route_steps") or [],
        total_travel_time=d.get("total_travel_time", ""),
        cost_inr=d.get("cost_inr", ""),
        settle_in_note=d.get("settle_in_note", ""),
    )


def _generate_return_instructions(
    city: str,
    hotel_name: str,
    hotel_city: str,
    last_location: str,
    local_transport: str,
    ai_client,
) -> Optional[ReturnInstructions]:
    """Ask AI to write brief return-to-hotel instructions."""
    prompt = (
        f"Write brief return-to-hotel instructions for travellers in {city}\n"
        f"heading back to {hotel_name} in {hotel_city}.\n"
        f"They are currently near {last_location}.\n"
        f"Local transport: {local_transport}\n\n"
        "Return JSON object:\n"
        "{\n"
        '  "instructions": "1-2 sentences describing the return journey",\n'
        '  "travel_note": "⏱️ Travel time: ~XX-YY mins 💡 [one practical tip about frequency or convenience]"\n'
        "}\n\n"
        "No markdown fences."
    )

    raw = ai_client.complete(prompt, max_tokens=512, temperature=0.3)
    d = _parse_json_dict(raw)
    if not d:
        return None

    return ReturnInstructions(
        instructions=d.get("instructions", ""),
        travel_note=d.get("travel_note", ""),
    )


def _enrich_restaurants(
    restaurants: list[dict],
    city: str,
    location_hint: str,
    dietary: list[str],
    ai_client,
) -> list[RestaurantCard]:
    """Add ambience, INR price, and travel note to restaurant dicts via AI."""
    if not restaurants:
        return []

    rests_input = [
        {"name": r.get("name", ""), "must_try_dishes": r.get("must_try_dishes", []), "hours": r.get("hours")}
        for r in restaurants
    ]
    rests_json = json.dumps(rests_input, ensure_ascii=False, indent=2)
    n = len(restaurants)
    dietary_str = ", ".join(dietary) if dietary else "none specified"

    prompt = (
        f"Enrich these restaurant recommendations for travellers in {city}.\n"
        f"Dietary restrictions: {dietary_str}\n"
        f"Location context: {location_hint}\n\n"
        "For each restaurant, add:\n"
        '- "ambience": 1 sentence describing the vibe and setting\n'
        '- "price_inr": price range per person in INR (e.g. "₹1,200-1,800 per person")\n'
        f'- "travel_note": "~XX mins walk from {location_hint}" (estimate)\n\n'
        f"Input restaurants:\n{rests_json}\n\n"
        f"Return JSON array of exactly {n} objects with fields: name, ambience, price_inr, travel_note.\n"
        "No markdown fences."
    )

    raw = ai_client.complete(prompt, max_tokens=2048, temperature=0.3)
    enriched = _parse_json_list(raw)

    cards = []
    for i, r in enumerate(restaurants):
        e = enriched[i] if i < len(enriched) and isinstance(enriched[i], dict) else {}
        cards.append(RestaurantCard(
            name=r.get("name", ""),
            maps_url=maps_url(r.get("name", ""), city),
            ambience=e.get("ambience"),
            must_try_dishes=r.get("must_try_dishes", []),
            hours=r.get("hours"),
            price_inr=e.get("price_inr"),
            travel_note=e.get("travel_note"),
            source="library",
        ))
    return cards


# ── Restaurant selection ──────────────────────────────────────────────────────

def _select_dinner_restaurants(all_rests: list[dict], dietary: list[str]) -> list[dict]:
    """Select up to 3 suitable restaurants for dinner."""
    dietary_lower = {d.lower() for d in dietary}

    def is_allowed(r: dict) -> bool:
        if dietary_lower and not r.get("vegetarian_friendly", False):
            if "vegetarian" in dietary_lower or "vegan" in dietary_lower:
                return False
        return True

    return [r for r in all_rests if is_allowed(r)][:3]


# ── Top-level build_day ───────────────────────────────────────────────────────

def build_day(
    context: AIGContext,
    day_number: int,
    input_dir: Path,
    overrides: Optional[dict] = None,
) -> DayContent:
    """Enrich one TripDay and save to input_dir/days/day_NN.json."""
    overrides = overrides or {}
    day = next(
        (d for d in context.facts.days if d.day_number == day_number),
        context.facts.days[day_number - 1] if day_number <= len(context.facts.days) else None,
    )
    if day is None:
        raise ValueError(f"Day {day_number} not found in TripFacts")

    city = day.overnight_city or ""
    hotel = next(
        (h for h in context.facts.hotels if h.city.lower() == city.lower()),
        context.facts.hotels[0] if context.facts.hotels else None,
    )
    hotel_name = hotel.hotel_name if hotel else ""
    hotel_city = hotel.city if hotel else city
    transport = overrides.get("transport") or day.transport_note or context.facts.local_transport or "taxi"
    cruise = _is_cruise_day(day)

    if cruise:
        content = DayContent(
            day_number=day_number,
            date=day.date,
            title=day.title,
            overnight_city=city or None,
            overnight_hotel=day.overnight_hotel,
            is_cruise_day=True,
            transport_note=day.transport_note,
        )
    else:
        lib = context.library.get(city)
        attraction_list = lib.attractions if lib else []
        dietary = list(context.facts.dietary_restrictions)

        # 1. Flight details and transfer instructions (arrival days only)
        flight_details = None
        transfer_instructions = None
        arrival_terminal = None

        for leg in (context.facts.transport_modes or []):
            if leg.mode == "flight" and _city_matches(leg.to_city, city):
                flight_details = _build_flight_details(context.facts.transport_modes, city)
                arrival_terminal = leg.to_terminal or leg.to_city
                break

        if arrival_terminal:
            transfer_instructions = _generate_transfer_instructions(
                arrival_terminal=arrival_terminal,
                city=city,
                hotel_name=hotel_name,
                hotel_city=hotel_city,
                local_transport=transport,
                ai_client=context.ai_client,
            )

        # Starting point for first activity
        start_point = arrival_terminal or hotel_name

        # 2. Activity sections
        sectionable = _filter_sectionable(day.activities)
        dinner_location = _extract_meal_location(day.activities)

        sections = _enrich_activities_to_sections(
            activities=sectionable,
            city=city,
            hotel_name=hotel_name,
            hotel_city=hotel_city,
            start_point=start_point,
            lib_attractions=attraction_list,
            ai_client=context.ai_client,
        )

        # 3. Return to hotel
        last_place = sections[-1].place_name or city if sections else city
        return_instructions = _generate_return_instructions(
            city=city,
            hotel_name=hotel_name,
            hotel_city=hotel_city,
            last_location=last_place,
            local_transport=transport,
            ai_client=context.ai_client,
        )

        # 4. Dinner restaurants
        lib_rests = lib.restaurants if lib else []
        dinner_raw = _select_dinner_restaurants(lib_rests, dietary)
        dinner_cards = _enrich_restaurants(
            dinner_raw, city, dinner_location or city, dietary, context.ai_client,
        )

        content = DayContent(
            day_number=day_number,
            date=day.date,
            title=day.title,
            overnight_city=city or None,
            overnight_hotel=day.overnight_hotel,
            is_cruise_day=False,
            transport_note=day.transport_note,
            flight_details=flight_details,
            transfer_instructions=transfer_instructions,
            sections=sections,
            dinner_location=dinner_location,
            dinner=dinner_cards,
            return_instructions=return_instructions,
        )

    out_dir = input_dir / "days"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"day_{day_number:02d}.json").write_text(
        content.model_dump_json(indent=2), encoding="utf-8"
    )
    return content
