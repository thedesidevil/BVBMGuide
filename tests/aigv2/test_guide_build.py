import json
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from src.aigv2.guide import MarkerRef
from src.aigv2.guide import model as m
from src.aigv2.guide.build import build_day_page, build_guide
from src.aigv2.models import HotelStay, Marker, TransportLeg
from src.aigv2.render.document import GuideData

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
    assert kinds[3:] == ["SightseeingCard", "SightseeingCard", "MealBlock", "SightseeingCard", "MealBlock",
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
    assert [pg.kind for pg in g.pages] == ["letter", "toc", "day", "day", "day", "thank_you"]
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
