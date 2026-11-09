import json
from datetime import date, datetime, time
from pathlib import Path

import pytest

from src.aigv2.google.maplink import MapLink
from src.aigv2.google.overrides import PlaceOverrides
from src.aigv2.models import DayPlan, HotelStay, PlannedItem, Place, Question, Traveller, Diet, TripPlan, place_key
from src.aigv2.place_links import apply_place_answers, override_report, place_link_questions, validate_place_link
from src.aigv2.preflight import unanswered, validate_answers
from tests.aigv2.test_preflight import ask, make
from tests.aigv2.test_pipeline import FIX, FakePlaces, _place, built, deps, started  # noqa: F401

FINAL = "https://www.google.com/maps/place/Baeren+Hotel/@46.66,7.86,17z/data=!3d46.6638!4d7.8607"


def _unmatched(name):
    return _place(name).model_copy(update={"match_ok": False})


def _trip():
    return make(hotels=[HotelStay(city="Paris", hotel="Hotel Baren", check_in=date(2026, 10, 10),
                                  check_out=date(2026, 10, 12), source="voucher")],
                days=[DayPlan(date=date(2026, 10, 10), title="t", city="Paris", items=[
                    PlannedItem(name="Secret Cave", kind="attraction", city="Paris"),
                    PlannedItem(name="Free time", kind="attraction", city="Paris"),
                    PlannedItem(name="Overnight in Paris", kind="activity", city="Paris"),
                    PlannedItem(name="Louvre", kind="attraction", city="Paris")]),
                      DayPlan(date=date(2026, 10, 11), title="t", city="Paris")])


def test_questions_for_unmatched_and_near_miss():
    trip = _trip()
    places = {"hotel baren|paris": None, "secret cave|paris": _unmatched("Secret Cavern"),
              "louvre|paris": _place("Louvre"), "free time|paris": None, "overnight in paris|paris": None}
    qs = place_link_questions(trip, places)
    assert [q.id for q in qs] == ["place_link:hotel baren|paris", "place_link:secret cave|paris"]
    assert 'Google could not find "Hotel Baren" (Paris)' in qs[0].text and qs[0].options == ["Skip"]
    assert 'suggested "Secret Cavern"' in qs[1].text and qs[1].options == ["Yes (accept suggestion)", "Skip"]


def test_checklist_appends_place_questions_last():
    qs = ask(_trip(), places={"hotel baren|paris": None})
    assert qs[-1].kind == "place_link"


def test_validation():
    q = Question(id="place_link:x|y", kind="place_link", text="t", options=["Skip"])
    qn = q.model_copy(update={"options": ["Yes (accept suggestion)", "Skip"]})
    ok = ["skip", "Skip", FINAL, "https://maps.app.goo.gl/abc", "Hotel Bear Inn"]
    for a in ok:
        assert validate_place_link(a, q) is None, a
    assert validate_place_link("yes", q) and validate_place_link("yes", qn) is None
    assert validate_place_link("https://example.com/x", q)
    assert validate_place_link("https://www.google.com/maps/dir/a/b", q)
    assert validate_place_link("ab", q)
    assert validate_answers([q], {q.id: "https://example.com"}) and not unanswered([q], {q.id: "Skip"})


class LinkClient:
    def __init__(self, tmp_path):
        self.overrides = PlaceOverrides(tmp_path / "_place_overrides.json")
        self.override_hits = {}
        self.found = {}

    def from_link(self, link):
        return _place(link.name).model_copy(update={"maps_url": link.url, "place_id": "", "name": link.name})

    def find(self, name, city, **k):
        return self.found.get(name)


def test_apply_url_name_yes_skip_and_failure(tmp_path):
    trip = _trip()
    qs = [Question(id="place_link:hotel baren|paris", kind="place_link", text="t", options=["Skip"]),
          Question(id="place_link:secret cave|paris", kind="place_link", text="t", options=["Yes", "Skip"]),
          Question(id="place_link:louvre|paris", kind="place_link", text="t", options=["Skip"])]
    raw = {"hotel baren|paris": None, "secret cave|paris": _unmatched("Secret Cavern").model_dump(mode="json"),
           "louvre|paris": None}
    c = LinkClient(tmp_path)
    ans = {qs[0].id: "https://maps.app.goo.gl/T", qs[1].id: "yes", qs[2].id: "Le Louvre Museum"}
    rep = apply_place_answers(trip, qs, ans, raw, c, fetch=lambda u: FINAL)
    assert raw["hotel baren|paris"]["match_ok"] and raw["hotel baren|paris"]["maps_url"] == "https://maps.app.goo.gl/T"
    assert raw["secret cave|paris"]["match_ok"] and raw["secret cave|paris"]["name"] == "Secret Cavern"
    assert raw["louvre|paris"] is None  # typed name did not match
    assert len(rep["applied"]) == 2 and "Louvre" in rep["failed"][0]
    assert c.overrides.get("Hotel Baren", "Paris")["maps_url"] == "https://maps.app.goo.gl/T"
    assert c.overrides.get("Secret Cave", "Paris")
    c.found["Le Louvre Museum"] = _place("Le Louvre Museum")
    rep = apply_place_answers(trip, qs[2:], ans, raw, c)
    assert raw["louvre|paris"]["name"] == "Le Louvre Museum" and not rep["failed"]


def test_bad_link_and_network_do_not_raise(tmp_path):
    trip = _trip()
    q = Question(id="place_link:hotel baren|paris", kind="place_link", text="t", options=["Skip"])
    raw = {"hotel baren|paris": None}

    def boom(u):
        raise OSError("down")
    rep = apply_place_answers(trip, [q], {q.id: "https://maps.app.goo.gl/T"}, raw, LinkClient(tmp_path), fetch=boom)
    assert raw["hotel baren|paris"] is None and "could not be used" in rep["failed"][0]


def test_override_report(tmp_path):
    c = LinkClient(tmp_path)
    c.overrides.put("Hotel Baren", "Paris", "Baeren Hotel", 1, 2, "https://maps.app.goo.gl/T")
    lines = override_report(_trip(), c)
    assert len(lines) == 1 and "Baeren Hotel" in lines[0] and "maps.app.goo.gl" in lines[0]


class UnmatchedPlaces(FakePlaces):
    def __init__(self, overrides):
        super().__init__()
        self.overrides = overrides
        self.override_hits = {}
        self.linked = []

    def find(self, name, city, near=None, fresh=False):
        e = self.overrides.get(name, city)
        if e:
            self.override_hits[name] = e
            return _place(e["google_name"])
        self.calls["text_search"] += 1
        return None if name == "Statue of Liberty ferry" else _place(name)

    def from_link(self, link):
        self.linked.append(link.url)
        return _place(link.name).model_copy(update={"maps_url": link.url})


def test_end_to_end_question_apply_and_persist(deps, tmp_path):
    from src.aigv2.pipeline import build_run, start_run
    ov = PlaceOverrides(tmp_path / "ov" / "_place_overrides.json")
    deps.places = UnmatchedPlaces(ov)
    deps.link_fetch = lambda u: FINAL
    store, qs = start_run(None, sorted(FIX.glob("*.txt")), deps)
    pl = [q for q in qs if q.kind == "place_link"]
    assert pl and qs[-len(pl):] == pl
    tmpl = json.loads(store.load_bytes("answers.template.json")) if hasattr(store, "load_bytes") else store.load_json("answers.template.json")
    assert all(q.id in tmpl for q in pl)
    answers = {q.id: ("yes" if q.kind != "place_link" and not q.options else (q.options[0] if q.options else "yes")) for q in qs}
    answers[pl[0].id] = "https://maps.app.goo.gl/XYZ"
    res = build_run(store, answers, deps)
    assert deps.places.linked == ["https://maps.app.goo.gl/XYZ"]
    assert ov.all()
    report = store.load_bytes("qc_report.md").decode() if hasattr(store, "load_bytes") else ""
    assert "## Place links applied this run" in report and "maps.app.goo.gl/XYZ" in report
    assert "## Places matched from saved overrides" in report


def test_pointless_questions_are_not_asked():
    from src.aigv2.models import Booking
    trip = make(hotels=[HotelStay(city="Paris", hotel="Hotel Baren", check_in=date(2026, 10, 10),
                                  check_out=date(2026, 10, 12), source="voucher")],
                bookings=[Booking(name="Big Bus: Paris Hop-on Hop-off", day=date(2026, 10, 10), source="v")],
                days=[DayPlan(date=date(2026, 10, 10), title="t", city="Paris", items=[
                    PlannedItem(name="Fireworks at Disneyland", kind="activity", city="Paris"),
                    PlannedItem(name="Big Bus: Paris Hop-on Hop-off", kind="activity", city="Paris"),
                    PlannedItem(name="Arrival in Paris", kind="activity", city="Paris"),
                    PlannedItem(name="Train to Lyon", kind="activity", city="Paris"),
                    PlannedItem(name="Secret Cave", kind="attraction", city="Paris")])])
    from src.aigv2.place_links import place_targets
    names = [v[0] for v in place_targets(trip).values()]
    assert names == ["Hotel Baren", "Secret Cave"]


def test_useless_near_miss_becomes_not_found_or_dropped():
    trip = make(days=[DayPlan(date=date(2026, 10, 10), title="t", city="Paris", items=[
        PlannedItem(name="Secret Cave", kind="attraction", city="Paris"),
        PlannedItem(name="Wine tasting", kind="activity", city="Paris")])])
    places = {"secret cave|paris": _unmatched("Paris"), "wine tasting|paris": _unmatched("Paris")}
    qs = place_link_questions(trip, places)
    assert len(qs) == 2 and all(q.options == ["Skip"] and "could not find" in q.text for q in qs)
    assert place_link_questions(trip, {"secret cave|paris": _unmatched("Secret Cavern")})[0].options[0].startswith("Yes")


def _hotel_trip(name, city):
    return make(hotels=[HotelStay(city=city, hotel=name, check_in=date(2026, 5, 1), check_out=date(2026, 5, 3),
                                  source="voucher")],
                days=[DayPlan(date=date(2026, 5, 1), title="t", city=city), DayPlan(date=date(2026, 5, 2), title="t", city=city)])


def _gp(name, address):
    return _place(name).model_copy(update={"address": address})


def test_fuzzy_matched_hotels_ask_for_confirmation_exact_ones_do_not(tmp_path):
    cases = [("Voco Paris- Porte de Clichy", "Paris", "voco Paris - Porte de Clichy by IHG", "2 Rue du 8 Mai 1945, 92110 Clichy, France"),
             ("Hotel Baren the Bear Inn", "Interlaken", "Baeren Hotel, The Bear Inn", "Oberdorfstrasse 1, 3812 Wilderswil, Switzerland")]
    for name, city, gname, addr in cases:
        trip = _hotel_trip(name, city)
        qs = place_link_questions(trip, {place_key(name, city): _gp(gname, addr)})
        assert len(qs) == 1 and qs[0].options == ["Yes (correct)", "Skip"] and gname in qs[0].text and addr in qs[0].text
        assert validate_place_link("Yes (correct)", qs[0]) is None and validate_place_link("yes", qs[0]) is None
    exact = _hotel_trip("Hotel Luzernerhof", "Lucerne")
    assert place_link_questions(exact, {place_key("Hotel Luzernerhof", "Lucerne"):
                                        _gp("Hotel Luzernerhof", "Alpenstrasse 3, 6002 Lucerne, Switzerland")}) == []
    # same name but the city is not in the address -> ask
    assert len(place_link_questions(exact, {place_key("Hotel Luzernerhof", "Lucerne"):
                                            _gp("Hotel Luzernerhof", "Somewhere 1, Zurich")})) == 1


def test_yes_confirms_hotel_and_saves_override(tmp_path):
    name, city = "Hotel Baren the Bear Inn", "Interlaken"
    trip = _hotel_trip(name, city)
    key = place_key(name, city)
    g = _gp("Baeren Hotel, The Bear Inn", "Wilderswil")
    q = place_link_questions(trip, {key: g})[0]
    raw = {key: g.model_dump(mode="json")}
    c = LinkClient(tmp_path)
    rep = apply_place_answers(trip, [q], {q.id: "Yes (correct)"}, raw, c)
    assert len(rep["applied"]) == 1 and not rep["failed"]
    e = c.overrides.get(name, city)
    assert e["google_name"] == "Baeren Hotel, The Bear Inn" and e["confirmed_by"] == "user"


EUROPE = [("Voco Paris- Porte de Clichy", "Paris", "voco Paris - Porte de Clichy by IHG", "2 Rue du 8 Mai 1945, 92110 Clichy, France"),
          ("Hotel Luzernerhof", "Lucerne", "Hotel Luzernerhof", "Alpenstrasse 3, 6004 Luzern, Switzerland"),
          ("Hotel Baren the Bear Inn", "Interlaken", "Baeren Hotel, The Bear Inn", "Oberdorfstrasse 1, 3812 Wilderswil, Switzerland"),
          ("Novotel Zurich Airport Messe", "Zurich", "Novotel Zurich Airport Messe", "Lindbergh-Platz 1, 8152 Glattpark (Opfikon), Switzerland")]


def _europe():
    hotels = [HotelStay(city=c, hotel=n, check_in=date(2026, 5, 1 + i), check_out=date(2026, 5, 2 + i), source="voucher")
              for i, (n, c, _g, _a) in enumerate(EUROPE)]
    trip = make(hotels=hotels, days=[DayPlan(date=date(2026, 5, 1 + i), title="t", city=c) for i, (_n, c, _g, _a) in enumerate(EUROPE)])
    places = {place_key(n, c): _gp(g, a) for n, c, g, a in EUROPE}
    return trip, places


def test_europe_hotels_asked_first_unless_exact(tmp_path):
    trip, places = _europe()
    trip.days[0].items.append(PlannedItem(name="Secret Cave", kind="attraction", city="Paris"))
    places[place_key("Secret Cave", "Paris")] = None
    qs = place_link_questions(trip, places)
    ids = [q.id for q in qs]
    # voco / baren (name differs) and novotel (no 'Zurich' in the address) are asked; Luzernerhof is exact (alias Luzern)
    assert ids[:3] == [PREFIX_ + place_key(n, c) for n, c, _g, _a in (EUROPE[0], EUROPE[2], EUROPE[3])]
    assert ids[3] == PREFIX_ + place_key("Secret Cave", "Paris")        # hotels come first
    assert PREFIX_ + place_key("Hotel Luzernerhof", "Lucerne") not in ids
    assert all(q.options == ["Yes (correct)", "Skip"] for q in qs[:3])
    assert "2 Rue du 8 Mai 1945" in qs[0].text and "maps" in qs[0].text and qs[0].day == date(2026, 5, 1)


def test_saved_override_stops_the_hotel_question(tmp_path):
    trip, places = _europe()
    c = LinkClient(tmp_path)
    assert len(place_link_questions(trip, places, c.overrides)) == 3
    c.overrides.put("Hotel Baren the Bear Inn", "Interlaken", "Baeren Hotel, The Bear Inn", 1, 2, "https://x")
    assert len(place_link_questions(trip, places, c.overrides)) == 2


def test_unmatched_hotel_says_could_not_find(tmp_path):
    trip, places = _europe()
    places[place_key(*EUROPE[0][:2])] = None
    q = place_link_questions(trip, places)[0]
    assert 'could not find' in q.text and "Voco" in q.text and q.options == ["Skip"]


PREFIX_ = "place_link:"
