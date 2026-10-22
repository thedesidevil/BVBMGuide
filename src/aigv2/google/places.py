import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import requests

from src.aigv2.hours import from_google, is_24h
from src.aigv2.models import Place, WeeklyHours
from src.aigv2.store import PlaceCache

SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
SEARCH_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
DETAILS_URL = "https://places.googleapis.com/v1/places/{}"
DETAILS_FIELD_MASK = "businessStatus,regularOpeningHours"
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


_WEAK_NOTE = "Google coverage is limited here — verify details"
_UNKNOWN_HOURS_NOTE = "check this hospital has 24-hour emergency care"


def weak_coverage(country_or_city: str) -> bool:
    parts = [_fold(p).strip() for p in country_or_city.split(",")]
    return any(p in _WEAK_COVERAGE for p in parts)


def _add_note(place: Place, note: str) -> None:
    place.verify_note = f"{place.verify_note}; {note}" if place.verify_note else note


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


def strip_tracking(url: Optional[str]) -> Optional[str]:
    if not url:
        return url
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    query = [(k, v) for k, v in pairs if not k.casefold().startswith("utm_")]
    return url if len(query) == len(pairs) else urlunsplit(parts._replace(query=urlencode(query)))


def _hours(raw: dict) -> Optional[WeeklyHours]:
    if not raw.get("regularOpeningHours"):
        return None
    try:
        return from_google(raw["regularOpeningHours"])
    except ValueError:
        return None


def _is_24h_week(hours: Optional[WeeklyHours]) -> bool:
    return hours is not None and len(hours.periods) == 7 and all(is_24h(p) for p in hours.periods.values())


class PlacesClient:
    def __init__(self, api_key: str, cache: PlaceCache, session: Optional[requests.Session] = None):
        self.api_key = api_key
        self.cache = cache
        self.session = session or requests.Session()
        self.calls: dict[str, int] = {"text_search": 0, "nearby": 0, "details": 0}

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

    def fresh_status(self, place: Place) -> Optional[Place]:
        """Re-fetch only business status and hours by place ID (Place Details); None if Google no longer has it."""
        self.calls["details"] += 1
        resp = self.session.get(
            DETAILS_URL.format(place.place_id),
            headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": DETAILS_FIELD_MASK},
            timeout=30,
        )
        if getattr(resp, "status_code", 200) == 404:
            return None
        resp.raise_for_status()
        raw = resp.json()
        return place.model_copy(update={"status": raw.get("businessStatus") or "UNKNOWN", "hours": _hours(raw),
                                        "fetched_at": datetime.now(timezone.utc)})

    def find(self, name: str, city: str, near: Optional[tuple[float, float]] = None, fresh: bool = False) -> Optional[Place]:
        key = f"{name}|{city}"
        if not fresh:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        body: dict = {"textQuery": f"{name}, {city}", "languageCode": "en"}
        if near:
            body["locationBias"] = {
                "circle": {"center": {"latitude": near[0], "longitude": near[1]}, "radius": 20000.0}
            }
        raw = [r for r in self._post(SEARCH_TEXT_URL, body, "text_search").get("places") or [] if _has_location(r)]
        if not raw:
            return None
        scored = [(self._match_ok(name, city, near, r), _overlap(name, _display(r)), r) for r in raw]
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        ok, _, best = scored[0]
        place = self._to_place(best, key, f"{name} {city}", ok)
        if weak_coverage(city):
            _add_note(place, _WEAK_NOTE)
        self.cache.put(key, place)
        return place

    def nearby(
        self, lat: float, lng: float, types: list[str], radius_m: int, max_results: int, city: Optional[str] = None
    ) -> list[Place]:
        found = self._nearby_once(lat, lng, types, radius_m, max_results, city)
        places = [p for _, p in found]
        if "hospital" in types:
            others = [p for t, p in found if t != "hospital"]
            hospitals = self._emergency_hospitals([p for t, p in found if t == "hospital"])
            if not any(_haversine_km(lat, lng, p.lat, p.lng) <= _HOSPITAL_RADIUS_KM for p in hospitals):
                hospitals = [p for _, p in self._nearby_once(lat, lng, _CLINIC_TYPES, radius_m, max_results, city)]
                for p in hospitals:
                    _add_note(p, _CLINIC_NOTE)
            places = others + hospitals
        if city and weak_coverage(city):
            for p in places:
                _add_note(p, _WEAK_NOTE)
        return places

    def _nearby_once(self, lat: float, lng: float, types: list[str], radius_m: int, max_results: int,
                     city: Optional[str] = None) -> list[tuple[str, Place]]:
        body = {
            "includedTypes": types,
            "maxResultCount": max_results,
            "rankPreference": "DISTANCE",
            "languageCode": "en",
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
            if not _has_location(r):
                continue
            link = f"{_display(r)} {city.split(',')[0].strip()}" if city else _display(r)
            out.append((r["primaryType"], self._to_place(r, f"nearby:{','.join(types)}", link, True)))
        return out

    @staticmethod
    def _emergency_hospitals(places: list[Place]) -> list[Place]:
        kept = []
        for p in places:
            named = "emergency" in p.name.casefold()
            if p.hours is None:
                if not named:
                    _add_note(p, _UNKNOWN_HOURS_NOTE)
            elif not (named or _is_24h_week(p.hours)):
                continue
            kept.append(p)
        return sorted(kept, key=lambda p: "emergency" not in p.name.casefold())

    @staticmethod
    def _match_ok(name: str, city: str, near: Optional[tuple[float, float]], raw: dict) -> bool:
        if _overlap(name, _display(raw)) < _MIN_OVERLAP:
            return False
        if re.search(rf"(?<!\w){re.escape(_fold(city))}(?!\w)", _fold(raw.get("formattedAddress", ""))):
            return True
        loc = raw.get("location")
        if near and loc:
            return _haversine_km(near[0], near[1], loc["latitude"], loc["longitude"]) <= _NEAR_KM
        return False

    @staticmethod
    def _to_place(raw: dict, query: str, link_text: str, match_ok: bool) -> Place:
        hours = _hours(raw)
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
            website=strip_tracking(raw.get("websiteUri")),
            phone=raw.get("internationalPhoneNumber"),
            maps_url=url,
            fetched_at=datetime.now(timezone.utc),
            match_ok=match_ok,
        )


def _has_location(raw: dict) -> bool:
    loc = raw.get("location")
    return isinstance(loc, dict) and isinstance(loc.get("latitude"), (int, float)) \
        and isinstance(loc.get("longitude"), (int, float))


def _display(raw: dict) -> str:
    return (raw.get("displayName") or {}).get("text", "")
