"""Batch A day-content fixes (Bali, Dilna): library lookup, good-to-know, package lunch, repeats, times, generic names."""
import json
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace

from src.aigv2.config import Settings
from src.aigv2.library import is_veg_only, wants_veg
from src.aigv2.models import Diet, DayPlan, HotelStay, PlannedItem, Place
from src.aigv2.planning.attraction_match import (good_to_know, is_generic_name, lookup, match_attraction,
                                                 parse_minutes)
from src.aigv2.planning.meals import plan_meals
from src.aigv2.planning.slots import MealSlot, round15, schedule_day
from src.aigv2.writing.days import unmatched_locality_problems
from tests.aigv2.test_meals import FakeLLM, FirstN, FakePlaces, FakeRoutes, S as MS, make_lib, place as mplace, rest

FIX = Path(__file__).parent / "fixtures" / "bali_batch_a"
ATTR = json.loads((FIX / "attractions.json").read_text(encoding="utf-8"))
REST = {r["name"]: r for r in json.loads((FIX / "restaurants.json").read_text(encoding="utf-8"))}
D = date(2026, 9, 25)


def _attr(name):
    return next(a for a in ATTR if a["name"] == name)


# ---- #2 no fuzzy matching (user ruling): unmatched stays unmatched
def test_marine_park_is_not_fuzzy_linked_to_the_safari_park():
    assert match_attraction("Marine Park (Sea Dragon Package)", ATTR) is None
    assert lookup("Marine Park (Sea Dragon Package)", ATTR, []) is None


def test_exact_and_parenthetical_names_still_match():
    assert match_attraction("Tirta Empul Temple", ATTR)[1] is True
    hit = match_attraction("Tegallalang Rice Terrace (Viewpoint & Scenic Cafe)", ATTR)
    assert hit and hit[0]["name"] == "Tegallalang Rice Terrace" and hit[1] is False


# ---- #3 good to know
def test_tirta_empul_surfaces_the_menstruation_warning_first_verbatim():
    tips = good_to_know(_attr("Tirta Empul Temple"))
    assert tips[0] == "Women who are menstruating are not permitted to enter the temple premises"
    assert len(tips) <= 4


def test_blue_lagoon_cliff_warning_and_tegallalang_tips():
    assert good_to_know(_attr("Blue Lagoon")) == ["Cliff edges are exposed, so treat it as a look-and-photograph stop"]
    assert "Wear comfortable footwear as paths can be uneven" in good_to_know(
        next(a for a in ATTR if a["name"] == "Tegallalang Rice Terrace" and a["city"] == "Tegallalang"))


def test_good_to_know_dedupes_caps_and_drops_first_person():
    lib = {"tips": ["Wear a hat.", "wear a hat", "We recommend booking", "a", "b", "c", "d", "e"]}
    out = good_to_know(lib)
    assert out[0] == "Wear a hat." and "We recommend booking" not in out and len(out) == 4


def test_hard_warnings_are_never_cut_by_the_cap():
    lib = {"tips": ["a", "b", "c", "d", "Entry is strictly prohibited for pets"]}
    assert "Entry is strictly prohibited for pets" in good_to_know(lib)


def test_sightseeing_card_renders_library_tips_and_dress_code():
    from tests.aigv2.test_guide_build import load, day as gday, SETTINGS
    from src.aigv2.guide.build import build_day_page
    data = load()
    rd = gday(data, 4)
    page = build_day_page(rd, data, SETTINGS)
    card = next(c for c in page.components if c.type == "SightseeingCard" and "Tirta Empul" in c.name.text)
    assert any("not permitted" in t for t in card.tips)
    assert any(f.label.upper() == "DRESS CODE" for f in card.facts)


# ---- #13 generic names
def test_generic_names_are_detected():
    for n in ("Coffee Plantation", "Local Market", "Beach", "Waterfall", "Viewpoint", "Temple visit"):
        assert is_generic_name(n), n
    for n in ("Kintamani Volcano View", "Tirta Empul Temple", "Bali Safari & Marine Park", "Yellow Bridge"):
        assert not is_generic_name(n), n


def test_generic_name_unmatched_unless_single_library_attraction():
    assert lookup("Coffee Plantation", ATTR, []) is None
    one = [{"name": "Coffee Plantation", "city": "Ubud", "description": "x"}]
    assert lookup("Coffee Plantation", [], one)[0]["city"] == "Ubud"
    two = one + [{"name": "Coffee Plantation", "city": "Kintamani"}]
    assert lookup("Coffee Plantation", [], two) is None


def test_resolve_places_does_not_search_generic_names():
    from src.aigv2 import pipeline
    from src.aigv2.models import TripPlan
    plan = json.loads((Path(__file__).parent / "fixtures" / "bali" / "trip_plan.json").read_text(encoding="utf-8"))
    trip = TripPlan.model_validate(plan)
    asked = []

    class Client:
        def find(self, name, city, near=None, fresh=False):
            asked.append(name)
            return None

    class Lib:
        def city(self, c):
            return {"attractions": []}

        def region_attractions(self, c):
            return []

    out = pipeline.resolve_places(trip, Client(), {"coffee plantation|ubud": SimpleNamespace(match_ok=True)}, Lib())
    assert "Coffee Plantation" not in asked
    assert [v for k, v in out.items() if k.startswith("coffee plantation")] == [None]


def test_writer_may_not_place_an_unmatched_stop_in_a_locality():
    bad = unmatched_locality_problems("Coffee Plantation", False, True, "Visit Coffee Plantation in Peliatan for a stop.")
    assert bad and "Peliatan" in bad[0]
    assert not unmatched_locality_problems("Coffee Plantation", False, True, "Visit Coffee Plantation for a stop.")
    assert not unmatched_locality_problems("Ubud Palace", True, False, "The palace in Ubud is lovely.")


# ---- #12 compact times
def test_parse_minutes():
    assert parse_minutes("30-45 minutes") == 45 and parse_minutes("1–1.5 Hours") == 90 and parse_minutes("x") is None


def test_round15():
    assert round15(time(14, 54)) == time(15, 0) and round15(time(16, 26)) == time(16, 30)
    assert round15(time(14, 38)) == time(14, 45) and round15(time(9, 0)) == time(9, 0)


def _sd(items, windows, durations, d=D):
    def pl(n, i):
        return Place(query=n, place_id=n, name=n, address="", lat=i, lng=i, status="OPERATIONAL", maps_url="u",
                     fetched_at=datetime(2026, 1, 1), match_ok=True)
    names = ["Hotel", *[i.name for i in items]]
    stay = HotelStay(city="X", hotel="Hotel", check_in=date(2026, 9, 24), check_out=date(2026, 9, 28), source="voucher")
    day = DayPlan(date=d, title="t", city="X", items=items)
    return schedule_day(day, [stay], None, None, {n: pl(n, i + 1.0) for i, n in enumerate(names)}, Settings(models={}),
                        windows=windows, durations=durations)


def test_day2_short_window_stops_are_packed_with_no_big_gaps():
    items = [PlannedItem(name=n, kind="attraction", city="X") for n in ("Terrace", "Palace", "Market")]
    win = {n: (time(13, 0), time(18, 0)) for n in ("Terrace", "Palace", "Market")}
    r = _sd(items, win, {"Terrace": 60, "Palace": 45, "Market": 45})
    got = [s.start for s in r.scheduled]
    assert got[0] == time(13, 0)
    assert got[1] == time(14, 20) and got[2] == time(15, 25)  # prior stop end + 20 min drive
    assert all(b > a for a, b in zip(got, got[1:]))
    assert got[2] < time(16, 0)  # was 4:26 PM with a 90 minute gap


def test_full_day_window_keeps_even_spread():
    items = [PlannedItem(name=n, kind="attraction", city="X") for n in ("A", "B", "C")]
    win = {n: (time(8, 0), time(18, 0)) for n in "ABC"}
    r = _sd(items, win, {"A": 45, "B": 45, "C": 45})
    assert [s.start for s in r.scheduled] == [time(8, 0), time(10, 30), time(13, 0)]


# ---- #5 package day lunch
def test_matched_stop_on_a_long_tour_anchors_lunch_with_a_wider_radius():
    items = [PlannedItem(name="Tirta Empul Temple", kind="attraction", city="X", time="09:00")]
    r = _sd(items, {"Tirta Empul Temple": (time(9, 0), time(18, 0))}, {})
    lunch = next(m for m in r.meals if m.meal == "lunch")
    assert lunch.anchors and lunch.anchors[0][0] == "Tirta Empul Temple" and lunch.max_min == 20


def test_unmatched_stop_on_a_package_day_stays_marker_only():
    items = [PlannedItem(name="Marine Park (Sea Dragon Package)", kind="activity", city="X", time="09:00")]
    stay = HotelStay(city="X", hotel="Hotel", check_in=date(2026, 9, 24), check_out=date(2026, 9, 28), source="voucher")
    pl = {"Hotel": Place(query="h", place_id="h", name="h", address="", lat=1.0, lng=1.0, status="OPERATIONAL",
                         maps_url="u", fetched_at=datetime(2026, 1, 1), match_ok=True),
          "Marine Park (Sea Dragon Package)": None}
    r = schedule_day(DayPlan(date=D, title="t", city="X", items=items), [stay], None, None, pl, Settings(models={}),
                     booking_ends={items[0].name: time(16, 0)})
    lunch = next(m for m in r.meals if m.meal == "lunch")
    assert lunch.in_package and not lunch.anchors


def test_wider_lunch_radius_lets_a_rural_restaurant_in(tmp_path):
    rs = [rest("Near"), rest("Rural"), rest("Rural2"), rest("Rural3")]
    lib = make_lib(tmp_path, {"Istanbul": rs})
    pl = {r["name"]: mplace(r["name"], i + 1) for i, r in enumerate(rs)}
    mins = {r["name"]: {"WALK": 40, "DRIVE": 18} for r in rs}
    anchor = ("Tirta Empul Temple", (41.0, 29.0), 3)
    days = lambda cap: [(4, D, "Istanbul", [MealSlot(meal="lunch", start=time(12, 30), anchors=[anchor], max_min=cap)])]
    picks, _, _ = plan_meals(days(None), lib, FakePlaces(pl), FakeRoutes(pl, mins), Diet(), ["taxi"], FirstN(), MS,
                             trip_scope="international")
    assert not picks[0].restaurants and len(picks[0].markers) == 3
    picks, _, _ = plan_meals(days(20), lib, FakePlaces(pl), FakeRoutes(pl, mins), Diet(), ["taxi"], FirstN(), MS,
                             trip_scope="international")
    assert len(picks[0].restaurants) == 3


# ---- #6 stay-wide repeats
def test_dinners_do_not_repeat_the_previous_list_when_fresh_candidates_exist(tmp_path):
    rs = [rest(n) for n in "ABCDEF"]
    lib = make_lib(tmp_path, {"Istanbul": rs})
    pl = {r["name"]: mplace(r["name"], i + 1) for i, r in enumerate(rs)}
    mins = {r["name"]: {"WALK": 5, "DRIVE": 4} for r in rs}
    anchor = ("Hotel", (41.0, 29.0), 3)
    din = lambda: MealSlot(meal="dinner", start=time(19, 30), anchors=[anchor])
    days = [(2, D, "Istanbul", [din()]), (3, date(2026, 9, 26), "Istanbul", [din()])]
    picks, _, _ = plan_meals(days, lib, FakePlaces(pl), FakeRoutes(pl, mins), Diet(), ["taxi"], FirstN(), MS,
                             trip_scope="international")
    a, b = ({c.lib["name"] for c in p.restaurants} for p in picks)
    assert len(a) == len(b) == 3 and not (a & b)


def test_repeats_fill_only_the_shortfall(tmp_path):
    rs = [rest(n) for n in "ABCD"]
    lib = make_lib(tmp_path, {"Istanbul": rs})
    pl = {r["name"]: mplace(r["name"], i + 1) for i, r in enumerate(rs)}
    mins = {r["name"]: {"WALK": 5, "DRIVE": 4} for r in rs}
    anchor = ("Hotel", (41.0, 29.0), 3)
    din = lambda: MealSlot(meal="dinner", start=time(19, 30), anchors=[anchor])
    days = [(2, D, "Istanbul", [din()]), (3, date(2026, 9, 26), "Istanbul", [din()])]
    picks, _, _ = plan_meals(days, lib, FakePlaces(pl), FakeRoutes(pl, mins), Diet(), ["taxi"], FirstN(), MS,
                             trip_scope="international")
    second = [c.lib["name"] for c in picks[1].restaurants]
    assert second[0] == "D" and len(second) == 3  # the one fresh place first, then two repeats


def test_dinner_cap_relaxed_by_five_minutes_when_too_few_candidates(tmp_path):
    rs = [rest("A"), rest("B"), rest("C")]
    lib = make_lib(tmp_path, {"Istanbul": rs})
    pl = {r["name"]: mplace(r["name"], i + 1) for i, r in enumerate(rs)}
    mins = {"A": {"WALK": 50, "DRIVE": 10}, "B": {"WALK": 50, "DRIVE": 12}, "C": {"WALK": 50, "DRIVE": 24}}
    slot = MealSlot(meal="dinner", start=time(19, 30), anchors=[("Hotel", (41.0, 29.0), 3)])
    picks, excl, _ = plan_meals([(1, D, "Istanbul", [slot])], lib, FakePlaces(pl), FakeRoutes(pl, mins), Diet(),
                                ["taxi"], FakeLLM([]), MS, trip_scope="international")
    assert {c.lib["name"] for c in picks[0].restaurants} == {"A", "B", "C"}  # C at 24 min is within 20 + 5
    mins["C"]["DRIVE"] = 26
    picks, excl, _ = plan_meals([(1, D, "Istanbul", [slot])], lib, FakePlaces(pl), FakeRoutes(pl, mins), Diet(),
                                ["taxi"], FakeLLM([]), MS, trip_scope="international")
    assert {c.lib["name"] for c in picks[0].restaurants} == {"A", "B"}


# ---- restaurant diet: veg-only venues
def test_veg_only_classifier_on_the_bali_data():
    assert is_veg_only(REST["Ginger & Jamu"])
    assert is_veg_only(REST["Prasadam – Plantbased Vegan and Vegetarian Restaurant"])
    assert not is_veg_only(REST["Galle Club | Sri Lankan & Coastal Indian Cuisine"])  # non-veg Sri Lankan; veg dishes only
    assert not is_veg_only(REST["Sendang Restaurant"])


def test_veg_friendly_wording_is_not_veg_only():
    assert not is_veg_only({"name": "X", "cuisine_type": ["Indian"], "notes": "vegetarian options available"})
    assert not is_veg_only({"name": "X", "cuisine_type": ["Thai"], "highlights": ["Vegetarian-friendly"]})
    assert is_veg_only({"name": "X", "cuisine_type": ["Indian"], "notes": "Purely vegetarian kitchen"})
    assert is_veg_only({"name": "Y", "cuisine_type": ["Cafe"], "ambience": "a vegan cafe"})


def test_wants_veg():
    assert wants_veg(Diet(pure_veg=True)) and wants_veg(Diet(restrictions=["vegetarian"]))
    assert not wants_veg(Diet()) and not wants_veg(Diet(restrictions=["no pork"]))


def test_veg_only_skipped_unless_the_client_is_vegetarian(tmp_path):
    rs = [rest("A", veg=False), rest("B", veg=False), rest("C", veg=False), rest("Greens", cuisine=("Plant-based",))]
    lib = make_lib(tmp_path, {"Istanbul": rs})
    pl = {r["name"]: mplace(r["name"], i + 1) for i, r in enumerate(rs)}
    mins = {r["name"]: {"WALK": 5, "DRIVE": 4} for r in rs}
    slot = lambda: MealSlot(meal="lunch", start=time(12, 30), anchors=[("Hotel", (41.0, 29.0), 3)])
    for diet, expect in ((Diet(), False), (Diet(restrictions=["vegetarian"]), True)):
        picks, excl, _ = plan_meals([(1, D, "Istanbul", [slot()])], lib, FakePlaces(pl), FakeRoutes(pl, mins), diet,
                                    ["taxi"], FakeLLM([]), MS, trip_scope="international")
        assert ("Greens" in {c.lib["name"] for c in picks[0].restaurants}) is expect or not expect
        if not expect:
            assert "Greens" not in {c.lib["name"] for c in picks[0].restaurants}
            assert ("Greens", "diet") in {(e.name, e.reason) for e in excl}
