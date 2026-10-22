import re
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.aigv2.config import Settings
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
_EARLY_ARRIVAL_BEFORE = time(5, 0)
_PACKED_BREAKFAST_BEFORE = time(7, 0)
_DEFAULT_CHECKIN = time(15, 0)
_TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})(?:\s*([ap])\.?m\b)?|(\d{1,2})\s*([ap])\.?m\b", re.I)
_DINNER_RULE = re.compile(r"dinner\s+(?:before|between|near)\s+(.+)", re.I)
_SEA_DAY = re.compile(r"\bat sea\b|\bsea day\b", re.I)


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


def _schedule_items(day: DayPlan, settings: Settings) -> list[ScheduledItem]:
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
    for it, slot, start in placed:
        if slot is None:
            slot = "morning" if counts["morning"] < _MORNING_CAP else "afternoon"
            counts[slot] += 1
        if start is None:
            start = _plus(_t(settings.slot_windows[slot][0]), _ITEM_MINUTES * used[slot])
        used[slot] += 1
        out.append(ScheduledItem(item=it, slot=slot, start=start))
    return sorted(out, key=lambda s: s.start)


def meal_start(meal: str, country: str, settings: Settings) -> time:
    custom = settings.country_meal_windows.get(country, {}).get(meal)
    if custom:
        return _t(custom[0])
    if meal == "breakfast":
        return _t(_BREAKFAST_WINDOW[0])
    return _t(settings.slot_windows[meal][0])


def leave_by(dep: TransportLeg, domestic: bool) -> Optional[time]:
    if not dep.depart:
        return None
    if dep.kind == "flight":
        minutes = 120 if domestic else 180
    elif dep.kind == "train":
        minutes = 40
    else:
        minutes = 60
    return (dep.depart - timedelta(minutes=minutes)).time()


def _stay_for(stays: list[HotelStay], d: date, meal: str, start: time) -> Optional[HotelStay]:
    out = [s for s in stays if s.check_in < d == s.check_out]
    new = [s for s in stays if s.check_in == d]
    mid = [s for s in stays if s.check_in < d < s.check_out]
    if meal == "breakfast":
        cands = [s for s in stays if s.check_in < d <= s.check_out]
        return cands[0] if cands else None
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
) -> DayResult:
    res = DayResult(scheduled=_schedule_items(day, settings))
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
    sea = bool(_SEA_DAY.search(f"{day.title} {day.city}")) and any(s.kind == "cruise" for s in stays)
    if early or sea:
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
    l_stay = _stay_for(stays, d, "lunch", l_start)
    new = [s for s in stays if s.check_in == d]
    midday_checkin = any(s.check_in_time and time(11) <= s.check_in_time <= time(13) for s in new)
    midday_arrival = hotel_arr is not None and time(11) <= hotel_arr <= time(13)
    late = hotel_arr is not None and hotel_arr > _LATE_LUNCH_CUTOFF
    morning = [s for s in res.scheduled if s.slot == "morning" and real(s)]
    at_hotel_rule = "lunch at hotel" in rules or any(
        0 <= r.find("return to hotel") < r.find("lunch") for r in (x.lower() for x in day.meal_rules))
    port = bool(l_stay and l_stay.kind == "cruise")

    def lunch_spec():
        if at_hotel_rule or midday_checkin or midday_arrival:
            return hotel_spec(l_stay, 3)
        if day.drive_stops:
            first = parse_time(day.items[0].time) if day.items else None
            stops = _cumulative_stops(day, first or _t(settings.slot_windows["morning"][0]))
            name = min(stops, key=lambda x: abs(x[1] - 13 * 60))[0]
            return [(name, 3, ())]
        if morning:
            it = morning[-1].item
            return [(it.locality or it.name, 3, (it.name,))]
        if port:
            return [(day.city, 3, ())]
        return hotel_spec(l_stay, 3)

    if not late:
        add("lunch", l_start, l_stay, lunch_spec)

    # dinner
    d_start = meal_start("dinner", country, settings)
    d_stay = _stay_for(stays, d, "dinner", d_start)
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
