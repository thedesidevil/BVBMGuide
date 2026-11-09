"""Every question that relates to a day starts with 'Day N (Sat 2 May) - ' so the team knows which day it is about."""
import re
from datetime import date, datetime
from typing import Iterable, Optional

from src.aigv2.models import Question, TripPlan
from src.aigv2.textnorm import fold

_HAS_DAY = re.compile(r"^\s*(?:Days?\s+\d|Whole trip|\w{3} \d{1,2} \w{3} - )")
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _short(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def day_label(trip: TripPlan, dates: Iterable[date]) -> str:
    """'Day 2 (Sat 2 May) - ', 'Days 2-3 (Sat 2 May - Sun 3 May) - ' or 'Sat 2 May - ' for a date outside the trip days."""
    ds = sorted(set(dates))
    if not ds:
        return "Whole trip - "
    order = {dp.date: i for i, dp in enumerate(sorted(trip.days, key=lambda x: x.date), 1)}
    nums = [order[d] for d in ds if d in order]
    span = _short(ds[0]) if len(ds) == 1 else f"{_short(ds[0])} - {_short(ds[-1])}"
    if not nums:
        return f"{span} - "
    if len(nums) == 1:
        return f"Day {nums[0]} ({span}) - "
    if nums == list(range(nums[0], nums[-1] + 1)):
        return f"Days {nums[0]}-{nums[-1]} ({span}) - "
    return f"Days {', '.join(map(str, nums))} ({span}) - "


def _parse_date(text: str, trip: TripPlan) -> Optional[date]:
    t = text.strip()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[a-z]*\.?(?:,?\s+(\d{4}))?", t) or None
    mon = day = year = None
    if m and m.group(2).lower() in _MONTHS:
        day, mon, year = int(m.group(1)), _MONTHS[m.group(2).lower()], m.group(3)
    else:
        m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?", t)
        if m and m.group(1).lower() in _MONTHS:
            day, mon, year = int(m.group(2)), _MONTHS[m.group(1).lower()], m.group(3)
    if mon is None:
        return None
    years = [int(year)] if year else sorted({dp.date.year for dp in trip.days})
    for y in years:
        try:
            cand = date(y, mon, day)
        except ValueError:
            continue
        if not trip.days or any(dp.date == cand for dp in trip.days) or year:
            return cand
    return None


def _choice_dates(trip: TripPlan, q: Question, idx: int) -> list[date]:
    oc = trip.open_choices[idx] if 0 <= idx < len(trip.open_choices) else None
    if oc is None:
        return []
    if oc.day:
        return [oc.day]
    keys = [fold(o) for o in oc.options if fold(o)]
    hits = [dp.date for dp in trip.days
            if any(k in fold(dp.title + " " + " ".join(i.name + " " + i.note for i in dp.items)) for k in keys)]
    return hits


def question_dates(q: Question, trip: TripPlan, attachments=()) -> list[date]:
    if q.day:
        return [q.day]
    kind, suffix = q.kind, (q.id.split(":", 1)[1] if ":" in q.id else "")
    if kind == "open_choice":
        try:
            return _choice_dates(trip, q, int(suffix))
        except ValueError:
            return []
    if kind == "no_departure":
        return [max(dp.date for dp in trip.days)] if trip.days else []
    if kind == "headcount":
        for leg in trip.transport:
            if suffix in (leg.ref, leg.number, f"{leg.from_place}-{leg.to_place}"):
                when = leg.depart or leg.arrive
                return [when.date()] if when else []
    if kind == "image_details":
        name = suffix
        a = next((x for x in attachments if x.name == name), None)
        found = {d for s in (getattr(a, "text_dates", None) or []) if (d := _parse_date(s, trip))}
        days = {dp.date for dp in trip.days}
        return sorted(found & days) if found & days else []
    return []


def prefix_questions(qs: list[Question], trip: TripPlan, attachments=()) -> list[Question]:
    for q in qs:
        if _HAS_DAY.match(q.text) or q.kind in ("missing", "unreadable", "zip_skipped", "image_only", "no_library",
                                                 "days_mismatch", "kids_ages", "conflict"):
            continue
        ds = question_dates(q, trip, attachments)
        if not ds and q.kind == "image_details":
            continue  # the dates are in the pasted text, not the file: no prefix rather than 'Whole trip'
        if ds and not q.day:
            q.day = ds[0]
        q.text = day_label(trip, ds) + q.text
    return qs
