import io

import pytest
import requests
from datetime import time
from types import SimpleNamespace

from docx import Document
from docx.oxml.ns import qn

from src.aigv2.config import load_settings
from src.aigv2.llm import StepLLM
from src.aigv2.models import Finding
from src.aigv2.planning.meals import Exclusion
from src.aigv2.qc import run_qc
from src.aigv2.qc.annotate import annotate
from src.aigv2.qc.facts import check_facts
from src.aigv2.qc.llm_checks import prose_fact_check, sense_check
from src.aigv2.qc.reader import read_docx
from src.aigv2.qc.report import QCResult, build_cost, marker_kinds, write_report
from tests.aigv2.test_qc_rules import edit_text, library, render  # noqa: F401
from tests.aigv2.test_render_document import HOTEL, place, trip


class FakePlaces:
    def __init__(self, cached, fresh=None):
        self.cached, self.fresh_map = cached, fresh or {}
        self.calls = {"text_search": 0, "nearby": 0, "details": 0}
        self.fresh_calls = []
        self.fresh_searches = []

    def find(self, name, city, near=None, fresh=False):
        if fresh:
            self.calls["text_search"] += 1
            self.fresh_searches.append(name)
            return self.fresh_map.get(name, self.cached.get(name))
        return self.cached.get(name)

    def fresh_status(self, place):
        self.calls["details"] += 1
        self.fresh_calls.append(place.name)
        return self.fresh_map.get(place.name, place)


class FakeRoutes:
    def __init__(self, minutes=6):
        self.minutes = minutes
        self.calls = {"matrix_elements": 0, "directions": 0}

    def durations(self, origins, destinations, mode):
        self.calls["matrix_elements"] += 1
        return {(0, 0): self.minutes}


def late_place(name):
    p = place(name)
    p.hours.periods = {d: [(time(9), time(23))] for d in range(7)}
    return p


def cached_places(**overrides):
    names = [HOTEL, "Mikla", "Saray Muhallebicisi", "Galata Tower", "Balikci Sabahattin", "Ciya Sofrasi", "Hamdi",
             "Topkapi Palace", "Bosphorus Sunset Cruise", "Bosphorus Sunset Cruise"]
    return {n: late_place(n) for n in names} | overrides


def closed(name, status="CLOSED_PERMANENTLY"):
    p = place(name)
    p.status = status
    return p


def test_closed_venue_found_fresh():
    doc = read_docx(render())
    places = FakePlaces(cached_places(), {"Mikla": closed("Mikla")})
    findings, rows = check_facts(doc, trip(), places, FakeRoutes())
    assert [f.rule for f in findings if f.rule == "closed_now"] == ["closed_now"]
    assert "Mikla" in places.fresh_calls and places.fresh_searches == [] and places.calls["text_search"] == 0
    assert next(r for r in rows if r.venue == "Mikla").match is False
    _, rows = check_facts(doc, trip(), FakePlaces(cached_places(), {"Mikla": closed("Mikla")}), FakeRoutes(), fresh=False)
    assert all(r.match for r in rows if r.venue == "Mikla")


def test_travel_time_mismatch_and_rows():
    doc = read_docx(render())
    findings, rows = check_facts(doc, trip(), FakePlaces(cached_places()), FakeRoutes(minutes=20))
    assert any(f.rule == "travel_time_mismatch" and f.anchor_text == "Mikla" for f in findings)
    row = next(r for r in rows if r.venue == "Mikla")
    assert row.guide_travel == "Walk · 6 min" and row.google_travel == "Walk · 20 min" and row.link.startswith("https://")
    findings, rows = check_facts(doc, trip(), FakePlaces(cached_places()), FakeRoutes(minutes=7))
    assert not [f for f in findings if f.rule == "travel_time_mismatch"]


def test_not_open_at_slot():
    p = place("Mikla")
    p.hours.periods = {d: [(time(9), time(17))] for d in range(7)}
    findings, _ = check_facts(read_docx(render()), trip(), FakePlaces(cached_places(), {"Mikla": p}), FakeRoutes())
    assert any(f.rule == "not_open_at_slot" and f.anchor_text == "Mikla" for f in findings)


class FakeClient:
    def __init__(self, model, replies, calls):
        self.model = model
        self._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self._create)))
        self._replies, self._calls = replies, calls

    def _create(self, **kw):
        self._calls.append((self.model, kw["messages"][-1]["content"]))
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
        msg = SimpleNamespace(content=self._replies)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)


def fake_llm(reply, monkeypatch):
    for k in ("AI_MODEL_FAST", "AIGV2_MODEL_QC_SENSE", "AIGV2_MODEL_QC_PROSE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AI_MODEL", "gpt-6.1-sol")
    calls = []
    return StepLLM(load_settings(), client_factory=lambda m: FakeClient(m, reply, calls)), calls


def test_sense_check_uses_sol(monkeypatch):
    llm, calls = fake_llm('{"issues": [{"quote": "Galata Tower", "problem": "Check timing"}]}', monkeypatch)
    doc = read_docx(render())
    out = sense_check(doc, trip(), llm, {"q1": "yes"})
    assert [c[0] for c in calls] == ["gpt-6.1-sol"]
    assert "Pera Palace" in calls[0][1] and '"q1"' in calls[0][1]
    assert out[0].rule == "sense" and out[0].anchor_text == "Galata Tower" and out[0].day == 1


def test_prose_check_batches_on_luna(monkeypatch):
    llm, calls = fake_llm('{"issues": [{"quote": "A medieval stone tower.", "problem": "Date unverified"}]}', monkeypatch)
    doc = read_docx(render())
    out = prose_fact_check(doc, llm)
    assert len(calls) == 1 and calls[0][0] == "gpt-6-luna"
    assert "Galata Tower" in calls[0][1] and "Ottoman palace" in calls[0][1]
    assert out[0].rule == "prose_fact" and out[0].anchor_text == "A medieval stone tower."


def paras(data):
    body = Document(io.BytesIO(data)).element.body
    return ["".join(t.text or "" for t in p.iter(qn("w:t"))) for p in body.iter(qn("w:p"))]


def test_annotate_inserts_after_anchor():
    data = render()
    before = paras(data)
    target = next(t for t in before if "A medieval stone tower." in t)
    out = annotate(data, [Finding(rule="prose_fact", severity="error", message="Check the date",
                                  anchor_text="A medieval stone tower.", day=1)])
    after = paras(out)
    i = after.index(target)
    assert after[i + 1] == "⚠ CHECK: Check the date"
    assert [t for t in after if not t.startswith("⚠ CHECK: Check")] == before
    marker_p = list(Document(io.BytesIO(out)).element.body.iter(qn("w:p")))[i + 1]
    assert marker_p.find(".//" + qn("w:highlight")).get(qn("w:val")) == "yellow"


def test_annotate_falls_back_to_day_header():
    out = annotate(render(), [Finding(rule="sense", severity="error", message="Odd", anchor_text="not in doc", day=2)])
    after = paras(out)
    i = next(i for i, t in enumerate(after) if t.startswith("Day 2 – ") and after[i + 1].startswith("⚠ CHECK"))
    assert after[i + 1] == "⚠ CHECK: Odd"


def test_pass_requires_zero_markers():
    assert QCResult.build([], 0, []).passed is True
    assert QCResult.build([], 2, []).passed is False
    f = Finding(rule="x", severity="warning", message="m")
    assert QCResult.build([f], 0, []).passed is False


def test_report_lists_exclusions_and_cost():
    cost = build_cost([{"step": "qc_sense", "model": "gpt-6.1-sol", "usd": 0.1},
                       {"step": "qc_prose", "model": "gpt-6-luna", "usd": 0.01}],
                      {"text_search": 2, "nearby": 0, "matrix_elements": 4, "directions": 0})
    res = QCResult.build([Finding(rule="closed_now", severity="error", message="Mikla closed", day=1)], 1, [],
                         marker_kinds(["⚠ ADD RESTAURANT – x", "⚠ PRICE UNKNOWN"]))
    md, js = write_report(res, [Exclusion(name="Hamdi", reason="closed", detail="Google says closed")], cost)
    assert "**FAIL**" in md and "Hamdi (closed): Google says closed" in md
    assert "### Day 1" in md and "PRICE UNKNOWN: 1" in md and "## Cost" in md
    assert "gpt-6.1-sol" in md and "Places text search: 2" in md
    assert js["cost"]["total_usd"] == pytest.approx(0.11 + 2 * 0.035 + 4 * 0.005)
    assert js["exclusions"][0]["name"] == "Hamdi"


def test_run_qc_end_to_end(library, monkeypatch):  # noqa: F811
    llm, _ = fake_llm('{"issues": []}', monkeypatch)
    places, routes = FakePlaces(cached_places(), {"Mikla": closed("Mikla")}), FakeRoutes()
    data = render()
    out, result, report = run_qc(data, trip(), {}, library, places, routes, llm, [])
    assert result.passed is False and result.marker_count > 0
    assert any(f.rule == "closed_now" for f in result.findings)
    assert "⚠ CHECK: Mikla is shown as closed" in "\n".join(paras(out))
    assert result.cost["google"]["usd"] > 0 and result.cost["ai"]["usd"] >= 0
    assert "## Cost" in report and "Google total" in report


def rules_of(findings, name=None):
    return [f for f in findings if f.rule == "fact_unverified" and (name is None or f.anchor_text == name)]


def test_unverified_when_no_google_match():
    p = cached_places()
    del p["Mikla"]
    findings, rows = check_facts(read_docx(render()), trip(), FakePlaces(p), FakeRoutes())
    assert rules_of(findings, "Mikla")
    assert all(r.match is False and r.google_hours == "Not verified" for r in rows if r.venue == "Mikla")
    bad = place("Mikla", match_ok=False)
    findings, _ = check_facts(read_docx(render()), trip(), FakePlaces(cached_places(Mikla=bad)), FakeRoutes())
    assert rules_of(findings, "Mikla")


def test_unverified_when_fresh_lookup_empty_or_unmatched():
    class NoFresh(FakePlaces):
        def fresh_status(self, place):
            return None if place.name == "Mikla" else super().fresh_status(place)

    findings, rows = check_facts(read_docx(render()), trip(), NoFresh(cached_places()), FakeRoutes())
    assert rules_of(findings, "Mikla") and not next(r for r in rows if r.venue == "Mikla").match


def test_unverified_when_hours_or_status_unknown():
    nohours = place("Mikla", hrs=False)
    findings, rows = check_facts(read_docx(render()), trip(), FakePlaces(cached_places(), {"Mikla": nohours}),
                                 FakeRoutes())
    assert any("opening hours" in f.message for f in rules_of(findings, "Mikla"))
    assert not next(r for r in rows if r.venue == "Mikla").match
    unknown = late_place("Mikla")
    unknown.status = "UNKNOWN"
    findings, _ = check_facts(read_docx(render()), trip(), FakePlaces(cached_places(), {"Mikla": unknown}), FakeRoutes())
    assert any("business status" in f.message for f in rules_of(findings, "Mikla"))


def test_unverified_when_anchor_unresolved():
    p = cached_places()
    del p[HOTEL]
    findings, rows = check_facts(read_docx(render()), trip(), FakePlaces(p), FakeRoutes())
    assert any("could not locate" in f.message for f in rules_of(findings, "Mikla"))
    assert not next(r for r in rows if r.venue == "Mikla").match


def test_unverified_when_route_missing():
    class NoRoute(FakeRoutes):
        def durations(self, origins, destinations, mode):
            return {(0, 0): None}

    findings, rows = check_facts(read_docx(render()), trip(), FakePlaces(cached_places()), NoRoute())
    assert any("no Google route" in f.message for f in rules_of(findings, "Mikla"))
    assert not next(r for r in rows if r.venue == "Mikla").match


def test_unverified_when_guide_states_no_travel_leg():
    data = edit_text(render(), "GETTING THERE", "ELSEWHERE")
    findings, _ = check_facts(read_docx(data), trip(), FakePlaces(cached_places()), FakeRoutes())
    assert any("none stated" in f.message for f in rules_of(findings, "Mikla"))


def test_fully_verified_row_matches():
    _, rows = check_facts(read_docx(render()), trip(), FakePlaces(cached_places()), FakeRoutes())
    assert next(r for r in rows if r.venue == "Mikla").match is True


class RaisingPlaces(FakePlaces):
    def __init__(self, exc):
        super().__init__(cached_places())
        self.exc = exc

    def find(self, name, city, near=None, fresh=False):
        if name == "Mikla":
            raise self.exc
        return super().find(name, city, near, fresh)


@pytest.mark.parametrize("exc", [requests.ConnectionError("down"), KeyError("location"), ValueError("bad json")])
def test_fact_check_failed_surfaces(exc):
    findings, rows = check_facts(read_docx(render()), trip(), RaisingPlaces(exc), FakeRoutes())
    assert any(f.rule == "fact_check_failed" and f.anchor_text == "Mikla" for f in findings)
    assert not next(r for r in rows if r.venue == "Mikla").match


def test_qc_llm_failed_surfaces(library, monkeypatch):  # noqa: F811
    llm, _ = fake_llm("not json", monkeypatch)
    out, result, report = run_qc(render(), trip(), {}, library, FakePlaces(cached_places()), FakeRoutes(), llm, [])
    failed = [f for f in result.findings if f.rule == "qc_llm_failed"]
    assert len(failed) == 2 and result.passed is False


def test_annotate_scopes_to_day_and_stays_out_of_tables():
    data = render()
    out = annotate(data, [Finding(rule="sense", severity="error", message="Hotel transfer odd",
                                  anchor_text=HOTEL, day=3),
                          Finding(rule="sense", severity="error", message="Tower odd", anchor_text="Galata Tower")])
    body = Document(io.BytesIO(out)).element.body
    all_p = list(body.iter(qn("w:p")))
    texts = ["".join(t.text or "" for t in p.iter(qn("w:t"))) for p in all_p]
    for msg in ("⚠ CHECK: Hotel transfer odd", "⚠ CHECK: Tower odd"):
        mp = all_p[texts.index(msg)]
        assert mp.getparent() is body
    day3 = next(i for i, t in enumerate(texts) if t.startswith("Day 3 – ") and "Farewell" in t
                and all_p[i].find(".//" + qn("w:hyperlink")) is None)
    assert texts.index("⚠ CHECK: Hotel transfer odd") > day3
    assert texts.index("⚠ CHECK: Tower odd") < day3


def test_unfound_llm_anchor_attaches_to_day_header(monkeypatch):
    llm, _ = fake_llm('{"issues": [{"quote": "text the guide never says", "problem": "Odd", "day": 2}]}', monkeypatch)
    out = sense_check(read_docx(render()), trip(), llm)
    assert out[0].day == 2 and out[0].anchor_text == "text the guide never says"
    after = paras(annotate(render(), out))
    i = next(i for i, t in enumerate(after) if t == "⚠ CHECK: Odd")
    assert after[i - 1].startswith("Day 2 – ")


def test_sense_check_accepts_pydantic_answers(monkeypatch):
    llm, calls = fake_llm('{"issues": []}', monkeypatch)
    sense_check(read_docx(render()), trip(), llm, Finding(rule="x", severity="error", message="m"))
    assert '"rule": "x"' in calls[0][1]


def test_fresh_search_only_without_cached_place_id():
    p = cached_places()
    p["Mikla"] = p["Mikla"].model_copy(update={"place_id": ""})
    places = FakePlaces(p, {"Mikla": place("Mikla", match_ok=False)})
    findings, _ = check_facts(read_docx(render()), trip(), places, FakeRoutes())
    assert places.fresh_searches == ["Mikla"] and "Mikla" not in places.fresh_calls
    assert rules_of(findings, "Mikla")


def test_meal_checked_at_country_window():
    from src.aigv2.config import Settings
    p = late_place("Mikla")
    p.hours.periods = {d: [(time(9), time(21, 15))] for d in range(7)}
    s = Settings(models={}, country_meal_windows={"Turkey": {"dinner": ("21:00", "23:00")}})
    findings, _ = check_facts(read_docx(render()), trip(), FakePlaces(cached_places(Mikla=p)), FakeRoutes())
    assert not [f for f in findings if f.rule == "not_open_at_slot" and f.anchor_text == "Mikla"]
    findings, _ = check_facts(read_docx(render()), trip(), FakePlaces(cached_places(Mikla=p)), FakeRoutes(),
                              countries={"Istanbul": "Turkey"}, settings=s)
    hit = [f for f in findings if f.rule == "not_open_at_slot" and f.anchor_text == "Mikla"]
    assert hit and "21:00" in hit[0].message


def test_attraction_checked_at_booked_time():
    p = late_place("Topkapi Palace")
    p.hours.periods = {d: [(time(8), time(9, 45))] for d in range(7)}
    findings, _ = check_facts(read_docx(render()), trip(), FakePlaces(cached_places(**{"Topkapi Palace": p})),
                              FakeRoutes())
    hit = [f for f in findings if f.rule == "not_open_at_slot" and f.anchor_text == "Topkapi Palace"]
    assert hit and "10:00" in hit[0].message
