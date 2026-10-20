from typing import Optional

from pydantic import BaseModel, Field

from src.aigv2.hours import format_week
from src.aigv2.models import HotelStay, Marker, Place

_WALK_LIMIT_MIN = 10
_WANTED = 2
_REQUEST = 6
_NEAR_RADIUS_M = 900
_HOSPITAL_RADIUS_M = 10_000
_GROCERY_TYPES = ["supermarket", "convenience_store", "grocery_store"]
_CAR_MODES = {"taxi", "self_drive", "private_driver"}


class NearbyPlace(BaseModel):
    place: Place
    walk_min: Optional[int] = None
    drive_min: Optional[int] = None
    hours_text: str
    markers: list[Marker] = Field(default_factory=list)


class ImportantPlaces(BaseModel):
    city: str
    hotel: str
    pharmacies: list[NearbyPlace] = Field(default_factory=list)
    groceries: list[NearbyPlace] = Field(default_factory=list)
    hospital: Optional[NearbyPlace] = None
    markers: list[Marker] = Field(default_factory=list)


def _measure(routes, origin: tuple[float, float], found: list[Place], mode: str) -> list[Optional[int]]:
    if not found:
        return []
    got = routes.durations([origin], [(p.lat, p.lng) for p in found], mode)
    return [got.get((0, j)) for j in range(len(found))]


def _wrap(place: Place, walk: Optional[int], drive: Optional[int]) -> NearbyPlace:
    markers = [Marker(kind="VERIFY", text=place.verify_note)] if place.verify_note else []
    if place.hours is None:
        markers.append(Marker(kind="VERIFY", text="opening hours unknown"))
    return NearbyPlace(place=place, walk_min=walk, drive_min=drive, hours_text=format_week(place.hours), markers=markers)


def _walkable(places, routes, origin, city: str, types: list[str], label: str, car: bool, skip: frozenset[str] = frozenset()) -> tuple[list[NearbyPlace], list[Marker]]:
    found = [p for p in places.nearby(origin[0], origin[1], types, _NEAR_RADIUS_M, _REQUEST, city=city) if not (p.place_id and p.place_id in skip)]
    walks = _measure(routes, origin, found, "WALK")
    drives = _measure(routes, origin, found, "DRIVE") if car else [None] * len(found)
    near = [(w, p, d) for p, w, d in zip(found, walks, drives) if w is not None and w <= _WALK_LIMIT_MIN]
    near.sort(key=lambda t: t[0])
    picked = [_wrap(p, w, d) for w, p, d in near[:_WANTED]]
    markers = []
    if len(picked) < _WANTED:
        markers.append(Marker(kind="VERIFY", text=f"fewer than {_WANTED} {label} within a {_WALK_LIMIT_MIN}-minute walk"))
    return picked, markers


def _hospital(places, routes, origin, city: str) -> Optional[NearbyPlace]:
    found = places.nearby(origin[0], origin[1], ["hospital"], _HOSPITAL_RADIUS_M, _REQUEST, city=city)
    if not found:
        return None
    # always by drive regardless of trip modes: emergency means taxi or ambulance
    drives = _measure(routes, origin, found, "DRIVE")
    ranked = sorted(zip(found, drives), key=lambda t: (t[1] is None, t[1] if t[1] is not None else 0))
    p, d = ranked[0]
    nearby = _wrap(p, None, d)
    if d is None:
        nearby.markers.append(Marker(kind="VERIFY", text="hospital drive time unknown — confirm this is the nearest emergency hospital"))
    return nearby


def important_places(
    stays: list[HotelStay], hotel_places: dict[str, Place], places, routes, modes: list[str]
) -> list[ImportantPlaces]:
    car = bool(_CAR_MODES & set(modes))
    out: list[ImportantPlaces] = []
    seen: set[tuple[str, str]] = set()
    for stay in stays:
        key = (stay.hotel.casefold(), stay.city.casefold())
        if key in seen:
            continue
        seen.add(key)
        hotel = hotel_places.get(stay.hotel)
        entry = ImportantPlaces(city=stay.city, hotel=stay.hotel)
        if hotel is None or not hotel.match_ok:
            entry.markers.append(Marker(kind="VERIFY", text=f"hotel location not found for {stay.hotel}; add nearby places by hand"))
            out.append(entry)
            continue
        origin = (hotel.lat, hotel.lng)
        entry.pharmacies, m1 = _walkable(places, routes, origin, stay.city, ["pharmacy"], "pharmacies", car)
        taken = frozenset(n.place.place_id for n in entry.pharmacies)
        entry.groceries, m2 = _walkable(places, routes, origin, stay.city, _GROCERY_TYPES, "groceries", car, taken)
        entry.markers = m1 + m2
        entry.hospital = _hospital(places, routes, origin, stay.city)
        if entry.hospital is None:
            entry.markers.append(Marker(kind="VERIFY", text="no emergency hospital found nearby"))
        out.append(entry)
    return out
