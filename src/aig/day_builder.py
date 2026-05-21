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

class TravelLeg(BaseModel):
    from_location: str
    mode: str
    duration: str
    tip: Optional[str] = None


class EnrichedActivity(BaseModel):
    name: str
    vivid_description: str = ""
    hours: Optional[str] = None
    entry_fee: Optional[str] = None
    recommended_duration: Optional[str] = None
    source: str = "ai_estimated"          # "library" or "ai_estimated"
    maps_url: str = ""
    travel_leg: Optional[TravelLeg] = None


class RestaurantCard(BaseModel):
    name: str
    maps_url: str
    ambience: Optional[str] = None
    must_try_dishes: list[str] = Field(default_factory=list)
    hours: Optional[str] = None
    price_range: Optional[str] = None
    travel_note: Optional[str] = None     # "near Duomo" or "5 min from hotel"
    source: str = "library"               # "library" or "ai_curated"


class DayContent(BaseModel):
    day_number: int
    date: Optional[str] = None
    title: Optional[str] = None
    overnight_city: Optional[str] = None
    overnight_hotel: Optional[str] = None
    activities: list[EnrichedActivity] = Field(default_factory=list)
    lunch: list[RestaurantCard] = Field(default_factory=list)
    dinner: list[RestaurantCard] = Field(default_factory=list)
    is_cruise_day: bool = False
    transport_note: Optional[str] = None


# ── Helper functions ──────────────────────────────────────────────────────────

_RESET_KEYWORDS = [
    "return to hotel", "back to hotel", "rest", "freshen up", "nap",
    "hotel break", "check in", "check-in",
]


def _is_cruise_day(day: TripDay) -> bool:
    if day.overnight_city is None:
        return True
    combined = " ".join([day.title or ""] + day.activities).lower()
    return "at sea" in combined


def _compute_chain(activities: list[str], hotel_name: str) -> list[str]:
    """Return from_location for each activity in order.

    Starts from hotel; resets to hotel after any activity that signals
    a return (rest, freshen up, etc.).
    """
    chain: list[str] = []
    current = hotel_name
    for activity in activities:
        chain.append(current)
        if any(kw in activity.lower() for kw in _RESET_KEYWORDS):
            current = hotel_name
        else:
            current = activity
    return chain


def _find_arrival_terminal(transport_modes: list, city: str) -> Optional[str]:
    """Return the arrival terminal for any transport leg arriving in this city."""
    city_lower = city.lower()
    for leg in transport_modes:
        to_city = getattr(leg, "to_city", "") or ""
        if to_city.lower() == city_lower:
            terminal = getattr(leg, "to_terminal", "") or ""
            if terminal:
                return terminal
    return None


def _match_attraction(activity_name: str, attractions: list[dict]) -> Optional[dict]:
    """Fuzzy-match an activity string to a library attraction record."""
    name_lower = activity_name.lower()
    # Exact match first
    for attr in attractions:
        if attr.get("name", "").lower() == name_lower:
            return attr
    # Substring: attraction name appears in activity string or vice versa
    for attr in attractions:
        attr_name = attr.get("name", "").lower()
        if attr_name and (attr_name in name_lower or name_lower in attr_name):
            return attr
    return None


# ── AI enrichment ─────────────────────────────────────────────────────────────

_ENRICHMENT_PROMPT = """\
You are enriching a travel day for {client_names} in {city}.
Default transport mode: {local_transport}

For each activity below, provide:
- "vivid_description": 2–3 vivid, immersive, sensory sentences. Be specific, not generic.
- "place_name": the canonical name of the specific place or attraction (e.g. "Dam Square" for \
"Relaxed walk around Dam Square & canals", "Anne Frank House" for "Visit Anne Frank House"). \
Use null if this is not a specific visitable place (e.g. "Arrival and hotel check-in", \
"Return to hotel", "Early dinner near canals").
- "travel_leg": how to travel TO this activity from the given from_location:
  - "mode": most practical transport. Use "walk" for distances under ~500m regardless of default.
  - "duration": estimated time e.g. "~20 min"
  - "tip": one practical tip (platform, app, route), or null

Activities (process in EXACTLY this order, never reorder):
{activities_json}

Return a JSON array of exactly {n} objects IN THE SAME ORDER AS THE INPUT.
No markdown fences. No explanation."""


def _enrich_activities_with_ai(
    activities: list[dict],
    city: str,
    local_transport: str,
    ai_client,
) -> list[dict]:
    """Call AI to add vivid_description and travel_leg to each activity dict."""
    client_names = "travellers"
    prompt = _ENRICHMENT_PROMPT.format(
        client_names=client_names,
        city=city,
        local_transport=local_transport,
        activities_json=json.dumps(activities, ensure_ascii=False, indent=2),
        n=len(activities),
    )
    raw = ai_client.complete(prompt, max_tokens=4096, temperature=0.3)
    enriched = _parse_json_list(raw)
    if not enriched or len(enriched) != len(activities):
        return activities  # fallback: return unenriched
    # Use positional indexing — AI is instructed to return items in input order,
    # so index i in enriched corresponds to index i in activities.
    # This also correctly handles duplicate activity names.
    result = []
    for i, original in enumerate(activities):
        merged = dict(original)
        if i < len(enriched):
            enriched_item = enriched[i]
            merged["vivid_description"] = enriched_item.get("vivid_description", "")
            travel_leg = enriched_item.get("travel_leg")
            if travel_leg and isinstance(travel_leg, dict) and "from_location" not in travel_leg:
                travel_leg["from_location"] = original.get("from_location", "")
            merged["travel_leg"] = travel_leg
            place_name = enriched_item.get("place_name")
            merged["maps_url"] = maps_url(place_name, city) if place_name else ""
        result.append(merged)
    return result


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


# ── Restaurant selection ──────────────────────────────────────────────────────

def _select_restaurants(
    city: str,
    context: AIGContext,
    morning_activities: list[str],
    day_number: int,
    used_restaurants: dict[str, list[int]],
) -> tuple[list[RestaurantCard], list[RestaurantCard]]:
    """Return (lunch_cards, dinner_cards) — max 3 each."""
    lib = context.library.get(city)
    all_rests = lib.restaurants if lib else []
    dietary = set(r.lower() for r in context.facts.dietary_restrictions)

    def is_allowed(r: dict) -> bool:
        if dietary and not r.get("vegetarian_friendly", False):
            if "vegetarian" in dietary or "vegan" in dietary:
                return False
        return True

    def rotation_ok(name: str) -> bool:
        recent = [d for d in used_restaurants.get(name, []) if day_number - d <= 2]
        return len(recent) < 2

    def to_card(r: dict, note: str) -> RestaurantCard:
        return RestaurantCard(
            name=r["name"],
            maps_url=maps_url(r["name"], city),
            must_try_dishes=r.get("must_try_dishes", []),
            hours=r.get("hours"),
            travel_note=note,
            source="library",
        )

    # Lunch: prefer restaurants near morning attractions
    morning_lower = [a.lower() for a in morning_activities]
    lunch_pool = [
        r for r in all_rests
        if is_allowed(r) and rotation_ok(r["name"])
        and any(
            lm.lower() in act or act in lm.lower()
            for lm in r.get("nearby_landmarks", [])
            for act in morning_lower
        )
    ]
    if len(lunch_pool) < 3:
        extras = [r for r in all_rests if is_allowed(r) and rotation_ok(r["name"])
                  and r not in lunch_pool]
        lunch_pool += extras

    lunch_cards = [to_card(r, f"near {r.get('area', city)}") for r in lunch_pool[:3]]

    # Dinner: prefer restaurants near hotel (no specific landmark required)
    hotel_name = ""
    for h in context.facts.hotels:
        if h.city.lower() == city.lower():
            hotel_name = h.hotel_name
            break
    used_lunch_names = {r["name"] for r in lunch_pool[:3]}
    dinner_pool = [
        r for r in all_rests
        if is_allowed(r) and rotation_ok(r["name"])
        and r["name"] not in used_lunch_names
    ]
    dinner_cards = [to_card(r, f"near {hotel_name or city}") for r in dinner_pool[:3]]

    return lunch_cards, dinner_cards


def _load_used_restaurants(input_dir: Path) -> dict[str, list[int]]:
    """Scan existing day JSONs to build a map of {restaurant_name: [day_numbers]}."""
    used: dict[str, list[int]] = {}
    days_dir = input_dir / "days"
    if not days_dir.exists():
        return used
    for f in sorted(days_dir.glob("day_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            day_num = data.get("day_number", 0)
            for meal in (data.get("lunch", []) + data.get("dinner", [])):
                name = meal.get("name", "")
                if name:
                    used.setdefault(name, []).append(day_num)
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            pass
    return used


# ── Top-level build_day ───────────────────────────────────────────────────────

def build_day(
    context: AIGContext,
    day_number: int,
    input_dir: Path,
    overrides: Optional[dict] = None,
) -> DayContent:
    """Enrich one TripDay and save to input_dir/days/day_NN.json."""
    overrides = overrides or {}
    # Look up by day_number field; fall back to positional index for backwards compat
    day = next(
        (d for d in context.facts.days if d.day_number == day_number),
        context.facts.days[day_number - 1] if day_number <= len(context.facts.days) else None,
    )
    if day is None:
        raise ValueError(f"Day {day_number} not found in TripFacts")
    city = day.overnight_city or ""
    hotel_name = next(
        (h.hotel_name for h in context.facts.hotels if h.city.lower() == city.lower()),
        context.facts.hotels[0].hotel_name if context.facts.hotels else "",
    )
    transport = overrides.get("transport") or day.transport_note or context.facts.local_transport or "taxi"
    cruise = _is_cruise_day(day)

    # Build activity list with from_location chain
    chain = _compute_chain(day.activities, hotel_name)
    # For arrival days, override the chain start with the arrival terminal
    if chain and context.facts.transport_modes:
        arrival = _find_arrival_terminal(context.facts.transport_modes, city)
        if arrival:
            chain[0] = arrival
    lib = context.library.get(city)
    attraction_list = lib.attractions if lib else []

    activity_dicts = []
    for activity, from_loc in zip(day.activities, chain):
        attr = _match_attraction(activity, attraction_list)
        d: dict = {
            "name": activity,
            "from_location": from_loc,
            "hours": attr["hours"] if attr else None,
            "entry_fee": attr.get("entry_fee") if attr else None,
            "recommended_duration": attr.get("recommended_duration") if attr else None,
            "source": "library" if attr else "ai_estimated",
            "maps_url": maps_url(attr["name"], city) if attr else "",
        }
        activity_dicts.append(d)

    # AI enrichment (skip for cruise days)
    if not cruise:
        enriched_dicts = _enrich_activities_with_ai(
            activity_dicts, city, transport, context.ai_client
        )
    else:
        enriched_dicts = activity_dicts

    activities = [
        EnrichedActivity(
            name=d["name"],
            vivid_description=d.get("vivid_description", ""),
            hours=d.get("hours"),
            entry_fee=d.get("entry_fee"),
            recommended_duration=d.get("recommended_duration"),
            source=d.get("source", "ai_estimated"),
            maps_url=d.get("maps_url", ""),
            travel_leg=TravelLeg(**d["travel_leg"]) if d.get("travel_leg") else None,
        )
        for d in enriched_dicts
    ]

    # Restaurants
    if cruise:
        lunch_cards, dinner_cards = [], []
    else:
        morning_acts = [a["name"] for a in activity_dicts[:len(activity_dicts) // 2 + 1]]
        used = _load_used_restaurants(input_dir)
        lunch_cards, dinner_cards = _select_restaurants(
            city, context, morning_acts, day_number, used
        )

    content = DayContent(
        day_number=day_number,
        date=day.date,
        title=day.title,
        overnight_city=city or None,
        overnight_hotel=day.overnight_hotel,
        activities=activities,
        lunch=lunch_cards,
        dinner=dinner_cards,
        is_cruise_day=cruise,
        transport_note=day.transport_note,
    )

    out_dir = input_dir / "days"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"day_{day_number:02d}.json").write_text(
        content.model_dump_json(indent=2), encoding="utf-8"
    )
    return content
