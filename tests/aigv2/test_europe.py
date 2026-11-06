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
