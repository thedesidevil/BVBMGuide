import threading
import time
from types import SimpleNamespace

import pytest

from src.aigv2 import cancel, pipeline
from src.aigv2.config import Settings
from src.aigv2.google.places import PlacesClient
from src.aigv2.google.routes import RoutesClient
from src.aigv2.llm import StepLLM
from src.library.ui.api import aigv2 as api
from tests.aigv2.test_ui_api import client, seed, wait  # noqa: F401

RID = "20260101-000000-abc123"


@pytest.fixture(autouse=True)
def _clear():
    cancel.clear()
    yield
    cancel.clear()


def test_token_checks_llm_and_google_paths():
    cancel.request()
    with pytest.raises(cancel.RunCancelled):
        StepLLM(Settings(models={"x": "m"}), client_factory=lambda m: None).run_json("x", "s", "p", object)

    class Sess:
        def post(self, *a, **k):
            raise AssertionError("HTTP issued after cancel")
        get = post
    with pytest.raises(cancel.RunCancelled):
        RoutesClient("k", session=Sess())._post("u", "m", {})
    pc = PlacesClient("k", cache=SimpleNamespace(), session=Sess())
    with pytest.raises(cancel.RunCancelled):
        pc._post("u", {}, "text_search")
    with pytest.raises(cancel.RunCancelled):
        pc.fresh_status(SimpleNamespace(place_id="p"))
    cancel.clear()
    cancel.check()


def test_cancel_running_job_ends_cancelled_and_releases_lock(client, monkeypatch):
    seed(client, built=False)
    started = threading.Event()

    def slow(store, answers, deps):
        started.set()
        for _ in range(500):
            cancel.check()
            time.sleep(0.01)

    monkeypatch.setattr(pipeline, "build_run", slow)
    j = client.post(f"/api/aigv2/runs/{RID}/build", json={"answers": {}}).json()
    assert started.wait(2)
    assert client.post(f"/api/aigv2/runs/{RID}/cancel").json()["cancelling"] is True
    done = wait(client, j["id"])
    assert done["status"] == "cancelled"
    assert client.get(f"/api/aigv2/runs/{RID}").json()["stage"] == "cancelled"
    assert api._RUN_LOCK.acquire(blocking=False)
    api._RUN_LOCK.release()
    # the flag is cleared at the next job start
    client.post(f"/api/aigv2/runs/{RID}/restore")
    monkeypatch.setattr(pipeline, "build_run", lambda s, a, d: SimpleNamespace(docx_name="x", qc=SimpleNamespace(passed=True)))
    assert wait(client, client.post(f"/api/aigv2/runs/{RID}/build", json={"answers": {}}).json()["id"])["status"] == "done"


def test_cancel_idle_run_409_and_restore(client, monkeypatch):
    store = seed(client, built=False)
    r = client.post(f"/api/aigv2/runs/{RID}/cancel").json()
    assert r["cancelling"] is False and not cancel.is_set()
    data = store.load_json("cancelled.json")
    assert data["spent_usd"] == 0.6 and data["stage"] == "started"
    assert client.get("/api/aigv2/runs").json()["runs"][0]["stage"] == "cancelled"
    for path in ("build", "plan", "regenerate"):
        resp = client.post(f"/api/aigv2/runs/{RID}/{path}", json={"answers": {}, "days": [1], "sections": []})
        assert resp.status_code == 409 and "cancelled" in resp.json()["detail"]
    assert client.post(f"/api/aigv2/runs/{RID}/qc", files={"file": ("a.docx", b"x")}).status_code == 409
    client.post(f"/api/aigv2/runs/{RID}/restore")
    assert not store.has("cancelled.json")
    monkeypatch.setattr(pipeline, "build_run", lambda s, a, d: SimpleNamespace(docx_name="x", qc=SimpleNamespace(passed=True)))
    assert client.post(f"/api/aigv2/runs/{RID}/build", json={"answers": {}}).status_code == 200


def test_cancel_start_job_by_job_id(client, monkeypatch):
    seed(client, built=False)

    def slow(intake, paths, deps):
        for _ in range(500):
            cancel.check()
            time.sleep(0.01)

    monkeypatch.setattr(pipeline, "start_run", slow)
    j = client.post("/api/aigv2/start", files=[("attachments", ("t.pdf", b"%PDF"))]).json()
    time.sleep(0.1)
    assert client.post(f"/api/aigv2/jobs/{j['id']}/cancel").json()["cancelling"] is True
    assert wait(client, j["id"])["status"] == "cancelled"


def test_cancelled_pipeline_keeps_cost(tmp_path):
    from tests.aigv2.test_pipeline import deps as _d  # noqa: F401
    store = SimpleNamespace()
    saved = {}

    class S:
        run_id = "r"
        def load_json(self, n): return saved.get(n)
        def save_json(self, n, d): saved[n] = d
    meter = SimpleNamespace(cost=lambda: {"total_usd": 1.5})

    def boom():
        raise cancel.RunCancelled("x")
    with pytest.raises(cancel.RunCancelled) as ei:
        pipeline._guarded(S(), meter, "build", boom)
    assert saved["cost.json"]["total_usd"] == 1.5 and ei.value.run_id == "r"
    assert saved["cost_history.json"]["runs"][0]["command"] == "build (cancelled)"


def test_duplicate_upload_names_are_kept(client, monkeypatch):
    store = seed(client, built=False)
    seen = {}

    def fake(intake, paths, deps):
        seen["names"] = [p.name for p in paths]
        seen["data"] = [p.read_bytes() for p in paths]
        return store, []
    monkeypatch.setattr(pipeline, "start_run", fake)
    files = [("attachments", ("itin.pdf", b"one")), ("attachments", ("itin.pdf", b"two")),
             ("attachments", ("itin.pdf", b"three"))]
    wait(client, client.post("/api/aigv2/start", files=files).json()["id"])
    assert seen["names"] == ["itin.pdf", "itin-2.pdf", "itin-3.pdf"] and seen["data"] == [b"one", b"two", b"three"]
