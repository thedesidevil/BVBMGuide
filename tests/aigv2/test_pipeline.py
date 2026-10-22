import copy
import io
import json
import re
from datetime import datetime, time
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from typer.testing import CliRunner

from src.aigv2 import pipeline
from src.aigv2.config import STEPS, Settings
from src.aigv2.library import Library
from src.aigv2.llm import StepLLM
from src.aigv2.models import Place, WeeklyHours
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
        self.calls = {"text_search": 0, "nearby": 0}

    def find(self, name, city, near=None, fresh=False):
        self.calls["text_search"] += 1
        return _place(name)

    def nearby(self, lat, lng, types, radius_m, max_results, city=None):
        self.calls["nearby"] += 1
        return [_place(f"{types[0]} {i}", i) for i in range(2)]


class FakeRoutes:
    def __init__(self):
        self.calls = {"matrix_elements": 0, "directions": 0}

    def durations(self, origins, destinations, mode):
        self.calls["matrix_elements"] += len(origins) * len(destinations)
        return {(i, j): 5 for i in range(len(origins)) for j in range(len(destinations))}

    def transit_steps(self, origin, destination):
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
        "title": f"Exploring {facts['city']}", "intro": "We take it gently today.",
        "attractions": [{"name": a["name"], "description": "A favorite of ours."} for a in facts["attractions"]],
        "restaurants": [{"name": r["name"], "ambience": "Relaxed", "best_for": "Families"} for r in facts["restaurants"]],
        "free_time_idea": None})


REPLIES = {
    "extract": lambda p: (FIX / "expected_trip_plan.json").read_text(encoding="utf-8"),
    "rank": _rank,
    "write_days": _day,
    "write_sections": lambda p: json.dumps({"items": [{"heading": "Good to know", "body": "Plan ahead and enjoy."}]}),
    "title": lambda p: json.dumps({"title": "Manhattan Lights Ahead"}),
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
    assert set(unit) == {"text_search", "nearby", "route_element"}
    for api in ("text_search", "nearby", "route_element"):
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
