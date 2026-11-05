import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from src.aigv2.config import STEPS, Settings, load_settings
from src.aigv2.guide.build import build_guide
from src.aigv2.google.places import PlacesClient
from src.aigv2.google.routes import RoutesClient
from src.aigv2.intake.attachments import read_attachments
from src.aigv2.intake.extract import extract_trip
from src.aigv2.intake.template import IntakeFields, parse_template
from src.aigv2.library import Library, norm_name
from src.aigv2.llm import StepLLM
from src.aigv2.models import (Answers, Booking, HotelStay, Marker, Place, Question, TransportLeg, TripPlan,
                              place_key)
from src.aigv2.money import FxRates, city_currency, price_text
from src.aigv2.planning.boat import BOAT_BOOKING, DEPARTS_AT, enrich_boat_legs, parse_check_in, parse_crossing_min
from src.aigv2.planning.late_night import AIRPORT_PICKUP, driver_time, is_late_night_landing
from src.aigv2.planning.important_places import ImportantPlaces, important_places
from src.aigv2.planning.meals import Exclusion, MealPick, PlanStats, plan_meals
from src.aigv2.planning.slots import DayResult, parse_time, region_day_city, resolve_day_city, schedule_day
from src.aigv2.planning.travel import Leg, boat_leg, compute_legs
from src.aigv2.preflight import apply_answers, run_checklist, unanswered
from src.aigv2.qc import run_qc
from src.aigv2.qc.report import PRICE_KEY, QCResult, write_report
from src.aigv2.render.document import GuideData, RenderDay, output_filename, render_guide
from src.aigv2.store import NearbyCache, PlaceCache, RouteCache, RunStore, default_backend
from src.aigv2.verification import build_sheet
from src.aigv2.writing.days import DayText, write_day
from src.aigv2.writing.sections import SECTION_KEYS, SectionContent, write_section

log = logging.getLogger(__name__)
from src.aigv2.writing.thanks import ThankYouText, write_thank_you
from src.aigv2.writing.title import write_title
from src.library.ui.storage import StorageBackend

WRITERS = 6
REGEN_SECTIONS = (*SECTION_KEYS, "title", "thanks")
_ITEM_KINDS = ("attraction", "activity", "meal_out")
_OUTPUTS = ("guide.docx", "qc_report.md", "qc_report.json", "verification.xlsx")
_STALE_ON_REGEN = ("guide.json", "guide_error.txt")
_EXCL_DAY = re.compile(r"^\w+, Day (\d+), ")
DOMESTIC_HEALTH_CHECK = ("Altitude / remote area / sea travel not assessed — add health and mountain-road guidance "
                         "if this trip goes above 2,500 m, to a remote area, or involves sea travel")
# Single-time-zone countries only; anything else gets no sunset time rather than a guessed one.
_TZ = {
    "india": "Asia/Kolkata", "turkey": "Europe/Istanbul", "türkiye": "Europe/Istanbul", "turkiye": "Europe/Istanbul",
    "uk": "Europe/London", "united kingdom": "Europe/London", "france": "Europe/Paris", "italy": "Europe/Rome",
    "greece": "Europe/Athens", "netherlands": "Europe/Amsterdam", "germany": "Europe/Berlin",
    "switzerland": "Europe/Zurich", "austria": "Europe/Vienna", "belgium": "Europe/Brussels",
    "ireland": "Europe/Dublin", "czechia": "Europe/Prague", "czech republic": "Europe/Prague",
    "hungary": "Europe/Budapest", "croatia": "Europe/Zagreb", "iceland": "Atlantic/Reykjavik",
    "norway": "Europe/Oslo", "sweden": "Europe/Stockholm", "finland": "Europe/Helsinki",
    "japan": "Asia/Tokyo", "south korea": "Asia/Seoul", "thailand": "Asia/Bangkok", "vietnam": "Asia/Ho_Chi_Minh",
    "singapore": "Asia/Singapore", "malaysia": "Asia/Kuala_Lumpur", "philippines": "Asia/Manila",
    "united arab emirates": "Asia/Dubai", "uae": "Asia/Dubai", "qatar": "Asia/Qatar", "sri lanka": "Asia/Colombo",
    "nepal": "Asia/Kathmandu", "bhutan": "Asia/Thimphu", "maldives": "Indian/Maldives",
    "mauritius": "Indian/Mauritius", "egypt": "Africa/Cairo", "hong kong": "Asia/Hong_Kong",
}


class UnansweredQuestions(Exception):
    def __init__(self, questions: list[Question]):
        self.questions = questions
        super().__init__("unanswered questions: " + ", ".join(q.id for q in questions))


@dataclass
class Deps:
    settings: Settings
    llm: StepLLM
    library: Library
    places: PlacesClient
    routes: RoutesClient
    fx: FxRates
    backend: StorageBackend


def default_deps() -> Deps:
    from dotenv import load_dotenv

    load_dotenv()
    settings = load_settings()
    backend = default_backend(settings)
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    library_dir = Path(os.environ.get("AIGV2_LIBRARY_DB") or "library_db_new")
    return Deps(settings=settings, llm=StepLLM(settings), library=Library(library_dir),
                places=PlacesClient(key, PlaceCache(backend, settings.cache_days),
                                    nearby_cache=NearbyCache(backend, settings.cache_days)),
                routes=RoutesClient(key, cache=RouteCache(backend, settings.cache_days)),
                fx=FxRates(backend), backend=backend)


class BuildResult(BaseModel):
    docx_name: str
    qc: QCResult
    cost_usd: float
    cost: dict = Field(default_factory=dict)


class DayState(BaseModel):
    index: int
    date: date
    city: str
    country: str = ""
    result: DayResult
    places: dict[str, Optional[Place]] = Field(default_factory=dict)
    legs: dict[str, Leg] = Field(default_factory=dict)
    arrival: Optional[int] = None
    departure: Optional[int] = None
    other_legs: list[int] = Field(default_factory=list)
    prev_city: Optional[str] = None
    utc_offset_hours: Optional[float] = None
    booking_by_item: dict[str, Booking] = Field(default_factory=dict)
    arrival_booking: Optional[Booking] = None
    library_attractions: dict[str, dict] = Field(default_factory=dict)


class PlanState(BaseModel):
    trip: TripPlan
    places: dict[str, Optional[Place]]
    countries: dict[str, str]
    days: list[DayState]
    picks: list[MealPick]
    exclusions: list[Exclusion]
    stats: PlanStats
    important: list[ImportantPlaces]


# ---------- cost ----------

class CostMeter:
    def __init__(self, deps: Deps):
        self.deps = deps
        self.log_start = len(deps.llm.cost_log)
        self.google_start = self._google()

    def _google(self) -> dict[str, int]:
        return {**self.deps.places.calls, **self.deps.routes.calls}

    def cost(self) -> dict:
        by_step: dict[str, dict] = {}
        warnings: list[str] = []
        for e in self.deps.llm.cost_log[self.log_start:]:
            key = f"{e['step']} (fallback)" if e.get("fallback") else e["step"]
            row = by_step.setdefault(key, {"model": e["model"], "prompt_tokens": 0, "completion_tokens": 0,
                                           "usd": 0.0})
            if e["model"] not in row["model"].split("+"):
                row["model"] += "+" + e["model"]
            row["prompt_tokens"] += e["prompt_tokens"]
            row["completion_tokens"] += e["completion_tokens"]
            row["usd"] += e["usd"]
            msg = f"No price for model {e['model']} (step {e['step']}); its cost is counted as $0"
            if e.get("unpriced") and msg not in warnings:
                warnings.append(msg)
        order = {s: i for i, s in enumerate(STEPS)}
        by_step = dict(sorted(by_step.items(), key=lambda kv: (order.get(kv[0].split(" ")[0], len(order)),
                                                               kv[0].endswith("(fallback)"))))
        unit = self.deps.settings.google_usd_per_call
        counts = {api: 0 for api in unit}
        for k, v in self._google().items():
            api = PRICE_KEY.get(k, k)
            counts[api] = counts.get(api, 0) + v - self.google_start.get(k, 0)
        by_api = {api: {"calls": n, "usd": n * unit.get(api, 0.0)} for api, n in counts.items()}
        ai_usd = sum(r["usd"] for r in by_step.values())
        google_usd = sum(r["usd"] for r in by_api.values())
        out = {"ai": {"total_usd": ai_usd, "by_step": by_step},
               "google": {"total_usd": google_usd, "by_api": by_api},
               "total_usd": ai_usd + google_usd}
        if warnings:
            out["warnings"] = warnings
        return out


def cost_summary(cost: dict) -> str:
    ai, google = cost["ai"], cost["google"]
    steps = " · ".join(f"{k} ${v['usd']:.2f}" for k, v in ai["by_step"].items()) or "none"
    apis = " · ".join(f"{k} {v['calls']}{'' if k == 'route_element' else ' calls'} ${v['usd']:.2f}"
                      for k, v in google["by_api"].items() if v["calls"]) or "none"
    return "\n".join([f"Cost this run: ${cost['total_usd']:.2f}",
                      f"  {'AI':<8}${ai['total_usd']:.2f}  ({steps})",
                      f"  {'Google':<8}${google['total_usd']:.2f}  ({apis})",
                      *(f"  WARNING: {w}" for w in cost.get("warnings", []))])


def _guarded(store: RunStore, meter: CostMeter, label: str, fn):
    try:
        out = fn()
    except Exception as e:
        cost = meter.cost()
        _record_cost(store, f"{label} (failed)", cost)
        e.run_cost, e.run_id = cost, store.run_id
        raise
    _record_cost(store, label, meter.cost())
    return out


def _record_cost(store: RunStore, label: str, cost: dict) -> None:
    history = (store.load_json("cost_history.json") or {}).get("runs", [])
    history.append({"command": label, "at": datetime.now(timezone.utc).isoformat(), "cost": cost})
    store.save_json("cost_history.json", {"runs": history})
    store.save_json("cost.json", cost)


# ---------- helpers ----------

def _xy(p: Optional[Place]) -> Optional[tuple[float, float]]:
    return (p.lat, p.lng) if p is not None and p.match_ok else None


def _stay_for_day(trip: TripPlan, d: date) -> Optional[HotelStay]:
    return next((s for s in trip.hotels if s.check_in <= d < s.check_out), None) or \
        next((s for s in trip.hotels if s.check_out == d), None)


def _morning_stay(trip: TripPlan, d: date) -> Optional[HotelStay]:
    return next((s for s in trip.hotels if s.check_in < d <= s.check_out), None)


def _new_stay(trip: TripPlan, d: date) -> Optional[HotelStay]:
    return next((s for s in trip.hotels if s.check_in == d), None)


pkey = place_key


def resolve_places(trip: TripPlan, client, places: dict[str, Optional[Place]]) -> dict[str, Optional[Place]]:
    """Resolve hotels and itinerary items; keys are pkey(name, city) so same-named places in two cities stay apart."""
    for h in trip.hotels:
        if pkey(h.hotel, h.city) not in places:
            places[pkey(h.hotel, h.city)] = client.find(h.hotel, h.city)
    for dp in trip.days:
        stay = _stay_for_day(trip, dp.date)
        near = _xy(places.get(pkey(stay.hotel, stay.city))) if stay else None
        for it in dp.items:
            k = pkey(it.name, it.city or dp.city)
            if it.kind not in ("free_time", "transfer") and k not in places:
                places[k] = client.find(it.name, it.city or dp.city, near=near)
    return places


def _day_view(trip: TripPlan, d: date, city: str, prev_city: Optional[str], arrival: Optional[int],
              departure: Optional[int], places: dict[str, Optional[Place]]) -> dict[str, Optional[Place]]:
    # bare names serve the renderer/scheduler (the arriving stay wins a clash); pkeys keep both stays and ports apart
    view: dict[str, Optional[Place]] = {}
    for s in sorted((s for s in trip.hotels if s.check_in <= d <= s.check_out), key=lambda s: s.check_in):
        view[pkey(s.hotel, s.city)] = view[s.hotel] = places.get(pkey(s.hotel, s.city))
    if departure is not None and trip.transport[departure].from_place.strip():
        name = trip.transport[departure].from_place
        view[pkey(name, prev_city or city)] = view[name] = places.get(pkey(name, prev_city or city))
    if arrival is not None and trip.transport[arrival].to_place.strip():
        name = trip.transport[arrival].to_place
        view[pkey(name, city)] = view[name] = places.get(pkey(name, city))
    for t in trip.transport:  # a boat's harbour is resolved by _plan for every boat day, even a day trip
        if t.kind == "boat" and t.from_place.strip() and _leg_date(t) == d:
            view.setdefault(pkey(t.from_place, prev_city or city), places.get(pkey(t.from_place, prev_city or city)))
    dp = next((x for x in trip.days if x.date == d), None)
    for it in (dp.items if dp else []):
        view[it.name] = places.get(pkey(it.name, it.city or city))
    return view


def _country_of(place: Optional[Place]) -> str:
    if place is None or not place.match_ok or not place.address:
        return ""
    last = re.split(r",|\s+[-–]\s+", place.address)[-1]
    return re.sub(r"[\d-]+", "", last).strip()


def _known_country(country: str) -> bool:
    return bool(country) and (country.casefold() in _TZ or bool(city_currency(country)))


def _city_country(place: Optional[Place], library: Library, city: str) -> str:
    """Address country when it is a known one, else the library's mapping, else whatever the address says."""
    addr = _country_of(place)
    return addr if _known_country(addr) else (_library_country(library, city) or addr)


def _library_country(library: Library, city: str) -> str:
    folders = [f for f, cities in library.coverage().items() if norm_name(city) in {norm_name(c) for c in cities}]
    known = [f for f in folders if _known_country(f)]
    return (known or folders or [""])[0]


def _utc_offset(country: str, d: date) -> Optional[float]:
    tz = _TZ.get(country.casefold())
    if not tz:
        return None
    return ZoneInfo(tz).utcoffset(datetime.combine(d, time(12))).total_seconds() / 3600


def _arrival_idx(trip: TripPlan, d: date) -> Optional[int]:
    """A late-night landing (before 05:00) the day after a stay's first night belongs to that night's day."""
    nxt = d + timedelta(days=1)
    stays_in = any(s.check_in == d for s in trip.hotels)
    hits = [(l.arrive, i) for i, l in enumerate(trip.transport) if l.arrive and stays_in and (
        l.arrive.date() == d or (l.arrive.hour < 5 and l.arrive.date() == nxt))]
    return max(hits)[1] if hits else None


_AIRPORT_PICKUP = AIRPORT_PICKUP


def _arrival_booking(trip: TripPlan, d: date, arrival: Optional[int], items) -> Optional[Booking]:
    """The airport pick-up/transfer booking of the day that owns the arrival, when no planned item covers it."""
    if arrival is None or trip.transport[arrival].kind != "flight":
        return None
    placed = {norm_name(i.name) for i in items} | {i.booking_ref for i in items if i.booking_ref}
    return next((b for b in trip.bookings if b.day == d and _AIRPORT_PICKUP.search(b.name)
                 and b.name not in placed and norm_name(b.name) not in placed), None)


def _departure_idx(trip: TripPlan, d: date, trip_days: set[date]) -> Optional[int]:
    """Only a leg on a day a stay checks out (or the trip's last leg) is the departure; day trips are not."""
    if _morning_stay(trip, d) is None:
        return None
    nxt = d + timedelta(days=1)
    timed = [(l.depart, i) for i, l in enumerate(trip.transport) if l.depart]
    last = max(timed)[1] if timed else None
    hits = []
    for dt, i in timed:
        overnight = dt.date() == nxt and dt.hour < 5 and nxt not in trip_days
        if not (dt.date() == d or overnight):
            continue
        checks_out = any(s.check_out == d or (overnight and s.check_out == nxt) for s in trip.hotels)
        moves_on = trip.transport[i].kind in ("boat", "ferry") and dt.date() == d and any(s.check_in == d for s in trip.hotels) and i != last
        if moves_on:
            continue
        if checks_out or (i == last and dt.date() >= max(trip_days)):
            hits.append((dt, i))
    return min(hits)[1] if hits else None


def _leg_date(leg) -> Optional[date]:
    dt = leg.depart or leg.arrive
    return dt.date() if dt else None


def _other_legs(trip: TripPlan, d: date, used: set[int]) -> list[int]:
    return [i for i, l in enumerate(trip.transport) if i not in used and _leg_date(l) == d]


_BOAT_BOOKING = BOAT_BOOKING
_DEPARTS_AT = DEPARTS_AT


def _boat_legs(trip: TripPlan, d: date) -> list[TransportLeg]:
    """Boat/ferry transfers exist only as bookings; give the lunch planner a departure time (no arrival)."""
    out = []
    for b in trip.bookings:
        if b.day != d or not _BOAT_BOOKING.search(b.name):
            continue
        t = None
        for line in b.instructions:
            m = _DEPARTS_AT.search(line)
            t = parse_time(m.group(1)) if m else None
            if t:
                break
        t = t or parse_time(b.time)
        if t:
            ci = parse_time(parse_check_in(b.instructions))
            out.append(TransportLeg(kind="boat", from_place=b.meeting_point or b.name, to_place=b.name,
                                    depart=datetime.combine(d, t), source="booking",
                                    check_in=datetime.combine(d, ci) if ci else None,
                                    duration_min=parse_crossing_min(b.instructions)))
    return out


_IATA = re.compile(r"[A-Z]{3}")


def _endpoint(name: str, city: str, places: dict, client) -> None:
    """Transport endpoints are often airport codes ('DPS'): search them as '<code> airport', keep the key as is."""
    if name.strip() and pkey(name, city) not in places:
        query = f"{name.strip()} airport" if _IATA.fullmatch(name.strip()) else name
        places[pkey(name, city)] = client.find(query, city)


def _pair(a: str, pa: Optional[Place], b: str, pb: Optional[Place], deps: Deps, modes: list[str]) -> Optional[Leg]:
    xa, xb = _xy(pa), _xy(pb)
    if xa is None or xb is None:
        return None
    return compute_legs([(a, xa), (b, xb)], deps.routes, modes, deps.settings.walk_max_min)[0]


def _legs(ds: DayState, trip: TripPlan, deps: Deps) -> dict[str, Leg]:
    d, modes, legs, places = ds.date, trip.travel_modes, {}, ds.places
    morning, new = _morning_stay(trip, d), _new_stay(trip, d)

    def hotel(s: HotelStay) -> Optional[Place]:
        return places.get(pkey(s.hotel, s.city))

    leg = None
    if ds.arrival is not None and new:
        t = trip.transport[ds.arrival]
        leg = _pair(t.to_place, places.get(pkey(t.to_place, ds.city)), new.hotel, hotel(new), deps, modes)
    elif new and morning and pkey(morning.hotel, morning.city) != pkey(new.hotel, new.city):
        leg = _pair(morning.hotel, hotel(morning), new.hotel, hotel(new), deps, modes)
    if leg and ds.arrival is None and (_boat_legs(trip, d) or any(trip.transport[i].kind == "boat" for i in ds.other_legs)):
        leg = boat_leg(leg.from_name, leg.to_name, None)  # the crossing is by boat: no car time
    if leg:
        legs["arrival"] = leg
    if ds.departure is not None and morning:
        t = trip.transport[ds.departure]
        port = places.get(pkey(t.from_place, ds.prev_city or ds.city))
        leg = _pair(morning.hotel, hotel(morning), t.from_place, port, deps, modes)
        if leg:
            legs["departure"] = leg
    boat = next((trip.transport[i] for i in ([ds.arrival, ds.departure] + ds.other_legs)
                 if i is not None and trip.transport[i].kind == "boat" and trip.transport[i].from_place.strip()), None)
    if boat and morning:  # hotel -> harbour by road; absent when the harbour is not placed (never guessed)
        harbour = places.get(pkey(boat.from_place, ds.prev_city or ds.city)) or places.get(pkey(boat.from_place, ds.city))
        road = _pair(morning.hotel, hotel(morning), boat.from_place, harbour, deps, modes)
        if road:
            legs["boat_pickup"] = road
    origin = new or morning
    tz = timezone(timedelta(hours=ds.utc_offset_hours)) if ds.utc_offset_hours is not None else None
    # on a day trip the client leaves by train/boat, so a hotel-to-first-stop drive would be wrong advice
    points = [(origin.hotel, _xy(hotel(origin)), None)] if origin and not ds.other_legs else []
    boats = [s.item.name for s in ds.result.scheduled if s.item.kind in _ITEM_KINDS and _BOAT_BOOKING.search(s.item.name)]
    for n in boats:
        legs[n] = boat_leg(origin.hotel if origin else "", n, None)
    points += [(s.item.name, _xy(places.get(s.item.name)), datetime.combine(d, s.start, tzinfo=tz))
               for s in ds.result.scheduled if s.item.kind in _ITEM_KINDS and s.item.name not in boats]
    points = [p for p in points if p[1] is not None]
    for leg in compute_legs([(n, xy) for n, xy, _ in points], deps.routes, modes, deps.settings.walk_max_min,
                            departures=[t for _, _, t in points[1:]]):
        legs[leg.to_name] = leg
    return legs


def _booking_map(trip: TripPlan, items) -> dict[str, Booking]:
    out = {}
    for it in items:
        b = next((b for b in trip.bookings if (it.booking_ref and b.name == it.booking_ref)
                  or norm_name(b.name) == norm_name(it.name)), None)
        if b:
            out[it.name] = b
    return out


def _item_windows(trip: TripPlan, d: date, items) -> dict[str, tuple[time, time]]:
    """Voucher time windows (start and end both stated) for the day's sightseeing items: a tour booking that names
    several stops covers each of them. Boat/airport bookings are handled by their own logic."""
    out: dict[str, tuple[time, time]] = {}
    for b in trip.bookings:
        s, e = parse_time(b.time), parse_time(b.end_time)
        if b.day != d or not b.timed or s is None or e is None or e <= s:
            continue
        if _BOAT_BOOKING.search(b.name) or _AIRPORT_PICKUP.search(b.name):
            continue
        for it in items:
            if it.kind in ("attraction", "activity") and it.name not in out and (
                    (it.booking_ref and b.name == it.booking_ref) or _names_match(it.name, b.name)):
                out[it.name] = (s, e)
    return out


def booking_window_facts(window: Optional[tuple[time, time]], in_package_lunch: bool) -> Optional[dict]:
    if window is None:
        return None
    s, e = window
    return {"start": s.strftime("%H:%M"), "end": e.strftime("%H:%M"),
            "hours": round(((e.hour * 60 + e.minute) - (s.hour * 60 + s.minute)) / 60, 1),
            "lunch_in_package": in_package_lunch}


_NAME_STOP = {"the", "and", "to", "of", "in", "at", "for", "with", "a", "an", "tour", "private", "transfer"}


def _name_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", norm_name(text)) if len(w) > 1 and w not in _NAME_STOP}


def _names_match(item: str, booking: str) -> bool:
    a, b = norm_name(item), norm_name(booking)
    if a and b and (a in b or b in a):
        return True
    ta, tb = _name_tokens(item), _name_tokens(booking)
    return bool(ta and tb and len(ta & tb) / min(len(ta), len(tb)) >= 0.5)


def _booking_placed(b: Booking, ds: "DayState", trip: TripPlan) -> bool:
    """A booking is in the plan when one of the day's stops carries its name, a stop starts at its time (tours),
    or it is a transfer/boat that the arrival, departure or boat-leg logic already consumed."""
    stops = [s for s in ds.result.scheduled]
    if any(_names_match(s.item.name, b.name) for s in stops):
        return True
    t = parse_time(b.time)
    if t is not None and any(s.start == t for s in stops):
        return True
    if _BOAT_BOOKING.search(b.name) and _boat_legs(trip, ds.date):
        return True
    if re.search(r"\btransfer\b|\bpick-?up\b|\bdrop\b", b.name, re.I) and (
            ds.arrival is not None or ds.departure is not None or any(s.item.kind == "transfer" for s in stops)):
        return True
    return False


def _unlinked_booking_markers(trip: TripPlan, days: list["DayState"]) -> None:
    linked = [b for d in days for b in [*d.booking_by_item.values(), d.arrival_booking] if b is not None]
    by_date = {d.date: d for d in days}
    for b in trip.bookings:
        if b in linked:
            continue
        if b.day in by_date and _booking_placed(b, by_date[b.day], trip):
            continue
        when = f" at {b.time}" if b.time else ""
        target = by_date.get(b.day)
        text = f"booking '{b.name}'{when} is not placed in the day plan"
        if target is None and days:
            target, text = days[0], f"booking '{b.name}' on {b.day.isoformat()} falls outside the trip days"
        if target is not None:
            target.result.markers.append(Marker(kind="VERIFY", text=text))


def _library_attractions(library: Library, city: str, items) -> dict[str, dict]:
    lib = {norm_name(a["name"]): a for a in library.city(city).get("attractions", [])
           if isinstance(a, dict) and isinstance(a.get("name"), str)}
    return {it.name: lib[norm_name(it.name)] for it in items if norm_name(it.name) in lib}


def _questions(store: RunStore) -> list[Question]:
    data = store.load_json("questions.json")
    if data is None:
        raise ValueError(f"run {store.run_id} has no questions.json; run start first")
    return [Question.model_validate(q) for q in data["questions"]]


def _load_plan(store: RunStore) -> PlanState:
    data = store.load_json("plan.json")
    if data is None:
        raise ValueError(f"run {store.run_id} has no plan.json; run build first")
    return PlanState.model_validate(data)


def _version(store: RunStore, stem: str, ext: str) -> int:
    pat = re.compile(rf"^{re.escape(stem)}\.v(\d+)\.{ext}$")
    nums = [int(m.group(1)) for n in store.names() if (m := pat.match(n))]
    return max(nums, default=0) + 1


# ---------- stages ----------

def start_run(intake_path: Path | None, attachment_paths: list[Path], deps: Deps) -> tuple[RunStore, list[Question]]:
    meter = CostMeter(deps)
    store = RunStore.create(deps.backend)
    return _guarded(store, meter, "start", lambda: _start(store, intake_path, list(attachment_paths), deps))


def _start(store: RunStore, intake_path: Path | None, paths: list[Path], deps: Deps) -> tuple[RunStore, list[Question]]:
    for p in ([intake_path] if intake_path else []) + paths:
        store.save_bytes(f"inputs/{p.name}", p.read_bytes())
    intake = parse_template(intake_path) if intake_path else IntakeFields()
    attachments = read_attachments(paths)
    trip = extract_trip(intake, attachments, deps.llm)
    places = resolve_places(trip, deps.places, {})
    questions = run_checklist(trip, intake, attachments, deps.library, places, deps.settings)
    store.save_json("intake.json", intake)
    store.save_json("attachments.json", {"attachments": [a.model_dump(mode="json") for a in attachments]})
    store.save_json("trip_plan.json", trip)
    store.save_json("places.json", {"places": {k: v.model_dump(mode="json") if v else None for k, v in places.items()}})
    store.save_json("questions.json", {"questions": [q.model_dump(mode="json") for q in questions]})
    store.save_json("answers.template.json", {q.id: "" for q in questions})
    return store, questions


def _plan(store: RunStore, answers: Answers, deps: Deps) -> PlanState:
    if store.has("plan.json"):
        return _load_plan(store)
    trip = enrich_boat_legs(apply_answers(TripPlan.model_validate(store.load_json("trip_plan.json")),
                                          _questions(store), answers))
    for dp in trip.days:
        dp.city = resolve_day_city(dp.city, dp.date, trip.hotels)
        dp.city = region_day_city(dp.city, dp.date, trip.hotels, lambda c: len(deps.library.restaurants(c)))
    raw = (store.load_json("places.json") or {}).get("places", {})
    places = resolve_places(trip, deps.places, {k: Place.model_validate(v) if v else None for k, v in raw.items()})
    s = deps.settings
    countries: dict[str, str] = {}
    for dp in trip.days:
        stay = _stay_for_day(trip, dp.date)
        if not countries.get(dp.city):
            countries[dp.city] = _city_country(places.get(pkey(stay.hotel, stay.city)) if stay else None,
                                               deps.library, dp.city)
    trip_days = {dp.date for dp in trip.days}
    ordered = sorted(trip.days, key=lambda x: x.date)
    ends = {dp.date: (_arrival_idx(trip, dp.date), _departure_idx(trip, dp.date, trip_days)) for dp in ordered}
    used = {i for pair in ends.values() for i in pair if i is not None}
    days: list[DayState] = []
    prev = None
    for n, dp in enumerate(ordered, 1):
        arr, dep = ends[dp.date]
        if arr is not None:
            _endpoint(trip.transport[arr].to_place, dp.city, places, deps.places)
        if dep is not None:
            _endpoint(trip.transport[dep].from_place, prev or dp.city, places, deps.places)
        for i in _other_legs(trip, dp.date, used):
            if trip.transport[i].kind == "boat":
                _endpoint(trip.transport[i].from_place, prev or dp.city, places, deps.places)
        ds = DayState(index=n, date=dp.date, city=dp.city, country=countries.get(dp.city, ""),
                      result=DayResult(), arrival=arr, departure=dep, prev_city=prev,
                      other_legs=_other_legs(trip, dp.date, used),
                      places=_day_view(trip, dp.date, dp.city, prev, arr, dep, places),
                      utc_offset_hours=_utc_offset(countries.get(dp.city, ""), dp.date),
                      booking_by_item=_booking_map(trip, dp.items),
                      arrival_booking=_arrival_booking(trip, dp.date, arr, dp.items),
                      library_attractions=_library_attractions(deps.library, dp.city, dp.items))
        ds.result = schedule_day(dp, trip.hotels, trip.transport[arr] if arr is not None else None,
                                 trip.transport[dep] if dep is not None else None, ds.places, s, ds.country,
                                 trip.trip_scope == "domestic",
                                 [trip.transport[i] for i in ds.other_legs] + _boat_legs(trip, dp.date),
                                 {n: t for n, b in ds.booking_by_item.items() if (t := parse_time(b.end_time))},
                                 _item_windows(trip, dp.date, dp.items))
        ds.legs = _legs(ds, trip, deps)
        days.append(ds)
        prev = dp.city
    _unlinked_booking_markers(trip, days)
    picks, exclusions, stats = plan_meals([(d.index, d.date, d.city, d.result.meals) for d in days], deps.library,
                                          deps.places, deps.routes, trip.diet, trip.travel_modes, deps.llm, s,
                                          trip_scope=trip.trip_scope)
    important = []
    for city in dict.fromkeys(h.city for h in trip.hotels):
        stays = [h for h in trip.hotels if h.city == city]
        found = {h.hotel: places[pkey(h.hotel, city)] for h in stays if places.get(pkey(h.hotel, city))}
        important += important_places(stays, found, deps.places, deps.routes, trip.travel_modes)
    state = PlanState(trip=trip, places=places, countries=countries, days=days, picks=picks, exclusions=exclusions,
                      stats=stats, important=important)
    store.save_json("plan.json", state)
    return state


def _address(p: Optional[Place]) -> Optional[str]:
    return p.address if p is not None and p.match_ok and p.address else None


def _day_facts(ds: DayState, state: PlanState) -> dict:
    dp = next(d for d in state.trip.days if d.date == ds.date)
    attractions = [{"name": s.item.name, "kind": s.item.kind, "slot": s.slot, "note": s.item.note,
                    "optional": s.item.optional,
                    "google_address": _address(ds.places.get(s.item.name)),
                    "area": ds.library_attractions.get(s.item.name, {}).get("area")
                    or ds.library_attractions.get(s.item.name, {}).get("location"),
                    "library_description": ds.library_attractions.get(s.item.name, {}).get("description")}
                   for s in ds.result.scheduled if s.item.kind in ("attraction", "activity")]
    restaurants, seen = [], set()
    for p in state.picks:
        if p.day_index != ds.index:
            continue
        for c in p.restaurants:
            if norm_name(c.lib["name"]) not in seen:
                seen.add(norm_name(c.lib["name"]))
                restaurants.append({"name": c.lib["name"], "meal": p.slot.meal, "cuisine": c.lib.get("cuisine_type"),
                                    "highlights": c.lib.get("highlights")})
    windows = _item_windows(state.trip, ds.date, dp.items)
    covered = [windows[s.item.name] for s in ds.result.scheduled if s.item.name in windows]
    facts = {"date": ds.date.isoformat(), "city": ds.city, "planned_title": dp.title, "attractions": attractions,
             "restaurants": restaurants, "travellers": state.trip.travellers.model_dump(mode="json"),
             "occasion": state.trip.occasion}
    if covered:
        w = max(covered, key=lambda x: (x[1].hour * 60 + x[1].minute) - (x[0].hour * 60 + x[0].minute))
        facts["booking_window"] = booking_window_facts(w, any(m.in_package for m in ds.result.meals))
    return facts


def _section_inputs(state: PlanState, library: Library) -> tuple[list[dict], dict]:
    cities = list(dict.fromkeys(d.city for d in state.days))
    city_data = [{**library.city(c), "city": c, "country": state.countries.get(c, "")} for c in cities]
    country_data: dict[str, dict] = {}
    for c in cities:
        country = state.countries.get(c, "")
        if country and country not in country_data:
            country_data[country] = library.country(country) or library.country(c)
            if not country_data[country]:
                log.warning("no country-level library data for %s (dos/don'ts, apps, embassies, money will be empty); "
                            "check AIGV2_LIBRARY_DB points at the rebuilt library", country)
    return city_data, country_data


def _write(store: RunStore, state: PlanState, deps: Deps) -> None:
    jobs: dict[str, Any] = {}
    city_data, country_data = _section_inputs(state, deps.library)
    trip_cities = list(dict.fromkeys([d.city for d in state.days] + [h.city for h in state.trip.hotels]))
    other_places = sorted(deps.library.other_destinations(trip_cities))
    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        for ds in state.days:
            name = f"days/day_{ds.index:02d}.json"
            if not store.has(name):
                jobs[name] = pool.submit(write_day, _day_facts(ds, state), deps.llm)
        for key in SECTION_KEYS:
            name = f"sections/{key}.json"
            if not store.has(name):
                jobs[name] = pool.submit(write_section, key, city_data, country_data, state.trip, deps.llm,
                                         places=deps.places, fx=deps.fx, today=date.today(), important=state.important,
                                         other_places=other_places)
        if not store.has("sections/title.json"):
            jobs["sections/title.json"] = pool.submit(write_title, state.trip, deps.llm)
        if not store.has("sections/thanks.json"):
            jobs["sections/thanks.json"] = pool.submit(write_thank_you, state.trip, deps.llm, state.countries)
    errors: list[tuple[str, Exception]] = []
    for name, fut in jobs.items():
        try:
            out = fut.result()
        except Exception as e:
            errors.append((name, e))
            continue
        if name == "sections/title.json":
            store.save_json(name, {"title": out})
        elif name == "sections/thanks.json":
            store.save_json(name, out.model_dump(mode="json"))
        elif name.startswith("sections/"):
            store.save_json(name, {"content": out.model_dump(mode="json") if out else None})
        else:
            store.save_json(name, out)
    if len(errors) == 1:
        raise errors[0][1]
    if errors:
        detail = "; ".join(f"{n}: {e.__class__.__name__}: {e}" for n, e in errors)
        raise RuntimeError(f"{len(errors)} writers failed — {detail}") from errors[0][1]


def _late_facts(ds, trip: TripPlan) -> dict:
    """lands_next_day / driver_from for a day's arrival leg and airport booking."""
    leg = trip.transport[ds.arrival] if ds.arrival is not None else None
    return {"lands_next_day": bool(leg and is_late_night_landing(leg, ds.date)),
            "driver_from": driver_time(ds.arrival_booking) if ds.arrival_booking else None}


def _render_days(store: RunStore, state: PlanState, deps: Deps) -> list[RenderDay]:
    out = []
    for ds in state.days:
        t = state.trip.transport
        picks = [p for p in state.picks if p.day_index == ds.index]
        currency = city_currency(ds.country, deps.library.city(ds.city)) or ""
        prices = {c.lib["name"]: price_text(c.lib, currency, deps.fx, ds.date) for p in picks for c in p.restaurants}
        out.append(RenderDay(
            index=ds.index, date=ds.date, city=ds.city,
            text=DayText.model_validate(store.load_json(f"days/day_{ds.index:02d}.json")),
            result=ds.result, meals=picks, legs=ds.legs, places=ds.places, booking_by_item=ds.booking_by_item,
            arrival_booking=ds.arrival_booking,
            price_by_restaurant=prices, arrival=t[ds.arrival] if ds.arrival is not None else None,
            departure=t[ds.departure] if ds.departure is not None else None, prev_city=ds.prev_city,
            other_transport=[t[i] for i in ds.other_legs],
            utc_offset_hours=ds.utc_offset_hours, library_attractions=ds.library_attractions,
            **_late_facts(ds, state.trip)))
    return out


def _stats_md(stats: PlanStats) -> str:
    lines = ["## Restaurant lookups", ""]
    lines += [f"- {c}: {n} Google lookups" for c, n in sorted(stats.lookups_by_city.items())] or ["None."]
    if stats.capped_cities:
        lines += ["", "Lookup cap reached (some library restaurants were not checked): " + ", ".join(stats.capped_cities)]
    return "\n".join(lines) + "\n"


def _save_guide_model(store: RunStore, data: GuideData, deps: Deps) -> None:
    """Save guide.json; never fail the build (the docx is the product during the transition)."""
    try:
        store.save_json("guide.json", build_guide(data, deps.settings))
    except Exception as exc:
        store.save_bytes("guide_error.txt", f"{type(exc).__name__}: {exc}".encode("utf-8"))


def _render_qc(store: RunStore, state: PlanState, answers: Answers, deps: Deps) -> QCResult:
    if store.has("guide.docx") and store.has("qc_report.json"):
        result = QCResult.model_validate(store.load_json("qc_report.json"))
    else:
        sections = {}
        for key in SECTION_KEYS:
            raw = store.load_json(f"sections/{key}.json")["content"]
            sections[key] = SectionContent.model_validate(raw) if raw else None
        if state.trip.trip_scope == "domestic":
            safety = sections.get("safety") or SectionContent(key="safety")
            safety.markers.append(Marker(kind="CHECK", text=DOMESTIC_HEALTH_CHECK))
            sections["safety"] = safety
        data = GuideData(trip=state.trip, title=store.load_json("sections/title.json")["title"],
                         days=_render_days(store, state, deps), sections=sections, important=state.important,
                         trip_scope=state.trip.trip_scope, modes=state.trip.travel_modes,
                         domestic=state.trip.trip_scope == "domestic",
                         thanks=ThankYouText.model_validate(store.load_json("sections/thanks.json"))
                         if store.has("sections/thanks.json") else None)
        guide = None
        if deps.settings.renderer == "new":
            from src.aigv2.render2.render import render_guide2
            guide = build_guide(data, deps.settings)
            docx = render_guide2(guide)
        else:
            docx = render_guide(data, deps.settings)
        annotated, result, report = run_qc(docx, state.trip, answers, deps.library, deps.places, deps.routes,
                                           deps.llm, state.exclusions, deps.settings.google_usd_per_call,
                                           countries=state.countries, settings=deps.settings)
        _, report_data = write_report(result, state.exclusions, result.cost)
        store.save_bytes("guide.docx", annotated)
        if guide is not None:
            store.save_json("guide.json", guide)
        else:
            _save_guide_model(store, data, deps)
        store.save_bytes("qc_report.md", (report + "\n" + _stats_md(state.stats)).encode("utf-8"))
        store.save_json("qc_report.json", {**report_data, "plan_stats": state.stats.model_dump(mode="json")})
    if not store.has("verification.xlsx"):
        store.save_bytes("verification.xlsx", build_sheet(result.fact_rows, state.exclusions))
    return result


def _finish(store: RunStore, answers: Answers, deps: Deps) -> tuple[str, QCResult]:
    state = _plan(store, answers, deps)
    _write(store, state, deps)
    return output_filename(state.trip), _render_qc(store, state, answers, deps)


def _result(store: RunStore, meter: CostMeter, label: str, fn) -> BuildResult:
    name, qc = _guarded(store, meter, label, fn)
    cost = store.load_json("cost.json")
    return BuildResult(docx_name=name, qc=qc, cost_usd=cost["total_usd"], cost=cost)


def build_run(store: RunStore, answers: Answers, deps: Deps) -> BuildResult:
    meter = CostMeter(deps)
    missing = unanswered(_questions(store), answers)
    if missing:
        raise UnansweredQuestions(missing)
    saved = store.load_json("answers.json")
    if saved is not None and saved != answers and store.has("plan.json"):
        raise ValueError("answers differ from the ones this run was built with; start a new run")
    store.save_json("answers.json", answers)
    return _result(store, meter, "build", lambda: _finish(store, answers, deps))


def regenerate(store: RunStore, days: list[int], sections: list[str], deps: Deps) -> BuildResult:
    meter = CostMeter(deps)
    state = _load_plan(store)
    answers = store.load_json("answers.json") or {}
    if not store.has("guide.docx"):
        raise ValueError(f"run {store.run_id} has no finished guide to regenerate; run `build` first")
    bad_days = [d for d in days if not 1 <= d <= len(state.days)]
    bad_keys = [k for k in sections if k not in REGEN_SECTIONS]
    if bad_days or bad_keys or not (days or sections):
        raise ValueError(f"nothing valid to regenerate (days 1–{len(state.days)}; sections {', '.join(REGEN_SECTIONS)})"
                         + (f"; bad days {bad_days}" if bad_days else "") + (f"; bad sections {bad_keys}" if bad_keys else ""))
    return _result(store, meter, "regenerate", lambda: _regenerate(store, state, answers, days, sections, deps))


def _regenerate(store: RunStore, state: PlanState, answers: Answers, days: list[int], sections: list[str],
                deps: Deps) -> tuple[str, QCResult]:
    v = _version(store, "guide", "docx")
    for name in _OUTPUTS:
        data = store.load_bytes(name)
        if data is not None:
            stem, ext = name.rsplit(".", 1)
            store.save_bytes(f"{stem}.v{v}.{ext}", data)
            store.delete(name)
    for name in _STALE_ON_REGEN:
        store.delete(name)
    for n in days:
        store.delete(f"days/day_{n:02d}.json")
    for key in sections:
        store.delete(f"sections/{key}.json")
    if days:
        targets = set(days)
        keep = [p for p in state.picks if p.day_index not in targets]
        city = {d.index: d.city for d in state.days}
        picks, excl, stats = plan_meals(
            [(d.index, d.date, d.city, d.result.meals) for d in state.days if d.index in targets], deps.library,
            deps.places, deps.routes, state.trip.diet, state.trip.travel_modes, deps.llm, deps.settings,
            trip_scope=state.trip.trip_scope, prior=[(city[p.day_index], p) for p in keep])
        state.picks = sorted(keep + picks, key=lambda p: p.day_index)
        state.exclusions = [e for e in state.exclusions
                            if not ((m := _EXCL_DAY.match(e.detail)) and int(m.group(1)) in targets)] + excl
        for c, k in stats.lookups_by_city.items():
            state.stats.lookups_by_city[c] = state.stats.lookups_by_city.get(c, 0) + k
        state.stats.capped_cities = list(dict.fromkeys(state.stats.capped_cities + stats.capped_cities))
        store.save_json("plan.json", state)
    return _finish(store, answers, deps)


def requalify(store_or_none: Optional[RunStore], docx_path: Path, deps: Deps) -> tuple[bytes, QCResult, str]:
    if store_or_none is None:
        raise ValueError("re-QC needs the run the guide came from (--run RUN_ID): the trip plan is required")
    store, meter = store_or_none, CostMeter(deps)
    return _guarded(store, meter, "qc", lambda: _requalify(store, Path(docx_path), deps))


def _requalify(store: RunStore, docx_path: Path, deps: Deps) -> tuple[bytes, QCResult, str]:
    docx = docx_path.read_bytes()
    state = _load_plan(store)
    answers, exclusions = store.load_json("answers.json") or {}, state.exclusions
    out, result, report = run_qc(docx, state.trip, answers, deps.library, deps.places, deps.routes, deps.llm,
                                 exclusions, deps.settings.google_usd_per_call, countries=state.countries,
                                 settings=deps.settings)
    n = _version(store, "requalify/guide", "docx")
    _, data = write_report(result, exclusions, result.cost)
    store.save_bytes(f"requalify/input.v{n}.docx", docx)
    store.save_bytes(f"requalify/guide.v{n}.docx", out)
    store.save_bytes(f"requalify/qc_report.v{n}.md", report.encode("utf-8"))
    store.save_json(f"requalify/qc_report.v{n}.json", data)
    store.save_bytes(f"requalify/verification.v{n}.xlsx", build_sheet(result.fact_rows, exclusions))
    return out, result, report
