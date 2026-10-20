import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

import requests

from src.aigv2.hours import _is_24h, from_google
from src.aigv2.models import Place, WeeklyHours
from src.aigv2.store import PlaceCache

SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
SEARCH_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
FIELD_MASK = ",".join(
    f"places.{f}"
    for f in (
        "id", "displayName", "formattedAddress", "location", "businessStatus",
        "regularOpeningHours", "websiteUri", "internationalPhoneNumber", "primaryType", "types",
    )
)
_DROP_WORDS = {"restaurant", "cafe", "the"}
_EXCLUDED_NAME_WORDS = (
    "dental", "dentist", "physio", "cardio", "sexual health", "circumcision", "sports",
    "cosmetic", "aesthetic", "veterinary", "equipment", "b.v.", "ltd", "gmbh", "petroleum", "fuel",
)
_CLINIC_TYPES = ["doctor", "medical_clinic"]
_CLINIC_NOTE = "nearest clinic, not a hospital"
_HOSPITAL_RADIUS_KM = 10
_NEAR_KM = 25
_MIN_OVERLAP = 0.6
_WEAK_COVERAGE = {
    "south korea", "korea", "seoul", "busan", "jeju", "incheon", "daegu", "gyeongju",
    "china", "beijing", "shanghai", "guangzhou", "shenzhen", "chengdu", "xian", "xi'an",
    "hangzhou", "guilin", "hong kong mainland",
}


def weak_coverage(country_or_city: str) -> bool:
    return _fold(country_or_city).strip() in _WEAK_COVERAGE


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def _tokens(name: str) -> set[str]:
    words = re.findall(r"\w+", _fold(name).replace("'", "").replace("’", ""))
    return {w for w in words if w not in _DROP_WORDS}


def _overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _is_24h_week(hours: Optional[WeeklyHours]) -> bool:
    return hours is not None and len(hours.periods) == 7 and all(_is_24h(p) for p in hours.periods.values())


class PlacesClient:
    def __init__(self, api_key: str, cache: PlaceCache, session: Optional[requests.Session] = None):
        self.api_key = api_key
        self.cache = cache
        self.session = session or requests.Session()
        self.calls: dict[str, int] = {"text_search": 0, "nearby": 0}
        self.verify_notes: dict[str, str] = {}

    def _post(self, url: str, body: dict, counter: str) -> dict:
        self.calls[counter] += 1
        resp = self.session.post(
            url,
            headers={
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": FIELD_MASK,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def find(self, name: str, city: str, near: Optional[tuple[float, float]] = None, fresh: bool = False) -> Optional[Place]:
        key = f"{name}|{city}"
        if not fresh:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        body: dict = {"textQuery": f"{name}, {city}"}
        if near:
            body["locationBias"] = {
                "circle": {"center": {"latitude": near[0], "longitude": near[1]}, "radius": 20000.0}
            }
        raw = self._post(SEARCH_TEXT_URL, body, "text_search").get("places") or []
        if not raw:
            return None
        scored = [(self._match_ok(name, city, near, r), _overlap(name, _display(r)), r) for r in raw]
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        ok, _, best = scored[0]
        place = self._to_place(best, key, f"{name} {city}", ok)
        self.cache.put(key, place)
        return place

    def nearby(self, lat: float, lng: float, types: list[str], radius_m: int, max_results: int) -> list[Place]:
        places = self._nearby_once(lat, lng, types, radius_m, max_results)
        if "hospital" in types:
            places = self._emergency_hospitals(places)
            if not any(_haversine_km(lat, lng, p.lat, p.lng) <= _HOSPITAL_RADIUS_KM for p in places):
                places = self._nearby_once(lat, lng, _CLINIC_TYPES, radius_m, max_results)
                for p in places:
                    self.verify_notes[p.place_id] = _CLINIC_NOTE
        return places

    def _nearby_once(self, lat: float, lng: float, types: list[str], radius_m: int, max_results: int) -> list[Place]:
        body = {
            "includedTypes": types,
            "maxResultCount": max_results,
            "rankPreference": "DISTANCE",
            "locationRestriction": {
                "circle": {"center": {"latitude": lat, "longitude": lng}, "radius": float(radius_m)}
            },
        }
        raw = self._post(SEARCH_NEARBY_URL, body, "nearby").get("places") or []
        wanted = set(types)
        out = []
        for r in raw:
            name = _display(r).casefold()
            if r.get("primaryType") not in wanted or any(w in name for w in _EXCLUDED_NAME_WORDS):
                continue
            out.append(self._to_place(r, f"nearby:{','.join(types)}", _display(r), True))
        return out

    @staticmethod
    def _emergency_hospitals(places: list[Place]) -> list[Place]:
        def emergency(p: Place) -> bool:
            return "emergency" in p.name.casefold() or _is_24h_week(p.hours)

        kept = [p for p in places if p.hours is None or emergency(p)]
        return sorted(kept, key=lambda p: not ("emergency" in p.name.casefold()))

    @staticmethod
    def _match_ok(name: str, city: str, near: Optional[tuple[float, float]], raw: dict) -> bool:
        if _overlap(name, _display(raw)) < _MIN_OVERLAP:
            return False
        if _fold(city) in _fold(raw.get("formattedAddress", "")):
            return True
        loc = raw.get("location")
        if near and loc:
            return _haversine_km(near[0], near[1], loc["latitude"], loc["longitude"]) <= _NEAR_KM
        return False

    @staticmethod
    def _to_place(raw: dict, query: str, link_text: str, match_ok: bool) -> Place:
        hours = None
        if raw.get("regularOpeningHours"):
            try:
                hours = from_google(raw["regularOpeningHours"])
            except ValueError:
                hours = None
        pid = raw.get("id", "")
        url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(link_text)}"
        if pid:
            url += f"&query_place_id={pid}"
        return Place(
            query=query,
            place_id=pid,
            name=_display(raw),
            address=raw.get("formattedAddress", ""),
            lat=raw["location"]["latitude"],
            lng=raw["location"]["longitude"],
            status=raw.get("businessStatus") or "UNKNOWN",
            hours=hours,
            website=raw.get("websiteUri"),
            phone=raw.get("internationalPhoneNumber"),
            maps_url=url,
            fetched_at=datetime.now(timezone.utc),
            match_ok=match_ok,
        )


def _display(raw: dict) -> str:
    return (raw.get("displayName") or {}).get("text", "")
