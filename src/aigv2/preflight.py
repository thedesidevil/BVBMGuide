import re
from datetime import date, datetime, time, timedelta
from typing import Optional

from .config import Settings
from .hours import is_open_for
from .intake.attachments import ZIP_MAX_BYTES, ZIP_MAX_FILES, Attachment
from .intake.template import IntakeFields
from .library import Library
from .models import Answers, DayPlan, HotelStay, PlannedItem, Place, Question, TransportLeg, TripPlan, place_key

DIET_LABEL = "Diet (restrictions, allergies, likes)"
BOOKING_WORDS = re.compile(r"ticket|booking|voucher|confirmation|reservation|e-?ticket", re.I)
_CONFIRMED_RE = re.compile(r"\b(confirmed|booked)\b", re.I)
_NEGATED_RE = re.compile(r"(?:\b(?:not|never|to be|be)|n't)\s*(?:yet\s*)?$")
PERMIT_RE = re.compile(r"permit|\bilp\b|inner line", re.I)
PERMIT_AREAS = ["nathula", "nathu la", "tsomgo", "changu", "gurudongmar", "pangong", "nubra", "arunachal", "nagaland"]
MODE_WORDS = {
    "taxi": ("taxi", "cab", "uber", "ola"),
    "public_transport": ("public", "metro", "train", "bus", "transit", "subway"),
    "self_drive": ("self", "rent", "rental"),
    "private_driver": ("driver", "private", "chauffeur"),
}
MODES = ["taxi", "public_transport", "self_drive", "private_driver"]
SLOTS = ("morning", "afternoon", "evening")
VISIT_MIN = 60


class PreflightStop(Exception):
    pass


def _d(d: date) -> str:
    return f"{d.day} {d:%b}"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _same(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a and b) and (a == b or a in b or b in a)


def _parse_time(s: Optional[str]) -> Optional[time]:
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})\s*([ap]\.?m\.?)?\s*$", s or "", re.I)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if m.group(3):
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if m.group(3)[0].lower() == "p" else 0)
    if h > 23 or mi > 59:
        return None
    return time(h, mi)


def _span(stays: list[HotelStay]) -> tuple[Optional[date], Optional[date]]:
    if not stays:
        return None, None
    return min(s.check_in for s in stays), max(s.check_out for s in stays)


def _nights(start: date, end: date):
    d = start
    while d < end:
        yield d
        d += timedelta(days=1)


def _runs(nights: list[date]) -> list[list[date]]:
    runs: list[list[date]] = []
    for n in nights:
        if runs and n - runs[-1][-1] == timedelta(days=1):
            runs[-1].append(n)
        else:
            runs.append([n])
    return runs


def _conflicting_notes(stays: list[HotelStay]) -> dict[int, HotelStay]:
    out: dict[int, HotelStay] = {}
    for i, n in enumerate(stays):
        if n.source != "notes":
            continue
        for v in stays:
            if v.source != "voucher" or _norm(v.city) != _norm(n.city):
                continue
            if v.check_in >= n.check_out or n.check_in >= v.check_out:
                continue
            if not _same(v.hotel, n.hotel) or (v.check_in, v.check_out) != (n.check_in, n.check_out):
                out[i] = v
                break
    return out


def _all_text(plan: TripPlan, attachments: list[Attachment]) -> list[str]:
    blobs = [plan.additional_notes]
    blobs += [a.text for a in attachments if not a.error]
    for b in plan.bookings:
        blobs.append(b.name)
        blobs += b.instructions
    return blobs


def _is_confirmed(note: str) -> bool:
    return any(not _NEGATED_RE.search(note[:m.start()].lower()) for m in _CONFIRMED_RE.finditer(note))


def _permit_area(item: PlannedItem) -> Optional[str]:
    hay = _norm(item.name)
    for area in PERMIT_AREAS:
        if _norm(area) in hay:
            return area
    return None


def _permit_mentioned(item: PlannedItem, area: str, blobs: list[str]) -> bool:
    if PERMIT_RE.search(item.note):
        return True
    for blob in blobs:
        for line in blob.splitlines():
            if PERMIT_RE.search(line) and _norm(area) in _norm(line):
                return True
    return False


def _window_open(place: Place, day: date, window: tuple[str, str]) -> Optional[bool]:
    start = _parse_time(window[0])
    end = _parse_time(window[1])
    if place.hours is None or start is None or end is None:
        return None
    s, e = start.hour * 60 + start.minute, end.hour * 60 + end.minute
    results = []
    while s + VISIT_MIN <= e:
        results.append(is_open_for(place.hours, day, time(s // 60, s % 60), VISIT_MIN))
        s += 30
    return any(results)


_PAX_WORD = r"adults?|seniors?|child(?:ren)?|youths?|infants?|kids?|pax|passengers?|persons?|people"
_PAX_RE = re.compile(rf"(\d+)\s*[x×]?\s*({_PAX_WORD})\b|\b({_PAX_WORD})\s*[x×]\s*(\d+)", re.I)


def _pax(label: str) -> Optional[tuple[int, int, int]]:
    adults = children = unspecified = 0
    for m in _PAX_RE.finditer(label):
        n = int(m.group(1) or m.group(4))
        word = (m.group(2) or m.group(3)).lower()
        if word.startswith(("adult", "senior")):
            adults += n
        elif word.startswith(("child", "youth", "infant", "kid")):
            children += n
        else:
            unspecified += n
    if adults + children + unspecified == 0:
        return None
    return adults, children, unspecified


def _pax_matches(label: str, adults: int, kids: int) -> bool:
    parsed = _pax(label)
    if parsed is None:
        return False
    la, lc, lu = parsed
    if lu:
        return la + lc + lu == adults + kids
    return la == adults and lc == kids


def run_checklist(
    plan: TripPlan,
    intake: IntakeFields,
    attachments: list[Attachment],
    library: Library,
    places: dict[str, Optional[Place]],
    settings: Optional[Settings] = None,
) -> list[Question]:
    windows = (settings or Settings(models={})).slot_windows
    qs: list[Question] = []
    seen: set[str] = set()

    def add(id: str, kind: str, text: str, options: Optional[list[str]] = None, day: Optional[date] = None) -> None:
        if id not in seen:
            seen.add(id)
            qs.append(Question(id=id, kind=kind, text=text, options=options or [], day=day))

    # missing
    if not [n for n in plan.client_names if n.strip()]:
        add("missing:client_names", "missing", "Client name(s) are missing — who is travelling?")
    if plan.travellers.adults <= 0:
        add("missing:adults", "missing", "Number of adults is missing — how many adults are travelling?")
    if not plan.travel_modes:
        add("missing:travel_modes", "missing", "Travel mode(s) are missing — how will the clients get around?", list(MODES))
    if not plan.days:
        add("missing:days", "missing", "No itinerary days were found — please paste the day-by-day itinerary.")
    d = plan.diet
    plan_diet_empty = not (d.restrictions or d.allergies or d.likes or d.pure_veg)
    if plan_diet_empty and not intake.values.get(DIET_LABEL, "").strip():
        add("missing:diet", "missing", "Diet is missing — any restrictions, allergies or likes? (write 'none' if not)")

    # attachments
    live = [a for a in attachments if not a.duplicate_of]
    for a in live:
        if a.error:
            add(f"unreadable:{a.name}", "unreadable", f"We couldn't read {a.name} — please re-upload it or paste its text")
    for a in live:
        if a.skipped_files:
            shown = ", ".join(a.skipped_files[:10]) + (", …" if len(a.skipped_files) > 10 else "")
            add(f"zip_skipped:{a.name}", "zip_skipped",
                f"{len(a.skipped_files)} file(s) in {a.name} were not read (limit {ZIP_MAX_FILES} files / "
                f"{ZIP_MAX_BYTES // (1024 * 1024)} MB): {shown} — upload them separately, or answer 'not needed'")
    for a in live:
        if not a.error and a.image_only and a.kind != "image":
            add(f"image_only:{a.name}", "image_only", f"{a.name} is an image — please paste its text")

    # hotels
    conflicts = _conflicting_notes(plan.hotels)
    stays = [s for i, s in enumerate(plan.hotels) if i not in conflicts]
    start, end = _span(stays)
    gaps: list[date] = []
    if start and end:
        cover = {n: sum(1 for s in stays if s.check_in <= n < s.check_out) for n in _nights(start, end)}
        gaps = [n for n, c in cover.items() if c == 0]
        for run in _runs(gaps):
            add(f"hotel_gap:{run[0].isoformat()}", "hotel_gap",
                f"No hotel is booked for the night of {_d(run[0])}" + (f" to {_d(run[-1])}" if len(run) > 1 else "")
                + ". Where are the clients staying?", day=run[0])
        for run in _runs([n for n, c in cover.items() if c > 1]):
            add(f"hotel_overlap:{run[0].isoformat()}", "hotel_overlap",
                f"Two hotels overlap on the night of {_d(run[0])}" + (f" to {_d(run[-1])}" if len(run) > 1 else "")
                + ". Which one is right?", day=run[0])

    for leg in plan.transport:
        if leg.kind in ("flight", "train") and leg.depart and leg.depart.hour < 5:
            dep = leg.depart.date()
            prev = dep - timedelta(days=1)
            add(f"late_departure:{dep.isoformat()}", "late_departure",
                f"Departure is at {leg.depart:%H:%M} on {_d(dep)}. Is checkout on {_d(prev)} or {_d(dep)}?",
                [prev.isoformat(), dep.isoformat()], day=dep)

    for i, n in conflicts.items():
        h = plan.hotels[i]
        add(f"conflict:hotel:{h.city}", "conflict",
            f"In {h.city}, the notes say {h.hotel} ({_d(h.check_in)}–{_d(h.check_out)}) but the voucher says "
            f"{n.hotel} ({_d(n.check_in)}–{_d(n.check_out)}). We'll use the voucher — please confirm.",
            ["voucher", "notes"])

    day_dates = sorted({dp.date for dp in plan.days})
    if start and end and day_dates and not gaps:
        first = start
        if day_dates[0] == start - timedelta(days=1) and any(
            l.arrive and l.arrive.hour < 5 and l.arrive.date() == start for l in plan.transport
        ):
            first = day_dates[0]
        nights = (end - first).days
        if len(day_dates) != nights + 1:
            add("days_mismatch", "days_mismatch",
                f"The itinerary has {len(day_dates)} days but the hotels cover {nights} nights "
                f"({nights + 1} days). Which is right?")

    for n, oc in enumerate(plan.open_choices):
        add(f"open_choice:{n}", "open_choice", f"Which do you want: {' or '.join(oc.options)}? ({oc.text})" if oc.options else oc.text,
            list(oc.options), day=oc.day)
    for vd in plan.vague_days:
        add(f"vague_day:{vd.isoformat()}", "vague_day",
            f"The plan for {_d(vd)} is vague. What should that day include? (comma-separated)", day=vd)

    cities: list[str] = []
    for dp in plan.days:
        if dp.city.strip() and dp.city not in cities:
            cities.append(dp.city)
    for c in cities:
        if not library.has_data(c):
            add(f"no_library:{c}", "no_library",
                f"We have no restaurant library data for {c}; restaurants there will be marked for a human. Proceed or stop?",
                ["Proceed", "Stop"])

    for dp in plan.days:
        for item in dp.items:
            key = place_key(item.name, item.city or dp.city)
            place = places[key] if key in places else places.get(item.name)
            window = windows.get(item.slot_hint)
            if item.kind != "attraction" or item.optional or place is None or place.hours is None or window is None:
                continue
            if _window_open(place, dp.date, window) is not False:
                continue
            if any(_window_open(place, dp.date, windows[s]) is not False for s in SLOTS if s in windows and s != item.slot_hint):
                continue
            add(f"hours_conflict:{dp.date.isoformat()}:{item.name}", "hours_conflict",
                f"{item.name} appears closed on {_d(dp.date)} during the {item.slot_hint}. Keep it or remove it?",
                ["Keep", "Remove"], day=dp.date)

    # amendments
    for leg in plan.transport:
        if leg.arrive and leg.arrive.hour < 5 and leg.kind in ("flight", "train", "bus", "boat"):
            arr = leg.arrive.date()
            prev = arr - timedelta(days=1)
            add(f"early_arrival:{arr.isoformat()}", "early_arrival",
                f"Arrival is at {leg.arrive:%H:%M} on {_d(arr)}. The hotel night would start on {_d(prev)} — "
                f"is Day 1 {_d(prev)} or {_d(arr)}?", [prev.isoformat(), arr.isoformat()], day=arr)

    last = max(day_dates) if day_dates else end
    if last and not any(l.depart and l.depart.date() >= last for l in plan.transport):
        add("no_departure", "no_departure",
            f"No departure was found for {_d(last)}. What are the departure time and mode (flight, train, bus, boat)?")

    for b in plan.bookings:
        for dp in plan.days:
            for item in dp.items:
                if item.booking_ref != b.name or item.optional:
                    continue
                bt, it = _parse_time(b.time), _parse_time(item.time)
                if dp.date != b.day or (bt and it and bt != it):
                    add(f"booking_conflict:{b.name}", "booking_conflict",
                        f"The notes place {item.name} on {_d(dp.date)}" + (f" at {item.time}" if item.time else "")
                        + f" but the booking says {_d(b.day)}" + (f" at {b.time}" if b.time else "")
                        + ". We'll use the booking — please confirm.", ["Use booking", "Use notes"], day=b.day)

    adults = plan.travellers.adults
    kids = max(sum(plan.travellers.child_counts.values()), len(plan.travellers.kids_ages))
    for leg in plan.transport:
        if leg.pax_label.strip() and not _pax_matches(leg.pax_label, adults, kids):
            ref = leg.ref or leg.number or f"{leg.from_place}-{leg.to_place}"
            add(f"headcount:{ref}", "headcount",
                f"The ticket for {ref} says '{leg.pax_label}' — does it cover all {adults + kids} travellers "
                f"({adults} adult(s), {kids} child(ren))?")

    blobs = _all_text(plan, attachments)
    booked = {b.name for b in plan.bookings}
    for dp in plan.days:
        for item in dp.items:
            if item.optional or not _is_confirmed(item.note):
                continue
            if item.booking_ref in booked or any(_same(item.name, b) for b in booked):
                continue
            if any(a.text and _norm(item.name) in _norm(a.text) for a in live if not a.error):
                continue
            add(f"unvouchered_confirmed:{item.name}", "unvouchered_confirmed",
                f"The notes say {item.name} is confirmed, but there is no ticket or voucher. Is it booked?",
                ["Booked — will send voucher", "Not booked yet"], day=dp.date)

    for a in live:
        if a.error:
            continue
        if a.kind == "image" or (
            a.has_images and not a.image_only and not a.text_dates and BOOKING_WORDS.search(a.name + " " + a.text[:2000])
        ):
            add(f"image_details:{a.name}", "image_details",
                f"{a.name} may contain bookings in images — please paste its text")

    if plan.travellers.child_counts and sum(plan.travellers.child_counts.values()) > len(plan.travellers.kids_ages):
        add("kids_ages", "kids_ages", "How old are the children? (comma-separated ages)")

    if plan.trip_scope == "domestic":
        areas_done: set[str] = set()
        for dp in plan.days:
            for item in dp.items:
                if item.optional:
                    continue
                area = _permit_area(item)
                if area and area not in areas_done and not _permit_mentioned(item, area, blobs):
                    areas_done.add(area)
                    add(f"permit:{item.name}", "permit",
                        f"{item.name} is in a permit area ({area.title()}). Is a permit arranged?",
                        ["Permit arranged", "Will arrange", "Not needed"], day=dp.date)
    return qs


_DOT_TIME_RE = re.compile(r"(?<![\d./:-])(\d{1,2})\.(\d{2})\s*([ap]\.?m\.?)(?![\d])", re.I)


def _departure_time(ans: str) -> Optional[time]:
    found: set[time] = set()
    for m in re.finditer(r"(?<![\d./:-])(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?(?![\d])", ans, re.I):
        if not m.group(2) and not m.group(3):
            continue
        t = _parse_time(f"{m.group(1)}:{m.group(2) or '00'}" + (f" {m.group(3)}" if m.group(3) else ""))
        if t is not None and (m.group(2) or m.group(3)):
            found.add(t)
    for m in _DOT_TIME_RE.finditer(ans):
        t = _parse_time(f"{m.group(1)}:{m.group(2)} {m.group(3)}")
        if t is not None:
            found.add(t)
    return next(iter(found)) if len(found) == 1 else None


def validate_answers(questions: list[Question], answers: Answers) -> dict[str, str]:
    bad: dict[str, str] = {}
    for q in questions:
        ans = (answers.get(q.id) or "").strip()
        if not ans:
            continue
        reason = None
        if q.kind in ("late_departure", "early_arrival"):
            try:
                date.fromisoformat(ans)
            except ValueError:
                reason = "expected a date like 2026-10-15"
            else:
                if q.options and ans not in q.options:
                    reason = f"choose one of {', '.join(q.options)}"
        elif q.kind == "open_choice":
            if q.options and not any(_same(ans, o) for o in q.options):
                reason = f"choose one of {', '.join(q.options)}"
        elif q.kind == "no_library":
            if ans.lower() not in ("proceed", "stop"):
                reason = "answer Proceed or Stop"
        elif q.kind == "no_departure":
            if _departure_time(ans) is None:
                reason = "give one departure time like 14:30 and the mode"
        elif q.id == "missing:travel_modes":
            if not _modes(ans):
                reason = "choose from taxi, public transport, self drive, private driver"
        elif q.id == "missing:adults":
            if not re.search(r"\d+", ans):
                reason = "give a number"
        elif q.id == "kids_ages":
            if not re.search(r"\d+", ans):
                reason = "give ages as numbers"
        if reason:
            bad[q.id] = reason
    return bad


def unanswered(questions: list[Question], answers: Answers) -> list[Question]:
    bad = validate_answers(questions, answers)
    return [q for q in questions if not (answers.get(q.id) or "").strip() or q.id in bad]


def _iso(s: str, what: str) -> date:
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        raise ValueError(f"{what}: expected a date like 2026-10-15, got {s!r}") from None


def _pick(stays: list[HotelStay], attr: str, dates: set[date], place: str) -> Optional[HotelStay]:
    cands = [s for s in stays if getattr(s, attr) in dates]
    for s in cands:
        if place and (_same(s.city, place) or _same(s.hotel, place)):
            return s
    return cands[0] if cands else None


def _modes(answer: str) -> list[str]:
    low = answer.lower()
    return [m for m in MODES if any(re.search(rf"\b{w}(?:s|es)?\b", low) for w in MODE_WORDS[m])]


def _items_for_choice(dp: DayPlan, chosen: str, options: list[str]) -> list[PlannedItem]:
    others = [o for o in options if not _same(o, chosen)]
    return [
        it for it in dp.items
        if not any(_same(it.name, o) for o in others) or _same(it.name, chosen)
    ]


def apply_answers(plan: TripPlan, questions: list[Question], answers: Answers) -> TripPlan:
    out = plan.model_copy(deep=True)
    invalid = validate_answers(questions, answers)
    drop_choices: set[int] = set()
    for q in questions:
        ans = (answers.get(q.id) or "").strip()
        if not ans or q.id in invalid:
            continue
        kind = q.kind
        suffix = q.id.split(":", 1)[1] if ":" in q.id else ""
        if kind == "late_departure":
            chosen = _iso(ans, q.id)
            dep = _iso(suffix, q.id)
            leg = next((l for l in out.transport if l.depart and l.depart.date() == dep and l.depart.hour < 5), None)
            stay = _pick(out.hotels, "check_out", {dep, dep - timedelta(days=1)}, leg.from_place if leg else "")
            if stay:
                stay.check_out = chosen
        elif kind == "early_arrival":
            chosen = _iso(ans, q.id)
            arr = _iso(suffix, q.id)
            leg = next((l for l in out.transport if l.arrive and l.arrive.date() == arr and l.arrive.hour < 5), None)
            stay = _pick(out.hotels, "check_in", {arr, arr - timedelta(days=1)}, leg.to_place if leg else "")
            if stay:
                stay.check_in = chosen
        elif kind == "conflict":
            city = q.id.split(":", 2)[2]
            drop = "voucher" if "notes" in ans.lower() else "notes"
            out.hotels = [h for h in out.hotels if not (_norm(h.city) == _norm(city) and h.source == drop)]
        elif kind == "open_choice":
            n = int(suffix)
            oc = plan.open_choices[n]
            for dp in out.days:
                if oc.day is None or dp.date == oc.day:
                    dp.items = _items_for_choice(dp, ans, oc.options)
            drop_choices.add(n)
        elif kind == "vague_day":
            vd = _iso(suffix, q.id)
            dp = next((x for x in out.days if x.date == vd), None)
            if dp:
                dp.items = [
                    PlannedItem(name=p.strip(), kind="activity", city=dp.city)
                    for p in ans.split(",") if p.strip()
                ]
            out.vague_days = [x for x in out.vague_days if x != vd]
        elif kind == "hours_conflict" and ans.lower().startswith("remove"):
            day_s, name = q.id.split(":", 2)[1:]
            for dp in out.days:
                if dp.date.isoformat() == day_s:
                    dp.items = [it for it in dp.items if it.name != name]
        elif kind == "booking_conflict" and "notes" not in ans.lower():
            name = suffix
            b = next((x for x in out.bookings if x.name == name), None)
            if b:
                target = next((x for x in out.days if x.date == b.day), None)
                moved: list[PlannedItem] = []
                for dp in out.days:
                    keep = []
                    for it in dp.items:
                        if it.booking_ref != name:
                            keep.append(it)
                            continue
                        if b.time:
                            it.time = b.time
                        if target is not None and dp is not target:
                            moved.append(it)
                        else:
                            keep.append(it)
                    dp.items = keep
                if target is not None:
                    target.items.extend(moved)
        elif kind == "no_departure":
            t = _departure_time(ans)
            last = max((dp.date for dp in out.days), default=None)
            if t and last:
                low = ans.lower()
                leg_kind = next((k for k in ("flight", "train", "bus", "boat") if k in low), "other")
                origin = next((dp.city for dp in out.days if dp.date == last), "")
                out.transport.append(TransportLeg(
                    kind=leg_kind, from_place=origin, to_place="", source="answer",
                    depart=datetime.combine(last, t),
                ))
        elif q.id == "missing:client_names":
            out.client_names = [n.strip() for n in re.split(r",|&|\band\b", ans) if n.strip()]
        elif q.id == "missing:adults":
            m = re.search(r"\d+", ans)
            if m:
                out.travellers.adults = int(m.group())
        elif q.id == "missing:travel_modes":
            out.travel_modes = _modes(ans) or out.travel_modes
        elif q.id == "missing:diet":
            if ans.lower() not in ("none", "no", "n/a", "nil"):
                out.diet.restrictions = [p.strip() for p in ans.split(",") if p.strip()]
        elif q.id == "kids_ages":
            out.travellers.kids_ages = [int(x) for x in re.findall(r"\d+", ans)]
        elif kind == "no_library" and ans.lower() == "stop":
            raise PreflightStop(f"Stopped: no library data for {suffix}")
    out.open_choices = [oc for i, oc in enumerate(out.open_choices) if i not in drop_choices]
    return out
