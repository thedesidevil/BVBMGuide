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
_MEDICAL_TYPES = {"hospital", "doctor", "medical_clinic"}
_UNWANTED_ANY = re.compile(
    r"\b(?:rent\w*|tours?|snorkel\w*|snorkl\w*|diving|divers?|surf\w*|motor\w*|bikes?|scooters?|spa|massage\w*|laundry)\b"
    r"|travel agen",
    re.I,
)
_UNWANTED_MEDICAL = re.compile(
    r"laborator|\blab\b|microbiolog|patholog|dental|dentist|\bgigi\b|orthodont|veterinar|\bvet\b|animal|\bpets?\b"
    r"|cosmetic|beauty|aesthetic|skin clinic|eye clinic",
    re.I,
)
_HOSPITAL_LIKE = re.compile(r"hospital|rumah sakit|\brs\b|emergency|medical cent(?:re|er)|clinic", re.I)


def unwanted_name(name: str, medical: bool = False) -> bool:
    """True for a place whose name shows it is not what we are looking for; 'emergency' in the name always keeps it."""
    low = name.casefold()
    if "emergency" in low:
        return False
    if any(w in low for w in _EXCLUDED_NAME_WORDS) or _UNWANTED_ANY.search(name):
        return True
    return medical and bool(_UNWANTED_MEDICAL.search(name))


def hospital_like(name: str) -> bool:
    return bool(_HOSPITAL_LIKE.search(name))
_CLINIC_NOTE = "nearest clinic, not a hospital"
_HOSPITAL_RADIUS_KM = 10
_NEAR_KM = 25
_LODGING_OVERLAP = 0.7
_LODGING_TYPES = {"lodging", "hotel", "resort_hotel", "bed_and_breakfast", "hostel", "guest_house", "motel"}
_CITY_ALIASES = {
    "lucerne": ("luzern",), "zurich": ("zuerich",), "geneva": ("geneve",), "munich": ("munchen",),
    "cologne": ("koln",), "vienna": ("wien",), "florence": ("firenze",), "rome": ("roma",),
    "venice": ("venezia",), "prague": ("praha",), "brussels": ("bruxelles", "brussel"), "bern": ("berne",),
    "milan": ("milano",), "naples": ("napoli",), "turin": ("torino",), "lisbon": ("lisboa",),
    "copenhagen": ("kobenhavn",), "athens": ("athina",),
}
_MIN_OVERLAP = 0.6
_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")
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


_GENERIC_WORDS = re.compile(r"\b(?:package|tour|experience|view)\b", re.I)
_AT_IN = re.compile(r"^.*\s(?:at|in)\s+", re.I)
_MAX_RETRIES = 3


def _simplified_names(name: str) -> list[str]:
    """Deterministic fallback queries for a broad attraction name, most faithful first (at most _MAX_RETRIES)."""
    out: list[str] = []

    def add(q: str) -> None:
        q = " ".join(q.split()).strip(" ,-")
        if q and q.casefold() != name.casefold() and q.casefold() not in {x.casefold() for x in out}:
            out.append(q)

    bare = _TRAILING_PAREN.sub("", name).strip()
    add(bare)
    stripped = _GENERIC_WORDS.sub(" ", bare)
    tail = _AT_IN.sub("", stripped) if _AT_IN.search(stripped) else stripped
    add(tail)
    add(stripped)
    last = out[-1] if out else bare
    if re.search(r"\btear$", last, re.I):
        add(re.sub(r"(?i)tear$", lambda m: m.group(0) + ("S" if m.group(0).isupper() else "s"), last))
    return out[:_MAX_RETRIES]


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def _adds_new_words(original: str, found: str, city: str) -> bool:
    """True when Google's name carries distinctive words the voucher name never had ('Ducks Marine Park' for 'Marine Park')."""
    known = {_stem(w) for w in _tokens(original) | _tokens(city)}
    return any(_stem(w) not in known for w in _tokens(found))


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
    def __init__(self, api_key: str, cache: PlaceCache, session: Optional[requests.Session] = None,
                 nearby_cache=None):
        self.api_key = api_key
        self.cache = cache
        self.nearby_cache = nearby_cache
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

    def peek(self, name: str, city: str) -> Optional[Place]:
        """The cached place `find` would return for this exact key; no HTTP call, no counters."""
        return self.cache.get(f"{name}|{city}")

    def find(self, name: str, city: str, near: Optional[tuple[float, float]] = None, fresh: bool = False) -> Optional[Place]:
        key = f"{name}|{city}"
        if not fresh:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        place = self._lookup(name, city, near, key)
        if place is None or not place.match_ok:
            bare = _TRAILING_PAREN.sub("", name).strip()
            for q in _simplified_names(name):
                retry = self._lookup(q, city, near, f"{q}|{city}")
                if retry is not None and retry.match_ok and not _adds_new_words(name, retry.name, city):
                    if q != bare:
                        _add_note(retry, f"Matched using the simplified name '{q}'")
                    self.cache.put(f"{q}|{city}", retry)
                    place = retry
                    break
        if place is not None:
            self.cache.put(key, place)
        return place

    def _lookup(self, name: str, city: str, near: Optional[tuple[float, float]], key: str) -> Optional[Place]:
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
        return place

    def nearby(
        self, lat: float, lng: float, types: list[str], radius_m: int, max_results: int, city: Optional[str] = None
    ) -> list[Place]:
        key = f"{lat:.5f},{lng:.5f}|{','.join(sorted(types))}|{radius_m}|{max_results}|{city or ''}"
        hit = self.nearby_cache.get(key) if self.nearby_cache else None
        if hit is not None:
            return hit
        places = self._nearby_uncached(lat, lng, types, radius_m, max_results, city)
        if self.nearby_cache:
            self.nearby_cache.put(key, places)
        return places

    def nearby_peek(self, lat: float, lng: float, types: list[str], radius_m: int, max_results: int,
                    city: Optional[str] = None) -> list[Place]:
        """Cached answer only; never calls Google (empty on a miss)."""
        key = f"{lat:.5f},{lng:.5f}|{','.join(sorted(types))}|{radius_m}|{max_results}|{city or ''}"
        return (self.nearby_cache.get(key) if self.nearby_cache else None) or []

    def _nearby_uncached(
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
        medical = bool(wanted & _MEDICAL_TYPES)
        out = []
        for r in raw:
            if r.get("primaryType") not in wanted or unwanted_name(_display(r), medical):
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
        overlap = _overlap(name, _display(raw))
        if overlap < _MIN_OVERLAP:
            return False
        addr = _fold(raw.get("formattedAddress", ""))
        for c in (city, *_CITY_ALIASES.get(_fold(city), ())):
            if re.search(rf"(?<!\w){re.escape(_fold(c))}(?!\w)", addr):
                return True
        if overlap >= _LODGING_OVERLAP and _LODGING_TYPES & set(raw.get("types") or []):
            # a named hotel in a suburb or neighbouring village ('Wilderswil' for Interlaken, 'Clichy' for Paris)
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
