import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.aigv2 import pipeline
from src.aigv2.store import RunStore
from src.library.ui import create_app
from src.library.ui.api import aigv2 as api
from src.library.ui.storage import LocalStorageBackend

COST = {"ai": {"total_usd": 0.5, "by_step": {}}, "google": {"total_usd": 0.1, "by_api": {}}, "total_usd": 0.6}


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = create_app(db_path=tmp_path / "lib")
    app.state.aigv2_deps = SimpleNamespace(backend=LocalStorageBackend(tmp_path / "data"))
    api._JOBS.clear()
    return TestClient(app)


def seed(client, run_id="20260101-000000-abc123", built=True):
    store = RunStore(client.app.state.aigv2_deps.backend, run_id)
    store.save_json("trip_plan.json", {"client_names": ["A", "B"], "days": [], "hotels": [], "transport": [],
                                       "trip_scope": "international"})
    store.save_json("questions.json", {"questions": [{"id": "q1", "kind": "k", "text": "Pick?", "options": ["x"]}]})
    store.save_json("cost.json", COST)
    if built:
        store.save_bytes("guide.docx", b"DOCX")
        store.save_json("qc_report.json", {"passed": True, "findings": []})
        store.save_bytes("inputs/secret.pdf", b"x")
    return store


def wait(client, job_id):
    for _ in range(100):
        j = client.get(f"/api/aigv2/jobs/{job_id}").json()
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_list_and_get_run(client):
    seed(client)
    runs = client.get("/api/aigv2/runs").json()["runs"]
    assert runs[0]["title"] == "A & B" and runs[0]["stage"] == "built" and runs[0]["google_usd"] == 0.1
    r = client.get("/api/aigv2/runs/20260101-000000-abc123").json()
    assert r["cost"]["total_usd"] == 0.6 and "guide.docx" in r["files"]
    assert not any(f.startswith("inputs/") for f in r["files"])
    assert client.get("/api/aigv2/runs/missing").status_code == 404
    assert client.get("/api/aigv2/runs/bad%0A").status_code in (400, 404)


def test_file_download_is_whitelisted(client):
    seed(client)
    ok = client.get("/api/aigv2/runs/20260101-000000-abc123/files/guide.docx")
    assert ok.status_code == 200 and ok.content == b"DOCX"
    for name in ("../../../etc/passwd", "nope.docx", "%2e%2e/trip_plan.json"):
        assert client.get(f"/api/aigv2/runs/20260101-000000-abc123/files/{name}").status_code == 404


def test_build_job_success_and_single_job_rule(client, monkeypatch):
    seed(client, built=False)
    gate = {"go": False}

    def fake_build(store, answers, deps):
        while not gate["go"]:
            time.sleep(0.01)
        return SimpleNamespace(docx_name="x.docx", qc=SimpleNamespace(passed=True))

    monkeypatch.setattr(pipeline, "build_run", fake_build)
    first = client.post("/api/aigv2/runs/20260101-000000-abc123/build", json={"answers": {"q1": "x"}}).json()
    assert client.post("/api/aigv2/runs/20260101-000000-abc123/build", json={"answers": {}}).status_code == 409
    gate["go"] = True
    done = wait(client, first["id"])
    assert done["status"] == "done" and done["result"]["docx_name"] == "x.docx"


def test_failed_job_reports_partial_cost_and_questions(client, monkeypatch):
    seed(client, built=False)

    def boom(store, answers, deps):
        e = RuntimeError("model exploded")
        e.run_cost, e.run_id = COST, store.run_id
        raise e

    monkeypatch.setattr(pipeline, "build_run", boom)
    j = wait(client, client.post("/api/aigv2/runs/20260101-000000-abc123/build", json={"answers": {}}).json()["id"])
    assert j["status"] == "error" and "RuntimeError" in j["error"] and j["cost"]["total_usd"] == 0.6

    q = pipeline.Question(id="q1", kind="k", text="Pick?")
    monkeypatch.setattr(pipeline, "build_run", lambda *a: (_ for _ in ()).throw(pipeline.UnansweredQuestions([q])))
    j = wait(client, client.post("/api/aigv2/runs/20260101-000000-abc123/build", json={"answers": {}}).json()["id"])
    assert j["status"] == "error" and j["questions"][0]["id"] == "q1"


def test_start_requires_input_and_runs(client, monkeypatch):
    assert client.post("/api/aigv2/start").status_code == 400
    assert client.post("/api/aigv2/start", files={"intake": ("a.txt", b"x")}).status_code == 400
    store = seed(client, built=False)
    monkeypatch.setattr(pipeline, "start_run", lambda intake, paths, deps: (store, [1, 2]))
    j = wait(client, client.post("/api/aigv2/start", files=[("attachments", ("trip.pdf", b"%PDF"))]).json()["id"])
    assert j["status"] == "done" and j["result"] == {"run_id": store.run_id, "questions": 2}


def test_template_download(client):
    r = client.get("/api/aigv2/template")
    assert r.status_code == 200 and r.content[:2] == b"PK"
