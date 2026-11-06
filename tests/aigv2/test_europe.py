import json
from datetime import date, datetime, time
from pathlib import Path

from src.aigv2 import pipeline
from src.aigv2.config import Settings
from src.aigv2.google.places import PlacesClient
from src.aigv2.intake.template import IntakeFields
from src.aigv2.models import Place, TransportLeg, TripPlan
from src.aigv2.planning.meals import _Planner
from src.aigv2.preflight import run_checklist

FIX = Path(__file__).parent / "fixtures" / "europe"


def _trip() -> TripPlan:
    return TripPlan.model_validate(json.loads((FIX / "trip_plan.json").read_text()))


class _Lib:
    def __init__(self, missing=()):
        self.missing = set(missing)

    def has_data(self, city):
        return city not in self.missing


def test_travel_day_titles_do_not_ask_for_missing_library_cities():
    qs = run_checklist(_trip(), IntakeFields(), [], _Lib(missing={"Paris / Lucerne", "Lucerne / Interlaken",
                                                                 "Grindelwald / Interlaken", "Lauterbrunnen / Zurich"}),
                       {})
    assert [q.id for q in qs if q.kind == "no_library"] == []


def test_resolved_city_without_data_is_still_asked():
    qs = run_checklist(_trip(), IntakeFields(), [], _Lib(missing={"Lucerne"}), {})
    assert [q.id for q in qs if q.kind == "no_library"] == ["no_library:Lucerne"]


def _raw(name, addr, types=("lodging",)):
    return {"displayName": {"text": name}, "formattedAddress": addr, "types": list(types),
            "location": {"latitude": 1.0, "longitude": 2.0}}


def test_hotel_match_uses_local_city_names_and_suburbs():
    ok = PlacesClient._match_ok
    assert ok("Hotel Luzernerhof", "Lucerne", None, _raw("Hotel Luzernerhof", "Alpenstrasse 3, 6004 Luzern, Switzerland"))
    assert ok("Hotel Baren the Bear Inn", "Interlaken", None,
              _raw("Baeren Hotel, The Bear Inn", "Oberdorfstrasse 1, 3812 Wilderswil, Switzerland"))
    assert not ok("Joe's Pizza", "New York", None, _raw("Joe's Pizza", "1 Main St, Chicago", ("restaurant",)))
    assert not ok("Hotel Luzernerhof", "Lucerne", None, _raw("Hotel Luzernerhof", "1 Main St, Chicago", ("restaurant",)))


class _Client:
    def __init__(self, name):
        self.name = name

    def find(self, name, city, near=None, fresh=False):
        return Place(query=name, place_id="p", name=self.name if name.startswith("Novotel") else name, address="x, Zurich",
                     lat=1, lng=2, status="OPERATIONAL", maps_url="u", fetched_at=datetime(2027, 1, 1), match_ok=True)


def test_hotel_typo_takes_google_display_name():
    trip = _trip()
    places = pipeline.resolve_places(trip, _Client("Novotel Zurich Airport Messe"), {})
    assert trip.hotels[-1].hotel == "Novotel Zurich Airport Messe"
    assert places["novotel zurich airport messe|zurich"] is not None


def test_extension_rule_is_narrow():
    assert pipeline.is_name_extension("Novotel Zurich Airport Mess", "Novotel Zurich Airport Messe")
    assert not pipeline.is_name_extension("Hotel A", "Hotel A")
    assert not pipeline.is_name_extension("Hotel Rex", "Hotel Savoy Paris")


def test_public_transport_only_widens_walk_and_transit_caps():
    from src.aigv2.models import Diet
    s = Settings(models={})
    p = _Planner(None, None, None, Diet(), ["public_transport"], None, s, "international")
    assert p.settings.walk_max_min == 15 and p.settings.lunch_max_min == 25 and p.settings.dinner_max_min == 25
    t = _Planner(None, None, None, Diet(), ["taxi"], None, s, "international")
    assert t.settings.walk_max_min == 10 and t.settings.lunch_max_min == 15
    both = _Planner(None, None, None, Diet(), ["taxi", "public_transport"], None, s, "international")
    assert both.settings.lunch_max_min == 15


def test_train_day_lunch_follows_arrival_and_dinner_in_new_city():
    from src.aigv2.planning.slots import schedule_day
    trip = _trip()
    dp = next(d for d in trip.days if d.date == date(2026, 5, 3))
    dp.city = "Lucerne"
    places = {h.hotel: Place(query="q", place_id=h.hotel, name=h.hotel, address="a", lat=47.0, lng=8.3, status="OPERATIONAL",
                             maps_url="u", fetched_at=datetime(2027, 1, 1), match_ok=True) for h in trip.hotels}
    res = schedule_day(dp, trip.hotels, trip.transport[1], None, places, Settings(models={}), "Switzerland")
    meals = {m.meal: m for m in res.meals}
    assert meals["lunch"].start >= time(13, 30) and meals["lunch"].anchors[0][0] == "Hotel Luzernerhof"
    assert meals["dinner"].anchors[0][0] == "Hotel Luzernerhof"


def _sched(day, arrival=None, departure=None):
    from src.aigv2.planning.slots import schedule_day
    trip = _trip()
    dp = next(d for d in trip.days if d.date == day)
    places = {}
    return schedule_day(dp, trip.hotels, arrival, departure, places, Settings(models={}), "France")


def test_arrival_day_visits_start_after_the_train_plus_buffer():
    from src.aigv2.planning.slots import schedule_day
    trip = _trip()
    dp = next(d for d in trip.days if d.date == date(2026, 4, 30))
    dp.items.insert(1, dp.items[0].model_copy(update={"name": "Walk along the Seine", "kind": "activity"}))
    res = schedule_day(dp, trip.hotels, trip.transport[0], None, {}, Settings(models={}), "France")
    starts = {s.item.name: s.start for s in res.scheduled}
    assert starts["Walk along the Seine"] >= time(12, 9)


def test_fireworks_are_last_and_late():
    res = _sched(date(2026, 5, 1))
    last = res.scheduled[-1]
    assert "fireworks" in last.item.name.lower() and last.start == time(21, 30)


def test_full_day_excursion_lunch_is_marked_at_the_destination_not_the_hotel_city():
    res = _sched(date(2026, 5, 1))
    lunch = next(m for m in res.meals if m.meal == "lunch")
    assert lunch.unanchored and lunch.near_label == "Disneyland Paris"
    from src.aigv2.planning.meals import _Planner
    from src.aigv2.models import Diet
    p = _Planner(None, None, None, Diet(), ["public_transport"], None, Settings(models={}), "international")
    pick = p.slot(2, date(2026, 5, 1), "Paris", lunch)
    assert [m.text for m in pick.markers] == ["Lunch, Day 2, near Disneyland Paris"] * 3


def test_is_full_day():
    from src.aigv2.planning.slots import is_full_day
    trip = _trip()
    items = {i.name: i for d in trip.days for i in d.items}
    assert is_full_day(items["Mount Titlis Excursion"]) and is_full_day(items["Full-day excursion to Jungfraujoch"])
    assert not is_full_day(items["Optional fireworks in the evening"])
    assert not is_full_day(items["Explore Höheweg"])


def test_image_details_answer_adds_timed_item_without_duplicates():
    from src.aigv2.models import Question
    from src.aigv2.preflight import apply_answers
    trip = _trip()
    ans = json.loads((FIX / "answers_final.json").read_text())
    key = next(k for k in ans if k.startswith("image_details"))
    out = apply_answers(trip, [Question(id=key, kind="image_details", text="x")], ans)
    d1 = next(d for d in out.days if d.date == date(2026, 4, 30))
    assert [(i.name, i.time) for i in d1.items if i.time] == [("Loure museum+Seine River", "15:30")]
    d2 = next(d for d in out.days if d.date == date(2026, 5, 2))
    assert len(d2.items) == len(next(d for d in trip.days if d.date == date(2026, 5, 2)).items)  # bus/tour/Eiffel exist
    d3 = next(d for d in out.days if d.date == date(2026, 5, 1))
    assert len(d3.items) == len(next(d for d in trip.days if d.date == date(2026, 5, 1)).items)  # Disney exists


def test_departure_day_has_no_9am_flight_item_and_meals_stop_at_leave_by():
    from src.aigv2.planning.slots import schedule_day
    trip = _trip()
    trip.transport.append(TransportLeg(kind="flight", from_place="Zurich", to_place="Mumbai", source="answer",
                                       depart=datetime(2026, 5, 9, 16, 30)))
    dp = next(d for d in trip.days if d.date == date(2026, 5, 9))
    res = schedule_day(dp, trip.hotels, None, trip.transport[2], {}, Settings(models={}), "Switzerland")
    assert [s.item.name for s in res.scheduled] == []
    assert all(m.start < time(13, 30) for m in res.meals)


def test_station_in_city():
    from src.aigv2.planning.slots import station_in_city
    assert station_in_city("Luzern", "Lucerne") and station_in_city("Paris Gare du Nord", "Paris")
    assert not station_in_city("BALE SBB", "Lucerne")


def test_return_to_stay_choice_adds_no_activity():
    from src.aigv2.models import Question
    from src.aigv2.preflight import apply_answers
    trip = _trip()
    n = next(i for i, oc in enumerate(trip.open_choices) if oc.text.startswith("Return"))
    out = apply_answers(trip, [Question(id=f"open_choice:{n}", kind="open_choice", text="x", options=["Interlaken", "nearby stay"])],
                        {f"open_choice:{n}": "Interlaken"})
    d = next(d for d in out.days if d.date == date(2026, 5, 7))
    assert "Interlaken" not in [i.name for i in d.items]


def test_library_country_prefers_the_cities_own_folder(tmp_path):
    from src.aigv2.library import Library
    (tmp_path / "Paris.json").write_text(json.dumps({"restaurants": [], "currency": "EUR",
                                                    "_currency_source": {"_source_file": "France/x.docx"}}))
    (tmp_path / "Lucerne.json").write_text(json.dumps({"restaurants": [], "currency": "CHF",
                                                      "_currency_source": {"_source_file": "France/y.docx"}}))
    (tmp_path / "_index.json").write_text(json.dumps({"_folder_coverage": {
        "Switzerland": ["Lucerne", "Paris", "Rome", "Zurich"], "France": ["Paris", "Lucerne"], "Italy": ["Paris", "Rome"]}}))
    lib = Library(tmp_path)
    assert pipeline._library_country(lib, "Paris") == "France"
    assert pipeline._library_country(lib, "Lucerne") == "Switzerland"
