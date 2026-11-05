import json
import re
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from src.aigv2.guide import MarkerRef
from src.aigv2.guide import model as m
from src.aigv2.guide.build import build_day_page, build_guide
from src.aigv2.models import HotelStay, Marker, TransportLeg
from src.aigv2.render.document import GuideData, destinations

SETTINGS = SimpleNamespace(walk_max_min=10)
FIX = Path(__file__).parent / "fixtures" / "bali_guide" / "guide_data.json"


def load() -> GuideData:
    return GuideData.model_validate(json.loads(FIX.read_text(encoding="utf-8")))


def day(data: GuideData, index: int):
    return next(d for d in data.days if d.index == index)


def page(index: int = 2, data: GuideData | None = None):
    data = data or load()
    return build_day_page(day(data, index), data, SETTINGS)


def test_day2_components_order():
    p = page(2)
    assert p.kind == "day" and p.bookmark == "day_2"
    assert p.title == "Day 2 – Fri, 25 Sep | Tegallalang Rice Terrace, Ubud Palace and Ubud Market"
    kinds = [c.type for c in p.components]
    assert kinds[:3] == ["Opener", "YourDay", "SimpleCard"]
    assert p.components[2].part == "Breakfast"
    # The real Day 2 has no return leg (no transport for a mid-stay sightseeing day), so no BookingCard;
    # the day-level VERIFY (tour booking not placed) closes the page as a ReviewMarkerBlock.
    assert p.components[3].part == "Your booking"  # the tour voucher is named ahead of its stops
    assert kinds[3:] == ["SimpleCard", "SightseeingCard", "SightseeingCard", "MealBlock", "SightseeingCard", "MealBlock",
                         "SimpleCard", "ReviewMarkerBlock"]
    assert p.components[-2].heading == "Overnight in Ubud"
    assert [c.meal for c in p.components if c.type == "MealBlock"] == ["lunch", "dinner"]
    opener = p.components[0]
    assert (opener.number, opener.weekday, opener.date) == (2, "Friday", "25 September")


def test_meal_block_has_three_restaurants_with_links():
    p = page(2)
    lunch = next(c for c in p.components if c.type == "MealBlock" and c.meal == "lunch")
    assert len(lunch.restaurants) == 3
    for r in lunch.restaurants:
        assert r.maps_url and r.maps_url.startswith("https://www.google.com/maps")
        assert r.hours and r.travel
    first = lunch.restaurants[0]
    assert first.hours == "12:00 PM – 11:30 PM" and first.cuisines == ["Indian"]
    assert first.travel == "Walk · 1 min"
    assert first.must_try == "Chole Bhature, Paneer Tikka, Vegetable Biryani"
    assert lunch.heading == "Lunch near Ubud Palace" and lunch.eyebrow.endswith("LUNCH")


def test_no_restaurants_gives_placeholder_meal():
    data = load()
    for pick in day(data, 2).meals:
        if pick.slot.meal == "lunch":
            pick.restaurants, pick.markers = [], [Marker(kind="ADD_RESTAURANT", text="Lunch, Day 2, near Ubud Palace")] * 3
    p = page(2, data)
    ph = [c for c in p.components if c.type == "PlaceholderMeal"]
    assert len(ph) == 1 and ph[0].meal == "lunch" and ph[0].count == 3
    assert not [c for c in p.components if c.type == "MealBlock" and c.meal == "lunch"]
    review = [c for c in p.components if c.type == "ReviewMarkerBlock"]
    texts = [mk.text for b in review for mk in b.markers if mk.kind == "ADD_RESTAURANT"]
    assert texts == ["Lunch, Day 2, near Ubud Palace"] * 3


def test_missing_hours_gives_marker_not_blank():
    data = load()
    pick = next(x for x in day(data, 2).meals if x.slot.meal == "lunch")
    c = pick.restaurants[0]
    name = c.lib["name"]
    c.hours_text, c.hours_verify = "", True
    day(data, 2).price_by_restaurant.pop(name, None)
    p = page(2, data)
    lunch = next(x for x in p.components if x.type == "MealBlock" and x.meal == "lunch")
    r = lunch.restaurants[0]
    assert r.price == MarkerRef(kind="PRICE_UNKNOWN", text=name)
    assert r.hours is None
    marks = [mk for b in p.components if b.type == "ReviewMarkerBlock" for mk in b.markers]
    assert MarkerRef(kind="VERIFY", text=f"{name}: opening hours") in marks


def test_build_guide_wraps_day_pages():
    data = load()
    g = build_guide(data, SETTINGS)
    assert [pg.kind for pg in g.pages] == ["letter", "toc", "day", "day", "day", "day", "day", "day", "thank_you"]
    letter = g.pages[0].components
    assert letter[0].paragraphs == [] and letter[1].markers == [MarkerRef(kind="WRITE_LETTER", text="")]
    assert g.client == "Test Client One" and g.title == data.title
    assert [c.type for c in g.pages[3].components][:2] == ["Opener", "YourDay"]


def test_day_markers_ride_on_the_day():
    p = page(2)
    marks = [mk for c in p.components if c.type == "ReviewMarkerBlock" for mk in c.markers]
    assert any("is not placed in the day plan" in mk.text for mk in marks)


def _stays(data, kind="hotel"):
    return [HotelStay(city="Ubud", hotel="Ship One", check_in=date(2026, 9, 24), check_out=date(2026, 9, 28),
                      source="voucher", kind=kind)]


def test_departure_line_survives_without_hotel_stay():
    data = load()
    rd = day(data, 2)
    data.trip.hotels = []
    rd.departure = TransportLeg(kind="flight", from_place="Ngurah Rai Airport", to_place="Singapore",
                                depart=datetime(2026, 9, 25, 18, 0), source="t")
    p = page(2, data)
    simple = [c.heading for c in p.components if c.type == "SimpleCard"]
    assert any(h.startswith("Leave for the airport by") for h in simple)


def test_cruise_day_uses_port_branch_and_overnight_on_board():
    data = load()
    data.trip.hotels = _stays(data, "cruise")
    rd = day(data, 2)
    rd.arrival = TransportLeg(kind="boat", from_place="A", to_place="Benoa", arrive=datetime(2026, 9, 25, 8, 0),
                              source="t")
    p = page(2, data)
    heads = [c.heading for c in p.components if c.type == "SimpleCard"]
    assert "Docks at Benoa" in heads and "Overnight on board Ship One" in heads
    marks = [mk.text for b in p.components if b.type == "ReviewMarkerBlock" for mk in b.markers]
    assert "docking and all-aboard times" in marks


def test_meal_without_pick_is_placeholder():
    data = load()
    day(data, 2).meals = []
    p = page(2, data)
    ph = [c for c in p.components if c.type == "PlaceholderMeal"]
    assert [c.meal for c in ph] == ["lunch", "dinner"]
    adds = [mk for b in p.components if b.type == "ReviewMarkerBlock" for mk in b.markers if mk.kind == "ADD_RESTAURANT"]
    assert len(adds) == 6 and adds[0].text == "Lunch, Day 2, near Ubud Palace"


def test_restaurant_without_maps_link_gets_search_url():
    data = load()
    pick = next(x for x in day(data, 2).meals if x.slot.meal == "lunch")
    pick.restaurants[0].place.maps_url = None
    p = page(2, data)
    lunch = next(x for x in p.components if x.type == "MealBlock" and x.meal == "lunch")
    assert lunch.restaurants[0].maps_url.startswith("https://www.google.com/maps/search/?api=1&query=")


def test_day_with_no_places_still_builds():
    data = load()
    day(data, 2).places = {}
    p = page(2, data)
    cards = [c for c in p.components if c.type == "SightseeingCard"]
    assert cards and all(c.name.url.startswith("https://www.google.com/maps/search") for c in cards)
    assert any(mk.text == "place not found on Google" for c in cards for mk in c.markers)


def test_self_drive_parking_text_survives():
    data = load()
    data.modes = ["self_drive"]
    pick = next(x for x in day(data, 2).meals if x.slot.meal == "lunch")
    pick.restaurants[0].lib["parking"] = "Free lot behind"
    pick.restaurants[1].lib.pop("parking", None)
    p = page(2, data)
    lunch = next(x for x in p.components if x.type == "MealBlock" and x.meal == "lunch")
    assert "Parking: Free lot behind" in lunch.restaurants[0].travel
    marks = [mk.text for b in p.components if b.type == "ReviewMarkerBlock" for mk in b.markers]
    assert any(t.endswith(": parking") for t in marks)


def _walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_day1_late_arrival_cards():
    from src.aigv2.models import TripPlan
    from src.aigv2.planning.late_night import driver_time
    data = load()
    rd = day(data, 1)
    bali = Path(__file__).parent / "fixtures" / "bali" / "trip_plan.json"
    trip = TripPlan.model_validate(json.loads(bali.read_text(encoding="utf-8")))
    pick = next(b for b in trip.bookings if b.time == "23:00")
    rd = rd.model_copy(update={"arrival_booking": pick, "driver_from": driver_time(pick)})
    assert rd.lands_next_day and rd.driver_from == time(23, 0)
    p = build_day_page(rd, data, SETTINGS)
    dumped = p.model_dump(mode="json")
    nodes = [n for n in _walk(dumped) if isinstance(n, dict)]
    assert not [n for n in nodes if n.get("type") in ("MealBlock", "PlaceholderMeal")]
    text = json.dumps(dumped, ensure_ascii=False)
    assert "Lands 00:10 on Fri 25 Sep" in text
    assert "driver is booked from 23:00 and will wait for your arrival at 00:10" in text


def test_journey_strip_day5():
    p = page(5)
    comps = p.components
    strip = next(c for c in comps if isinstance(c, m.JourneyStrip))
    assert isinstance(comps[comps.index(strip) - 1], m.YourDay)
    names = [s.name.text.upper() for s in strip.stops]
    assert names == ["MAYURA UBUD RETREAT", "SANUR HARBOUR", "D'NUSA BEACH CLUB AND RESORT"]
    assert strip.stops[0].time == "Leave 7:00 AM"
    assert strip.stops[1].time == "Check-in 8:15 AM · Departs 9:15 AM"
    assert len(strip.legs) == len(strip.stops) - 1
    assert strip.legs[1] == ""  # the voucher states no crossing time: nothing invented
    boat = next(c for c in comps if isinstance(c, m.BookingCard) and c.kind == "FAST BOAT")
    labels = [f.label for f in boat.facts]
    assert "Check in" in labels and "Departs" in labels and "Crossing" not in labels


def test_journey_strip_road_leg_and_crossing_only_when_known():
    from src.aigv2.planning.travel import Leg
    data = load()
    rd = day(data, 5)
    legs = dict(rd.legs)
    legs["boat_pickup"] = Leg(from_name="MAYURA UBUD RETREAT", to_name="Sanur Harbour", drive_min=60, kind="drive")
    boat = rd.arrival if rd.arrival and rd.arrival.kind == "boat" else next(t for t in rd.other_transport if t.kind == "boat")
    boat = boat.model_copy(update={"duration_min": 35})
    other = [boat if t.kind == "boat" else t for t in rd.other_transport]
    rd = rd.model_copy(update={"legs": legs, "other_transport": other, **({"arrival": boat} if rd.arrival else {})})
    p = build_day_page(rd, data, SETTINGS)
    strip = next(c for c in p.components if isinstance(c, m.JourneyStrip))
    assert strip.legs[0].startswith("Approx. ") and "min" in strip.legs[0]
    assert strip.legs[1] == "Approx. 35 min by boat"
    card = next(c for c in p.components if isinstance(c, m.BookingCard) and c.kind == "FAST BOAT")
    assert ("Crossing", "Approx. 35 min") in [(f.label, f.value) for f in card.facts]


def test_day7_option_cards():
    comps = page(7).components
    types = [c.type for c in comps]
    assert types.count("OptionCards") == 1
    oc = next(c for c in comps if c.type == "OptionCards")
    assert len(oc.options) == 2 and oc.own_expense is True
    assert oc.eyebrow.startswith("AFTERNOON") and oc.eyebrow.endswith("YOUR CHOICE")
    assert oc.heading == "Icon Mall or Sindhu Market"
    hours = {o.name.text: next(f.value for f in o.facts if f.label == "Opening hours") for o in oc.options}
    assert hours == {"Icon Mall": "10:00 AM – 10:00 PM", "Sindhu Market": "5:00 PM – 10:00 PM"}
    notes = {o.name.text: o.note for o in oc.options}
    assert notes["Icon Mall"] is None and "Best visited later in the day" in notes["Sindhu Market"]
    assert "5:00 PM" in notes["Sindhu Market"]
    # no separate cards for the two options
    assert not [c for c in comps if c.type == "SightseeingCard" and c.name.text in hours]
    at = types.index("OptionCards")
    boat = next(i for i, c in enumerate(comps) if c.type == "BookingCard" and c.kind == "FAST BOAT")
    transfer = next(i for i, c in enumerate(comps) if c.type == "BookingCard" and c.kind == "Transfer" and "TAKSU" in c.title.text.upper())
    checkin = next(i for i, c in enumerate(comps) if c.type == "BookingCard" and c.kind == "Check-in")
    dinner = next(i for i, c in enumerate(comps) if c.type == "MealBlock" and c.meal == "dinner")
    assert boat < transfer < checkin < at < dinner


def _day8_cards(rd=None, data=None):
    data = data or load()
    p = build_day_page(rd or day(data, 8), data, SETTINGS)
    marks = [mk for c in p.components if c.type == "ReviewMarkerBlock" for mk in c.markers]
    return p.components, marks


def test_day8_departure_cards():
    from src.aigv2.planning.slots import arrival_buffer_min, leave_by
    from src.aigv2.planning.travel import Leg
    data = load()
    comps, marks = _day8_cards(data=data)
    types = [c.type for c in comps]
    check = next(c for c in comps if c.type == "ChecklistCard")
    assert "Your child's essentials" in check.items and len(check.items) == 7
    assert check.lead == "Complete check-out and keep these in your hand luggage:"
    xfer = next(c for c in comps if c.type == "BookingCard" and c.kind == "AIRPORT TRANSFER")
    flight = next(c for c in comps if c.type == "BookingCard" and c.kind == "Flight")
    assert types.index("ChecklistCard") < comps.index(xfer) < comps.index(flight)
    # no road leg: a leave-by time only, no margin number claimed, and the VERIFY marker stays
    dep = day(data, 8).departure
    assert "leave-by time" in xfer.text and "giving about" not in xfer.text and "13:15 departure" in xfer.text
    assert not any(f.label == "Margin" for f in xfer.facts)
    assert "leave-by time" in xfer.text and "3 hours before departure" in xfer.text and "9:45 AM" in xfer.text
    assert any(mk.kind == "VERIFY" and mk.text == "departure time" for mk in marks)
    assert "30-minute allowance" in xfer.text
    # with a 45 minute road leg
    rd = day(data, 8)
    legs = dict(rd.legs)
    legs["departure"] = Leg(from_name="a", to_name="b", drive_min=45, kind="drive")
    comps2, marks2 = _day8_cards(rd.model_copy(update={"legs": legs}), data)
    x2 = next(c for c in comps2 if c.type == "BookingCard" and c.kind == "AIRPORT TRANSFER")
    by = leave_by(dep, False, 45)
    assert by == time(9, 30) and arrival_buffer_min("flight", False) == 180
    assert "approximately 9:30 AM" in x2.text and "about 3 hours at the airport before" in x2.text
    assert [f.value for f in x2.facts if f.label == "Margin"] == ["About 3 hours"]  # 13:15 - (9:30 + 45 min road)
    assert not any(mk.text == "departure time" for mk in marks2)
    assert "buffer only" not in x2.text


def test_thank_you_page_components():
    from src.aigv2.writing.thanks import ThankYouText
    data = load()
    data.thanks = ThankYouText(paragraphs=["One.", "Two."])
    pg = build_guide(data, SETTINGS).pages[-1]
    c = pg.components[0]
    assert pg.kind == "thank_you" and c.paragraphs == ["One.", "Two."]
    assert c.signoff == "With love," and c.signature == "Bon Voyage by Marina"
    data.thanks = None
    c = build_guide(data, SETTINGS).pages[-1].components[0]
    assert len(c.paragraphs) == 2
    assert destinations(data.trip)[0] in c.paragraphs[0]
    text = " ".join(c.paragraphs).lower()
    assert not re.search(r"\b(we|our|us)\b", text)


# ---------- Bali QC fixes (todo B) ----------

def _texts(p):
    return [(c.type, getattr(c, "when", None), getattr(c, "part", None), getattr(c, "heading", None))
            for c in p.components]


def test_day1_late_pickup_card_time_is_landing_and_voucher_time_flagged():
    from src.aigv2.models import TripPlan
    from src.aigv2.planning.late_night import driver_time
    data = load()
    rd = day(data, 1)
    trip = TripPlan.model_validate(json.loads((Path(__file__).parent / "fixtures" / "bali" / "trip_plan.json").read_text(encoding="utf-8")))
    book = next(b for b in trip.bookings if b.time == "23:00").model_copy(update={"time": "00:10", "instructions": ["Driver will come to the airport at 11:00 PM."]})
    rd = rd.model_copy(update={"booking_by_item": {k: book for k in rd.booking_by_item}})
    p = build_day_page(rd, data, SETTINGS)
    card = next(c for c in p.components if c.type == "SightseeingCard")
    assert card.when == "00:10" and card.part == "Late night"
    assert any(mk.kind == "VERIFY" and "driver pick-up" in mk.text for mk in card.markers)


def test_day7_dinner_in_sanur_is_not_a_second_dinner_card():
    p = page(7)
    names = [getattr(getattr(c, "name", None), "text", None) for c in p.components]
    assert "Dinner in Sanur" not in names
    dinner = [c for c in p.components if c.type == "MealBlock" and c.meal == "dinner"]
    assert len(dinner) == 1 and "OWN EXPENSE" in dinner[0].eyebrow


def test_restaurant_description_drops_not_specified_filler():
    data = load()
    rd = day(data, 2)
    pick = next(x for x in rd.meals if x.slot.meal == "lunch")
    name = pick.restaurants[0].lib["name"]
    rt = next(r for r in rd.text.restaurants if r.name == name) if any(r.name == name for r in rd.text.restaurants) else None
    assert rt is not None
    rt.ambience = "Not specified in the verified details."
    rt.best_for = "grilled meats"
    p = build_day_page(rd, data, SETTINGS)
    lunch = next(c for c in p.components if c.type == "MealBlock" and c.meal == "lunch")
    r0 = next(r for r in lunch.restaurants if r.name == name)
    assert r0.text == "Best for grilled meats"


def test_every_trip_booking_name_is_in_the_rendered_guide():
    """Regression: tour/transfer bookings no item card carried only reached the guide via a 'not placed' marker."""
    from src.aigv2.models import TripPlan
    from src.aigv2.qc.reader import read_docx
    from src.aigv2.render2.render import render_guide2
    from src.aigv2.library import norm_name
    data = load()
    assert [b.name for b in data.trip.bookings][2] != ""  # fixture trip carries the 8 bookings
    for rd in data.days:  # as in a fresh plan: no 'not placed' markers
        rd.result.markers[:] = [mk for mk in rd.result.markers if "not placed" not in mk.text]
    guide = build_guide(data, SETTINGS)
    blob = norm_name(read_docx(render_guide2(guide)).text)
    trip = data.trip
    assert len(trip.bookings) == 8
    # the fixture has no render days for the activity-only days 3 and 6: clone a tour day for each, as a fresh plan has them
    base = day(data, 4)
    for idx, d_, bk_name in ((3, date(2026, 9, 26), "Marine Park (Sea Dragon Package)"),
                             (6, date(2026, 9, 29), "Nusa Lembongan tour")):
        bk = next(b for b in trip.bookings if b.day == d_ and norm_name(b.name).startswith(norm_name(bk_name)[:10]))
        sc = base.result.scheduled[0]
        item = sc.item.model_copy(update={"name": bk_name if idx == 3 else "Yellow Bridge"})
        rd = base.model_copy(deep=True, update={"index": idx, "date": d_, "booking_by_item": {item.name: bk} if idx == 3 else {}})
        rd.result.scheduled[:] = [sc.model_copy(update={"item": item})]
        rd.result.markers[:] = []
        data.days.append(rd)
    data.days.sort(key=lambda r: r.index)
    blob = norm_name(read_docx(render_guide2(build_guide(data, SETTINGS))).text)
    missing = [b.name for b in trip.bookings if norm_name(b.name) not in blob]
    assert not missing


def test_day5_check_in_card_sits_at_its_time_after_the_morning_activity():
    p = page(5)
    order = [(c.type, getattr(c, "kind", None), getattr(c, "when", None)) for c in p.components
             if c.type in ("BookingCard", "SightseeingCard", "MealBlock")]
    kinds = [o[1] or o[0] for o in order]
    mangrove = max(i for i, k in enumerate(kinds) if k == "SightseeingCard")
    assert kinds.index("FAST BOAT") < mangrove < kinds.index("Check-in")


def test_port_and_hotel_names_read_in_proper_case():
    from src.aigv2.guide.build import nice_name, port_name
    assert nice_name("TAKSU SANUR HOTEL") == "Taksu Sanur Hotel" and nice_name("DPS") == "DPS"
    assert port_name("DPS", "flight") == "Airport (DPS)"
    assert port_name("DPS", "flight", "Ngurah Rai International Airport") == "Ngurah Rai International Airport"
    assert port_name("", "boat") == "Harbor"


def test_day8_transfer_title_is_proper_case():
    comps, _ = _day8_cards()
    xfer = next(c for c in comps if c.type == "BookingCard" and c.kind == "AIRPORT TRANSFER")
    assert xfer.title.text.startswith("Taksu Sanur Hotel → ") and "TAKSU" not in xfer.title.text
    chk = next(c for c in comps if c.type == "ChecklistCard")
    assert "TAKSU" not in chk.title.text


def test_day5_arrival_transfer_is_labelled_by_the_boat_origin():
    comps = page(5).components
    t = next(c for c in comps if c.type == "BookingCard" and c.kind == "Transfer" and "→" in c.title.text)
    assert not t.title.text.startswith("Ubud") and t.title.text.startswith("Nusa Lembongan")


def test_package_lunch_note_follows_voucher_text():
    from datetime import date as _d
    from src.aigv2.models import Booking
    data = load()
    rd = day(data, 2)
    meals = [m.model_copy(update={"in_package": True, "included": False, "anchors": []}) if m.meal == "lunch" else m
             for m in rd.result.meals]
    if not any(m.meal == "lunch" for m in meals):
        from src.aigv2.planning.slots import MealSlot
        meals.append(MealSlot(meal="lunch", start=time(12, 30), in_package=True))
    res = rd.result.model_copy(update={"meals": meals})

    def note(*instructions):
        bk = Booking(name="Sea Dragon Package", day=rd.date, source="voucher", instructions=list(instructions))
        rd2 = rd.model_copy(update={"result": res, "booking_by_item": {"Sea Dragon Package": bk}})
        comps = build_day_page(rd2, data, SETTINGS).components
        return next(c.text for c in comps if c.type == "SimpleCard" and "during your package" in (c.heading or ""))
    assert note("Private basis.") == ("Lunch falls within your full-day package; confirm with the operator "
                                      "whether it is included.")
    assert note("Private basis.", "Lunch included.") == "Lunch is included in your package."
    assert "confirm with the operator" in note("Lunch not included.")


def test_nice_text_and_choose_sentence():
    from src.aigv2.guide.build import nice_text, _CHOOSE
    assert nice_text("Airport pick-up and transfer to MAYURA UBUD RETREAT") == "Airport pick-up and transfer to Mayura Ubud Retreat"
    assert nice_text("Icon Mall") == "Icon Mall"
    assert _CHOOSE.sub(" ", "Nice. Choose A or B; any expenses are your own.").strip() == "Nice."
