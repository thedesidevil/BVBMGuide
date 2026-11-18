"""Lambda job path: a request records the job and fires a worker invocation; the worker runs it; any instance can poll."""
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.aigv2 import cancel, jobs, pipeline
from src.aigv2.store import RunStore
from src.library.ui import create_app
from src.library.ui.storage import LocalStorageBackend


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "fn")
    backend = LocalStorageBackend(tmp_path / "data")
    deps = SimpleNamespace(backend=backend)
    app = create_app(db_path=tmp_path / "lib")
    app.state.aigv2_deps = deps
    fired = []
    monkeypatch.setattr(jobs, "invoke_worker", lambda job_id: fired.append(job_id))
    return SimpleNamespace(client=TestClient(app), deps=deps, fired=fired, backend=backend)


def seed(env, run_id="20260101-000000-abc123"):
    store = RunStore(env.backend, run_id)
    store.save_json("trip_plan.json", {"client_names": ["A"], "days": [], "hotels": [], "transport": []})
    store.save_json("questions.json", {"questions": []})
    return store


def test_request_records_job_and_fires_worker_without_running_it(env, monkeypatch):
    seed(env)
    monkeypatch.setattr(pipeline, "build_run", lambda *a, **k: pytest.fail("must not run in the request"))
    r = env.client.post("/api/aigv2/runs/20260101-000000-abc123/build", json={"answers": {"q": "x"}})
    job = r.json()
    assert r.status_code == 200 and job["status"] == "queued" and env.fired == [job["id"]]
    assert env.backend.read_json(f"jobs/{job['id']}.spec.json")["answers"] == {"q": "x"}
    assert env.client.get(f"/api/aigv2/jobs/{job['id']}").json()["status"] == "queued"  # any instance can poll it


def test_second_job_is_refused_while_one_is_active(env):
    seed(env)
    assert env.client.post("/api/aigv2/runs/20260101-000000-abc123/build", json={"answers": {}}).status_code == 200
    assert env.client.post("/api/aigv2/runs/20260101-000000-abc123/build", json={"answers": {}}).status_code == 409


def test_worker_runs_job_and_releases_lock(env, monkeypatch):
    store = seed(env)
    monkeypatch.setattr(pipeline, "build_run", lambda s, a, d: SimpleNamespace(
        docx_name="g.docx", qc=SimpleNamespace(passed=True)))
    job_id = env.client.post(f"/api/aigv2/runs/{store.run_id}/build", json={"answers": {}}).json()["id"]
    jobs.run_worker(job_id, env.deps)
    j = env.client.get(f"/api/aigv2/jobs/{job_id}").json()
    assert j["status"] == "done" and j["result"] == {"docx_name": "g.docx", "passed": True}
    assert env.client.post(f"/api/aigv2/runs/{store.run_id}/build", json={"answers": {}}).status_code == 200


def test_worker_is_idempotent_against_duplicate_delivery(env, monkeypatch):
    store = seed(env)
    calls = []
    monkeypatch.setattr(pipeline, "build_run", lambda s, a, d: calls.append(1) or SimpleNamespace(
        docx_name="g", qc=SimpleNamespace(passed=True)))
    job_id = env.client.post(f"/api/aigv2/runs/{store.run_id}/build", json={"answers": {}}).json()["id"]
    jobs.run_worker(job_id, env.deps)
    jobs.run_worker(job_id, env.deps)  # Lambda delivered the event twice
    assert calls == [1]


def test_worker_failure_is_recorded(env, monkeypatch):
    store = seed(env)

    def boom(*a):
        raise RuntimeError("kaput")
    monkeypatch.setattr(pipeline, "build_run", boom)
    job_id = env.client.post(f"/api/aigv2/runs/{store.run_id}/build", json={"answers": {}}).json()["id"]
    jobs.run_worker(job_id, env.deps)
    j = env.client.get(f"/api/aigv2/jobs/{job_id}").json()
    assert j["status"] == "error" and "kaput" in j["error"]


def test_start_uploads_reach_the_worker(env, monkeypatch):
    seen = {}

    def fake_start(intake, paths, deps):
        seen["names"] = [p.name for p in paths]
        seen["data"] = [p.read_bytes() for p in paths]
        s = RunStore.create(deps.backend)
        return s, []
    monkeypatch.setattr(pipeline, "start_run", fake_start)
    r = env.client.post("/api/aigv2/start", files=[("attachments", ("a.pdf", b"PDF", "application/pdf"))])
    job_id = r.json()["id"]
    jobs.run_worker(job_id, env.deps)
    j = env.client.get(f"/api/aigv2/jobs/{job_id}").json()
    assert j["status"] == "done" and seen == {"names": ["a.pdf"], "data": [b"PDF"]} and j["run_id"]


def test_cancel_reaches_the_worker_through_the_flag(env, monkeypatch):
    store = seed(env)

    def slow(s, a, d):
        for _ in range(200):
            cancel.check()
            time.sleep(0.01)
    monkeypatch.setattr(pipeline, "build_run", slow)
    monkeypatch.setattr(cancel, "EXTERNAL_POLL_SECONDS", 0.0)
    job_id = env.client.post(f"/api/aigv2/runs/{store.run_id}/build", json={"answers": {}}).json()["id"]
    assert env.client.post(f"/api/aigv2/jobs/{job_id}/cancel").json()["cancelling"] is True
    jobs.run_worker(job_id, env.deps)
    assert env.client.get(f"/api/aigv2/jobs/{job_id}").json()["status"] == "cancelled"
    assert not cancel.is_set() or cancel.clear() is None


def test_stuck_jobs_are_reported_failed_and_free_the_lock(env):
    seed(env)
    job = jobs.new_job("build", "20260101-000000-abc123")
    job["status"], job["started_at"] = "running", (datetime.now(timezone.utc) - timedelta(seconds=2000)).isoformat()
    js = jobs.JobStore(env.backend)
    js.save(job)
    js.acquire(job)
    j = env.client.get(f"/api/aigv2/jobs/{job['id']}").json()
    assert j["status"] == "error" and "timed out" in j["error"]
    assert js.active() is None


def test_failed_invoke_does_not_leave_the_lock_held(env, monkeypatch):
    seed(env)

    def nope(job_id):
        raise PermissionError("not allowed to invoke")
    monkeypatch.setattr(jobs, "invoke_worker", nope)
    j = env.client.post("/api/aigv2/runs/20260101-000000-abc123/build", json={"answers": {}}).json()
    assert j["status"] == "error" and "not allowed" in j["error"]
    assert jobs.JobStore(env.backend).active() is None


def test_web_side_on_lambda_never_builds_the_library(tmp_path, monkeypatch):
    """A cold instance must answer list/start quickly: no library sync, no Google or model clients."""
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "fn")
    monkeypatch.setenv("AIGV2_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setattr(pipeline, "default_deps", lambda: pytest.fail("web side must not build the full deps"))
    monkeypatch.setattr(jobs, "invoke_worker", lambda job_id: None)
    app = create_app(db_path=tmp_path / "lib")
    c = TestClient(app)
    assert c.get("/api/aigv2/runs").json() == {"runs": []}
    r = c.post("/api/aigv2/start", files=[("attachments", ("a.pdf", b"PDF", "application/pdf"))])
    assert r.status_code == 200 and r.json()["status"] == "queued"
