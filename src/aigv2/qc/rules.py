import re
from collections import Counter
from datetime import date
from typing import Iterable, Optional

from src.aigv2.library import Library, diet_fits, norm_name
from src.aigv2.models import Finding, TripPlan
from src.aigv2.qc.reader import MAPS_RE, MEAL_SLOT_RE, SECTION_TITLES, THANK_YOU, DocDay, DocModel, DocSlot, DocVenue

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
HEADER_RE = re.compile(r"^Day (\d+) – (Mon|Tue|Wed|Thu|Fri|Sat|Sun), (\d{1,2}) "
                       r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \| \S.*$")
_DAY_PREFIX = re.compile(r"^Day\s*\d+")
_WEEKDAY_RE = re.compile(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day|s|sday|nesday|rsday|r|urday)?\b", re.I)
_MON = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
_DATE_DM = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON, re.I)
_DATE_MD = re.compile(r"\b" + _MON + r"\s+(\d{1,2})\b", re.I)

PLACEHOLDER_RE = re.compile(r"\[fill in|\bTBD\b|mention timings|lorem|Not specified|Please see options below|"
                            r"choose one of", re.I)
CHATTER_RE = re.compile(r"\bI would recommend\b|\bI['’]d (?:aim|keep|suggest|skip|treat|choose)\b|\bHere are clear\b|"
                        r"\bin your preferred format\b|\bLet me know if\b|\bas an AI\b", re.I)
CLOSING_RE = re.compile(r"\b(?:we\s+(?:truly\s+)?hope\s+(?:this|your)\s+(?:vacation|trip|journey|holiday)|"
                        r"hope\s+(?:this|your)\s+(?:vacation|trip|journey|holiday)\s+(?:brought|was|has been|gave)|"
                        r"thank you for (?:giving us the opportunity|choosing|trusting))", re.I)
THIRD_PERSON_RE = re.compile(r"\b(?:her|him|the client['’]?s?|the clients['’]?)\b", re.I)
_WALK_RES = [re.compile(r"\bwalk(?:ing)?\s*[·:\-–—]?\s*(?:about\s+)?(\d+)\s*(?:min|minutes?)\b", re.I),
             re.compile(r"\b(\d+)\s*-?\s*min(?:ute)?s?\.?\s+(?:walk|on foot)", re.I)]
_TRANSPORT = re.compile(r"^(Flight|Train|Boat|Bus|Transfer)\b|→")
_MEALS = ("breakfast", "lunch", "dinner")
_MARKER_KIND = re.compile(r"⚠ ([A-Z ]*[A-Z])")
_BEST_FOR_RE = re.compile(r"best for[^.\n]{0,30}?\b(breakfast|lunch|dinner)\b", re.I)


def _f(rule, message, anchor="", day=None, severity="error") -> Finding:
    return Finding(rule=rule, severity=severity, message=message, anchor_text=anchor, day=day)


def _trip_days(trip: TripPlan):
    return sorted(trip.days, key=lambda d: d.date)


def _section_order(doc: DocModel) -> list[Finding]:
    h1 = [t for lvl, t in doc.headings if lvl == 1]
    day_pos = [i for i, t in enumerate(h1) if _DAY_PREFIX.match(t)]
    known = [(i, t) for i, t in enumerate(h1) if t in SECTION_TITLES]
    out = []
    if not day_pos:
        out.append(_f("section_order", "No day headers found"))
    last_day = day_pos[-1] if day_pos else -1
    prev = -1
    for i, t in known:
        rank = SECTION_TITLES.index(t)
        if i < last_day:
            out.append(_f("section_order", f"'{t}' appears before the last day", t))
        elif rank < prev:
            out.append(_f("section_order", f"'{t}' is out of order", t))
        prev = max(prev, rank)
    if THANK_YOU not in h1:
        out.append(_f("section_order", "Thank You page missing"))
    elif h1[-1] != THANK_YOU:
        out.append(_f("section_order", "Thank You page is not last", THANK_YOU))
    return out


def _parse_header(text: str) -> tuple[Optional[int], Optional[tuple[int, int]]]:
    rest = _DAY_PREFIX.sub("", text, count=1)
    head = rest.split("|")[0]
    wd = _WEEKDAY_RE.search(head)
    weekday = _WEEKDAYS.index(wd.group(1).lower()) if wd else None
    m = _DATE_DM.search(head)
    md = (_MONTHS.index(m.group(2)[:3].lower()) + 1, int(m.group(1))) if m else None
    if md is None:
        m = _DATE_MD.search(head)
        md = (_MONTHS.index(m.group(1)[:3].lower()) + 1, int(m.group(2))) if m else None
    return weekday, md


def _resolve(md: tuple[int, int], near: date) -> Optional[date]:
    cands = []
    for y in (near.year - 1, near.year, near.year + 1):
        try:
            cands.append(date(y, *md))
        except ValueError:
            pass
    return min(cands, key=lambda d: abs((d - near).days)) if cands else None


def _days(doc: DocModel, trip: TripPlan) -> list[Finding]:
    out, tdays = [], _trip_days(trip)
    seen = set()
    for d in doc.days:
        n = d.index
        seen.add(n)
        if not HEADER_RE.match(d.header):
            out.append(_f("day_header_format", "Day header should look like 'Day 1 – Thu, 29 Oct | Title'",
                          d.header, n))
        weekday, md = _parse_header(d.header)
        expected = tdays[n - 1].date if n and 0 < n <= len(tdays) else None
        if expected is None:
            out.append(_f("day_dates", f"Day {n} is not in the trip ({len(tdays)} days)", d.header, n))
        if md is None:
            continue
        near = expected or (tdays[0].date if tdays else date.today())
        actual = _resolve(md, near)
        if actual and weekday is not None and actual.weekday() != weekday:
            out.append(_f("day_weekday", f"{actual:%d %b %Y} is a {actual:%A}, not the weekday in the header",
                          d.header, n))
        if expected and actual and (actual.month, actual.day) != (expected.month, expected.day):
            out.append(_f("day_dates", f"Header date {actual:%d %b} but trip day {n} is {expected:%a, %d %b}",
                          d.header, n))
    for i, td in enumerate(tdays, 1):
        if doc.days and i not in seen:
            out.append(_f("day_dates", f"Day {i} ({td.date:%a, %d %b}) is missing from the guide", "", i))
    return out


def _venue_link(doc: DocModel) -> list[Finding]:
    out = []
    pairs = [(v, d.index) for d in doc.days for s in d.slots for v in s.venues]
    pairs += [(v, None) for v in doc.section_venues]
    for v, n in pairs:
        if not v.url:
            out.append(_f("venue_link", f"'{v.name}' has no Google Maps link", v.name, n))
        elif not MAPS_RE.match(v.url):
            out.append(_f("venue_link", f"'{v.name}' links to {v.url}, not Google Maps", v.name, n))
    return out


def _is_restaurant(v: DocVenue) -> bool:
    return not _TRANSPORT.search(v.name)


def _meal_groups(day: DocDay) -> list[tuple[str, list[DocSlot]]]:
    groups: list[tuple[str, list[DocSlot]]] = []
    prev_meal = None
    for s in day.slots:
        m = MEAL_SLOT_RE.match(s.heading)
        if not m or "included" in s.heading.casefold():
            prev_meal = None
            continue
        meal = m.group(1).lower()
        if meal == prev_meal:
            groups[-1][1].append(s)
        else:
            groups.append((meal, [s]))
        prev_meal = meal
    return groups


def _venues(slots: Iterable[DocSlot]) -> list[DocVenue]:
    return [v for s in slots for v in s.venues if _is_restaurant(v)]


def _meals(doc: DocModel, trip: TripPlan, library: Library) -> list[Finding]:
    out = []
    tdays = _trip_days(trip)
    lib: dict[str, dict[str, dict]] = {}
    for city in dict.fromkeys([h.city for h in trip.hotels] + [d.city for d in tdays]):
        lib[norm_name(city)] = {norm_name(r["name"]): r for r in library.restaurants(city)
                                if isinstance(r, dict) and isinstance(r.get("name"), str)}
    city_counts: Counter = Counter()
    for d in doc.days:
        n = d.index
        city = norm_name(tdays[n - 1].city) if n and 0 < n <= len(tdays) else ""
        day_seen: dict[str, int] = {}
        for gi, (meal, slots) in enumerate(_meal_groups(d)):
            venues = _venues(slots)
            if len(venues) < 3 and not any(m.startswith("⚠ ADD RESTAURANT") for s in slots for m in s.markers):
                out.append(_f("meal_count", f"{meal.capitalize()} has {len(venues)} restaurant(s) and no "
                                            "ADD RESTAURANT marker", slots[0].heading, n))
            in_set = set()
            for v in venues:
                key = norm_name(v.name)
                if key in in_set:
                    out.append(_f("repeat_in_set", f"'{v.name}' is listed twice for {meal}", v.name, n))
                    continue
                in_set.add(key)
                if key in day_seen and day_seen[key] != gi:
                    out.append(_f("repeat_day", f"'{v.name}' appears twice on day {n}", v.name, n))
                    continue
                day_seen[key] = gi
                city_counts[(city, key)] += 1
                if city_counts[(city, key)] == 3:
                    out.append(_f("repeat_city", f"'{v.name}' is used more than twice in this city", v.name, n))
                r = lib.get(city, {}).get(key) or next((m[key] for m in lib.values() if key in m), None)
                if r is not None and not diet_fits(r, trip.diet):
                    out.append(_f("diet", f"'{v.name}' is not known to fit the client's diet", v.name, n))
                other = _meal_mismatch(v, meal)
                if other:
                    out.append(_f("meal_label_mismatch", f"'{v.name}' is described as best for {other} but "
                                                         f"listed for {meal}", v.name, n, "warning"))
    return out


def _meal_mismatch(v: DocVenue, meal: str) -> Optional[str]:
    best = v.facts.get("BEST FOR", "").casefold()
    said = {m for m in _MEALS if re.search(rf"\b{m}\b", best)}
    said |= {m.group(1).lower() for m in _BEST_FOR_RE.finditer(v.body)}
    if said and meal not in said:
        return sorted(said)[0]
    return None


def _minutes(s: str) -> Optional[int]:
    h = re.search(r"(\d+)\s*h(?:ours?|rs?)?\b", s)
    m = re.search(r"(\d+)\s*min", s)
    if not h and not m:
        return None
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def _walk(doc: DocModel) -> list[Finding]:
    out, seen = [], set()
    for p in doc.paragraphs:
        if p.day is None:
            continue
        for rx in _WALK_RES:
            mins = [int(x) for x in rx.findall(p.text)]
            if any(x > 10 for x in mins) and p.text not in seen:
                seen.add(p.text)
                out.append(_f("walk_limit", f"Walk of {max(mins)} min (limit 10)", p.text, p.day))
    for d in doc.days:
        for s in d.slots:
            for v in s.venues:
                mins = _minutes(v.facts.get("WALK", ""))
                if mins is not None and mins > 10:
                    out.append(_f("walk_limit", f"Walk of {mins} min to '{v.name}' (limit 10)", v.name, d.index))
    return out


def _prose(doc: DocModel) -> list[Finding]:
    out = []
    for p in doc.paragraphs:
        if PLACEHOLDER_RE.search(p.text):
            out.append(_f("placeholder", "Placeholder text left in the guide", p.text, p.day))
        m = CHATTER_RE.search(p.text)
        if m:
            out.append(_f("assistant_chatter", f"Planner/AI voice: '{m.group(0)}'", p.text, p.day))
        if p.section != THANK_YOU and CLOSING_RE.search(p.text):
            out.append(_f("closing_phrase_misplaced", "Closing phrase belongs on the Thank You page", p.text, p.day))
        m = THIRD_PERSON_RE.search(p.text)
        if m:
            out.append(_f("third_person_client", f"Refers to the client in the third person ('{m.group(0)}')",
                          p.text, p.day))
        if "utm_" in p.text:
            out.append(_f("utm", "Tracking parameter (utm_) in text", p.text, p.day))
    return out


def _utm_links(doc: DocModel) -> list[Finding]:
    out, seen = [], set()
    for text, url in doc.links:
        if "utm_" in url and url not in seen:
            seen.add(url)
            out.append(_f("utm", f"Link has a tracking parameter: {url}", text))
    return out


def _commentary(doc: DocModel, trip: TripPlan) -> list[Finding]:
    out = []
    for sentence in trip.commentary_removed:
        key = norm_name(sentence).rstrip(".!? ")
        if len(key.split()) < 3:
            continue
        para = next((p for p in doc.paragraphs if key in norm_name(p.text)), None)
        if para is not None:
            out.append(_f("commentary", f"Planner commentary in the guide: '{sentence}'", para.text, para.day))
    return out


def _title(doc: DocModel, trip: TripPlan) -> list[Finding]:
    blob = norm_name(f"{doc.title} {doc.subtitle}")
    anchor = doc.subtitle or doc.title
    if not blob:
        return [_f("title_destination", "No title or subtitle found")]
    dests = [norm_name(c) for c in dict.fromkeys([h.city for h in trip.hotels] + [d.city for d in trip.days])]
    if dests and not any(re.search(rf"(?<!\w){re.escape(c)}(?!\w)", blob) for c in dests):
        return [_f("title_destination", f"Title does not name the trip's destinations ({', '.join(dests)})",
                   anchor)]
    return []


def _markers(doc: DocModel) -> list[Finding]:
    if not doc.markers:
        return []
    kinds = Counter(k.group(1) if (k := _MARKER_KIND.match(m)) else m for m in doc.markers)
    detail = ", ".join(f"{k} × {v}" for k, v in kinds.most_common())
    return [_f("markers_remaining", f"{len(doc.markers)} markers remain: {detail}")]


def check_rules(doc: DocModel, trip: TripPlan, library: Library) -> list[Finding]:
    return (_section_order(doc) + _days(doc, trip) + _title(doc, trip) + _venue_link(doc)
            + _meals(doc, trip, library) + _walk(doc) + _prose(doc) + _utm_links(doc) + _commentary(doc, trip)
            + _markers(doc))
