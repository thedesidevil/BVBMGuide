import json
from datetime import date, datetime, time
from pathlib import Path

import pytest

from src.aigv2.google.maplink import MapLink
from src.aigv2.google.overrides import PlaceOverrides
from src.aigv2.models import DayPlan, HotelStay, PlannedItem, Place, Question, Traveller, Diet, TripPlan
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
    assert 'Google could not find "Hotel Baren" (Paris, day 1)' in qs[0].text and qs[0].options == ["Skip"]
    assert 'suggested "Secret Cavern"' in qs[1].text and qs[1].options == ["Yes", "Skip"]


def test_checklist_appends_place_questions_last():
    qs = ask(_trip(), places={"hotel baren|paris": None})
    assert qs[-1].kind == "place_link"


def test_validation():
    q = Question(id="place_link:x|y", kind="place_link", text="t", options=["Skip"])
    qn = q.model_copy(update={"options": ["Yes", "Skip"]})
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
