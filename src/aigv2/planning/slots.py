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


class MealSlot(BaseModel):
    meal: Literal["breakfast", "lunch", "dinner"]
    start: time
    anchors: list[Anchor] = Field(default_factory=list)
    included: bool = False
    unanchored: bool = False


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


def _schedule_items(day: DayPlan, settings: Settings, floor: Optional[time] = None) -> list[ScheduledItem]:
    placed: list[tuple[PlannedItem, Optional[Slot], Optional[time]]] = []
    for it in day.items:
        start = parse_time(it.pickup_time) or parse_time(it.time)
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
    for it, slot, start in placed:
        if floor is not None and start is None:
            start = _plus(floor, _ITEM_MINUTES * after_boat)
            if it.kind == "meal_out":
                start = max(start, _t(settings.slot_windows["evening"][0]))
            after_boat += 1
            out.append(ScheduledItem(item=it, slot=_slot_for(start, settings), start=start))
            continue
        if slot is None:
            slot = "morning" if counts["morning"] < _MORNING_CAP else "afternoon"
            counts[slot] += 1
        if start is None:
            start = _plus(_t(settings.slot_windows[slot][0]), _ITEM_MINUTES * used[slot])
        used[slot] += 1
        out.append(ScheduledItem(item=it, slot=slot, start=start))
    return sorted(out, key=lambda s: s.start)


_OPTIONAL_VISIT_MIN = 30
_LATEST_OPTIONAL_OPENING = time(21, 0)


def is_optional(it: PlannedItem) -> bool:
    return it.optional or (it.note or "").strip().lower().startswith("choose one")


def _shift_late_openers(res: "DayResult", d: date, places: dict[str, Optional[Place]], settings: Settings) -> None:
    """An optional / choose-one stop that opens after its slot starts when the place opens, if that is the same evening."""
    changed = False
    for i, s in enumerate(res.scheduled):
        it = s.item
        if not is_optional(it) or it.kind not in ("attraction", "activity") or parse_time(it.time) or parse_time(it.pickup_time):
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


def arrival_buffer_min(kind: str, domestic: bool) -> int:
    if kind == "flight":
        return 120 if domestic else 180
    return 40 if kind == "train" else 60


def leave_by(dep: TransportLeg, domestic: bool, road_min: Optional[int] = None) -> Optional[time]:
    """Departure minus the arrival buffer and, when known, the road time to the port; floored to 5 minutes."""
    if not dep.depart:
        return None
    minutes = arrival_buffer_min(dep.kind, domestic) + (road_min or 0)
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
) -> DayResult:
    floor = boat_floor(day.date, legs, stays, (arrival, departure))
    res = DayResult(scheduled=_schedule_items(day, settings, floor))
    _shift_late_openers(res, day.date, places, settings)
    rules = " ".join(day.meal_rules).lower()
    d = day.date

    arr = arrival.arrive if arrival and arrival.arrive and arrival.arrive.date() == d else None
    arr_t = arr.time() if arr else None
    hotel_arr = None
    if arr:
        hotel_arr = _plus(arr_t, _HOTEL_ARRIVAL_BUFFER.get(arrival.kind, _DEFAULT_BUFFER))
    dep = departure if departure and departure.depart and departure.depart.date() == d else None
    cutoff = leave_by(dep, domestic) if dep else None
    if dep and dep.depart.time() < _PACKED_BREAKFAST_BEFORE:
        res.tips.append("Ask the hotel for a packed breakfast")
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

    def add(meal: str, start: time, stay: Optional[HotelStay], spec) -> None:
        if cutoff is not None and start >= cutoff:
            return
        if _included(meal, stay, res.scheduled, d):
            res.meals.append(MealSlot(meal=meal, start=start, included=True))
            return
        found = anchors(spec(), stay)
        res.meals.append(MealSlot(meal=meal, start=start, anchors=found, unanchored=not found))

    # breakfast
    b_start = meal_start("breakfast", country, settings)
    b_stay = _stay_for(stays, d, "breakfast", b_start)
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
    new = [s for s in stays if s.check_in == d]
    midday_checkin = any(s.check_in_time and time(11) <= s.check_in_time <= time(13) for s in new)
    midday_arrival = hotel_arr is not None and time(11) <= hotel_arr <= time(13)
    late = hotel_arr is not None and hotel_arr > _LATE_LUNCH_CUTOFF
    morning = [s for s in res.scheduled if s.slot == "morning" and real(s)]
    at_hotel_rule = "lunch at hotel" in rules or any(
        0 <= r.find("return to hotel") < r.find("lunch") for r in (x.lower() for x in day.meal_rules))
    port = bool(l_stay and l_stay.kind == "cruise")

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

    def lunch_spec():
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

    if not late and not l_drop:
        add("lunch", l_start, l_stay, lunch_spec)

    # dinner
    d_start = meal_start("dinner", country, settings)
    d_stay = _stay_for(stays, d, "dinner", d_start, day.city)
    evening = [s for s in res.scheduled if s.slot == "evening" and real(s)]

    def dinner_spec():
        joined = " ".join(day.meal_rules)
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
