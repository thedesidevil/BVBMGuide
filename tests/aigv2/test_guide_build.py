import json
from pathlib import Path

from types import SimpleNamespace
from src.aigv2.guide import MarkerRef
from src.aigv2.guide import model as m
from src.aigv2.guide.build import build_day_page, build_guide
from src.aigv2.models import Marker
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
                         "ReviewMarkerBlock"]
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
    c = day(data, 2).meals[0].restaurants[0]
    c.hours_text, c.hours_verify = "", True
    day(data, 2).price_by_restaurant.pop(c.lib["name"], None)
    p = page(2, data)
    lunch = next(x for x in p.components if x.type == "MealBlock" and x.meal == "lunch")
    r = lunch.restaurants[0]
    assert r.price == MarkerRef(kind="PRICE_UNKNOWN", text="")
    assert r.hours in (None, "")
    stray = [x for x in p.components if x.type == "ReviewMarkerBlock"]
    assert any(mk == MarkerRef(kind="VERIFY", text="opening hours") for b in stray for mk in b.markers)


def test_build_guide_wraps_day_pages():
    data = load()
    g = build_guide(data, SETTINGS)
    assert [pg.kind for pg in g.pages] == ["letter", "toc", "day", "day", "thank_you"]
    letter = g.pages[0].components
    assert letter[0].paragraphs == [] and letter[1].markers == [MarkerRef(kind="WRITE_LETTER", text="")]
    assert g.client == "Test Client One" and g.title == data.title
    assert [c.type for c in g.pages[2].components][:2] == ["Opener", "YourDay"]


def test_day_markers_ride_on_the_day():
    p = page(2)
    marks = [mk for c in p.components if c.type == "ReviewMarkerBlock" for mk in c.markers]
    assert any("is not placed in the day plan" in mk.text for mk in marks)
