import json

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from src.aigv2 import pipeline
from src.aigv2.google.maplink import MapLink
from src.aigv2.google.overrides import PlaceOverrides
from src.aigv2.pipeline import build_run, plan_run
from src.aigv2.plan_review import apply_plan_answers, meal_gaps, plan_items
from src.library.ui import create_app
from src.library.ui.api import aigv2 as api
from tests.aigv2.test_pipeline import FakePlaces, _place, answers_for, deps, started, FIX  # noqa: F401

LINK = "https://www.google.com/maps/place/Chez+Nous/@40.75,-73.98,17z/data=!3d40.7501!4d-73.9801"


class LinkPlaces(FakePlaces):
    def __init__(self, tmp_path):
        super().__init__()
        self.overrides = PlaceOverrides(tmp_path / "_place_overrides.json")
        self.override_hits = {}

    def from_link(self, link):
        return _place(link.name).model_copy(update={"maps_url": link.url})


def _gap(store, drop=1):
    """Plan once, then empty `drop` restaurants of the first meal slot into ADD RESTAURANT markers."""
    plan = store.load_json("plan.json")
    p = plan["picks"][0]
    text = f"{p['slot']['meal'].capitalize()}, Day {p['day_index']}, near Somewhere"
    removed = [r["lib"]["name"] for r in p["restaurants"][-drop:]]
    p["restaurants"] = p["restaurants"][:-drop]
    p["markers"] += [{"kind": "ADD_RESTAURANT", "text": text}] * drop
    plan["exclusions"] += [{"name": n, "reason": "no_match", "detail": f"{text}: no confident Google match"}
                           for n in ["Lib A", "Lib B", "Lib C", "Lib D"]]
    store.save_json("plan.json", plan)
    return p["day_index"], p["slot"]["meal"], removed


def _ids(state):
    return [g.id for g in meal_gaps(state)]


def _planned(deps, tmp_path):
    deps.places = LinkPlaces(tmp_path)
    deps.link_fetch = lambda u: LINK
    store, qs, answers = started(deps)
    plan_run(store, answers, deps)
    return store, answers


def test_gap_detection_and_items(deps, tmp_path):
    store, answers = _planned(deps, tmp_path)
    day, meal, _ = _gap(store)
    state = pipeline._load_plan(store)
    gaps = meal_gaps(state)
    gaps = [g for g in gaps if g.id.startswith(f"meal_gap:{day}:{meal}")]
    assert gaps[0].id == f"meal_gap:{day}:{meal}" and "Library suggests: Lib A, Lib B, Lib C" in gaps[0].text
    assert "Lib D" not in gaps[0].text and "only 2 of 3" in gaps[0].text
    items = [q for q in plan_items(state) if q.id == gaps[0].id]
    assert items[0].kind == "plan_gap" and items[0].options == ["Skip"]


def test_apply_url_adds_pick_and_clears_marker(deps, tmp_path):
    store, answers = _planned(deps, tmp_path)
    day, meal, _ = _gap(store)
    state = pipeline._load_plan(store)
    gid = f"meal_gap:{day}:{meal}"
    before = len(state.picks[0].restaurants)
    rep = apply_plan_answers(state, {gid: LINK}, deps.places, fetch=deps.link_fetch)
    assert not rep["failed"] and len(rep["applied"]) == 1
    p = state.picks[0]
    assert len(p.restaurants) == before + 1 and not [m for m in p.markers if m.kind == "ADD_RESTAURANT"]
    assert p.restaurants[-1].lib["source"] == "user_link" and p.restaurants[-1].place.maps_url == LINK
    assert deps.places.overrides.get("Chez Nous", state.days[0].city)
    assert gid not in _ids(state)


def test_skip_and_bad_link_keep_marker(deps, tmp_path):
    store, answers = _planned(deps, tmp_path)
    day, meal, _ = _gap(store)
    state = pipeline._load_plan(store)
    gid = f"meal_gap:{day}:{meal}"
    assert apply_plan_answers(state, {gid: "Skip"}, deps.places)["applied"] == []
    rep = apply_plan_answers(state, {gid: "https://example.com/x"}, deps.places)
    assert rep["applied"] == [] and "not a Google Maps link" in rep["failed"][0]

    def boom(u):
        raise OSError("down")
    rep = apply_plan_answers(state, {gid: "https://maps.app.goo.gl/T"}, deps.places, fetch=boom)
    assert "could not be used" in rep["failed"][0] and gid in _ids(state)


def test_plan_run_persists_and_build_uses_it(deps, tmp_path):
    store, answers = _planned(deps, tmp_path)
    day, meal, _ = _gap(store)
    gid = f"meal_gap:{day}:{meal}"
    items = plan_run(store, {**answers, gid: LINK}, deps)
    assert gid not in [q.id for q in items] and store.load_json("plan_review.json")["applied"]
    names = [r["lib"]["name"] for r in store.load_json("plan.json")["picks"][0]["restaurants"]]
    assert "Chez Nous" in names
    res = build_run(store, {**answers, gid: LINK}, deps)  # same plan answers: no double add
    assert res.docx_name
    names2 = [r["lib"]["name"] for r in store.load_json("plan.json")["picks"][0]["restaurants"]]
    assert names2.count("Chez Nous") == 1
    assert deps.llm.calls  # writing happened only at build


def test_build_without_plan_step_unchanged(deps):
    store, qs, answers = started(deps)
    res = build_run(store, answers, deps)
    assert res.docx_name and store.has("plan_review.json") and store.has("guide.docx")


def test_plan_run_does_not_write(deps):
    store, qs, answers = started(deps)
    plan_run(store, answers, deps)
    assert store.has("plan.json") and not store.has("guide.docx")
    assert not [s for s, _ in deps.llm.calls if s.startswith("write") or s == "title"]


def test_api_plan_endpoint(deps, tmp_path):
    store, qs, answers = started(deps)
    app = create_app(db_path=tmp_path / "lib2")
    app.state.aigv2_deps = deps
    api._JOBS.clear()
    c = TestClient(app)
    j = c.post(f"/api/aigv2/runs/{store.run_id}/plan", json={"answers": answers}).json()
    import time
    for _ in range(300):
        job = c.get(f"/api/aigv2/jobs/{j['id']}").json()
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    assert job["status"] == "done" and "questions" in job and job["result"]["run_id"] == store.run_id
    assert "plan_items" in c.get(f"/api/aigv2/runs/{store.run_id}").json()


def test_cli_plan_output(deps, tmp_path, monkeypatch):
    from src.aigv2 import __main__ as cli
    store, qs, answers = started(deps)
    plan_run(store, answers, deps)
    _gap(store)
    f = tmp_path / "a.json"
    f.write_text(json.dumps(answers))
    monkeypatch.setattr(pipeline, "default_deps", lambda: deps)
    out = CliRunner().invoke(cli.app, ["plan", store.run_id, "--answers", str(f)]).output
    assert "Needs attention (" in out and "meal_gap:" in out and "Library suggests" in out
