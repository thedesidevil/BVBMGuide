import math
import re
from datetime import date, datetime, time
from typing import Optional

from src.aigv2.hours import format_for_day
from src.aigv2.library import norm_name
from src.aigv2.models import HotelStay, Marker, Place, TransportLeg
from src.aigv2.planning.meals import ChosenRestaurant
from src.aigv2.planning.slots import MealSlot, ScheduledItem, leave_by
from src.aigv2.planning.travel import Leg, drive_day_legs, leg_markers, leg_options
from src.aigv2.render.blocks import add_card, add_eyebrow, add_link, add_slot_heading
from src.aigv2.render.sections_render import marker_lines, minutes_text, place_markers, search_url, heading1
from src.aigv2.writing.days import AttractionText

_PORT = {"flight": "Airport", "train": "Station", "boat": "Harbor", "bus": "Bus station", "other": "Arrival point"}
_REACH = {"flight": "Leave for the airport by", "train": "Reach the station by", "boat": "Reach the harbor by"}
_SLOT_TITLE = {"morning": "Morning", "afternoon": "Afternoon", "evening": "Evening"}
_SUNSET = re.compile(r"sunset", re.I)


def day_header(index: int, d: date, title: str) -> str:
    return f"Day {index} – {d:%a}, {d.day} {d:%b} | {title}"


def sunset_time(lat: float, lng: float, d: date, utc_offset_hours: float) -> Optional[time]:
    """NOAA approximate solar equations; None during polar day or night."""
    g = 2 * math.pi / 365 * (d.timetuple().tm_yday - 1)
    eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                   - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    c = math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl)) - math.tan(la) * math.tan(decl)
    if not -1 <= c <= 1:
        return None
    minutes = round(720 - 4 * (lng - math.degrees(math.acos(c))) - eq + utc_offset_hours * 60) % 1440
    return time(minutes // 60, minutes % 60)


def _verify(text: str) -> Marker:
    return Marker(kind="VERIFY", text=text)


def _hm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


class DayRenderer:
    def __init__(self, doc, data, rd, walk_max: int):
        self.doc, self.data, self.rd, self.walk_max = doc, data, rd, walk_max
        self.self_drive = "self_drive" in data.modes
        self.texts = {norm_name(a.name): a for a in rd.text.attractions}
        self.rtexts = {norm_name(r.name): r for r in rd.text.restaurants}
        self.plan = next((p for p in data.trip.days if p.date == rd.date), None)
        self.free_time_used = False

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

    def render(self) -> None:
        rd, doc = self.rd, self.doc
        heading1(doc, day_header(rd.index, rd.date, rd.text.title), f"day_{rd.index}")
        doc.add_paragraph(rd.text.intro)
        for tip in rd.result.tips:
            doc.add_paragraph(tip, style="List Bullet")
        marker_lines(doc, rd.result.markers)
        cruise = self._cruise()
        arr, dep = rd.arrival, rd.departure
        early_dep = bool(dep and arr and (dep is arr or (dep.depart and arr.arrive and dep.depart <= arr.arrive)))
        if rd.prev_city and norm_name(rd.prev_city) != norm_name(rd.city) and not cruise:
            marker_lines(doc, [_verify("inter-city travel day logistics")])
        if cruise:
            self._port_day(arr, dep)
        else:
            if early_dep:
                self._departure(dep, transport_card=dep is not arr, city=rd.prev_city or rd.city)
            if arr:
                self._arrival(arr)
            else:
                self._check_in()
        self._drive_stops()
        self._timeline()
        if rd.text.free_time_idea and not self.free_time_used:
            doc.add_paragraph(rd.text.free_time_idea)
        final = bool(dep and not early_dep and not cruise)
        if final:
            self._departure(dep, transport_card=True, city=rd.city)
        else:
            self._overnight(cruise)

    def _overnight(self, cruise: Optional[HotelStay]) -> None:
        d = self.rd.date
        ship = cruise or next((s for s in self.data.trip.hotels
                               if s.kind == "cruise" and s.check_in <= d < s.check_out), None)
        text = f"Overnight on board {ship.hotel}" if ship else f"Overnight in {self.rd.city}"
        p = self.doc.add_paragraph()
        run = p.add_run(text)
        run.italic = True

    def _port_day(self, arr: Optional[TransportLeg], dep: Optional[TransportLeg]) -> None:
        if arr and arr.arrive:
            self.doc.add_paragraph(f"Docks at {arr.to_place or self.rd.city} at {_hm(arr.arrive)}")
        if dep and dep.depart:
            self.doc.add_paragraph(f"Back on board by {leave_by(dep, self.data.domestic):%H:%M}")
        if (arr and arr.arrive) or (dep and dep.depart):
            marker_lines(self.doc, [_verify("docking and all-aboard times")])

    def _hotel_markers(self, hotel: str) -> list[Marker]:
        p = self.rd.places.get(hotel)
        missing = [] if p is not None and p.match_ok else [_verify(f"{hotel} not found on Google")]
        return missing + place_markers(p)

    def _check_in(self) -> None:
        stay = next((s for s in self.data.trip.hotels if s.check_in == self.rd.date), None)
        if stay is None:
            return
        prev = self.rd.prev_city
        if prev and norm_name(prev) != norm_name(self.rd.city):
            self._transfer_card(f"{prev} → {stay.hotel}", self._url(stay.hotel), self.rd.legs.get("arrival"),
                                None, stay.hotel)
            return
        facts = [("CHECK-IN", f"from {stay.check_in_time:%H:%M}")] if stay.check_in_time else []
        add_card(self.doc, stay.hotel, self._url(stay.hotel), facts, None, [])
        marker_lines(self.doc, self._hotel_markers(stay.hotel))

    def _transfer_card(self, title: str, url: str, leg: Optional[Leg], body: Optional[str],
                       hotel: Optional[str]) -> None:
        if leg is None:
            facts = [("TRANSFER", _verify("transfer time")), ("COST", _verify("transfer cost"))]
            markers = []
        else:
            opts = self._options(leg)
            facts = [("TRANSFER", opts or _verify("transfer time")), ("COST", _verify("transfer cost"))]
            markers = leg_markers(leg, self.data.modes, self.walk_max)
        add_card(self.doc, title, url, facts, body, [])
        marker_lines(self.doc, markers + (self._hotel_markers(hotel) if hotel else []))

    def _transport_card(self, t: TransportLeg, link_to: str, city: str = "") -> None:
        kind = {"flight": "Flight", "train": "Train", "boat": "Boat", "bus": "Bus"}.get(t.kind, "Transfer")
        title = f"{kind}: {t.from_place} to {t.to_place}" if t.from_place and t.to_place else kind
        facts: list = []
        if t.operator:
            facts.append(("OPERATOR", t.operator))
        if t.number:
            facts.append(("SERVICE", t.number))
        if t.seat:
            facts.append(("CLASS / SEAT", t.seat))
        if t.depart:
            facts.append(("DEPARTS", f"{_hm(t.depart)} · {t.from_place}" if t.from_place else _hm(t.depart)))
        if t.arrive:
            facts.append(("ARRIVES", f"{_hm(t.arrive)} · {t.to_place}" if t.to_place else _hm(t.arrive)))
        if t.kind == "train" and t.depart and t.arrive and t.arrive > t.depart:
            mins = int((t.arrive - t.depart).total_seconds() // 60)
            facts.append(("DURATION", [minutes_text(mins), _verify("duration (check time zones)")]))
        if t.kind == "train" and t.ref and t.platform:
            facts.append(("PLATFORM", t.platform))
        if t.ref:
            facts.append(("REFERENCE", t.ref))
        where = link_to or t.to_place or t.from_place
        add_card(self.doc, title, search_url(where, city) if where.strip() else None, facts, None, [])

    def _arrival(self, arr: TransportLeg) -> None:
        stay = self._stay(arriving=True)
        if arr is not self.rd.departure:
            self._transport_card(arr, arr.to_place, self.rd.city)
        else:
            self._transport_card(arr, arr.from_place, self.rd.prev_city or self.rd.city)
        if stay is None:
            marker_lines(self.doc, [_verify(f"hotel for {self.rd.date.isoformat()}")])
            return
        port = arr.to_place or _PORT[arr.kind]
        body = None
        check_in = stay.check_in_time or time(15)
        if arr.arrive and stay.check_in == self.rd.date and arr.arrive.time() < check_in:
            body = ("You arrive before check-in. If your room is not ready yet, ask the front desk to hold your "
                    "luggage while you head out.")
        self._transfer_card(f"{port} → {stay.hotel}", self._url(stay.hotel), self.rd.legs.get("arrival"), body,
                            stay.hotel)

    def _departure(self, dep: TransportLeg, transport_card: bool, city: str) -> None:
        by = leave_by(dep, self.data.domestic)
        if by:
            self.doc.add_paragraph(f"{_REACH.get(dep.kind, 'Leave by')} {_hm(by)}")
        marker_lines(self.doc, [_verify("departure time")])
        stay = self._stay(arriving=False)
        port = dep.from_place or _PORT[dep.kind]
        if stay:
            self._transfer_card(f"{stay.hotel} → {port}", search_url(port, city),
                                self.rd.legs.get("departure"), None, None)
        else:
            marker_lines(self.doc, [_verify(f"hotel to leave from on {self.rd.date.isoformat()}")])
        if transport_card:
            self._transport_card(dep, dep.from_place, city)

    def _drive_stops(self) -> None:
        if not self.plan or not self.plan.drive_stops:
            return
        _, minutes, km = drive_day_legs(self.rd.city, self.plan.drive_stops)
        add_eyebrow(self.doc, "Today's drive")
        for s in self.plan.drive_stops:
            self.doc.add_paragraph(f"{s.name} — {s.km_from_prev:g} km · {minutes_text(s.minutes_from_prev)}",
                                   style="List Bullet")
        self.doc.add_paragraph(f"Total today: {km:g} km · {minutes_text(minutes)}")

    def _timeline(self) -> None:
        entries = [(s.start, 0, i, s) for i, s in enumerate(self.rd.result.scheduled)]
        entries += [(m.start, 1, i, m) for i, m in enumerate(self.rd.result.meals)]
        entries += [((t.depart or t.arrive).time(), -1, i, t) for i, t in enumerate(self.rd.other_transport)
                    if t.depart or t.arrive]
        slot = None
        for _, _, _, e in sorted(entries, key=lambda x: x[:3]):
            if isinstance(e, TransportLeg):
                self._transport_card(e, e.to_place)
                marker_lines(self.doc, [_verify(f"day-trip transport {e.from_place or '?'} → {e.to_place or '?'}: "
                                                "confirm times and how to reach the departure point")])
                slot = None
            elif isinstance(e, ScheduledItem):
                if e.slot != slot:
                    slot = e.slot
                    add_slot_heading(self.doc, _SLOT_TITLE[slot])
                self._item(e)
            else:
                self._meal(e)
                slot = None

    def _travel_line(self, name: str) -> None:
        leg = self.rd.legs.get(name)
        if leg is None:
            return
        opts = self._options(leg)
        if opts:
            self.doc.add_paragraph("Getting there: " + "  |  ".join(opts))
        if leg.transit_steps and any("public transport" in o for o in opts):
            st = leg.transit_steps
            self.doc.add_paragraph(f"Public transport: {' → '.join(s.line for s in st)}, alight {st[-1].alight}, "
                                   f"{sum(s.stops for s in st)} stops")
        marker_lines(self.doc, leg_markers(leg, self.data.modes, self.walk_max))

    def _parking(self, lib: dict):
        v = lib.get("parking")
        return v if isinstance(v, str) and v.strip() else _verify("parking")

    def _item(self, s: ScheduledItem) -> None:
        it, rd = s.item, self.rd
        if it.kind == "free_time":
            add_eyebrow(self.doc, "Free time")
            self.doc.add_paragraph(rd.text.free_time_idea or it.name)
            self.free_time_used = True
            return
        self._travel_line(it.name)
        at: Optional[AttractionText] = self.texts.get(norm_name(it.name))
        p = rd.places.get(it.name)
        found = p is not None and p.match_ok
        b = rd.booking_by_item.get(it.name)
        lib = rd.library_attractions.get(it.name, {})
        facts: list = []
        if it.pickup_time:
            facts.append(("PICKUP", it.pickup_time + (f" · {it.pickup_place}" if it.pickup_place else "")))
        if b:
            if not b.timed:
                facts.append(("YOUR BOOKING", "Valid all day"))
            elif b.time:
                facts.append(("YOUR BOOKING", b.time + (f"–{b.end_time}" if b.end_time else "")))
            else:
                facts.append(("YOUR BOOKING", _verify("booking time")))
            if b.meeting_point:
                facts.append(("MEETING POINT", b.meeting_point))
        elif it.time and not it.pickup_time:
            facts.append(("TIME", it.time))
        duration = (b.duration if b else "") or lib.get("recommended_duration") or lib.get("duration")
        if duration:
            facts.append(("DURATION", duration))
        elif at and at.duration:
            facts.append(("DURATION", [at.duration, _verify("duration")]))
        if found and it.kind != "transfer":
            facts.append(("OPENING HOURS", format_for_day(p.hours, rd.date) if p.hours else _verify("opening hours")))
        for label, value, what in (("ENTRY FEE", at and at.entry_fee, "entry fee"),
                                   ("DRESS CODE", at and at.dress_code, "dress code"),
                                   ("BEST TIME", at and at.best_time, "best time"),
                                   ("TIP", at and at.tips, "tip")):
            if value:
                facts.append((label, [value, _verify(what)]))
        if self.self_drive:
            facts.append(("PARKING", self._parking(lib)))
        sunset = self._sunset(it, at, p if found else None)
        if sunset:
            facts.append(("SUNSET", f"about {sunset:%H:%M}"))
        pills = (["Optional"] if it.optional else []) + (["Included in your package"] if b and b.included_in_package else [])
        url = p.maps_url if found else search_url(it.name, rd.city)
        table = add_card(self.doc, it.name, url, facts, at.description if at else None, pills)
        cell = table.cell(0, 0)
        if found and p.website and at and at.entry_fee:
            lp = cell.add_paragraph("Tickets and entry fees: ")
            add_link(lp, "official website", p.website)
        for instr in (b.instructions if b else []):
            cell.add_paragraph(instr, style="List Bullet")
        markers = [] if found else [_verify("place not found on Google")]
        if p is not None and p.status not in ("OPERATIONAL", "UNKNOWN"):
            markers.append(_verify(f"Google lists this place as {p.status.replace('_', ' ').lower()}"))
        marker_lines(self.doc, markers + place_markers(p))

    def _sunset(self, it, at: Optional[AttractionText], p: Optional[Place]) -> Optional[time]:
        if self.rd.utc_offset_hours is None:
            return None
        blob = " ".join(x for x in (it.name, it.note, at and at.description, at and at.tips) if x)
        if not _SUNSET.search(blob):
            return None
        hotel = self.rd.places.get(getattr(self._stay(arriving=True), "hotel", ""))
        where = p or (hotel if hotel is not None and hotel.match_ok else None)
        if where is None:
            return None
        return sunset_time(where.lat, where.lng, self.rd.date, self.rd.utc_offset_hours)

    def _meal(self, slot: MealSlot) -> None:
        meal = slot.meal.capitalize()
        if slot.included:
            p = self.doc.add_paragraph()
            p.add_run(f"{meal} — Included in your package").bold = True
            return
        pick = next((m for m in self.rd.meals if m.slot.meal == slot.meal and m.slot.start == slot.start), None)
        if pick is None:
            for name, _, count in (slot.anchors if not slot.unanchored and slot.anchors else [(self.rd.city, None, 3)]):
                add_slot_heading(self.doc, f"{meal} near {name}")
                where = f"{meal}, Day {self.rd.index}, near {name}"
                marker_lines(self.doc, [Marker(kind="ADD_RESTAURANT", text=where)] * count)
            return
        if slot.unanchored or not slot.anchors:
            add_slot_heading(self.doc, f"{meal} near {self.rd.city}")
            for c in pick.restaurants:
                self._restaurant(c)
            marker_lines(self.doc, pick.markers)
            return
        rest, markers = list(pick.restaurants), list(pick.markers)
        for i, (name, _, count) in enumerate(slot.anchors):
            add_slot_heading(self.doc, f"{meal} near {name}")
            where = f"{meal}, Day {pick.day_index}, near {name}"
            mine = [m for m in markers if m.kind == "ADD_RESTAURANT" and m.text == where]
            take = len(rest) if i == len(slot.anchors) - 1 else max(count - len(mine), 0)
            for c in rest[:take]:
                self._restaurant(c)
            rest = rest[take:]
            marker_lines(self.doc, mine)
            markers = [m for m in markers if m not in mine]
        marker_lines(self.doc, markers)

    def _restaurant(self, c: ChosenRestaurant) -> None:
        lib, name = c.lib, c.lib.get("name", c.place.name)
        facts: list = []
        cuisine = lib.get("cuisine_type")
        if cuisine:
            facts.append(("CUISINE", ", ".join(cuisine) if isinstance(cuisine, list) else str(cuisine)))
        facts.append(("PRICE", self.rd.price_by_restaurant.get(name) or Marker(kind="PRICE_UNKNOWN", text="")))
        facts.append(("OPENING HOURS", [c.hours_text, _verify("opening hours from the library")]
                      if c.hours_verify else c.hours_text))
        facts.append(("GETTING THERE", f"{c.travel_label} · {c.travel_min} min"))
        dishes = lib.get("must_try_dishes")
        if isinstance(dishes, list) and dishes:
            facts.append(("MUST TRY", ", ".join(str(x) for x in dishes[:3])))
        rt = self.rtexts.get(norm_name(name))
        if rt and rt.best_for:
            facts.append(("BEST FOR", rt.best_for))
        if self.self_drive:
            facts.append(("PARKING", self._parking(lib)))
        pills = ["Vegetarian friendly"] if lib.get("vegetarian_friendly") is True else []
        add_card(self.doc, name, c.place.maps_url or search_url(name, self.rd.city), facts,
                 rt.ambience if rt else None, pills)
        marker_lines(self.doc, place_markers(c.place))


