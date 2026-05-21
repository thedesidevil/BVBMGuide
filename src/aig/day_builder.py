"""Build enriched day content from TripFacts + library and save to JSON."""

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
    return "at sea" in combined or "cruise" in combined


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
