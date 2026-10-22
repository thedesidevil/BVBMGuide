import re
from datetime import date, time
from typing import Optional

import requests
from pydantic import BaseModel

from src.aigv2.config import Settings
from src.aigv2.hours import format_for_day, is_open_for
from src.aigv2.models import Place, TripPlan
from src.aigv2.qc.reader import DocModel, DocVenue
from src.aigv2.qc.rules import _f

_NEAR = re.compile(r"\bnear\s+(.+)$", re.I)
_TRAVEL = re.compile(r"(Walk|By car|By public transport)\s*·\s*(\d+)\s*min", re.I)
_MODES = {"walk": "WALK", "by car": "DRIVE", "by public transport": "TRANSIT"}
_SLOT_START = {"breakfast": "07:30", "morning": "09:00", "lunch": "12:30", "afternoon": "14:00",
               "evening": "17:30", "dinner": "19:30"}
_LOOKUP_ERRORS = (requests.RequestException, ValueError, KeyError)
_UNVERIFIED = "Not verified"
_VISIT_MIN = 30
_MAX_DIFF_MIN = 5
_MAX_DIFF_RATIO = 0.3


class FactRow(BaseModel):
    day: int
    venue: str
    guide_hours: str
    google_hours: str
    guide_travel: str
    google_travel: str
    link: str
    match: bool


def _slot_time(heading: str) -> Optional[time]:
    word = heading.split()[0].casefold() if heading.split() else ""
    start = _SLOT_START.get(word) or Settings(models={}).slot_windows.get(word, (None,))[0]
    if not start:
        return None
    h, m = start.split(":")
    return time(int(h), int(m))


def _minutes_text(mode: str, minutes: int) -> str:
    return f"{mode} · {minutes} min"


def _guide_travel(v: DocVenue) -> list[tuple[str, int]]:
    text = v.facts.get("GETTING THERE", "")
    return [(m.group(1), int(m.group(2))) for m in _TRAVEL.finditer(text)]


def _differs(guide: int, google: int) -> bool:
    diff = abs(guide - google)
    return diff > _MAX_DIFF_MIN or diff > _MAX_DIFF_RATIO * google


def _unverified(v: DocVenue, day_no: int, what: str):
    return _f("fact_unverified", f"Could not verify {what} for {v.name}; check it by hand", v.name, day_no, "warning")


def check_facts(doc: DocModel, trip: TripPlan, places, routes, fresh: bool = True) -> tuple[list, list[FactRow]]:
    findings, rows = [], []
    plan_days = sorted(trip.days, key=lambda d: d.date)
    for day in doc.days:
        if day.index is None or not 1 <= day.index <= len(plan_days):
            continue
        plan = plan_days[day.index - 1]
        for slot in day.slots:
            near = _NEAR.search(slot.heading)
            for v in slot.venues:
                if v.kind != "venue":
                    continue
                try:
                    f, row = _check_venue(v, day.index, plan.date, plan.city, slot.heading,
                                          near.group(1).strip() if near else None, places, routes, fresh)
                except _LOOKUP_ERRORS as e:
                    f = [_f("fact_check_failed", f"{v.name}: Google lookup failed ({e.__class__.__name__})",
                            v.name, day.index)]
                    row = _row(v, day.index, _UNVERIFIED, "", _UNVERIFIED, False)
                findings += f
                rows.append(row)
    return findings, rows


def _row(v: DocVenue, day_no: int, google_hours: str, guide_travel: str, google_travel: str, match: bool) -> FactRow:
    return FactRow(day=day_no, venue=v.name, guide_hours=v.facts.get("OPENING HOURS", ""), google_hours=google_hours,
                   guide_travel=guide_travel, google_travel=google_travel, link=v.url or "", match=match)


def _check_venue(v: DocVenue, day_no: int, d: date, city: str, heading: str, anchor: Optional[str],
                 places, routes, fresh: bool):
    cached = places.find(v.name, city)
    place = None
    if cached is not None and cached.match_ok:
        place = places.find(v.name, city, near=(cached.lat, cached.lng), fresh=True) if fresh else cached
    if place is None or not place.match_ok:
        return [_unverified(v, day_no, "status, hours and travel time (no confident Google match)")], \
            _row(v, day_no, _UNVERIFIED, "", _UNVERIFIED, False)
    findings = []
    if place.status in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
        state = "permanently" if place.status == "CLOSED_PERMANENTLY" else "temporarily"
        findings.append(_f("closed_now", f"{v.name} is shown as closed {state} on Google", v.name, day_no))
    elif place.status == "UNKNOWN":
        findings.append(_unverified(v, day_no, "business status"))
    start = _slot_time(heading)
    if place.hours is None:
        findings.append(_unverified(v, day_no, "opening hours (Google has none)"))
    elif start is None:
        findings.append(_unverified(v, day_no, "opening hours (unknown slot time)"))
    elif is_open_for(place.hours, d, start, _VISIT_MIN) is False:
        findings.append(_f("not_open_at_slot", f"{v.name} does not look open on {d:%a %d %b} at {start:%H:%M} "
                           f"(Google: {format_for_day(place.hours, d)})", v.name, day_no))
    guide_travel, google_travel = _travel(v, city, anchor, place, places, routes, findings, day_no)
    return findings, _row(v, day_no, format_for_day(place.hours, d), guide_travel, google_travel, not findings)


def _travel(v, city, anchor, place: Place, places, routes, findings, day_no):
    if not anchor:
        return "", ""
    legs = _guide_travel(v)
    if not legs:
        findings.append(_unverified(v, day_no, "travel time (none stated in the guide)"))
        return "", ""
    a = places.find(anchor, city)
    if a is None or not a.match_ok:
        findings.append(_unverified(v, day_no, f"travel time (could not locate {anchor})"))
        return "; ".join(_minutes_text(l, m) for l, m in legs), ""
    guide, google = [], []
    for label, minutes in legs:
        mode = _MODES[label.casefold()]
        got = routes.durations([(a.lat, a.lng)], [(place.lat, place.lng)], mode).get((0, 0))
        guide.append(_minutes_text(label, minutes))
        if got is None:
            findings.append(_unverified(v, day_no, f"{label.lower()} travel time (no Google route)"))
            continue
        google.append(_minutes_text(label, got))
        if _differs(minutes, got):
            findings.append(_f("travel_time_mismatch", f"{v.name}: guide says {label.lower()} {minutes} min from "
                               f"{anchor}, Google says {got} min", v.name, day_no))
    return "; ".join(guide), "; ".join(google)
