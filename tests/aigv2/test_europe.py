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


def test_reference_filters_for_a_western_europe_train_trip():
    from src.aigv2.writing.sections import _library_named
    trip = _trip()
    trip.transport.append(TransportLeg(kind="flight", from_place="Zurich", to_place="Mumbai", source="answer",
                                       depart=datetime(2026, 5, 9, 16, 30)))
    paris = {"city": "Paris", "country": "France", "transport_options": [
        {"mode": "Airport", "details": "RER B from Charles de Gaulle airport to the city"},
        {"mode": "Metro", "details": "Buy a carnet of tickets"},
        {"mode": "Pass", "details": "The Swiss Travel Pass covers trains"}]}
    zurich = {"city": "Zurich", "country": "Switzerland", "transport_options": [
        {"mode": "Airport", "details": "Train from Zurich Airport to the main station"}]}
    got = _library_named("getting_around", [paris, zurich], [{}], trip=trip, countries=["France", "Switzerland"])
    modes = [x["mode"] for x in got["transport_options"]]
    assert modes == ["Metro", "Airport"]
    trip.additional_notes += " Swiss Travel Pass bought."
    got = _library_named("getting_around", [paris], [{}], trip=trip, countries=["France"])
    assert "Pass" in [x["mode"] for x in got["transport_options"]]
    health = {"city": "Paris", "country": "France", "health_tips": [
        {"tip": "Hepatitis A and typhoid vaccines are advised for Europe"}, {"tip": "Carry your prescriptions"}]}
    got = _library_named("health", [health], [{}], trip=trip, countries=["France", "Switzerland"])
    assert len(got["health_tips"]) == 1


def _multi_content():
    from src.aigv2.writing.sections import SectionContent, SectionItem
    from src.aigv2.writing.structured import Contact, EmergencyNumber
    return SectionContent(
        key="safety", items=[SectionItem(heading="Scams", body="Be alert.")],
        by_country={"France": [SectionItem(heading="Scams", body="Be alert.")], "Switzerland": []},
        numbers_by_country={"France": [EmergencyNumber(service="Ambulance", number="15")],
                            "Switzerland": [EmergencyNumber(service="Ambulance", number="144")]},
        contacts_by_country={"France": [Contact(name="Embassy of India, Paris", phone="+33 1 40 50 70 70", kind="embassy")],
                             "Switzerland": [Contact(name="Embassy of India, Bern", phone="+41 31 350 11 30", kind="embassy")]},
        numbers=[EmergencyNumber(service="Ambulance", number="15"), EmergencyNumber(service="Ambulance", number="144")])


def test_multi_country_safety_has_strip_and_cards_per_country():
    from src.aigv2.guide import model as g
    from src.aigv2.guide.reference import structured_components
    comps = structured_components("safety", _multi_content(), None)
    strips = [c for c in comps if isinstance(c, g.EmergencyStrip)]
    cards = [c for c in comps if isinstance(c, g.ContactCards)]
    assert [s.country for s in strips] == ["France", "Switzerland"] and [s.numbers[0].number for s in strips] == ["15", "144"]
    assert [c.country for c in cards] == ["France", "Switzerland"]
    assert strips[0].dial == "International dial code for France: +33"


def test_multi_country_money_shows_both_currencies():
    from src.aigv2.guide import model as g
    from src.aigv2.guide.reference import structured_components
    from src.aigv2.writing.sections import SectionContent, SectionItem
    c = SectionContent(key="money", by_country={
        "France": [SectionItem(heading="Currency: EUR", body="1 EUR = ₹105.00. Indicative rate (check before you travel).")],
        "Switzerland": [SectionItem(heading="Currency: CHF", body="1 CHF = ₹112.00. Indicative rate (check before you travel).")]},
        items=[SectionItem(heading="Currency: EUR", body="1 EUR = ₹105.00. Indicative rate (check before you travel).")])
    comps = structured_components("money", c, None)
    row = next(x for x in comps if isinstance(x, g.FactRowBlock))
    vals = {f.label: f.value for f in row.facts}
    assert vals["Currency"] == "EUR (France) · CHF (Switzerland)"
    assert "₹105.00" in vals["Indicative rate"] and "₹112.00" in vals["Indicative rate"]


def test_multi_country_safety_renders():
    from docx import Document
    from src.aigv2.guide import model as g
    from src.aigv2.guide.reference import structured_components
    from src.aigv2.render2 import reference_components as RC
    comps = structured_components("safety", _multi_content(), None)
    doc = Document()
    for c in comps:
        if isinstance(c, g.EmergencyStrip):
            RC.render_emergency_strip(doc, 16.0, c)
        elif isinstance(c, g.ContactCards):
            RC.render_contact_cards(doc, 16.0, c)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "FRANCE" in text and "SWITZERLAND" in text


def test_eiffel_choice_and_image_line_merge_into_one_timed_item():
    from src.aigv2.models import Question
    from src.aigv2.preflight import apply_answers
    trip = _trip()
    ans = json.loads((FIX / "answers_final.json").read_text())
    qs = [Question(id="open_choice:0", kind="open_choice", text="x"),
          Question(id=next(k for k in ans if k.startswith("image_details")), kind="image_details", text="x")]
    out = apply_answers(trip, qs, ans)
    d = next(d for d in out.days if d.date == date(2026, 5, 2))
    eiffel = [i for i in d.items if "eiffel" in i.name.lower() or "2nd floor" in i.name.lower()]
    assert [(i.name, i.time) for i in eiffel] == [("Eiffel Tower (2nd floor)", "10:45")]


def test_transport_options_off_the_trip_are_dropped():
    from src.aigv2.writing.sections import transport_off_trip
    trip = _trip()
    for mode, desc in [("Taxi (Charles de Gaulle Airport to Bercy)", "about 1 hr 10 mins"),
                       ("TGV (Gare de Lyon to Annecy)", "Direct high-speed train"),
                       ("Pilatus Railway", "World's steepest cogwheel railway"),
                       ("Train to Bern", "Interlaken Ost to Bern Hauptbahnhof"),
                       ("Train to Innsbruck", "Zurich to Innsbruck by train")]:
        assert transport_off_trip({"mode": mode, "description": desc}, trip), mode
    for mode, desc in [("Train to Zurich", "Interlaken Ost to Zurich Hauptbahnhof, ~2 hours"),
                       ("Metro", "Lines 1 and 13 reach the Louvre"), ("Tram", "Tram 10 runs to Zurich Airport"),
                       ("Paris Visite card", "3-day travel pass")]:
        assert not transport_off_trip({"mode": mode, "description": desc}, trip), mode


def test_route_specific_transport_mode_does_not_absorb_a_generic_one():
    from src.aigv2.writing.structured import extract_transport
    out = extract_transport([{"mode": "Train", "description": "Interlaken-Lucerne Express runs hourly."},
                             {"mode": "Train to Zurich", "description": "Interlaken Ost to Zurich HB, ~2 hours."}])
    byh = {p.heading: p.body for p in out}
    assert "Zurich" in byh["Train to Zurich"] and "Lucerne" not in byh["Train to Zurich"]


def test_section_inputs_dishes_come_from_the_city_own_shard():
    from types import SimpleNamespace
    from src.aigv2.pipeline import _section_inputs

    class Lib:
        def city(self, c, region=True):
            own = {"local_dishes": [{"name": "Rösti"}]}
            return {**own, "local_dishes": own["local_dishes"] + ([{"name": "Crepes"}] if region else [])}

        def country(self, c):
            return {"money": []}

    state = SimpleNamespace(days=[SimpleNamespace(city="Lucerne")], countries={"Lucerne": "Switzerland"})
    city_data, _ = _section_inputs(state, Lib())
    assert [d["name"] for d in city_data[0]["local_dishes"]] == ["Rösti"]
