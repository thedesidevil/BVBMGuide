import copy
import io
import json
import re
from datetime import datetime, time
from types import SimpleNamespace
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from typer.testing import CliRunner

from src.aigv2 import pipeline
from src.aigv2.config import STEPS, Settings
from src.aigv2.library import Library
from src.aigv2.llm import StepLLM
from src.aigv2.models import Booking, Place, TransportLeg, WeeklyHours
from src.aigv2.planning.boat import enrich_boat_legs, parse_boat_type, parse_check_in, parse_crossing_min
from src.aigv2.pipeline import Deps, UnansweredQuestions, build_run, cost_summary, regenerate, requalify, start_run
from src.library.ui.storage import LocalStorageBackend

FIX = Path(__file__).parent / "fixtures" / "nyc_trip"
VEG = ["Saravana Bhavan", "Dirt Candy", "Hangawi", "Bhavan Express", "Green Leaf", "Udupi Palace",
       "Leafy Table", "Garden Plate", "Sprout House", "Veg Corner"]


def _place(name: str, i: int = 0) -> Place:
    hours = WeeklyHours(periods={d: [(time(7), time(23))] for d in range(7)}, source="google")
    return Place(query=name, place_id=f"pid_{re.sub(r'\W', '_', name)}", name=name, address="1 Test St, New York, NY 10001, USA",
                 lat=40.75 + i * 0.0001, lng=-73.98, status="OPERATIONAL", hours=hours, website=None, phone="+1 212 000 0000",
                 maps_url=f"https://www.google.com/maps/search/?api=1&query={name.replace(' ', '+')}&query_place_id=pid",
                 fetched_at=datetime(2027, 1, 1), match_ok=True)


class FakePlaces:
    def __init__(self):
        self.calls = {"text_search": 0, "nearby": 0, "details": 0}

    def find(self, name, city, near=None, fresh=False):
        self.calls["text_search"] += 1
        return _place(name)

    def fresh_status(self, place):
        self.calls["details"] += 1
        return place

    def nearby(self, lat, lng, types, radius_m, max_results, city=None):
        self.calls["nearby"] += 1
        return [_place(f"{types[0]} {i}", i) for i in range(2)]


class FakeRoutes:
    def __init__(self):
        self.calls = {"matrix_elements": 0, "directions": 0}

    def durations(self, origins, destinations, mode, when=None):
        self.calls["matrix_elements"] += len(origins) * len(destinations)
        return {(i, j): 5 for i in range(len(origins)) for j in range(len(destinations))}

    def transit_steps(self, origin, destination, when=None):
        self.calls["directions"] += 1
        return []


class FakeFx:
    def rate(self, code, on=None):
        return 1.0 if code == "INR" else 85.0


def _rank(prompt: str) -> str:
    count = int(re.search(r"Choose exactly (\d+)", prompt).group(1))
    cands = json.loads(prompt.split("Candidates (JSON): ", 1)[1].split("\n", 1)[0])
    ordered = sorted(cands, key=lambda c: not c["indian"])
    return json.dumps({"picks": [c["name"] for c in ordered[:count]]})


def _day(prompt: str) -> str:
    facts = json.loads(prompt.split("\n", 1)[1])
    return json.dumps({
        "title": f"Exploring {facts['city']}", "intro": "The day moves gently.",
        "attractions": [{"name": a["name"], "description": "A local favorite."} for a in facts["attractions"]],
        "restaurants": [{"name": r["name"], "ambience": "Relaxed", "best_for": "Families"} for r in facts["restaurants"]],
        "free_time_idea": None})


REPLIES = {
    "extract": lambda p: (FIX / "expected_trip_plan.json").read_text(encoding="utf-8"),
    "rank": _rank,
    "write_days": _day,
    "write_sections": lambda p: json.dumps(
        {"items": [], "groups": [{"title": "Clothing", "items": ["Light layers"]}]} if p.startswith("Section: packing")
        else {"items": [{"heading": "Good to know", "body": "Plan ahead and enjoy."}]}),
    "title": lambda p: json.dumps({"title": p.split("Destinations in order: ")[1].split("\n")[0].split(",")[0] + " Lights Ahead"}),
    "thanks": lambda p: json.dumps({"paragraphs": ["Thank you for the opportunity to plan your trip to New York.",
                                                   "Bon Voyage by Marina is a message away."]}),
    "qc_prose": lambda p: json.dumps({"issues": []}),
    "qc_sense": lambda p: json.dumps({"issues": []}),
}


class FakeLLM(StepLLM):
    def __init__(self, settings):
        super().__init__(settings, client_factory=lambda m: None)
        self.calls: list[tuple[str, str]] = []

    def _attempt(self, step, model, system, prompt, schema, validate, max_tokens, fallback):
        self.calls.append((step, prompt))
        self._log.append({"step": step, "model": model, "prompt_tokens": 100, "completion_tokens": 20,
                          "usd": 0.001, "fallback": fallback})
        obj = schema.model_validate_json(REPLIES[step](prompt))
        problems = validate(obj) if validate else []
        return (None, problems) if problems else (obj, [])


def _library(root: Path) -> Library:
    root.mkdir()
    rests = [{"name": n, "cuisine_type": ["South Indian"] if "Bhavan" in n or "Udupi" in n else ["Vegetarian"],
              "vegetarian_friendly": True, "highlights": "Pure vegetarian kitchen", "price_range": "$20-30"}
             for n in VEG]
    rests.append({"name": "Prime Steakhouse", "cuisine_type": ["Steak"], "vegetarian_friendly": False,
                  "price_range": "$80"})
    shard = {"restaurants": rests, "attractions": [{"name": "Statue of Liberty ferry", "recommended_duration": "3 hours"}],
             "safety_tips": [{"tip": "Keep valuables close."}]}
    (root / "New York.json").write_text(json.dumps(shard), encoding="utf-8")
    (root / "_index.json").write_text(json.dumps({"_folder_coverage": {"USA": ["New York"]}}), encoding="utf-8")
    (root / "_country").mkdir()
    (root / "_country" / "USA.json").write_text(json.dumps({"currency": "USD"}), encoding="utf-8")
    return Library(root)


@pytest.fixture
def deps(tmp_path):
    models = {s: "gpt-6-luna" for s in STEPS} | {"qc_sense": "gpt-6.1-sol"}
    settings = Settings(models=models, data_root=tmp_path / "data")
    return Deps(settings=settings, llm=FakeLLM(settings), library=_library(tmp_path / "lib"), places=FakePlaces(),
                routes=FakeRoutes(), fx=FakeFx(), backend=LocalStorageBackend(tmp_path / "data"))


def answers_for(questions) -> dict:
    out = {}
    for q in questions:
        if q.kind == "vague_day":
            out[q.id] = "Museum of Modern Art"
        else:
            out[q.id] = q.options[0] if q.options else "yes"
    return out


def started(deps):
    store, questions = start_run(None, sorted(FIX.glob("*.txt")), deps)
    return store, questions, answers_for(questions)


def built(deps):
    store, questions, answers = started(deps)
    return store, answers, build_run(store, answers, deps)


def day_headers(docx: bytes) -> list[str]:
    doc = Document(io.BytesIO(docx))
    return [p.text for p in doc.paragraphs if p.style.name == "Heading 1" and p.text.startswith("Day ")]


def steps(llm, name):
    return [p for s, p in llm.calls if s == name]


def test_end_to_end_fakes(deps):
    store, questions, answers = started(deps)
    assert questions and {q.kind for q in questions} >= {"open_choice", "vague_day"}
    assert store.load_json("trip_plan.json")["client_names"] == ["Test Client"]
    assert store.load_json("questions.json")
    result = build_run(store, answers, deps)
    for name in ("guide.docx", "qc_report.md", "qc_report.json", "verification.xlsx", "cost.json", "plan.json",
                 "days/day_01.json", "sections/packing.json"):
        assert store.has(name), name
    headers = day_headers(store.load_bytes("guide.docx"))
    assert len(headers) == 4
    assert [int(re.match(r"Day (\d+) – ", h).group(1)) for h in headers] == [1, 2, 3, 4]
    assert headers[0].startswith("Day 1 – Fri, 12 Mar | ")
    assert result.docx_name == "All Inclusive Guide - Test Client - New York.docx"
    assert result.cost_usd > 0 and result.qc.marker_count >= 0
    assert "Museum of Modern Art" in "\n".join(steps(deps.llm, "write_days"))
    assert "Prime Steakhouse" not in "\n".join(p for _, p in deps.llm.calls if _ in ("rank", "write_days"))


def test_build_refuses_unanswered(deps):
    store, questions, answers = started(deps)
    with pytest.raises(UnansweredQuestions) as exc:
        build_run(store, {}, deps)
    assert {q.id for q in exc.value.questions} == {q.id for q in questions}
    partial = dict(answers)
    partial.pop(next(iter(partial)))
    with pytest.raises(UnansweredQuestions):
        build_run(store, partial, deps)
    assert not store.has("plan.json")


def test_checkpoint_skips_stage(deps):
    store, answers, first = built(deps)
    before = len(deps.llm.calls)
    second = build_run(store, answers, deps)
    assert len(deps.llm.calls) == before
    assert second.docx_name == first.docx_name and second.qc.passed == first.qc.passed
    assert second.cost_usd == 0


def test_regenerate_one_day(deps):
    store, answers, _ = built(deps)
    deps.llm.calls.clear()
    old = store.load_bytes("guide.docx")
    result = regenerate(store, [2], [], deps)
    writes = steps(deps.llm, "write_days")
    assert len(writes) == 1 and '"date": "2027-03-13"' in writes[0]
    assert not steps(deps.llm, "write_sections") and not steps(deps.llm, "title")
    assert steps(deps.llm, "qc_sense")
    assert store.load_bytes("guide.v1.docx") == old
    assert store.has("guide.docx") and store.has("qc_report.v1.md")
    assert len(day_headers(store.load_bytes("guide.docx"))) == 4
    assert result.docx_name.endswith(".docx")
    regenerate(store, [], ["packing"], deps)
    assert store.has("guide.v2.docx")
    assert len(steps(deps.llm, "write_sections")) == 1


def test_regenerate_keeps_repeat_limits(deps):
    store, answers, _ = built(deps)
    regenerate(store, [2], [], deps)
    plan = store.load_json("plan.json")
    uses: dict = {}
    for pick in plan["picks"]:
        names = [c["lib"]["name"] for c in pick["restaurants"]]
        assert len(names) == len(set(names))
        for n in names:
            uses[n] = uses.get(n, 0) + 1
    assert uses and max(uses.values()) <= 2


def test_regenerate_rejects_unknown(deps):
    store, answers, _ = built(deps)
    with pytest.raises(ValueError):
        regenerate(store, [9], [], deps)
    with pytest.raises(ValueError):
        regenerate(store, [], ["nonsense"], deps)


def _strip_markers(doc) -> None:
    for p in list(doc.element.body.iter(qn("w:p"))):
        text = "".join(t.text or "" for t in p.iter(qn("w:t")))
        if "⚠" not in text:
            continue
        if p.getparent() is doc.element.body:
            p.getparent().remove(p)
        else:
            for t in p.iter(qn("w:t")):
                if t.text and "⚠" in t.text:
                    t.text = "checked"


def _add_restaurant(doc, name: str) -> None:
    for tbl in doc.element.body.iter(qn("w:tbl")):
        text = "".join(t.text or "" for t in tbl.iter(qn("w:t")))
        hit = next((n for n in VEG if n in text), None)
        if hit and "CUISINE" in text.upper():
            new = copy.deepcopy(tbl)
            for t in new.iter(qn("w:t")):
                if t.text and hit in t.text:
                    t.text = t.text.replace(hit, name)
            tbl.addnext(new)
            return
    raise AssertionError("no restaurant card found")


def test_requalify_edited_doc(deps, tmp_path):
    store, answers, _ = built(deps)
    doc = Document(io.BytesIO(store.load_bytes("guide.docx")))
    _strip_markers(doc)
    _add_restaurant(doc, "Hand Added Bistro")
    path = tmp_path / "edited.docx"
    doc.save(str(path))
    out, result, report = requalify(store, path, deps)
    assert out[:2] == b"PK" and "# QC report" in report
    mine = [f for f in result.findings if f.anchor_text == "Hand Added Bistro" or "Hand Added Bistro" in f.message]
    assert not [f for f in mine if f.rule == "diet" or "library" in f.message.casefold()]
    assert "Hand Added Bistro" in [r.venue for r in result.fact_rows]
    assert not any(f.rule == "diet" for f in result.findings)


def test_cost_log_totals(deps):
    store, answers, result = built(deps)
    cost = store.load_json("cost.json")
    assert cost["ai"]["total_usd"] + cost["google"]["total_usd"] == pytest.approx(cost["total_usd"])
    assert result.cost_usd == pytest.approx(cost["total_usd"])
    by_step, by_api = cost["ai"]["by_step"], cost["google"]["by_api"]
    assert {"write_days", "write_sections", "title", "qc_prose", "qc_sense"} <= set(by_step)
    assert by_step["qc_sense"]["model"] == "gpt-6.1-sol" and by_step["write_days"]["prompt_tokens"] > 0
    assert sum(s["usd"] for s in by_step.values()) == pytest.approx(cost["ai"]["total_usd"])
    unit = deps.settings.google_usd_per_call
    assert set(unit) == {"text_search", "nearby", "details", "route_element"}
    for api in ("text_search", "nearby", "details", "route_element"):
        assert by_api[api]["calls"] > 0
        assert by_api[api]["usd"] == pytest.approx(by_api[api]["calls"] * unit[api])
    assert by_api["route_element"]["calls"] == deps.routes.calls["matrix_elements"] + deps.routes.calls["directions"]
    assert sum(a["usd"] for a in by_api.values()) == pytest.approx(cost["google"]["total_usd"])
    text = cost_summary(cost)
    assert text.startswith(f"Cost this run: ${cost['total_usd']:.2f}")
    assert "write_days $" in text and "text_search " in text and " calls $" in text


def test_cli_prints_cost_split(deps, tmp_path, monkeypatch):
    from src.aigv2.__main__ import app
    store, questions, answers = started(deps)
    ans = tmp_path / "answers.json"
    ans.write_text(json.dumps(answers), encoding="utf-8")
    monkeypatch.setattr(pipeline, "default_deps", lambda: deps)
    out = CliRunner().invoke(app, ["build", store.run_id, "--answers", str(ans)])
    assert out.exit_code == 0, out.output
    lines = out.output.splitlines()
    assert any(l.startswith("Cost this run: $") for l in lines)
    assert any(l.strip().startswith("AI ") and "write_days" in l for l in lines)
    assert any(l.strip().startswith("Google ") and "text_search" in l for l in lines)
    assert "PASS" in out.output or "FAIL" in out.output
    assert "guide.docx" in out.output and "Markers:" in out.output


def test_cli_start_and_qc(deps, tmp_path, monkeypatch):
    from src.aigv2.__main__ import app
    monkeypatch.setattr(pipeline, "default_deps", lambda: deps)
    args = ["start", *[str(p) for p in sorted(FIX.glob("*.txt"))]]
    out = CliRunner().invoke(app, args)
    assert out.exit_code == 0, out.output
    assert "Run id:" in out.output and re.search(r"^ *1\. ", out.output, re.M) and "Cost this run:" in out.output
    store, answers, _ = built(deps)
    edited = tmp_path / "edited.docx"
    edited.write_bytes(store.load_bytes("guide.docx"))
    out = CliRunner().invoke(app, ["qc", str(edited), "--run", store.run_id])
    assert out.exit_code == 0, out.output
    assert "Cost this run:" in out.output and ("PASS" in out.output or "FAIL" in out.output)
    assert (tmp_path / "edited.qc.docx").exists() and (tmp_path / "edited.qc_report.md").exists()
    assert json.loads((tmp_path / "edited.cost.json").read_text())["total_usd"] >= 0


# ---------- fix round 1 ----------

from datetime import date, timedelta  # noqa: E402

from src.aigv2.models import DayPlan, Diet, HotelStay, PlannedItem, TransportLeg, Traveller, TripPlan  # noqa: E402
from src.aigv2.pipeline import pkey  # noqa: E402
from src.aigv2.preflight import run_checklist  # noqa: E402
from src.aigv2.intake.template import IntakeFields  # noqa: E402
from src.aigv2.store import RunStore  # noqa: E402
from src.aigv2.writing.sections import write_section  # noqa: E402

D0 = date(2027, 5, 10)
COUNTRY = {"Prague": "Czechia", "Vienna": "Austria"}


class CityPlaces(FakePlaces):
    def __init__(self):
        super().__init__()
        self.lookups = []
        self.closed: set[tuple[str, str]] = set()

    def find(self, name, city, near=None, fresh=False):
        self.calls["text_search"] += 1
        self.lookups.append((name, city))
        p = _place(name)
        p.lat = 50.0 if city == "Prague" else 48.2 if city == "Vienna" else 40.75
        p.address = f"1 Test St, {city}, {COUNTRY.get(city, 'USA')}"
        p.place_id = f"pid_{name}_{city}".replace(" ", "_")
        p.lng = -73.98 + len(name) * 0.001
        if (name, city) in self.closed:
            p.hours = WeeklyHours(periods={6: [(time(9), time(17))]}, source="google")
        return p


def two_city_trip() -> TripPlan:
    d = [D0 + timedelta(days=i) for i in range(4)]
    return TripPlan(
        client_names=["Test Client"], travellers=Traveller(adults=2), diet=Diet(), travel_modes=["taxi"],
        hotels=[HotelStay(city="Prague", hotel="Grand Hotel", check_in=d[0], check_out=d[2], source="voucher"),
                HotelStay(city="Vienna", hotel="Grand Hotel", check_in=d[2], check_out=d[3], source="voucher")],
        transport=[
            TransportLeg(kind="flight", from_place="Mumbai", to_place="Airport", depart=datetime(2027, 5, 10, 2, 0),
                         arrive=datetime(2027, 5, 10, 9, 0), source="ticket"),
            TransportLeg(kind="flight", from_place="Airport", to_place="Airport", depart=datetime(2027, 5, 12, 10, 0),
                         arrive=datetime(2027, 5, 12, 11, 0), source="ticket"),
            TransportLeg(kind="flight", from_place="Airport", to_place="Mumbai", depart=datetime(2027, 5, 13, 18, 0),
                         arrive=datetime(2027, 5, 14, 6, 0), source="ticket")],
        bookings=[],
        days=[DayPlan(date=d[0], title="Arrive", city="Prague"),
              DayPlan(date=d[1], title="Old Town", city="Prague",
                      items=[PlannedItem(name="Old Town", kind="attraction", city="Prague", slot_hint="morning"),
                             PlannedItem(name="Castle", kind="attraction", city="Prague", slot_hint="afternoon")]),
              DayPlan(date=d[2], title="To Vienna", city="Vienna",
                      items=[PlannedItem(name="Old Town", kind="attraction", city="Vienna", slot_hint="afternoon")]),
              DayPlan(date=d[3], title="Home", city="Vienna")],
        open_choices=[], vague_days=[], commentary_removed=[], trip_scope="international")


def seeded(deps, trip: TripPlan) -> RunStore:
    store = RunStore.create(deps.backend)
    store.save_json("trip_plan.json", trip)
    store.save_json("questions.json", {"questions": []})
    return store


def test_places_keyed_by_city(deps):
    deps.places = CityPlaces()
    store = seeded(deps, two_city_trip())
    build_run(store, {}, deps)
    state = pipeline._load_plan(store)
    d2, d3, d4 = state.days[1], state.days[2], state.days[3]
    assert d2.places["Old Town"].lat == 50.0 and d3.places["Old Town"].lat == 48.2
    assert d3.places["Grand Hotel"].lat == 48.2 and d2.places["Grand Hotel"].lat == 50.0
    assert d4.places["Airport"].lat == 48.2 and state.days[0].places["Airport"].lat == 50.0
    assert ("Airport", "Vienna") in deps.places.lookups and ("Airport", "Prague") in deps.places.lookups
    assert state.countries == {"Prague": "Czechia", "Vienna": "Austria"}
    assert {i.city for i in state.important} == {"Prague", "Vienna"}


class RecordingRoutes(FakeRoutes):
    def __init__(self):
        super().__init__()
        self.pairs = []

    def durations(self, origins, destinations, mode, when=None):
        self.pairs.append((list(origins), list(destinations)))
        return super().durations(origins, destinations, mode, when)


def test_arrival_departure_and_legs(deps):
    deps.places, deps.routes = CityPlaces(), RecordingRoutes()
    store = seeded(deps, two_city_trip())
    build_run(store, {}, deps)
    state = pipeline._load_plan(store)
    assert [(d.arrival, d.departure) for d in state.days] == [(0, None), (None, None), (1, 1), (None, 2)]
    assert set(state.days[0].legs) == {"arrival"}
    assert set(state.days[1].legs) == {"Old Town", "Castle"}
    assert state.days[1].legs["Castle"].from_name == "Old Town"
    assert set(state.days[2].legs) == {"arrival", "departure", "Old Town"}
    assert state.days[2].legs["departure"].from_name == "Grand Hotel"
    assert state.days[2].legs["arrival"].to_name == "Grand Hotel"
    view = state.days[2].places
    assert view[pkey("Grand Hotel", "Prague")].lat == 50.0 and view[pkey("Grand Hotel", "Vienna")].lat == 48.2
    assert view[pkey("Airport", "Prague")].lat == 50.0 and view[pkey("Airport", "Vienna")].lat == 48.2
    assert view["Grand Hotel"].lat == 48.2
    prague_hotel, prague_port = (50.0, view[pkey("Grand Hotel", "Prague")].lng), (50.0, view[pkey("Airport", "Prague")].lng)
    vienna_port, vienna_hotel = (48.2, view[pkey("Airport", "Vienna")].lng), (48.2, view[pkey("Grand Hotel", "Vienna")].lng)
    assert ([prague_hotel], [prague_port]) in deps.routes.pairs
    assert ([vienna_port], [vienna_hotel]) in deps.routes.pairs
    assert set(state.days[3].legs) == {"departure"}
    rds = pipeline._render_days(store, state, deps)
    assert rds[2].arrival is rds[2].departure and rds[2].prev_city == "Prague"
    assert rds[0].departure is None and rds[3].arrival is None
    assert rds[2].utc_offset_hours == 2.0


def test_early_arrival_and_after_midnight_departure():
    d = [D0 + timedelta(days=i) for i in range(3)]
    trip = two_city_trip().model_copy(update={
        "hotels": [HotelStay(city="Prague", hotel="H", check_in=d[0], check_out=d[2], source="voucher")],
        "transport": [
            TransportLeg(kind="flight", from_place="X", to_place="Airport", arrive=datetime(2027, 5, 11, 2, 30),
                         source="t"),
            TransportLeg(kind="flight", from_place="Airport", to_place="X", depart=datetime(2027, 5, 13, 1, 30),
                         source="t")]})
    # late-night arrival (02:30 on d[1]) belongs to the hotel night of d[0]
    assert pipeline._arrival_idx(trip, d[0]) == 0
    assert pipeline._arrival_idx(trip, d[1]) is None
    assert pipeline._departure_idx(trip, d[2], {d[0], d[1], d[2]}) == 1
    assert pipeline._departure_idx(trip, d[2], {d[0], d[1], d[2], d[2] + timedelta(days=1)}) is None
    late = trip.model_copy(update={"transport": [trip.transport[1].model_copy(
        update={"depart": datetime(2027, 5, 13, 6, 0)})]})
    assert pipeline._departure_idx(late, d[2], {d[2]}) is None


def test_mid_trip_leg_is_not_departure_when_final_flight_missing():
    d = [D0 + timedelta(days=i) for i in range(4)]
    trip = two_city_trip().model_copy(update={
        "hotels": [HotelStay(city="Prague", hotel="H", check_in=d[0], check_out=d[3], source="voucher")],
        "transport": [TransportLeg(kind="train", from_place="A", to_place="B",
                                   depart=datetime(2027, 5, 11, 15, 0), source="t")]})
    assert pipeline._departure_idx(trip, d[1], set(d)) is None
    assert pipeline._departure_idx(trip, d[3], set(d)) is None


def test_utc_offset_and_country():
    assert pipeline._utc_offset("Austria", date(2027, 1, 15)) == 1.0
    assert pipeline._utc_offset("Austria", date(2027, 7, 15)) == 2.0
    assert pipeline._utc_offset("India", date(2027, 7, 15)) == 5.5
    assert pipeline._utc_offset("USA", date(2027, 7, 15)) is None
    assert pipeline._utc_offset("", date(2027, 7, 15)) is None
    p = _place("Hotel")
    p.address = "Kärntner Ring 1, 1010 Wien, Austria"
    assert pipeline._country_of(p) == "Austria"
    p.address = "10 Bayfront Ave, Singapore 018956"
    assert pipeline._country_of(p) == "Singapore"
    p.match_ok = False
    assert pipeline._country_of(p) == "" and pipeline._country_of(None) == ""


def test_country_falls_back_to_library(deps, tmp_path):
    assert pipeline._library_country(deps.library, "New York") == "USA"
    assert pipeline._library_country(deps.library, "Atlantis") == ""

    class NoCountry(FakePlaces):
        def find(self, name, city, near=None, fresh=False):
            p = super().find(name, city, near, fresh)
            p.address = ""
            return p
    deps.places = NoCountry()
    store, answers, _ = built(deps)
    assert pipeline._load_plan(store).countries == {"New York": "USA"}


def test_regenerate_swaps_exclusions(deps):
    store, answers, _ = built(deps)
    plan = store.load_json("plan.json")
    plan["exclusions"] += [{"name": "S2", "reason": "closed", "detail": "Lunch, Day 2, near X: sentinel"},
                           {"name": "S3", "reason": "closed", "detail": "Lunch, Day 3, near X: sentinel"}]
    store.save_json("plan.json", plan)
    regenerate(store, [2], [], deps)
    names = [e["name"] for e in store.load_json("plan.json")["exclusions"]]
    assert "S2" not in names and "S3" in names
    assert any(", Day 2, " in e["detail"] for e in store.load_json("plan.json")["exclusions"])


def test_changed_answers_refused(deps):
    store, answers, _ = built(deps)
    changed = dict(answers)
    changed["open_choice:0"] = "Top of the Rock sunset visit"
    with pytest.raises(ValueError, match="start a new run"):
        build_run(store, changed, deps)


def test_failed_build_saves_partial_and_cost(deps, tmp_path, monkeypatch):
    store, questions, answers = started(deps)

    def boom(prompt):
        raise RuntimeError("title service down")
    monkeypatch.setitem(REPLIES, "title", boom)
    with pytest.raises(RuntimeError) as exc:
        build_run(store, answers, deps)
    assert exc.value.run_id == store.run_id and exc.value.run_cost["ai"]["total_usd"] > 0
    assert store.has("days/day_01.json") and store.has("days/day_04.json") and store.has("sections/safety.json")
    assert not store.has("sections/title.json") and not store.has("guide.docx")
    cost = store.load_json("cost.json")
    assert cost == exc.value.run_cost and cost["google"]["by_api"]["text_search"]["calls"] > 0
    assert store.load_json("cost_history.json")["runs"][-1]["command"] == "build (failed)"
    ans = tmp_path / "answers.json"
    ans.write_text(json.dumps(answers), encoding="utf-8")
    from src.aigv2.__main__ import app
    monkeypatch.setattr(pipeline, "default_deps", lambda: deps)
    out = CliRunner().invoke(app, ["build", store.run_id, "--answers", str(ans)])
    assert out.exit_code == 1 and "FAILED: RuntimeError: title service down" in out.output
    assert "Cost this run: $" in out.output and "  Google " in out.output
    monkeypatch.setitem(REPLIES, "title", lambda p: json.dumps({"title": "New York Lights Ahead"}))
    before = len(steps(deps.llm, "write_days"))
    build_run(store, answers, deps)
    assert len(steps(deps.llm, "write_days")) == before and store.has("guide.docx")


def test_requalify_requires_run(deps, tmp_path, monkeypatch):
    store, answers, _ = built(deps)
    edited = tmp_path / "edited.docx"
    edited.write_bytes(store.load_bytes("guide.docx"))
    with pytest.raises(ValueError, match="--run"):
        requalify(None, edited, deps)
    from src.aigv2.__main__ import app
    monkeypatch.setattr(pipeline, "default_deps", lambda: deps)
    out = CliRunner().invoke(app, ["qc", str(edited)])
    assert out.exit_code != 0 and "--run" in out.output


def test_domestic_guide_has_health_check_marker(deps, monkeypatch):
    plan = json.loads((FIX / "expected_trip_plan.json").read_text(encoding="utf-8"))
    plan["trip_scope"] = "domestic"
    monkeypatch.setitem(REPLIES, "extract", lambda p: json.dumps(plan))
    store, answers, result = built(deps)
    text = "\n".join(p.text for p in Document(io.BytesIO(store.load_bytes("guide.docx"))).paragraphs)
    assert "⚠ CHECK: Altitude / remote area / sea travel not assessed" in text
    assert result.qc.marker_kinds.get("CHECK", 0) >= 1


def test_health_section_for_high_altitude(deps):
    plan = TripPlan.model_validate_json((FIX / "expected_trip_plan.json").read_text(encoding="utf-8"))
    domestic = plan.model_copy(update={"trip_scope": "domestic"})
    city = [{"city": "Leh", "country": "India"}]
    assert write_section("health", city, {}, domestic, deps.llm) is None
    assert write_section("health", city, {}, domestic, deps.llm, high_altitude=True) is not None
    assert write_section("money", city, {}, domestic, deps.llm, high_altitude=True) is None


def test_checklist_hours_checked_per_city(deps, monkeypatch):
    trip = two_city_trip()
    places = CityPlaces()
    places.closed = {("Old Town", "Prague")}
    resolved = pipeline.resolve_places(trip, places, {})
    qs = run_checklist(trip, IntakeFields(), [], deps.library, resolved, deps.settings)
    hours = [q for q in qs if q.kind == "hours_conflict"]
    assert [(q.id, q.day) for q in hours] == [(f"hours_conflict:{D0 + timedelta(days=1)}:Old Town", D0 + timedelta(days=1))]
    places.closed = {("Old Town", "Vienna")}
    monkeypatch.setitem(REPLIES, "extract", lambda p: trip.model_dump_json())
    deps.places = places
    _, qs = start_run(None, sorted(FIX.glob("*.txt")), deps)
    assert [q.day for q in qs if q.kind == "hours_conflict"] == [D0 + timedelta(days=2)]


# ---------- final review fixes ----------

from src.aigv2.qc.reader import read_docx  # noqa: E402
from src.aigv2.qc.rules import check_rules  # noqa: E402

M = [date(2027, 3, 10) + timedelta(days=i) for i in range(4)]


def day_trip() -> TripPlan:
    return TripPlan(
        client_names=["Test Client"], travellers=Traveller(adults=2), diet=Diet(), travel_modes=["taxi"],
        hotels=[HotelStay(city="Florence", hotel="Hotel Arno", check_in=M[0], check_out=M[3], source="voucher")],
        transport=[
            TransportLeg(kind="flight", from_place="Mumbai", to_place="Florence Airport",
                         depart=datetime(2027, 3, 10, 2, 0), arrive=datetime(2027, 3, 10, 10, 0), source="ticket"),
            TransportLeg(kind="train", from_place="Firenze SMN", to_place="Pisa Centrale",
                         depart=datetime(2027, 3, 11, 9, 0), arrive=datetime(2027, 3, 11, 10, 0), source="ticket"),
            TransportLeg(kind="train", from_place="Pisa Centrale", to_place="Firenze SMN",
                         depart=datetime(2027, 3, 11, 18, 0), arrive=datetime(2027, 3, 11, 19, 0), source="ticket"),
            TransportLeg(kind="flight", from_place="Florence Airport", to_place="Mumbai",
                         depart=datetime(2027, 3, 13, 15, 0), arrive=datetime(2027, 3, 13, 23, 0), source="ticket")],
        bookings=[],
        days=[DayPlan(date=M[0], title="Arrive", city="Florence"),
              DayPlan(date=M[1], title="Day trip to Pisa", city="Florence",
                      items=[PlannedItem(name="Leaning Tower", kind="attraction", city="Pisa", time="11:00")]),
              DayPlan(date=M[2], title="Uffizi", city="Florence"),
              DayPlan(date=M[3], title="Home", city="Florence")],
        open_choices=[], vague_days=[], commentary_removed=[], trip_scope="international")


def day_text(docx: bytes, n: int) -> str:
    m = read_docx(docx)
    return "\n".join(p.text for p in m.paragraphs if p.day == n)


def test_same_hotel_day_trip_is_not_a_departure(deps):
    trip = day_trip()
    days = {d.date for d in trip.days}
    assert pipeline._departure_idx(trip, M[1], days) is None
    assert pipeline._departure_idx(trip, M[3], days) == 3
    store = seeded(deps, trip)
    result = build_run(store, {}, deps)
    state = pipeline._load_plan(store)
    d2 = state.days[1]
    assert (d2.arrival, d2.departure) == (None, None) and d2.other_legs == [1, 2]
    assert {m.meal for m in d2.result.meals} >= {"lunch", "dinner"}
    assert "arrival" not in d2.legs and "departure" not in d2.legs
    docx = store.load_bytes("guide.docx")
    text = day_text(docx, 2)
    assert "Reach the station by" not in text and "Overnight in Florence" in text
    assert "Train: Firenze SMN to Pisa Centrale" in text and "Train: Pisa Centrale to Firenze SMN" in text
    assert "⚠ VERIFY: day-trip transport" in text
    assert "Lunch near" in text and "Dinner near" in text
    assert not [f for f in result.qc.findings if f.rule == "transport_missing"]


def test_qc_flags_transport_leg_not_in_guide(deps):
    trip = day_trip()
    store = seeded(deps, trip)
    build_run(store, {}, deps)
    docx = store.load_bytes("guide.docx")
    doc = Document(io.BytesIO(docx))
    for tbl in list(doc.element.body.iter(qn("w:tbl"))):
        if "Train: Pisa Centrale to Firenze SMN" in "".join(t.text or "" for t in tbl.iter(qn("w:t"))):
            tbl.getparent().remove(tbl)
    buf = io.BytesIO()
    doc.save(buf)
    fs = [f for f in check_rules(read_docx(buf.getvalue()), trip, deps.library) if f.rule == "transport_missing"]
    assert len(fs) == 1 and "Pisa Centrale" in fs[0].message and fs[0].day == 2


def test_unlinked_bookings_get_verify_marker_and_qc_rule(deps):
    from src.aigv2.models import Booking
    trip = day_trip().model_copy(update={"bookings": [
        Booking(name="Leaning Tower", day=M[1], time="11:00", source="voucher"),
        Booking(name="Uffizi Skip-the-line", day=M[2], time="10:00", source="voucher"),
        Booking(name="Cooking Class", day=date(2027, 4, 1), source="voucher")]})
    store = seeded(deps, trip)
    build_run(store, {}, deps)
    state = pipeline._load_plan(store)
    texts = {d.index: [m.render() for m in d.result.markers] for d in state.days}
    assert "Leaning Tower" in state.days[1].booking_by_item
    assert not any("Leaning Tower" in t for t in texts[2])
    assert any(t.startswith("⚠ VERIFY: booking 'Uffizi Skip-the-line' at 10:00") for t in texts[3])
    assert any("'Cooking Class'" in t and "2027-04-01" in t for t in texts[1])
    docx = store.load_bytes("guide.docx")
    assert "Uffizi Skip-the-line" in day_text(docx, 3)
    doc = Document(io.BytesIO(docx))
    for p in list(doc.element.body.iter(qn("w:p"))):
        if "Uffizi Skip-the-line" in "".join(t.text or "" for t in p.iter(qn("w:t"))):
            p.getparent().remove(p)
    buf = io.BytesIO()
    doc.save(buf)
    fs = [f for f in check_rules(read_docx(buf.getvalue()), trip, deps.library) if f.rule == "booking_missing"]
    assert [(f.day, "Uffizi Skip-the-line" in f.message) for f in fs] == [(3, True)]


def test_cost_rows_per_model_and_unpriced_warning(deps):
    meter = pipeline.CostMeter(deps)
    log = deps.llm._log
    log.append({"step": "rank", "model": "gpt-6-luna", "prompt_tokens": 100, "completion_tokens": 10, "usd": 0.01,
                "fallback": False})
    log.append({"step": "rank", "model": "gpt-6.1-sol", "prompt_tokens": 200, "completion_tokens": 20, "usd": 0.05,
                "fallback": True})
    log.append({"step": "title", "model": "mystery-model", "prompt_tokens": 50, "completion_tokens": 5, "usd": 0.0,
                "fallback": False, "unpriced": True})
    cost = meter.cost()
    rows = cost["ai"]["by_step"]
    assert list(rows) == ["rank", "rank (fallback)", "title"]
    assert rows["rank"] == {"model": "gpt-6-luna", "prompt_tokens": 100, "completion_tokens": 10, "usd": 0.01}
    assert rows["rank (fallback)"]["model"] == "gpt-6.1-sol" and rows["rank (fallback)"]["usd"] == 0.05
    assert cost["ai"]["total_usd"] == pytest.approx(0.06)
    assert cost["warnings"] == ["No price for model mystery-model (step title); its cost is counted as $0"]
    text = cost_summary(cost)
    assert "rank (fallback) $0.05" in text and "WARNING: No price for model mystery-model" in text


def test_country_from_dash_separated_address(deps):
    p = _place("Hotel")
    p.address = "Sheikh Zayed Rd - Trade Centre - Dubai - United Arab Emirates"
    assert pipeline._country_of(p) == "United Arab Emirates"
    p.address = "Al Barsha 1, Sheikh Zayed Rd - Al Barsha"
    assert pipeline._city_country(p, deps.library, "New York") == "USA"
    p.address = "1 Test St, New York, NY 10001, USA"
    assert pipeline._city_country(p, deps.library, "Atlantis") == "USA"
    p.address = "Calle 1, Cusco, Peru"
    assert pipeline._city_country(p, deps.library, "Cusco") == "Peru"


def test_transfer_items_not_sent_to_google(deps):
    trip = day_trip()
    trip.days[2].items = [PlannedItem(name="Private transfer to the vineyard", kind="transfer", city="Florence")]
    places = CityPlaces()
    pipeline.resolve_places(trip, places, {})
    assert ("Private transfer to the vineyard", "Florence") not in places.lookups
    store = seeded(deps, trip)
    build_run(store, {}, deps)
    text = day_text(store.load_bytes("guide.docx"), 3)
    assert "Private transfer to the vineyard" in text and "place not found on Google" not in text


def test_write_reports_every_failed_writer(deps, monkeypatch):
    store, questions, answers = started(deps)
    monkeypatch.setitem(REPLIES, "title", lambda p: (_ for _ in ()).throw(RuntimeError("title down")))
    monkeypatch.setitem(REPLIES, "write_days", lambda p: (_ for _ in ()).throw(RuntimeError("days down")))
    with pytest.raises(RuntimeError) as exc:
        build_run(store, answers, deps)
    msg = str(exc.value)
    assert "title down" in msg and "days down" in msg and "sections/title.json" in msg and "days/day_01.json" in msg


def test_default_deps_library_path_from_env(monkeypatch, tmp_path):
    (tmp_path / "Rome.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AIGV2_LIBRARY_DB", str(tmp_path))
    deps = pipeline.default_deps()
    assert deps.library.root == tmp_path
    monkeypatch.delenv("AIGV2_LIBRARY_DB")
    assert pipeline.default_deps().library.root == Path("library_db_new")


# ---------- late-night arrival belongs to the night-of day ----------

BALI = Path(__file__).parent / "fixtures" / "bali"


def _bali_trip(check_in: date) -> TripPlan:
    trip = TripPlan.model_validate(json.loads((BALI / "trip_plan.json").read_text(encoding="utf-8")))
    trip.hotels[0].check_in = check_in
    return trip


def test_arrival_idx_late_night_answers():
    night, arrival_day = date(2026, 9, 24), date(2026, 9, 25)
    t24 = _bali_trip(night)
    assert pipeline._arrival_idx(t24, night) == 0
    assert pipeline._arrival_idx(t24, arrival_day) is None
    t25 = _bali_trip(arrival_day)
    assert pipeline._arrival_idx(t25, night) is None
    assert pipeline._arrival_idx(t25, arrival_day) == 0


def test_bali_late_night_arrival_pipeline(deps):
    store = RunStore.create(deps.backend)
    store.save_bytes("trip_plan.json", (BALI / "trip_plan.json").read_bytes())
    store.save_bytes("questions.json", (BALI / "questions.json").read_bytes())
    answers = json.loads((BALI / "answers.json").read_text(encoding="utf-8"))
    state = pipeline._plan(store, answers, deps)
    d1, d2 = state.days[0], state.days[1]
    assert d1.date == date(2026, 9, 24) and d1.arrival is not None and d1.result.meals == []
    assert d1.arrival_booking is not None and d1.arrival_booking.time == "23:00"
    assert d2.arrival is None and "breakfast" in [m.meal for m in d2.result.meals]
    text = "\n".join(m.text for d in state.days for m in d.result.markers)
    assert "Airport pick-up" not in text


# ---------- boat bookings as lunch-shifting legs; Bali change-over days ----------

def _boat_trip(bookings):
    trip = TripPlan.model_validate(json.loads((BALI / "trip_plan.json").read_text(encoding="utf-8")))
    trip.bookings = bookings
    return trip


def _bk(name, day, time_=None, instr=()):
    return Booking(name=name, day=day, time=time_, source="voucher", instructions=list(instr))


def test_boat_legs_parse_cases():
    d = date(2026, 9, 30)
    t = _boat_trip([
        _bk("Fast boat to Sanur", d, "10:30", ["Shared fast boat departs at 12:00 PM."]),
        _bk("Fast boat to Lembongan", d, "07:00", ["Shared fast boat departs Sanur Harbour at 09:15 AM."]),
        _bk("Ferry crossing", d, "08:00", ["Boat departs at 14:45"]),
        _bk("Boat transfer", d, "11:15", ["no time here"]),
        _bk("Boat transfer none", d, None, []),
        _bk("Museum tour", d, "12:00", ["Tour departs at 12:00"]),
        _bk("Fast boat other day", date(2026, 10, 1), "09:00", []),
    ])
    got = [(l.to_place, l.depart.time(), l.arrive, l.kind) for l in pipeline._boat_legs(t, d)]
    assert got == [("Fast boat to Sanur", time(12, 0), None, "boat"),
                   ("Fast boat to Lembongan", time(9, 15), None, "boat"),
                   ("Ferry crossing", time(14, 45), None, "boat"),
                   ("Boat transfer", time(11, 15), None, "boat")]


def test_bali_change_over_days_replay(deps):
    store = RunStore.create(deps.backend)
    for f in ("trip_plan.json", "questions.json", "places.json"):
        store.save_bytes(f, (BALI / f).read_bytes())
    answers = json.loads((BALI / "answers.json").read_text(encoding="utf-8"))
    state = pipeline._plan(store, answers, deps)
    by = {d.index: {m.meal: m for m in d.result.meals} for d in state.days}
    assert by[1] == {}
    assert by[5]["lunch"].anchors[0][0].startswith("D'NUSA BEACH CLUB")
    assert "lunch" not in by[7]
    assert by[7]["dinner"].anchors[0][0].startswith("TAKSU SANUR HOTEL")


def test_bali_day5_multicity_replay():
    import json
    from pathlib import Path
    from src.aigv2.models import TripPlan
    from src.aigv2.pipeline import _boat_legs, _day_view
    from src.aigv2.planning.slots import resolve_day_city, schedule_day
    base = Path("/Users/mjain/library_backups/aigv2_bali_2026-11-02/run_rebuild2")
    if not (base / "trip_plan.json").exists():
        pytest.skip("saved Bali run not available")
    trip = TripPlan.model_validate(json.loads((base / "trip_plan.json").read_text()))
    for dp in trip.days:
        dp.city = resolve_day_city(dp.city, dp.date, trip.hotels)
    assert [d.city for d in trip.days][4:] == ["Nusa Lembongan", "Nusa Lembongan", "Sanur", "Sanur"]
    raw = json.loads((base / "places.json").read_text())["places"]
    places = {k: Place.model_validate(v) if v else None for k, v in raw.items()}
    dp = trip.days[4]
    view = _day_view(trip, dp.date, dp.city, "Ubud", None, None, places)
    res = schedule_day(dp, trip.hotels, None, None, view, Settings(models={}), "Indonesia", False,
                       _boat_legs(trip, dp.date))
    anchors = {m.meal: [a[0] for a in m.anchors] for m in res.meals}
    print("DAY5 anchors", anchors)
    assert all("MAYURA" not in a.upper() for names in anchors.values() for a in names)


def test_boat_to_next_hotel_is_not_a_departure():
    d = [D0 + timedelta(days=i) for i in range(4)]
    trip = two_city_trip().model_copy(update={
        "hotels": [HotelStay(city="Ubud", hotel="A", check_in=d[0], check_out=d[1], source="voucher"),
                   HotelStay(city="Island", hotel="B", check_in=d[1], check_out=d[3], source="voucher")],
        "transport": [TransportLeg(kind="boat", from_place="Harbour", to_place="Island",
                                   depart=datetime(2027, 5, 11, 9, 15), source="t"),
                      TransportLeg(kind="flight", from_place="Airport", to_place="X",
                                   depart=datetime(2027, 5, 13, 13, 0), source="t")]})
    assert pipeline._departure_idx(trip, d[1], set(d)) is None
    assert pipeline._other_legs(trip, d[1], set()) == [0]
    assert pipeline._departure_idx(trip, d[3], set(d)) == 1


def _bali_rebuild4_days():
    from src.aigv2.planning.slots import resolve_day_city, schedule_day, parse_time
    base = Path("/Users/mjain/library_backups/aigv2_bali_2026-11-02/run_rebuild4")
    if not (base / "trip_plan.json").exists():
        pytest.skip("saved Bali run not available")
    trip = TripPlan.model_validate(json.loads((base / "trip_plan.json").read_text()))
    for dp in trip.days:
        dp.city = resolve_day_city(dp.city, dp.date, trip.hotels)
    raw = json.loads((base / "places.json").read_text())["places"]
    places = {k: Place.model_validate(v) if v else None for k, v in raw.items()}
    td = {d.date for d in trip.days}
    ordered = sorted(trip.days, key=lambda x: x.date)
    ends = {d.date: (pipeline._arrival_idx(trip, d.date), pipeline._departure_idx(trip, d.date, td)) for d in ordered}
    used = {i for pair in ends.values() for i in pair if i is not None}
    out, prev = {}, None
    for n, dp in enumerate(ordered, 1):
        arr, dep = ends[dp.date]
        view = pipeline._day_view(trip, dp.date, dp.city, prev, arr, dep, places)
        oth = pipeline._other_legs(trip, dp.date, used)
        bmap = pipeline._booking_map(trip, dp.items)
        out[n] = schedule_day(dp, trip.hotels, trip.transport[arr] if arr is not None else None,
                              trip.transport[dep] if dep is not None else None, view, Settings(models={}),
                              "Indonesia", False, [trip.transport[i] for i in oth] + pipeline._boat_legs(trip, dp.date),
                              {k: t for k, b in bmap.items() if (t := parse_time(b.end_time))})
        prev = dp.city
    return out


def test_bali_lunch_anchor_replay():
    res = _bali_rebuild4_days()
    lunch = lambda n: [a[0] for m in res[n].meals if m.meal == "lunch" for a in m.anchors]
    assert lunch(4) == ["Tirta Empul Temple"]
    assert lunch(6) and lunch(6)[0] != "Dream Beach"
    print("DAY6 lunch anchor", lunch(6), "DAY2", lunch(2))


def test_bali_day7_boat_order_and_no_car_leg():
    res = _bali_rebuild4_days()[7]
    names = [s.item.name for s in res.scheduled]
    assert names[0].startswith("Fast boat")
    assert names.index("Private transfer to Sanur for hotel check-in") < names.index("Shopping at ICON Mall/Sindhu Market")
    assert names.index("Shopping at ICON Mall/Sindhu Market") < names.index("Dinner in Sanur")
    boat_start = next(s.start for s in res.scheduled if s.item.name.startswith("Fast boat"))
    assert all(s.start >= boat_start for s in res.scheduled)


def test_boat_item_gets_boat_leg_not_car():
    from src.aigv2.planning.travel import leg_options
    leg = pipeline.boat_leg("Hotel", "Fast boat to X")
    assert leg_options(leg, ["private_driver"], 10) == []


def _placed_state(item_names, start=time(9, 0), kind="attraction"):
    from src.aigv2.models import PlannedItem
    from src.aigv2.planning.slots import ScheduledItem
    items = [ScheduledItem(item=PlannedItem(name=n, kind=kind, city="X"), slot="morning", start=start) for n in item_names]
    ds = pipeline.DayState(index=1, date=date(2026, 9, 25), city="X", result=pipeline.DayResult(scheduled=items))
    return ds


def _placed_bk(name, t=None):
    from src.aigv2.models import Booking
    return Booking(name=name, day=date(2026, 9, 25), time=t, source="voucher")


def test_tour_booking_is_placed_when_one_of_its_stops_is_in_the_day():
    ds = _placed_state(["Tegallalang Rice Terrace (Viewpoint & Scenic Cafe)", "Ubud Palace"])
    trip = day_trip()
    b = _placed_bk("Tegallalang Rice Terrace, Ubud Palace and Ubud Market tour", "13:00")
    assert pipeline._booking_placed(b, ds, trip)


def test_tour_booking_is_placed_by_matching_start_time():
    ds = _placed_state(["Yellow Bridge"], start=time(9, 0))
    assert pipeline._booking_placed(_placed_bk("Nusa Lembongan tour", "09:00"), ds, day_trip())


def test_genuinely_unplaced_booking_keeps_the_marker():
    ds = _placed_state(["Yellow Bridge"], start=time(9, 0))
    assert not pipeline._booking_placed(_placed_bk("Uffizi Skip-the-line", "10:00"), ds, day_trip())


def test_transfer_booking_consumed_by_a_transfer_item_is_placed():
    ds = _placed_state(["Hotel check-out and airport drop"], kind="transfer")
    assert pipeline._booking_placed(_placed_bk("TAKSU SANUR HOTEL to Bali Airport transfer"), ds, day_trip())


def test_saved_bali_trip_has_no_false_unplaced_markers():
    import json, os
    path = "/Users/mjain/library_backups/aigv2_bali_2026-11-02/run_rebuild8/plan.json"
    if not os.path.exists(path):
        pytest.skip("saved run not available")
    state = pipeline.PlanState.model_validate(json.load(open(path)))
    by_date = {d.date: d for d in state.days}
    assert all(pipeline._booking_placed(b, by_date[b.day], state.trip) for b in state.trip.bookings)


def test_day_facts_carry_google_address_of_each_stop():
    from src.aigv2.models import PlannedItem
    from src.aigv2.planning.slots import ScheduledItem
    trip = day_trip()
    d = trip.days[0]
    pl = Place(query="Blue Lagoon", place_id="p", name="Blue Lagoon", address="Ceningan Island, Bali", lat=1, lng=2,
               status="OPERATIONAL", maps_url="u", fetched_at=datetime(2026, 1, 1), match_ok=True)
    ds = pipeline.DayState(index=1, date=d.date, city=d.city, places={"Blue Lagoon": pl},
                           result=pipeline.DayResult(scheduled=[ScheduledItem(
                               item=PlannedItem(name="Blue Lagoon", kind="attraction", city=d.city),
                               slot="morning", start=time(9, 0))]))
    state = type("S", (), {"trip": trip, "picks": []})()
    facts = pipeline._day_facts(ds, state)
    assert facts["attractions"][0]["google_address"] == "Ceningan Island, Bali"


def test_airport_code_endpoint_is_searched_as_an_airport():
    class Rec:
        def __init__(self): self.q = []
        def find(self, name, city, near=None): self.q.append(name); return None
    c, places = Rec(), {}
    pipeline._endpoint("DPS", "Sanur", places, c)
    pipeline._endpoint("Ngurah Rai Airport", "Sanur", places, c)
    pipeline._endpoint("DPS", "Sanur", places, c)
    assert c.q == ["DPS airport", "Ngurah Rai Airport"] and "dps|sanur" in places


# ---------- guide.json ----------


def test_guide_json_saved(deps):
    from src.aigv2.guide.model import Guide
    store, _, _ = built(deps)
    assert store.has("guide.json")
    guide = Guide.model_validate(store.load_json("guide.json"))
    days = [p.title for p in guide.pages if p.kind == "day"]
    assert len(days) == 4
    assert days == day_headers(store.load_bytes("guide.docx"))


def test_guide_failure_does_not_break_build(deps, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("guide boom")
    monkeypatch.setattr("src.aigv2.pipeline.build_guide", boom)
    store, _, result = built(deps)
    assert result.docx_name.endswith(".docx")
    assert store.has("guide.docx") and not store.has("guide.json")
    assert "guide boom" in store.load_bytes("guide_error.txt").decode()


def test_regenerate_refreshes_guide_json(deps):
    from src.aigv2.guide.model import Guide
    store, _, _ = built(deps)
    store.delete("guide.json")
    regenerate(store, [2], [], deps)
    assert store.has("guide.json")
    Guide.model_validate(store.load_json("guide.json"))


def test_cli_guide_json(deps, monkeypatch):
    from src.aigv2.__main__ import app
    monkeypatch.setattr(pipeline, "default_deps", lambda: deps)
    store, _, _ = built(deps)
    out = CliRunner().invoke(app, ["guide-json", store.run_id])
    assert out.exit_code == 0, out.output
    assert Path(out.output.strip()).is_absolute() and Path(out.output.strip()).exists()
    store.delete("guide.json")
    out = CliRunner().invoke(app, ["guide-json", store.run_id])
    assert out.exit_code == 1 and "no guide.json" in out.output


def test_late_facts_for_bali_arrival():
    trip = _bali_trip(date(2026, 9, 24))
    arr = next(i for i, l in enumerate(trip.transport) if l.kind == "flight")
    pick = next(b for b in trip.bookings if b.time == "23:00")
    ds = SimpleNamespace(date=date(2026, 9, 24), arrival=arr, arrival_booking=pick)
    assert pipeline._late_facts(ds, trip) == {"lands_next_day": True, "driver_from": time(23, 0)}
    ds2 = SimpleNamespace(date=date(2026, 9, 25), arrival=None, arrival_booking=None)
    assert pipeline._late_facts(ds2, trip) == {"lands_next_day": False, "driver_from": None}


def test_boat_leg_facts():
    d = date(2026, 9, 28)
    t = _boat_trip([_bk("Transfer to Sanur Harbour and shared fast boat", d, "07:00",
                        ["Hotel check-in in Nusa Lembongan.", "Shared fast boat ETD 09:15 AM; check in at 08:15 AM."])])
    (leg,) = pipeline._boat_legs(t, d)
    assert leg.depart == datetime(2026, 9, 28, 9, 15) and leg.check_in == datetime(2026, 9, 28, 8, 15)
    assert leg.duration_min is None
    t.transport = [TransportLeg(kind="boat", from_place="Sanur Harbour", to_place="Nusa Lembongan",
                                depart=datetime(2026, 9, 28, 9, 15), source="voucher")]
    (got,) = enrich_boat_legs(t).transport
    assert got.check_in == datetime(2026, 9, 28, 8, 15) and got.duration_min is None


def test_boat_regex_helpers():
    assert parse_check_in(["Fast boat check-in at 08:15 AM."]) == "08:15 AM"
    assert parse_check_in(["Check in by 7.30 am"]) == "7.30 am"
    assert parse_check_in(["Hotel check-in at 2:00 PM"]) is None
    assert parse_check_in(["Be early"]) is None
    assert parse_crossing_min(["The crossing takes approx. 30 min."]) == 30
    assert parse_crossing_min(["Boat journey about 45 minutes"]) == 45
    assert parse_crossing_min(["Crossing takes 30-45 min"]) is None
    assert parse_crossing_min(["Boat departs at 09:15"]) is None
    assert parse_boat_type(["Shared fast boat ETD"]) == "Shared fast boat"
    assert parse_boat_type(["nothing"]) is None


def test_boat_pickup_leg_when_boat_is_a_day_leg(deps):
    d = [D0 + timedelta(days=i) for i in range(3)]
    trip = two_city_trip()
    trip.hotels = [HotelStay(city="Ubud", hotel="Ubud Retreat", check_in=d[0], check_out=d[1], source="voucher"),
                   HotelStay(city="Lembongan", hotel="Lembongan Resort", check_in=d[1], check_out=d[2], source="voucher")]
    trip.transport = [TransportLeg(kind="boat", from_place="Sanur Harbour", to_place="Lembongan",
                                   depart=datetime.combine(d[1], time(9, 15)), source="voucher"),
                       TransportLeg(kind="boat", from_place="Lembongan", to_place="Sanur Harbour",
                                    depart=datetime.combine(d[2], time(12, 0)), source="voucher")]
    trip.days = [DayPlan(date=x, title="x", city=c) for x, c in zip(d, ["Ubud", "Lembongan", "Lembongan"])]
    deps.places, deps.routes = CityPlaces(), RecordingRoutes()
    store = seeded(deps, trip)
    build_run(store, {}, deps)
    state = pipeline._load_plan(store)
    day = state.days[1]
    assert day.other_legs == [0] and "boat_pickup" in day.legs
    assert day.legs["boat_pickup"].to_name == "Sanur Harbour"
    minutes = day.legs["boat_pickup"].drive_min
    assert minutes
    from src.aigv2.guide import model as m
    from src.aigv2.guide.build import build_day_page
    from src.aigv2.render.document import RenderDay
    rd = RenderDay(index=2, date=day.date, city=day.city, text=pipeline.DayText(title="t", intro="i"),
                   result=day.result, legs=day.legs, places=day.places, prev_city=day.prev_city,
                   other_transport=[state.trip.transport[0]])
    data = pipeline.GuideData(trip=state.trip, title="T", days=[rd], sections={}, important=[],
                              trip_scope="international", modes=["taxi"], domestic=False)
    page = build_day_page(rd, data, SimpleNamespace(walk_max_min=10))
    strip = next(c for c in page.components if isinstance(c, m.JourneyStrip))
    assert strip.legs[0] == f"Approx. {minutes} min by car"


def test_crossing_minutes_ignores_road_lines():
    assert parse_crossing_min(["Drive to Sanur Harbour takes 60 min"]) is None
    assert parse_crossing_min(["Hotel transfer takes 45 minutes"]) is None
    assert parse_crossing_min(["The crossing takes about 35 min"]) == 35


def test_thanks_checkpointed(deps):
    store, answers, _ = built(deps)
    assert store.has("sections/thanks.json")
    assert store.load_json("sections/thanks.json")["sign_off"] == "With love,"
    assert len(steps(deps.llm, "thanks")) == 1
    build_run(store, answers, deps)
    assert len(steps(deps.llm, "thanks")) == 1


def test_new_renderer_flag(deps, monkeypatch):
    from src.aigv2.render2 import toc as render2_toc
    monkeypatch.setattr(render2_toc, "page_map", lambda *a, **k: {})
    deps.settings.renderer = "new"
    store, _, result = built(deps)
    doc = Document(io.BytesIO(store.load_bytes("guide.docx")))
    assert "Thank You" in [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]
    assert store.has("guide.json") and not store.has("guide_error.txt")


def test_old_renderer_default(deps):
    assert deps.settings.renderer == "old"
    store, _, _ = built(deps)
    assert day_headers(store.load_bytes("guide.docx"))


def test_load_settings_renderer_env(monkeypatch):
    from src.aigv2.config import load_settings
    monkeypatch.delenv("AIGV2_RENDERER", raising=False)
    assert load_settings().renderer == "old"
    monkeypatch.setenv("AIGV2_RENDERER", "NEW")
    assert load_settings().renderer == "new"
    monkeypatch.setenv("AIGV2_RENDERER", "bogus")
    assert load_settings().renderer == "old"


def test_cli_renderer_option(deps, tmp_path, monkeypatch):
    from src.aigv2.__main__ import app
    store, questions, answers = started(deps)
    ans = tmp_path / "answers.json"
    ans.write_text(json.dumps(answers), encoding="utf-8")
    monkeypatch.setattr(pipeline, "default_deps", lambda: deps)
    out = CliRunner().invoke(app, ["build", store.run_id, "--answers", str(ans), "--renderer", "bogus"])
    assert out.exit_code != 0 and "renderer" in out.output.lower()
    seen = []
    monkeypatch.setattr(pipeline, "build_run", lambda s, a, d: seen.append(d.settings.renderer) or (_ for _ in ()).throw(ValueError("stop")))
    CliRunner().invoke(app, ["build", store.run_id, "--answers", str(ans), "--renderer", "new"])
    assert seen == ["new"]


def test_item_windows_from_saved_bali_voucher():
    from datetime import time as _t
    base = Path(__file__).parent / "fixtures" / "bali" / "trip_plan.json"
    trip = TripPlan.model_validate(json.loads(base.read_text()))
    dp = next(d for d in trip.days if d.date == date(2026, 9, 25))
    w = pipeline._item_windows(trip, dp.date, dp.items)
    assert set(w) == {i.name for i in dp.items}
    assert set(w.values()) == {(_t(13, 0), _t(18, 0))}
    from src.aigv2.planning.slots import schedule_day
    res = schedule_day(dp, trip.hotels, None, None, {}, Settings(models={}), "Indonesia", False, (), {}, w)
    assert res.scheduled[0].start == _t(13, 0)
    assert all(_t(13, 0) <= s.start < _t(18, 0) for s in res.scheduled)
    assert all(m.start < _t(13, 0) for m in res.meals if m.meal == "lunch")


def test_booking_window_facts_shape():
    from datetime import time as _t
    f = pipeline.booking_window_facts((_t(9, 0), _t(16, 0)), True)
    assert f == {"start": "09:00", "end": "16:00", "hours": 7.0, "lunch_in_package": True,
                 "lunch_included": None}
    assert pipeline.booking_window_facts(None, False) is None


def test_default_deps_wires_overrides_in_library(tmp_path, monkeypatch):
    monkeypatch.setenv("AIGV2_LIBRARY_DB", str(tmp_path / "lib"))
    monkeypatch.setattr(pipeline, "default_backend", lambda s: LocalStorageBackend(tmp_path / "be"))
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    d = pipeline.default_deps()
    assert d.places.overrides.path == tmp_path / "lib" / "_place_overrides.json"
