import re
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional, Sequence

from pydantic import BaseModel, Field

from src.aigv2.config import Settings
from src.aigv2.hours import is_open_for, next_opening
from src.aigv2.models import DayPlan, HotelStay, Marker, PlannedItem, Place, TransportLeg

Slot = Literal["morning", "afternoon", "evening"]
Anchor = tuple[str, tuple[float, float], int]

_BREAKFAST_WINDOW = ("07:30", "09:30")
_MORNING_CAP = 2
_ITEM_MINUTES = 90
_HOTEL_ARRIVAL_BUFFER = {"flight": 60}
_DEFAULT_BUFFER = 20
_LATE_LUNCH_CUTOFF = time(15, 0)
_NO_DINNER_AFTER = time(21, 0)
_LATEST_LUNCH = time(13, 30)
_LEG_DEFAULT_MIN = 90
_LEG_MARGIN_MIN = 30
_EARLY_ARRIVAL_BEFORE = time(5, 0)
_PACKED_BREAKFAST_BEFORE = time(7, 0)
_DEFAULT_CHECKIN = time(15, 0)
_TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})(?:\s*([ap])\.?m\b)?|(\d{1,2})\s*([ap])\.?m\b", re.I)
_DINNER_RULE = re.compile(r"dinner\s+(?:before|between|near)\s+(.+)", re.I)
_SEA_DAY = re.compile(r"\bat sea\b|\bsea day\b", re.I)
_TOUR_DEFAULT_MIN = 8 * 60
_VAGUE_NAMES = {"coffee plantation", "local market", "market", "beach", "temple", "viewpoint", "viewpoint stop",
                "waterfall", "shopping", "free time", "city tour", "sightseeing", "lunch"}
_VAGUE_TAIL = re.compile(r"\s+(?:visit|tour)$")


def _is_vague(name: str) -> bool:
    return _VAGUE_TAIL.sub("", " ".join(name.casefold().split())) in _VAGUE_NAMES


class ScheduledItem(BaseModel):
    item: PlannedItem
    slot: Slot
    start: time

    @property
    def option_group(self) -> Optional[str]:
        return self.item.option_group


class MealSlot(BaseModel):
    meal: Literal["breakfast", "lunch", "dinner"]
    start: time
    anchors: list[Anchor] = Field(default_factory=list)
    included: bool = False
    unanchored: bool = False
    in_package: bool = False  # a full-day package covers this meal window (options only when anchors are known)
    near_label: Optional[str] = None  # where the group is at this meal when it is not the hotel city (a full-day excursion)
    max_min: Optional[int] = None  # car-time cap for this slot when it differs from the settings (rural anchors)


class DayResult(BaseModel):
    scheduled: list[ScheduledItem] = Field(default_factory=list)
    meals: list[MealSlot] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)


def parse_time(text: Optional[str]) -> Optional[time]:
    if not text:
        return None
    m = _TIME_RE.search(text)
    if not m:
        return None
    if m.group(1):
        h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        h, mi, ap = int(m.group(4)), 0, m.group(5)
    if ap:
        h = h % 12 + (12 if ap.lower() == "p" else 0)
    if h > 23 or mi > 59:
        return None
    return time(h, mi)


def _t(s: str) -> time:
    return time.fromisoformat(s)


def _plus(t: time, minutes: int) -> time:
    return (datetime.combine(date.min, t) + timedelta(minutes=minutes)).time()


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def round15(t: time) -> time:
    """Display time: the nearest quarter hour (an estimated start is never shown as 2:54 PM)."""
    m = (_minutes(t) + 7) // 15 * 15
    return time(m // 60 % 24, m % 60)


def _slot_for(t: time, settings: Settings) -> Slot:
    if t < _t(settings.slot_windows["morning"][1]):
        return "morning"
    if t < _t(settings.slot_windows["evening"][0]):
        return "afternoon"
    return "evening"


def boat_floor(d: date, legs: Sequence[TransportLeg], stays: list[HotelStay],
               skip: Sequence[Optional[TransportLeg]] = ()) -> Optional[time]:
    """Earliest time an untimed activity may start on a day the group boats to a new hotel."""
    if not any(s.check_in == d for s in stays):
        return None
    ends = []
    for lg in legs:
        if lg.kind != "boat" or not (lg.depart and lg.depart.date() == d) or any(lg is x for x in skip):
            continue
        end = lg.arrive if lg.arrive and lg.arrive.date() == d and lg.arrive > lg.depart \
            else lg.depart + timedelta(minutes=_LEG_DEFAULT_MIN + _DEFAULT_BUFFER)
        if end.date() == d:
            ends.append(end.time())
    return max(ends) if ends else None


_WINDOW_STEP_MAX_MIN = 150


_COMPACT_TRAVEL_MIN = 20  # allowance for the drive between stops when packing a short window
DEFAULT_STOP_MIN = 45  # a stop with no known duration


def _window_starts(day: DayPlan, windows: Optional[dict[str, tuple[time, time]]],
                   durations: Optional[dict[str, int]] = None) -> dict[int, time]:
    """Start times for untimed items a voucher window covers: the first at the window start, the rest spread across it.
    A short window (under six hours) with known durations is packed: each stop starts when the previous one ends
    plus an allowance for the drive, so the day has no invented gaps."""
    groups: dict[tuple[time, time], list[PlannedItem]] = {}
    for it in day.items:
        w = (windows or {}).get(it.name)
        if w and not (parse_time(it.pickup_time) or parse_time(it.time)) and not it.option_group:
            groups.setdefault(w, []).append(it)
    out: dict[int, time] = {}
    for (start, end), items in groups.items():
        span = _minutes(end) - _minutes(start)
        if durations is not None and 0 < span < _FULL_DAY_PACKAGE_MIN:
            t, packed = 0, []
            for it in items:
                packed.append(t)
                t += durations.get(it.name, DEFAULT_STOP_MIN) + _COMPACT_TRAVEL_MIN
            if packed[-1] < span:
                for it, off in zip(items, packed):
                    out[id(it)] = _plus(start, off)
                continue
        step = min(_WINDOW_STEP_MAX_MIN, max(span // len(items) // 5 * 5, 5)) if span > 0 else _ITEM_MINUTES
        for i, it in enumerate(items):
            out[id(it)] = _plus(start, step * i)
    return out


def _schedule_items(day: DayPlan, settings: Settings, floor: Optional[time] = None,
                    windows: Optional[dict[str, tuple[time, time]]] = None,
                    durations: Optional[dict[str, int]] = None) -> list[ScheduledItem]:
    forced = _window_starts(day, windows, durations)
    placed: list[tuple[PlannedItem, Optional[Slot], Optional[time]]] = []
    for it in day.items:
        start = parse_time(it.pickup_time) or parse_time(it.time) or forced.get(id(it))
        if start:
            placed.append((it, _slot_for(start, settings), start))
        elif it.slot_hint != "any":
            placed.append((it, it.slot_hint, None))
        else:
            placed.append((it, None, None))
    counts = {"morning": 0, "afternoon": 0, "evening": 0}
    for _, slot, _ in placed:
        if slot:
            counts[slot] += 1
    out = []
    used = {"morning": 0, "afternoon": 0, "evening": 0}
    after_boat = 0
    if floor is not None:
        # transfers to the new hotel come first, then the other untimed items, all after the boat lands
        placed = [p for p in placed if p[2]] + sorted([p for p in placed if not p[2]], key=lambda p: p[0].kind != "transfer")
    group_at: dict[str, ScheduledItem] = {}
    for it, slot, start in placed:
        first = group_at.get(it.option_group) if it.option_group else None
        if first is not None:
            # open choices share one stop: same start, the clock does not advance again
            out.append(ScheduledItem(item=it, slot=first.slot, start=first.start))
            continue
        if floor is not None and start is None:
            start = _plus(floor, _ITEM_MINUTES * after_boat)
            if it.kind == "meal_out":
                start = max(start, _t(settings.slot_windows["evening"][0]))
            after_boat += 1
            out.append(ScheduledItem(item=it, slot=_slot_for(start, settings), start=start))
            if it.option_group:
                group_at[it.option_group] = out[-1]
            continue
        if slot is None:
            slot = "morning" if counts["morning"] < _MORNING_CAP else "afternoon"
            counts[slot] += 1
        if start is None:
            start = _plus(_t(settings.slot_windows[slot][0]), _ITEM_MINUTES * used[slot])
        used[slot] += 1
        out.append(ScheduledItem(item=it, slot=slot, start=start))
        if it.option_group:
            group_at[it.option_group] = out[-1]
    return sorted(out, key=lambda s: s.start)


_LUNCH_DURATION_MIN = 75
_UNKNOWN_TRAVEL_MIN = 30


def space_after_lunch(res: "DayResult", settings: Settings, travel: Optional[dict[str, Optional[int]]] = None,
                      windows: Optional[dict[str, tuple[time, time]]] = None,
                      durations: Optional[dict[str, int]] = None) -> None:
    """Untimed stops that fall after lunch start no earlier than lunch end plus the drive to them (a conservative
    30 minutes when the drive is unknown); later untimed stops are pushed on so the order never inverts."""
    lunch = next((m for m in res.meals if m.meal == "lunch" and not m.included and not m.in_package), None)
    if lunch is None:
        return
    travel = travel or {}
    floor = _minutes(lunch.start) + _LUNCH_DURATION_MIN
    changed = False
    for i, s in enumerate(res.scheduled):
        it = s.item
        if s.start < lunch.start or it.kind not in ("attraction", "activity"):
            continue
        w = (windows or {}).get(it.name)
        # the first stop of a voucher window is anchored to the window start; later ones may move
        movable = not (it.time or it.pickup_time or it.option_group or (w and s.start == w[0]))
        if movable:
            mins = travel.get(it.name)
            need = floor + (mins if mins is not None else _UNKNOWN_TRAVEL_MIN)
            if _minutes(s.start) < need < 24 * 60:
                new = time(need // 60, need % 60)
                res.scheduled[i] = ScheduledItem(item=it, slot=_slot_for(new, settings), start=new)
                changed = True
                s = res.scheduled[i]
        floor = max(floor, _minutes(s.start) + (durations or {}).get(it.name, _ITEM_MINUTES))
    if changed:
        res.scheduled.sort(key=lambda x: x.start)


_OPTIONAL_VISIT_MIN = 30
_FULL_DAY_PACKAGE_MIN = 6 * 60
_WINDOW_LUNCH_CLASH_MIN = 120
_WINDOW_LUNCH_LEAD_MIN = 90
_EARLIEST_LUNCH = time(11, 0)
_RURAL_LUNCH_MAX_MIN = 20
_BREAKFAST_LEAD_MIN = 45
_EARLIEST_BREAKFAST = time(5, 30)
_LATEST_OPTIONAL_OPENING = time(21, 0)


def is_optional(it: PlannedItem) -> bool:
    return it.optional or (it.note or "").strip().lower().startswith("choose one")


def _shift_late_openers(res: "DayResult", d: date, places: dict[str, Optional[Place]], settings: Settings) -> None:
    """An optional / choose-one stop that opens after its slot starts when the place opens, if that is the same evening."""
    changed = False
    for i, s in enumerate(res.scheduled):
        it = s.item
        if it.option_group or not is_optional(it) or it.kind not in ("attraction", "activity") or parse_time(it.time) or parse_time(it.pickup_time):
            continue
        p = places.get(it.name)
        if not (p and p.match_ok and p.hours):
            continue
        if is_open_for(p.hours, d, s.start, _OPTIONAL_VISIT_MIN):
            continue
        opening = next_opening(p.hours, d, s.start)
        if opening and opening < _LATEST_OPTIONAL_OPENING:
            res.scheduled[i] = ScheduledItem(item=it, slot=_slot_for(opening, settings), start=opening)
            changed = True
    if changed:
        res.scheduled.sort(key=lambda x: x.start)


def meal_start(meal: str, country: str, settings: Settings) -> time:
    custom = settings.country_meal_windows.get(country, {}).get(meal)
    if custom:
        return _t(custom[0])
    if meal == "breakfast":
        return _t(_BREAKFAST_WINDOW[0])
    return _t(settings.slot_windows[meal][0])


_UNKNOWN_ROAD_MIN = 30  # conservative allowance for the road when the drive time is not confirmed


def arrival_buffer_min(kind: str, domestic: bool) -> int:
    if kind == "flight":
        return 120 if domestic else 180
    return 40 if kind == "train" else 60


def leave_by(dep: TransportLeg, domestic: bool, road_min: Optional[int] = None) -> Optional[time]:
    """Departure minus the arrival buffer and, when known, the road time to the port; floored to 5 minutes."""
    if not dep.depart:
        return None
    minutes = arrival_buffer_min(dep.kind, domestic) + (road_min if road_min else _UNKNOWN_ROAD_MIN if dep.kind == "flight" else 0)
    t = dep.depart - timedelta(minutes=minutes)
    return t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0).time()


def _norm_city(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", text.casefold()).split())


_CITY_SEP = re.compile(r"\s*(?:/|→|->|,|&|\s-\s|\s+to\s+|\s+and\s+)\s*", re.I)


def split_city(text: str) -> list[str]:
    return [p for p in (x.strip() for x in _CITY_SEP.split(text or "")) if p]


def resolve_day_city(text: str, d: date, stays: list[HotelStay]) -> str:
    """A day title like 'Ubud / Nusa Lembongan' names two cities: use the one the group sleeps in that night."""
    parts = split_city(text)
    if len(parts) < 2:
        return text
    night = [s for s in stays if s.check_in <= d < s.check_out]
    for s in night:
        for part in parts:
            if _norm_city(part) == _norm_city(s.city):
                return part
    return parts[-1]


def region_day_city(text: str, d: date, stays: list[HotelStay], size) -> str:
    """A day labelled with a region ('Bali') while the group sleeps in a town ('Ubud'): use the town when the
    region has a thinner restaurant list (size(city) -> number of library restaurants)."""
    night = [s for s in stays if s.check_in <= d < s.check_out]
    if not night or any(_norm_city(s.city) == _norm_city(text) for s in stays):
        return text
    best = max(night, key=lambda s: size(s.city))
    return best.city if size(best.city) > size(text) else text


def _stay_for(stays: list[HotelStay], d: date, meal: str, start: time, city: str = "") -> Optional[HotelStay]:
    out = [s for s in stays if s.check_in < d == s.check_out]
    new = [s for s in stays if s.check_in == d]
    mid = [s for s in stays if s.check_in < d < s.check_out]
    if meal == "breakfast":
        cands = [s for s in stays if s.check_in < d <= s.check_out]
        return cands[0] if cands else None
    if city and len(out) + len(new) + len(mid) > 1:
        want = _norm_city(city)
        match = lambda xs: [s for s in xs if _norm_city(s.city) == want]
        if match(out) or match(new) or match(mid):
            out, new, mid = match(out), match(new), match(mid)
    if meal == "lunch":
        if mid:
            return mid[0]
        for s in new:
            if s.check_in_time and s.check_in_time <= start:
                return s
        return (out or new or [None])[0]
    for s in new:
        if s.check_in_time is None or s.check_in_time <= start:
            return s
    return (mid or out or new or [None])[0]


def _included(meal: str, stay: Optional[HotelStay], items: list[ScheduledItem], d: date) -> bool:
    if any(meal in s.item.includes_meal for s in items):
        return True
    if not stay:
        return False
    if meal == "dinner" and stay.check_out == d:
        return False
    plan = stay.meal_plan
    if plan in ("full_board", "all_inclusive"):
        return True
    if stay.kind == "cruise" and meal != "lunch":
        return True
    if meal == "breakfast":
        return plan in ("breakfast", "half_board")
    return meal == "dinner" and plan == "half_board"


def _cumulative_stops(day: DayPlan, start: time) -> list[tuple[str, int]]:
    t = _minutes(start)
    out = []
    for i, st in enumerate(day.drive_stops):
        t += st.minutes_from_prev + (day.drive_stops[i - 1].suggested_stop_min if i else 0)
        out.append((st.name, t))
    return out


_CHECKIN_BUFFER_MIN = 60
FULL_DAY_NAME = re.compile(r"full[- ]day|1[- ]day pass|day pass|disneyland|jungfraujoch|titlis|top of europe", re.I)
FULL_DAY_MIN = 300


def is_full_day(it: PlannedItem, durations: Optional[dict[str, int]] = None,
                windows: Optional[dict[str, tuple[time, time]]] = None) -> bool:
    """A ticketed excursion that fills the day (theme park, high-mountain trip): lunch is taken at the destination."""
    if it.kind not in ("attraction", "activity") or it.optional:
        return False
    if (durations or {}).get(it.name, 0) >= FULL_DAY_MIN:
        return True
    w = (windows or {}).get(it.name)
    if w and _minutes(w[1]) - _minutes(w[0]) >= _FULL_DAY_PACKAGE_MIN:
        return True
    return bool(FULL_DAY_NAME.search(f"{it.name} {it.note}"))


_JOURNEY_LINE = re.compile(r"(?:scenic |direct |morning |afternoon )?(?:train|flight|bus|coach|ferry|travel)(?: journey| ride| transfer)?\s+(?:to|from)\s+.+", re.I)


def is_journey_item(it: PlannedItem) -> bool:
    """An untimed itinerary line that moves the group between hotel cities ('Scenic train to Interlaken')."""
    return it.kind == "transfer" and not it.time and not it.pickup_time and bool(_JOURNEY_LINE.fullmatch(it.name.strip()))


def after_journey(res: "DayResult", minutes: Optional[int], settings: Settings) -> None:
    """Untimed visits that would start before an inter-city journey has ended (journey start + its minutes + 30)
    start after it instead, one after another. Visits already after the journey are left alone."""
    if not minutes:
        return
    j = next((s for s in res.scheduled if is_journey_item(s.item)), None)
    if j is None:
        return
    floor = _minutes(j.start) + minutes + _LEG_MARGIN_MIN
    floor = (floor + 14) // 15 * 15
    changed = False
    moved_ends: list[int] = []
    for i, s in enumerate(res.scheduled):
        it = s.item
        if s is j or it.kind == "transfer" or it.time or it.pickup_time or it.option_group or _minutes(s.start) >= floor \
                or _minutes(s.start) < _minutes(j.start) or floor >= 24 * 60:
            continue
        new = time(floor // 60, floor % 60)
        res.scheduled[i] = ScheduledItem(item=it, slot=_slot_for(new, settings), start=new)
        floor += _ITEM_MINUTES
        moved_ends.append(floor)
        changed = True
    if changed:
        res.scheduled.sort(key=lambda x: x.start)
        lunch = next((m for m in res.meals if m.meal == "lunch" and not m.included and not m.in_package), None)
        if lunch is not None:
            end = max(moved_ends)
            if _minutes(lunch.start) < end and end <= _minutes(_LATEST_LUNCH) + 60:
                lunch.start = round15(time(end // 60, end % 60))


def _is_journey_line(it: PlannedItem) -> bool:
    return it.kind == "transfer" and bool(_JOURNEY_LINE.fullmatch(it.name.strip()))


_RESTATES_DEPARTURE = re.compile(
    r"(?:(?:flight|train|bus|ferry)(?: home| departure)?|departure|departure flight|fly home|check[- ]?out(?: and departure)?)",
    re.I)
_RESTATES_ARRIVAL = re.compile(r"(?:arrival|arrive|arriving)(?:\s+(?:in|at|into|to)\s+[\w .'-]+)?", re.I)
_ONWARD_LATE_LUNCH_CUTOFF = time(16, 0)
_ONWARD_TRAIN_MIN = 75  # Basel -> Lucerne style leg that the tickets do not cover
_DEPARTURE_LUNCH_NEEDED_MIN = 135  # lunch (75) + 60 spare before leave-by
_DEPARTURE_LUNCH_MAX_MIN = 15
_FIREWORKS = re.compile(r"fireworks?|light show|illumination", re.I)
_FIREWORKS_AT = time(21, 30)


_STATION_FILLER = {"hbf", "hauptbahnhof", "station", "gare", "bahnhof", "central", "centrale", "sbb", "main", "railway", "train", "stazione"}


def station_in_city(station: str, city: str) -> bool:
    """True when a station name plausibly lies in the city ('Luzern' / 'Lucerne', 'Paris Gare du Nord' / 'Paris')."""
    from src.aigv2.google.places import _CITY_ALIASES
    st, ct = set(_norm_city(station).split()), set(_norm_city(city).split())
    names = [ct] + [set(_norm_city(a).split()) for a in _CITY_ALIASES.get(_norm_city(city), ())]
    return any(n and n <= st for n in names)


def _after_arrival(res: "DayResult", arr_t: time, settings: Settings) -> None:
    """Untimed visits on an arrival day start after the arrival plus a check-in buffer, one after another."""
    floor = _minutes(arr_t) + _CHECKIN_BUFFER_MIN
    changed = False
    for i, s in enumerate(res.scheduled):
        it = s.item
        if it.kind == "transfer" or it.time or it.pickup_time or it.option_group or _minutes(s.start) >= floor:
            continue
        if it.slot_hint == "evening" and s.start >= _t(settings.slot_windows["evening"][0]):
            continue
        new = _plus(time(floor // 60, floor % 60), 0)
        res.scheduled[i] = ScheduledItem(item=it, slot=_slot_for(new, settings), start=new)
        floor += _ITEM_MINUTES
        changed = True
    if changed:
        res.scheduled.sort(key=lambda x: x.start)


def _fireworks_last(res: "DayResult", settings: Settings) -> None:
    """An untimed fireworks / light show is the day's last event, at a late hour, not at the start of the evening."""
    changed = False
    for i, s in enumerate(res.scheduled):
        it = s.item
        if _FIREWORKS.search(it.name) and not (it.time or it.pickup_time) and s.start < _FIREWORKS_AT:
            res.scheduled[i] = ScheduledItem(item=it, slot="evening", start=_FIREWORKS_AT)
            changed = True
    if changed:
        res.scheduled.sort(key=lambda x: x.start)


def schedule_day(
    day: DayPlan,
    stays: list[HotelStay],
    arrival: Optional[TransportLeg],
    departure: Optional[TransportLeg],
    places: dict[str, Optional[Place]],
    settings: Settings,
    country: str = "",
    domestic: bool = False,
    legs: Sequence[TransportLeg] = (),
    booking_ends: Optional[dict[str, time]] = None,
    windows: Optional[dict[str, tuple[time, time]]] = None,
    durations: Optional[dict[str, int]] = None,
) -> DayResult:
    floor = boat_floor(day.date, legs, stays, (arrival, departure))
    res = DayResult(scheduled=_schedule_items(day, settings, floor, windows, durations))
    _shift_late_openers(res, day.date, places, settings)
    rules = " ".join(day.meal_rules).lower()
    d = day.date

    arr = arrival.arrive if arrival and arrival.arrive and arrival.arrive.date() == d else None
    onward = False
    if arr and arrival.kind == "train" and arrival.to_place.strip():
        new_stay = next((x for x in stays if x.check_in == d), None)
        if new_stay is not None and not station_in_city(arrival.to_place, new_stay.city):
            # the ticket ends short of the hotel city (Paris -> Basel for Lucerne): the unticketed rest takes time
            arr = arr + timedelta(minutes=_ONWARD_TRAIN_MIN)
            onward = True
    arr_t = arr.time() if arr else None
    hotel_arr = None
    if arr:
        hotel_arr = _plus(arr_t, _HOTEL_ARRIVAL_BUFFER.get(arrival.kind, _DEFAULT_BUFFER))
    dep = departure if departure and departure.depart and departure.depart.date() == d else None
    cutoff = leave_by(dep, domestic) if dep else None
    if dep and dep.depart.time() < _PACKED_BREAKFAST_BEFORE:
        res.tips.append("Ask the hotel for a packed breakfast")
    if dep:
        # the day's departure shows once (check-out, transfer and the flight card at its own time): an untimed
        # itinerary line that only restates it ('Flight', 'Departure') is dropped
        res.scheduled = [sc for sc in res.scheduled if not _is_journey_line(sc.item) and not (
            sc.item.kind == "transfer" and not sc.item.time and not sc.item.pickup_time
            and _RESTATES_DEPARTURE.fullmatch(sc.item.name.strip()))]
    if arrival is not None and arr is not None:
        # the booking card shows the arrival; an untimed itinerary line that only restates it ("Arrival in Paris")
        # would otherwise sit at a default 9:00 AM before the train even lands
        res.scheduled = [sc for sc in res.scheduled if not (
            sc.item.kind == "transfer" and not sc.item.time and not sc.item.pickup_time
            and _RESTATES_ARRIVAL.fullmatch(sc.item.name.strip()))]
    if dep and cutoff:
        # the untimed "check-out and airport drop" happens at the leave-by time, not at a default 9:00
        for i, sc in enumerate(res.scheduled):
            if sc.item.kind == "transfer" and not sc.item.time and not sc.item.pickup_time \
                    and re.search(r"airport|station|port", sc.item.name, re.I):
                res.scheduled[i] = ScheduledItem(item=sc.item, slot=_slot_for(cutoff, settings), start=cutoff)
        res.scheduled.sort(key=lambda x: x.start)
    if arr_t is not None and arr_t >= _EARLY_ARRIVAL_BEFORE and arrival.kind in ("train", "flight"):
        _after_arrival(res, arr_t, settings)
    _fireworks_last(res, settings)
    early = arr_t is not None and arr_t < _EARLY_ARRIVAL_BEFORE
    next_night = bool(arrival and arrival.arrive and arrival.arrive.date() == d + timedelta(days=1)
                      and arrival.arrive.hour < 5)
    sea = bool(_SEA_DAY.search(f"{day.title} {day.city}")) and any(s.kind == "cruise" for s in stays)
    if early or next_night or sea:
        return res

    flagged: set[str] = set()

    def coords(name: str, *fallbacks: str) -> Optional[tuple[float, float]]:
        for n in (name, *fallbacks):
            p = places.get(n)
            if p and p.match_ok:
                return (p.lat, p.lng)
        if name not in flagged:
            flagged.add(name)
            res.markers.append(Marker(kind="VERIFY", text=f"location of {name} unknown"))
        return None

    def anchors(spec: list[tuple[str, int, tuple[str, ...]]], stay: Optional[HotelStay]) -> list[Anchor]:
        out: list[Anchor] = []
        dropped = 0
        for name, n, fb in spec:
            c = coords(name, *fb)
            if c:
                out.append((name, c, n))
            else:
                dropped += n
        if dropped and stay:
            hc = coords(stay.hotel)
            if hc:
                for i, (nm, c, n) in enumerate(out):
                    if nm == stay.hotel:
                        out[i] = (nm, c, n + dropped)
                        break
                else:
                    out.append((stay.hotel, hc, dropped))
        return out

    def real(s: ScheduledItem) -> bool:
        return s.item.kind in ("attraction", "activity") and not s.item.optional

    def hotel_spec(stay: Optional[HotelStay], n: int) -> list[tuple[str, int, tuple[str, ...]]]:
        if stay:
            return [(stay.hotel, n, ())]
        if "no hotel" not in flagged:
            flagged.add("no hotel")
            res.markers.append(Marker(kind="VERIFY", text=f"no hotel known for {d.isoformat()}"))
        return []

    # a train/flight between two hotel cities is the day's arrival as well: the group is in the new city after it,
    # so the leave-by time of the old city does not close the day's meals
    full_day = next((s.item for s in res.scheduled if is_full_day(s.item, durations, windows)), None)
    meal_cutoff = None if arrival is not None and arrival is departure else cutoff

    def included_lunch(stay: Optional[HotelStay]) -> bool:
        return _included("lunch", stay, res.scheduled, d)

    def add(meal: str, start: time, stay: Optional[HotelStay], spec, max_min: Optional[int] = None) -> None:
        if meal_cutoff is not None and start >= meal_cutoff:
            return
        if meal == "lunch" and dep is not None and meal_cutoff is not None and not included_lunch(stay):
            # departure day: a sit-down lunch needs an hour to spare before leave-by, and a restaurant close by
            if _minutes(meal_cutoff) - (_minutes(start) + _LUNCH_DURATION_MIN) < 60:
                res.tips.append("Lunch: have a light meal at the airport")
                return
            max_min = _DEPARTURE_LUNCH_MAX_MIN
        if _included(meal, stay, res.scheduled, d):
            res.meals.append(MealSlot(meal=meal, start=start, included=True))
            return
        found = anchors(spec(), stay)
        label = None
        if not found and meal == "lunch" and visit_first and not at_hotel_rule:
            seen = lunch_anchor_item()
            label = re.sub(r"\s*\([^)]*\)", "", seen.name).strip() if seen else None
        elif not found and (meal == "lunch" or (meal == "dinner" and show_at_park)) and full_day is not None \
                and not at_hotel_rule:
            label = re.sub(r"\s*\([^)]*\)", "", full_day.name).strip()  # no hotel-city restaurants for a lunch elsewhere
        res.meals.append(MealSlot(meal=meal, start=start, anchors=found, unanchored=not found, max_min=max_min,
                                  near_label=label))

    # breakfast
    b_start = meal_start("breakfast", country, settings)
    b_stay = _stay_for(stays, d, "breakfast", b_start)
    if res.scheduled and res.scheduled[0].start <= b_start:
        # an early pick-up: breakfast comes before the group leaves, not after
        b_start = _plus(res.scheduled[0].start, -_BREAKFAST_LEAD_MIN)
        if b_start < _EARLIEST_BREAKFAST or b_start > res.scheduled[0].start:
            b_stay = None
    if b_stay and not (arr_t and arr_t > b_start):
        out_rule = "breakfast out" in rules
        if _included("breakfast", b_stay, res.scheduled, d) or out_rule:
            add("breakfast", b_start, b_stay, lambda: hotel_spec(b_stay, 3))

    # lunch
    l_start = meal_start("lunch", country, settings)
    l_stay = _stay_for(stays, d, "lunch", l_start, day.city)
    l_drop = False
    for lg in legs:
        if not (lg.depart and lg.depart.date() == d) or lg == arrival or lg == departure:
            continue
        end = lg.arrive if lg.arrive and lg.arrive.date() == d and lg.arrive > lg.depart \
            else lg.depart + timedelta(minutes=_LEG_DEFAULT_MIN)
        margin = timedelta(minutes=_LEG_MARGIN_MIN)
        ls = datetime.combine(d, l_start)
        if lg.depart - margin <= ls <= end + margin:
            shifted = end + margin
            if shifted.date() != d or shifted.time() > _LATEST_LUNCH:
                l_drop = True
                break
            l_start = shifted.time()
    for w_start in sorted({w[0] for w in (windows or {}).values()}):
        if l_start < w_start < _plus(l_start, _WINDOW_LUNCH_CLASH_MIN):
            # the tour leaves right after the usual lunch hour: eat before the pick-up, not mid-transfer
            l_start = max(_plus(w_start, -_WINDOW_LUNCH_LEAD_MIN), _EARLIEST_LUNCH)
    if hotel_arr is not None and hotel_arr > l_start and arrival is not None and arrival.depart \
            and arrival.depart.date() == d and (arrival.depart.time() < l_start or onward):
        l_start = round15(hotel_arr)  # still on the train/flight at the usual lunch hour: lunch follows the arrival
    new = [s for s in stays if s.check_in == d]
    midday_checkin = any(s.check_in_time and time(11) <= s.check_in_time <= time(13) for s in new)
    midday_arrival = hotel_arr is not None and time(11) <= hotel_arr <= time(13)
    late = hotel_arr is not None and hotel_arr > (_ONWARD_LATE_LUNCH_CUTOFF if onward else _LATE_LUNCH_CUTOFF)
    morning = [s for s in res.scheduled if s.slot == "morning" and real(s)]
    at_hotel_rule = "lunch at hotel" in rules or any(
        0 <= r.find("return to hotel") < r.find("lunch") for r in (x.lower() for x in day.meal_rules))
    port = bool(l_stay and l_stay.kind == "cruise")
    show_at_park = full_day is not None and not at_hotel_rule and any(
        _FIREWORKS.search(x.item.name) for x in res.scheduled)

    def lunch_anchor_item() -> Optional[PlannedItem]:
        pool = [s for s in res.scheduled if s.slot in ("morning", "afternoon") and real(s) and s.start <= l_start]
        if not pool:
            return None
        all_real = [s for s in res.scheduled if s.slot in ("morning", "afternoon") and real(s)]

        def est(s: ScheduledItem) -> float:
            group = [g for g in all_real if g.start == s.start]
            if len(group) < 2:
                return _minutes(s.start)
            end = next((_minutes(booking_ends[g.item.name]) for g in group
                        if booking_ends and g.item.name in booking_ends), None)
            begin = _minutes(s.start)
            if end is None or end <= begin:
                end = begin + _TOUR_DEFAULT_MIN
            return begin + (group.index(s) + 0.5) * (end - begin) / len(group)

        def matched(s: ScheduledItem) -> bool:
            p = places.get(s.item.name)
            return bool(p and p.match_ok)

        target = _minutes(l_start)
        best = min(pool, key=lambda s: (_is_vague(s.item.name), not matched(s), abs(est(s) - target)))
        return best.item

    # a hotel-change day whose visits come before the untimed journey: lunch is where the visits are, not at the new hotel
    journey = next((x for x in res.scheduled if is_journey_item(x.item)), None)
    visit_first = bool(journey is not None and arrival is None and any(
        real(x) and x.start < journey.start for x in res.scheduled))

    def lunch_spec():
        if visit_first and not at_hotel_rule:
            it = lunch_anchor_item()
            p = places.get(it.name) if it else None
            if it is not None and p is not None and p.match_ok:
                return [(it.locality or it.name, 3, (it.name,))]
            return []
        if full_day is not None and not at_hotel_rule:
            p = places.get(full_day.name)
            if p is not None and p.match_ok:
                return [(full_day.locality or full_day.name, 3, (full_day.name,))]
            return []
        if at_hotel_rule or midday_checkin or midday_arrival:
            return hotel_spec(l_stay, 3)
        if day.drive_stops:
            first = parse_time(day.items[0].time) if day.items else None
            stops = _cumulative_stops(day, first or _t(settings.slot_windows["morning"][0]))
            name = min(stops, key=lambda x: abs(x[1] - 13 * 60))[0]
            return [(name, 3, ())]
        it = lunch_anchor_item()
        if it:
            return [(it.locality or it.name, 3, (it.name,))]
        if port:
            return [(day.city, 3, ())]
        return hotel_spec(l_stay, 3)

    covering = next((s for s in res.scheduled if booking_ends and s.item.name in booking_ends
                     and real(s) and s.start <= l_start < booking_ends[s.item.name]
                     and sum(1 for x in res.scheduled if x.start == s.start and real(x)) == 1
                     and _minutes(booking_ends[s.item.name]) - _minutes(s.start) >= _FULL_DAY_PACKAGE_MIN), None)
    tour_day = any(_minutes(w[1]) - _minutes(w[0]) >= _FULL_DAY_PACKAGE_MIN for w in (windows or {}).values())
    # a lunch taken out on a long tour day is anchored on the stop where the group is at lunchtime: the
    # countryside around it needs a wider drive than a hotel in town
    rural_cap = _RURAL_LUNCH_MAX_MIN if tour_day and not (at_hotel_rule or midday_checkin or midday_arrival) \
        and not day.drive_stops else None
    if covering is not None and not (meal_cutoff is not None and l_start >= meal_cutoff):
        slot = MealSlot(meal="lunch", start=l_start, in_package=True)
        it = lunch_anchor_item()
        p = places.get(it.name) if it else None
        if it is not None and p is not None and p.match_ok and not _is_vague(it.name):
            # options are offered at the stop where the group is at lunchtime; the unmatched case keeps the note only
            slot.anchors = [(it.locality or it.name, (p.lat, p.lng), 3)]
            slot.max_min = _RURAL_LUNCH_MAX_MIN
        res.meals.append(slot)
    elif not late and not l_drop:
        add("lunch", l_start, l_stay, lunch_spec, rural_cap if rural_cap and lunch_anchor_item() is not None else None)

    # dinner
    d_start = meal_start("dinner", country, settings)
    d_stay = _stay_for(stays, d, "dinner", d_start, day.city)
    evening = [s for s in res.scheduled if s.slot == "evening" and real(s)]

    def dinner_spec():
        joined = " ".join(day.meal_rules)
        if show_at_park:
            # a late show at the park: dinner is at the park before it, not an hour away at the hotel
            p = places.get(full_day.name)
            return [(full_day.locality or full_day.name, 3, (full_day.name,))] if p is not None and p.match_ok else []
        names = "|".join(["hotel"] + ([re.escape(d_stay.hotel)] if d_stay else []))
        if re.search(rf"dinner\s+(?:at|in|near|before|after)?\s*(?:the\s+|my\s+|your\s+)?(?:{names})\b", joined, re.I):
            return hotel_spec(d_stay, 3)
        m = _DINNER_RULE.search(joined)
        target = ""
        if m:
            target = re.split(r"\s+and\s+", m.group(1).strip(), maxsplit=1)[0].strip().rstrip(".")
            if parse_time(target):
                target = ""
        if target:
            for s in res.scheduled:
                n = s.item.name.lower()
                if n in target.lower() or target.lower() in n:
                    return [(s.item.name, 3, ())]
            return [(target, 3, ())]
        if evening:
            it = evening[-1].item
            return [(it.name, 1, ()), *hotel_spec(d_stay, 2)] if d_stay else [(it.name, 3, ())]
        return hotel_spec(d_stay, 3)

    if not (arr_t and arr_t > _NO_DINNER_AFTER):
        add("dinner", d_start, d_stay, dinner_spec)

    return res
