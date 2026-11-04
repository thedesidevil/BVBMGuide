"""Build the renderer-agnostic Guide from a finished run (GuideData).

Logic mirrored from render/day_render.py::DayRenderer; that module is removed in plan Task 27,
so the copied logic here is accepted debt.
"""
from datetime import date, datetime, time
from typing import Optional

from src.aigv2.guide import model as g
from src.aigv2.hours import _fmt12, format_for_day, is_open_for, next_opening
from src.aigv2.library import norm_name
from src.aigv2.models import HotelStay, Marker, TransportLeg
from src.aigv2.planning.boat import boat_bookings, parse_boat_type
from src.aigv2.planning.important_places import ImportantPlaces, NearbyPlace
from src.aigv2.planning.late_night import is_late_night_landing, pickup_before_landing
from src.aigv2.planning.meals import ChosenRestaurant, MealPick
from src.aigv2.planning.slots import MealSlot, ScheduledItem, arrival_buffer_min, is_optional, leave_by, parse_time
from src.aigv2.planning.travel import Leg, drive_day_legs, leg_markers, leg_options
from src.aigv2.render.day_render import _PORT, _REACH, _SLOT_TITLE, day_header, sunset_time
from src.aigv2.render.document import BEFORE_YOU_GO, WHILE_THERE, GuideData, RenderDay, _present, destinations
from src.aigv2.render.sections_render import minutes_text, place_markers, search_url
from src.aigv2.writing.days import AttractionText
from src.aigv2.writing.sections import SectionContent, SectionItem

_LATE = "Late night"
_KIND = {"flight": "Flight", "train": "Train", "boat": "Boat", "bus": "Bus"}
_BRAND = "Bon Voyage by Marina"


def _ref(m: Marker) -> g.MarkerRef:
    return g.MarkerRef(kind=m.kind, text=m.text)

def _verify(text: str) -> Marker:
    return Marker(kind="VERIFY", text=text)

def _hm(dt: datetime) -> str:
    return dt.strftime("%H:%M")

def _when(dt: datetime, d: date) -> str:
    return _hm(dt) if dt.date() == d else f"{_hm(dt)}, {dt:%a} {dt.day} {dt:%b}"


def _facts(pairs: list) -> tuple[list[g.Fact], list[g.MarkerRef]]:
    """Old-renderer (LABEL, value) pairs; a value may be text, a Marker, or a list of both."""
    facts, marks = [], []
    for label, value in pairs:
        items = value if isinstance(value, list) else [value]
        text = " | ".join(i for i in items if isinstance(i, str))
        marks += [_ref(i) for i in items if isinstance(i, Marker)]
        if text:
            facts.append(g.Fact(label=label.capitalize(), value=text))
    return facts, marks


class _Day:
    def __init__(self, rd: RenderDay, data: GuideData, walk_max: int):
        self.rd, self.data, self.walk_max = rd, data, walk_max
        self.self_drive = "self_drive" in data.modes
        self.texts = {norm_name(a.name): a for a in rd.text.attractions}
        self.rtexts = {norm_name(r.name): r for r in rd.text.restaurants}
        self.plan = next((p for p in data.trip.days if p.date == rd.date), None)
        self.out: list = []
        self.free_time_used = False
        self._after_boat: Optional[tuple[TransportLeg, object]] = None

    # ---- helpers
    def marks(self, markers) -> None:
        refs = [_ref(m) if isinstance(m, Marker) else m for m in markers]
        if refs:
            self.out.append(g.ReviewMarkerBlock(markers=refs))

    def _stay(self, *, arriving: bool) -> Optional[HotelStay]:
        d, stays = self.rd.date, self.data.trip.hotels
        exact = [s for s in stays if (s.check_in if arriving else s.check_out) == d]
        cover = [s for s in stays if s.check_in <= d <= s.check_out]
        return (exact or cover or [None])[0]

    def _cruise(self) -> Optional[HotelStay]:
        d = self.rd.date
        return next((s for s in self.data.trip.hotels if s.kind == "cruise" and s.check_in < d < s.check_out), None)

    def _url(self, name: str) -> str:
        p = self.rd.places.get(name)
        return p.maps_url if p is not None and p.match_ok else search_url(name, self.rd.city)

    def _options(self, leg: Leg) -> list[str]:
        return [label if label.startswith("about") else f"{label} · {m} min"
                for label, m in leg_options(leg, self.data.modes, self.walk_max)]

    def _hotel_markers(self, hotel: str) -> list[Marker]:
        p = self.rd.places.get(hotel)
        return ([] if p is not None and p.match_ok else [_verify(f"{hotel} not found on Google")]) + place_markers(p)

    @staticmethod
    def _road_minutes(leg: Optional[Leg]) -> Optional[int]:
        if leg is None or leg.no_route:
            return None
        return leg.drive_min if leg.drive_min is not None else leg.approx_min

    def _parking(self, lib: dict):
        v = lib.get("parking")
        return v if isinstance(v, str) and v.strip() else _verify("parking")

    # ---- page
    def build(self) -> g.Page:
        rd = self.rd
        title = day_header(rd.index, rd.date, rd.text.title)
        self.out = [g.Opener(number=rd.index, weekday=f"{rd.date:%A}", date=f"{rd.date.day} {rd.date:%B}",
                             title=[rd.text.title], intro=rd.text.intro), g.YourDay()]
        strip = self._journey_strip()
        if strip:
            self.out.append(strip)
        if rd.result.tips:
            self.out.append(g.SimpleCard(when="Today", part="Good to know", heading="Good to know",
                                         text="\n".join(rd.result.tips)))
        cruise = self._cruise()
        arr, dep = rd.arrival, rd.departure
        early_dep = bool(dep and arr and (dep is arr or (dep.depart and arr.arrive and dep.depart <= arr.arrive)))
        if rd.prev_city and norm_name(rd.prev_city) != norm_name(rd.city) and not cruise:
            self.marks([_verify("inter-city travel day logistics")])
        if cruise:
            self._port_day(arr, dep)
        else:
            if early_dep:
                self._departure(dep, transport_card=dep is not arr, city=rd.prev_city or rd.city)
            if arr:
                self._arrival(arr)
            else:
                boat = self._arrival_boat()
                if boat is None:
                    self._check_in()
                else:
                    self._after_boat = (boat, self._check_in)
        self._drive_stops()
        self._timeline()
        if rd.text.free_time_idea and not self.free_time_used:
            self.out.append(g.SimpleCard(when="Free time", heading="Free time", text=rd.text.free_time_idea))
        if dep and not early_dep and not cruise:
            self._departure(dep, transport_card=True, city=rd.city)
        else:
            self._overnight(cruise)
        self.marks(rd.result.markers)  # day-level review notes close the page
        return g.Page(kind="day", title=title, bookmark=f"day_{rd.index}", components=self.out)

    def _boat_leg(self) -> Optional[TransportLeg]:
        rd = self.rd
        legs = [rd.arrival, rd.departure] + list(rd.other_transport)
        return next((t for t in legs if t is not None and t.kind == "boat" and t.from_place.strip()), None)

    def _place_link(self, name: str, city: str = "") -> g.Link:
        p = self.rd.places.get(name)
        found = p is not None and p.match_ok
        return g.Link(text=p.name if found and p.name else name,
                      url=p.maps_url if found else search_url(name, city or self.rd.city))

    def _journey_strip(self) -> Optional[g.JourneyStrip]:
        """Hotel -> harbour -> destination for a day with a boat crossing; only stated facts become text."""
        t = self._boat_leg()
        if t is None:
            return None
        rd, trip, d = self.rd, self.data.trip, self.rd.date
        booking = next(iter(boat_bookings(trip, t)), None)
        morning = next((s for s in trip.hotels if s.check_in < d <= s.check_out), None)
        new = next((s for s in trip.hotels if s.check_in == d), None)
        leave = parse_time(booking.time) if booking else None
        harbour_time = " · ".join(x for x in (
            f"Check-in {_fmt12(t.check_in.time())}" if t.check_in else "",
            f"Departs {_fmt12(t.depart.time())}" if t.depart else "") if x) or None
        stops: list[g.JourneyStop] = []
        legs: list[str] = []
        road = self._road_minutes(rd.legs.get("boat_pickup"))
        if morning:
            stops.append(g.JourneyStop(label=morning.city, name=self._place_link(morning.hotel, morning.city),
                                       time=f"Leave {_fmt12(leave)}" if leave else None))
            legs.append(f"Approx. {road} min by car" if road else "")
        stops.append(g.JourneyStop(label="Harbour", name=g.Link(text=t.from_place, url=self._url(t.from_place)),
                                   time=harbour_time))
        legs.append(f"Approx. {t.duration_min} min by boat" if t.duration_min else "")
        if new:
            stops.append(g.JourneyStop(label=new.city, name=self._place_link(new.hotel, new.city),
                                       time=f"Check-in from {_fmt12(new.check_in_time)}" if new.check_in_time else None))
        elif t.to_place.strip():
            stops.append(g.JourneyStop(label="Arrive", name=g.Link(text=t.to_place, url=self._url(t.to_place))))
        else:
            legs.pop()
        return g.JourneyStrip(stops=stops, legs=legs)

    def _boat_card(self, t: TransportLeg, city: str) -> None:
        trip = self.data.trip
        booking = next(iter(boat_bookings(trip, t)), None)
        pairs: list = []
        if t.check_in:
            pairs.append(("CHECK IN", f"{_hm(t.check_in)} · {t.from_place}" if t.from_place else _hm(t.check_in)))
        if t.depart:
            pairs.append(("DEPARTS", f"{_hm(t.depart)} · {t.from_place}" if t.from_place else _hm(t.depart)))
        if t.duration_min:
            pairs.append(("CROSSING", f"Approx. {t.duration_min} min"))
        boat_type = parse_boat_type(booking.instructions) if booking else None
        if boat_type:
            pairs.append(("TYPE", boat_type))
        facts, marks = _facts(pairs)
        at_time = t.check_in or t.depart or t.arrive
        self.out.append(g.BookingCard(
            when=_fmt12(at_time.time()) if at_time else "Boat", kind="FAST BOAT",
            title=g.Link(text=f"{t.from_place} to {t.to_place}" if t.to_place else t.from_place,
                         url=self._url(t.from_place)),
            subtitle=None, facts=facts, ref=t.ref or None))
        self.marks(marks)

    def _overnight(self, cruise: Optional[HotelStay]) -> None:
        d = self.rd.date
        ship = cruise or next((x for x in self.data.trip.hotels if x.kind == "cruise" and x.check_in <= d < x.check_out), None)
        text = f"Overnight on board {ship.hotel}" if ship else f"Overnight in {self.rd.city}"
        self.out.append(g.SimpleCard(when="Evening", part="Evening", heading=text))

    def _port_day(self, arr, dep) -> None:
        if arr and arr.arrive:
            self.out.append(g.SimpleCard(when=_hm(arr.arrive), heading=f"Docks at {arr.to_place or self.rd.city}"))
        if dep and dep.depart:
            by = leave_by(dep, self.data.domestic)
            self.out.append(g.SimpleCard(when=f"{by:%H:%M}", heading=f"Back on board by {by:%H:%M}"))
        if (arr and arr.arrive) or (dep and dep.depart):
            self.marks([_verify("docking and all-aboard times")])

    def _arrival_boat(self) -> Optional[TransportLeg]:
        """The boat that carries the group to a new city today (the hotel cards then follow the boat card)."""
        rd = self.rd
        if not rd.prev_city or norm_name(rd.prev_city) == norm_name(rd.city):
            return None
        return next((t for t in rd.other_transport
                     if t.kind == "boat" and t.depart and t.depart.date() == rd.date), None)

    def _check_in(self) -> None:
        stay = next((s for s in self.data.trip.hotels if s.check_in == self.rd.date), None)
        if stay is None:
            return
        prev = self.rd.prev_city
        if prev and norm_name(prev) != norm_name(self.rd.city):
            self._transfer(f"{prev} → {stay.hotel}", self._url(stay.hotel), self.rd.legs.get("arrival"), None,
                           stay.hotel, when="Arrival")
            return
        facts = [g.Fact(label="Check-in", value=f"from {stay.check_in_time:%H:%M}")] if stay.check_in_time else []
        self.out.append(g.BookingCard(when=_fmt12(stay.check_in_time) if stay.check_in_time else "Check-in",
                                      kind="Check-in", title=g.Link(text=stay.hotel, url=self._url(stay.hotel)),
                                      facts=facts))
        self.marks(self._hotel_markers(stay.hotel))

    def _hotel_check_in_card(self) -> None:
        stay = next((s for s in self.data.trip.hotels if s.check_in == self.rd.date), None)
        if stay is None:
            return
        facts = [g.Fact(label="Check-in", value=f"from {_fmt12(stay.check_in_time)}")] if stay.check_in_time else []
        self.out.append(g.BookingCard(when=_fmt12(stay.check_in_time) if stay.check_in_time else "Check-in",
                                      kind="Check-in", title=g.Link(text=stay.hotel, url=self._url(stay.hotel)),
                                      facts=facts))

    def _transfer(self, title, url, leg: Optional[Leg], body, hotel, pickup=None, when="Transfer") -> None:
        if leg is None:
            pairs, markers = [("TRANSFER", _verify("transfer time")), ("COST", _verify("transfer cost"))], []
        else:
            pairs = [("TRANSFER", self._options(leg) or _verify("transfer time")), ("COST", _verify("transfer cost"))]
            markers = leg_markers(leg, self.data.modes, self.walk_max)
        if pickup:
            pairs.insert(0, ("PICKUP", pickup))
        facts, fmarks = _facts(pairs)
        self.out.append(g.BookingCard(when=when, kind="Transfer", title=g.Link(text=title, url=url), facts=facts,
                                      text=body or ""))
        self.marks(fmarks + [_ref(m) for m in markers + (self._hotel_markers(hotel) if hotel else [])])

    def _transport(self, t: TransportLeg, link_to: str, city: str = "", day: Optional[date] = None) -> None:
        if t.kind == "boat":
            return self._boat_card(t, city)
        kind = _KIND.get(t.kind, "Transfer")
        title = f"{kind}: {t.from_place} to {t.to_place}" if t.from_place and t.to_place else kind
        pairs: list = []
        for label, v in (("OPERATOR", t.operator), ("SERVICE", t.number), ("CLASS / SEAT", t.seat)):
            if v:
                pairs.append((label, v))
        if t.depart:
            pairs.append(("DEPARTS", f"{_hm(t.depart)} · {t.from_place}" if t.from_place else _hm(t.depart)))
        if t.arrive:
            if day and is_late_night_landing(t, day):
                at = f"Lands {_hm(t.arrive)} on {t.arrive:%a} {t.arrive.day} {t.arrive:%b}"
            else:
                at = _when(t.arrive, day) if day else _hm(t.arrive)
            pairs.append(("ARRIVES", f"{at} · {t.to_place}" if t.to_place else at))
        if t.kind == "train" and t.depart and t.arrive and t.arrive > t.depart:
            mins = int((t.arrive - t.depart).total_seconds() // 60)
            pairs.append(("DURATION", [minutes_text(mins), _verify("duration (check time zones)")]))
        if t.kind == "train" and t.ref and t.platform:
            pairs.append(("PLATFORM", t.platform))
        where = link_to or t.to_place or t.from_place
        facts, marks = _facts(pairs)
        at_time = t.depart or t.arrive
        self.out.append(g.BookingCard(
            when=_hm(at_time) if at_time else kind, kind=kind,
            title=g.Link(text=title, url=search_url(where, city) if where.strip() else None),
            facts=facts, ref=t.ref or None))
        self.marks(marks)

    def _arrival(self, arr: TransportLeg) -> None:
        rd, stay = self.rd, self._stay(arriving=True)
        if arr is not rd.departure:
            self._transport(arr, arr.to_place, rd.city, rd.date)
        else:
            self._transport(arr, arr.from_place, rd.prev_city or rd.city)
        if stay is None:
            self.marks([_verify(f"hotel for {rd.date.isoformat()}")])
            return
        port = arr.to_place or _PORT[arr.kind]
        lines = []
        if arr.arrive and stay.check_in == rd.date == arr.arrive.date() and arr.arrive.time() < (stay.check_in_time or time(15)):
            lines.append("You arrive before check-in. If your room is not ready yet, ask the front desk to hold "
                         "your luggage while you head out.")
        pick = rd.arrival_booking
        if pick:
            lines.insert(0, f"Your booking: {pick.name}")
        if pick and arr.arrive and (rd.lands_next_day or is_late_night_landing(arr, rd.date)):
            driver = rd.driver_from or parse_time(pick.time)
            before = pickup_before_landing(f"{driver:%H:%M}" if driver else None, arr.arrive, rd.date)
            if before:
                lines.insert(1, f"Your driver will meet you at the airport after you land, so a pick-up shown as "
                                f"{before} means the driver is booked from {before} and will wait for your arrival "
                                f"at {_hm(arr.arrive)}.")
        self._transfer(f"{port} → {stay.hotel}", self._url(stay.hotel), rd.legs.get("arrival"), "\n".join(lines) or None,
                       stay.hotel, pickup=pick.time if pick and pick.time else None,
                       when=_hm(arr.arrive) if arr.arrive else "Arrival")

    def _departure(self, dep: TransportLeg, transport_card: bool, city: str) -> None:
        rd = self.rd
        road = self._road_minutes(rd.legs.get("departure"))
        by = leave_by(dep, self.data.domestic, road)
        line = None
        if by:
            line = f"{_REACH.get(dep.kind, 'Leave by')} {_hm(by)}"
            if road:
                hours = arrival_buffer_min(dep.kind, self.data.domestic)
                buffer = f"{hours // 60} hours" if hours % 60 == 0 else f"{hours} minutes"
                line += (f", allowing about {minutes_text(road)} on the road and {buffer} before departure "
                         "for traffic and check-in")
        if not road:
            self.marks([_verify("departure time")])
        stay = self._stay(arriving=False)
        port = dep.from_place or _PORT[dep.kind]
        if stay:
            self._transfer(f"{stay.hotel} → {port}", search_url(port, city), rd.legs.get("departure"), line, None,
                           when=_hm(by) if by else "Departure")
        else:
            if line:
                self.out.append(g.SimpleCard(when=_hm(by), heading=line))
            self.marks([_verify(f"hotel to leave from on {rd.date.isoformat()}")])
        if transport_card:
            self._transport(dep, dep.from_place, city)

    def _drive_stops(self) -> None:
        if not self.plan or not self.plan.drive_stops:
            return
        _, minutes, km = drive_day_legs(self.rd.city, self.plan.drive_stops)
        lines = [f"{s.name} — {s.km_from_prev:g} km · {minutes_text(s.minutes_from_prev)}" for s in self.plan.drive_stops]
        lines.append(f"Total today: {km:g} km · {minutes_text(minutes)}")
        self.out.append(g.SimpleCard(when="Drive", heading="Today's drive", text="\n".join(lines)))

    # ---- timeline
    def _timeline(self) -> None:
        rd = self.rd
        entries = [(s.start, 0, i, s) for i, s in enumerate(rd.result.scheduled)]
        entries += [(m.start, 1, i, m) for i, m in enumerate(rd.result.meals)]
        entries += [((t.depart or t.arrive).time(), -1, i, t) for i, t in enumerate(rd.other_transport)
                    if t.depart or t.arrive]
        slot = None
        done_groups: set[str] = set()
        for _, _, _, e in sorted(entries, key=lambda x: x[:3]):
            if isinstance(e, TransportLeg):
                self._transport(e, e.to_place)
                self.marks([_verify(f"day-trip transport {e.from_place or '?'} → {e.to_place or '?'}: confirm "
                                    "times and how to reach the departure point")])
                slot = None
                if self._after_boat and e is self._after_boat[0]:
                    after, self._after_boat = self._after_boat[1], None
                    after()
                    self._hotel_check_in_card()
            elif isinstance(e, ScheduledItem):
                part = None
                if e.slot != slot:
                    slot = e.slot
                    part = _LATE if self._late_night_item(e) else _SLOT_TITLE[slot]
                if e.option_group:
                    if e.option_group not in done_groups:
                        done_groups.add(e.option_group)
                        self._option_cards(e)
                    continue
                self._item(e, part)
            else:
                self._meal(e)
                slot = None

    def _option_cards(self, first: ScheduledItem) -> None:
        """One OptionCards block for every scheduled item sharing the first item's option_group."""
        rd = self.rd
        members = [m for m in rd.result.scheduled if m.option_group == first.option_group]
        options: list[g.Option] = []
        marks: list = []
        for n, m in enumerate(members, 1):
            saved, self.out = self.out, []
            try:
                self._item(m, None)
                card = next((c for c in self.out if c.type == "SightseeingCard"), None)
            finally:
                self.out = saved
            if card is None:
                continue
            p = rd.places.get(m.item.name)
            note = None
            if p is not None and p.match_ok and p.hours and is_open_for(p.hours, rd.date, m.start, 30) is False:
                opening = next_opening(p.hours, rd.date, m.start)
                if opening:
                    note = f"Best visited later in the day: it opens at {_fmt12(opening)}"
            options.append(g.Option(label=f"OPTION {n}", name=card.name,
                                    facts=[f for f in card.facts if f.label != "Note"], text=card.text, note=note))
            marks += card.markers
        if not options:
            return
        own = any("own expense" in f"{m.item.note}".lower() for m in members)
        self.out.append(g.OptionCards(
            eyebrow=f"{_SLOT_TITLE[first.slot].upper()}  ·  YOUR CHOICE",
            heading=" or ".join(o.name.text for o in options),
            chip="At your own expense" if own else None, own_expense=own, options=options))
        if marks:
            self.out.append(g.ReviewMarkerBlock(markers=marks))

    def _late_night_item(self, s: ScheduledItem) -> bool:
        arr = self.rd.arrival
        if not (arr and is_late_night_landing(arr, self.rd.date)):
            return False
        return s.item.kind == "transfer" or (s.slot == "evening" and s.start >= time(22))

    def _item(self, s: ScheduledItem, part: Optional[str]) -> None:
        it, rd = s.item, self.rd
        when = it.time or _fmt12(s.start)
        if it.kind == "free_time":
            self.out.append(g.SimpleCard(when=when, part="Free time", heading="Free time",
                                         text=rd.text.free_time_idea or it.name))
            self.free_time_used = True
            return
        at: Optional[AttractionText] = self.texts.get(norm_name(it.name))
        p = rd.places.get(it.name)
        found = p is not None and p.match_ok
        b = rd.booking_by_item.get(it.name)
        lib = rd.library_attractions.get(it.name, {})
        pairs: list = []
        marks: list[Marker] = []
        leg = rd.legs.get(it.name)
        if leg is not None:
            opts = self._options(leg)
            if opts:
                pairs.append(("GETTING THERE", "  |  ".join(opts)))
            if leg.transit_steps and any("public transport" in o for o in opts):
                st = leg.transit_steps
                pairs.append(("PUBLIC TRANSPORT", f"{' → '.join(x.line for x in st)}, alight {st[-1].alight}, "
                                                  f"{sum(x.stops for x in st)} stops"))
            marks += leg_markers(leg, self.data.modes, self.walk_max)
        if it.pickup_time:
            pairs.append(("PICKUP", it.pickup_time + (f" · {it.pickup_place}" if it.pickup_place else "")))
        if b:
            if not b.timed:
                pairs.append(("YOUR BOOKING", "Valid all day"))
            elif b.time:
                pairs.append(("YOUR BOOKING", b.time + (f"–{b.end_time}" if b.end_time else "")))
            else:
                pairs.append(("YOUR BOOKING", _verify("booking time")))
            if b.meeting_point:
                pairs.append(("MEETING POINT", b.meeting_point))
        elif it.time and not it.pickup_time:
            pairs.append(("TIME", it.time))
        duration = (b.duration if b else "") or lib.get("recommended_duration") or lib.get("duration")
        if duration:
            pairs.append(("DURATION", duration))
        elif at and at.duration:
            pairs.append(("DURATION", [at.duration, _verify("duration")]))
        note = (it.note or "").strip()
        if note and (it.optional or note.lower().startswith("choose one") or "own expense" in note.lower()):
            pairs.append(("NOTE", note))
        if found and p.hours and is_optional(it) and is_open_for(p.hours, rd.date, s.start, 30) is False:
            opening = next_opening(p.hours, rd.date, s.start)
            if opening:
                pairs.append(("NOTE", f"Opens {_fmt12(opening)}: best visited later in the day"))
        if found and it.kind != "transfer":
            pairs.append(("OPENING HOURS", format_for_day(p.hours, rd.date) if p.hours else _verify("opening hours")))
        for label, value, what in (("ENTRY FEE", at and at.entry_fee, "entry fee"),
                                   ("DRESS CODE", at and at.dress_code, "dress code"),
                                   ("BEST TIME", at and at.best_time, "best time"),
                                   ("TIP", at and at.tips, "tip")):
            if value:
                pairs.append((label, [value, _verify(what)]))
        if self.self_drive:
            pairs.append(("PARKING", self._parking(lib)))
        sunset = self._sunset(it, at, p if found else None)
        if sunset:
            pairs.append(("SUNSET", f"about {sunset:%H:%M}"))
        if it.optional:
            pairs.append(("NOTE", "Optional"))
        if b and b.included_in_package:
            pairs.append(("NOTE", "Included in your package"))
        facts, fmarks = _facts(pairs)
        if found and p.website and at and at.entry_fee:
            facts.append(g.Fact(label="Tickets and entry fees", value="official website",
                                link=g.Link(text="official website", url=p.website)))
        if not found and it.kind != "transfer":
            marks.append(_verify("place not found on Google"))
        if p is not None and p.status not in ("OPERATIONAL", "UNKNOWN"):
            marks.append(_verify(f"Google lists this place as {p.status.replace('_', ' ').lower()}"))
        text = at.description if at and at.description else ""
        if it.kind == "transfer" and self._late_night_item(s):
            text = f"Your representative and driver will meet you after you land at {_hm(rd.arrival.arrive)}. {text}".strip()
        self.out.append(g.SightseeingCard(
            when=when, part=part, name=g.Link(text=it.name, url=p.maps_url if found else search_url(it.name, rd.city)),
            facts=facts, text=text, tips=list(b.instructions) if b else [],
            markers=fmarks + [_ref(m) for m in marks + place_markers(p)]))

    def _sunset(self, it, at, p):
        if self.rd.utc_offset_hours is None:
            return None
        blob = " ".join(x for x in (it.name, it.note, at and at.description, at and at.tips) if x)
        if "sunset" not in blob.lower():
            return None
        hotel = self.rd.places.get(getattr(self._stay(arriving=True), "hotel", ""))
        where = p or (hotel if hotel is not None and hotel.match_ok else None)
        return sunset_time(where.lat, where.lng, self.rd.date, self.rd.utc_offset_hours) if where else None

    # ---- meals
    def _meal(self, slot: MealSlot) -> None:
        meal, rd = slot.meal.capitalize(), self.rd
        eyebrow = f"{_fmt12(slot.start)}  ·  {slot.meal.upper()}"
        if slot.included:
            self.out.append(g.SimpleCard(when=_fmt12(slot.start), part=meal, heading=f"{meal} — Included in your package"))
            return
        pick: Optional[MealPick] = next((m for m in rd.meals if m.slot.meal == slot.meal and m.slot.start == slot.start), None)
        anchors = slot.anchors if not slot.unanchored and slot.anchors else [(rd.city, None, 3)]
        rest, markers = (list(pick.restaurants), list(pick.markers)) if pick else ([], [])
        day_index = pick.day_index if pick else rd.index
        for i, (name, _, count) in enumerate(anchors):
            where = f"{meal}, Day {day_index}, near {name}"
            mine = [m for m in markers if m.kind == "ADD_RESTAURANT" and m.text == where]
            if pick is None:
                mine = [Marker(kind="ADD_RESTAURANT", text=where)] * count
            take = len(rest) if i == len(anchors) - 1 else max(count - len(mine), 0)
            chunk, rest = rest[:take], rest[take:]
            markers = [m for m in markers if m not in mine]
            self._meal_block(slot, eyebrow, f"{meal} near {name}", chunk, mine, count)
        self.marks(markers)

    def _meal_block(self, slot, eyebrow, heading, chunk, mine, count) -> None:
        if not chunk:
            self.out.append(g.PlaceholderMeal(meal=slot.meal, eyebrow=eyebrow, heading=heading, count=count))
            self.marks(mine)
            return
        built = [self._restaurant(c) for c in chunk]
        self.out.append(g.MealBlock(meal=slot.meal, eyebrow=eyebrow, heading=heading, restaurants=[r for r, _ in built]))
        self.marks([m for _, ms in built for m in ms] + mine)

    def _restaurant(self, c: ChosenRestaurant) -> tuple[g.Restaurant, list]:
        rd, lib = self.rd, c.lib
        name = lib.get("name", c.place.name)
        cuisine = lib.get("cuisine_type")
        cuisines = [str(x) for x in cuisine] if isinstance(cuisine, list) else ([str(cuisine)] if cuisine else [])
        price = rd.price_by_restaurant.get(name) or Marker(kind="PRICE_UNKNOWN", text="")
        if isinstance(price, Marker):
            price = g.MarkerRef(kind=price.kind, text=name if price.kind == "PRICE_UNKNOWN" else price.text)
        marks: list = []
        hours = c.hours_text.strip() or None
        if hours is None:
            marks.append(g.MarkerRef(kind="VERIFY", text=f"{name}: opening hours"))
        elif c.hours_verify:
            marks.append(g.MarkerRef(kind="VERIFY", text=f"{name}: opening hours from the library"))
        dishes = lib.get("must_try_dishes")
        rt = self.rtexts.get(norm_name(name))
        travel = f"{c.travel_label} · {c.travel_min} min"
        if self.self_drive:
            pk = self._parking(lib)
            if isinstance(pk, Marker):
                marks.append(g.MarkerRef(kind="VERIFY", text=f"{name}: parking"))
            else:
                travel += f" · Parking: {pk}"
        marks += [_ref(m) for m in place_markers(c.place)]
        text = " ".join(x for x in (rt.ambience if rt else "", f"Best for {rt.best_for}" if rt and rt.best_for else "") if x)
        return g.Restaurant(
            name=name, maps_url=c.place.maps_url or search_url(name, rd.city), cuisines=cuisines,
            veg=lib.get("vegetarian_friendly") is True, text=text,
            must_try=", ".join(str(x) for x in dishes[:3]) if isinstance(dishes, list) and dishes else "",
            hours=hours, price=price, travel=travel), marks


# ------------------------------------------------------------------ reference pages
_TITLES = dict(BEFORE_YOU_GO + WHILE_THERE)


def _paras(items: list[SectionItem]) -> list[g.TitledPara]:
    return [g.TitledPara(heading=i.heading, body=i.body) for i in items]


def build_reference_page(key: str, content: SectionContent, data: GuideData) -> g.Page:
    title = _TITLES.get(key, key.replace("_", " ").title())
    eyebrow = "BEFORE YOU GO" if key in dict(BEFORE_YOU_GO) else "WHILE YOU'RE THERE"
    comps: list = [g.ReferenceOpener(eyebrow=eyebrow, title=title, intro="")]
    items = list(content.items)
    if content.by_country:
        many = len(content.by_country) > 1
        for country, its in content.by_country.items():
            head = [g.TitledPara(heading=country or "General", body="")] if many else []
            comps.append(g.TitledParas(items=head + _paras(its)))
            items += its
    elif content.items:
        comps.append(g.TitledParas(items=_paras(content.items)))
    marks = [g.MarkerRef(kind="VERIFY", text=i.heading) for i in items if i.verify]
    marks += [_ref(x) for x in content.markers]
    if marks:
        comps.append(g.ReviewMarkerBlock(markers=marks))
    return g.Page(kind="reference", title=title, bookmark=f"sec_{key}", components=comps)


def _span(a: date, b: date) -> str:
    if a.year != b.year:
        return f"{a.day} {a:%B} {a.year} \u2013 {b.day} {b:%B} {b.year}"
    if a.month == b.month:
        return f"{a.day} \u2013 {b.day} {b:%B}"
    return f"{a.day} {a:%B} \u2013 {b.day} {b:%B}"


def _nearby(n: NearbyPlace, city: str) -> g.NearbyPlace:
    p = n.place
    marks = [_ref(x) for x in n.markers + place_markers(p, n.markers)]
    if n.walk_min is None and n.drive_min is None:
        marks.append(g.MarkerRef(kind="VERIFY", text=f"{p.name}: travel time from the hotel"))
    return g.NearbyPlace(name=g.Link(text=p.name, url=p.maps_url or search_url(p.name, city)),
                         walk_min=n.walk_min, drive_min=n.drive_min, hours_text=n.hours_text, phone=p.phone,
                         markers=marks)


def build_important_page(entries: list[ImportantPlaces], data: Optional[GuideData] = None) -> Optional[g.Page]:
    if not entries:
        return None
    stays = data.trip.hotels if data else []
    places = {name: p for d in (data.days if data else []) for name, p in d.places.items()}
    hotels = []
    unused = sorted(stays, key=lambda s: s.check_in)
    for e in entries:
        same = [s for s in unused if norm_name(s.hotel) == norm_name(e.hotel)]
        stay = next((s for s in same if norm_name(s.city) == norm_name(e.city)), same[0] if same else None)
        if stay is not None:
            unused.remove(stay)
        p = places.get(e.hotel)
        url = p.maps_url if p is not None and p.match_ok else search_url(e.hotel, e.city)
        hotels.append(g.HotelPlaces(
            hotel=g.Link(text=e.hotel, url=url), city=e.city,
            dates=_span(stay.check_in, stay.check_out) if stay else "",
            pharmacies=[_nearby(n, e.city) for n in e.pharmacies],
            groceries=[_nearby(n, e.city) for n in e.groceries],
            hospitals=[_nearby(e.hospital, e.city)] if e.hospital else [],
            markers=[_ref(x) for x in e.markers]))
    title = _TITLES["important"]
    return g.Page(kind="reference", title=title, bookmark="sec_important", components=[
        g.ReferenceOpener(eyebrow="WHILE YOU'RE THERE", title=title, intro=""), g.PlaceGroups(hotels=hotels)])


def build_day_page(rd: RenderDay, data: GuideData, settings) -> g.Page:
    return _Day(rd, data, settings.walk_max_min).build()


def build_guide(data: GuideData, settings) -> g.Guide:
    names = [n for n in data.trip.client_names if n.strip()]
    first = names[0].split()[0] if names else "Guest"
    dest = ", ".join(destinations(data.trip))
    letter = g.Page(kind="letter", title="Letter", bookmark="letter", components=[
        g.Letter(salutation=f"Dear {first},", paragraphs=[], signoff="With love,", signature=_BRAND),
        g.ReviewMarkerBlock(markers=[g.MarkerRef(kind="WRITE_LETTER", text="")])])
    pages = [letter, g.Page(kind="toc", title="Contents", bookmark="toc")]
    pages += [build_day_page(rd, data, settings) for rd in data.days]
    for key, _ in BEFORE_YOU_GO + WHILE_THERE:
        if not _present(data, key):
            continue
        ref = build_important_page(data.important, data) if key == "important" else build_reference_page(key, data.sections[key], data)
        if ref is not None:
            pages.append(ref)
    pages.append(g.Page(kind="thank_you", title="Thank You", bookmark="thank_you"))
    return g.Guide(client=names[0] if names else "Guest", destination=dest, title=data.title,
                   subtitle=f"All Inclusive Guide – {dest}", pages=pages)
