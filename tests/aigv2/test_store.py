from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from src.aigv2.config import Settings
from src.aigv2.models import Place
from src.aigv2.store import PlaceCache, RunStore, default_backend
from src.library.ui.storage import LocalStorageBackend


def _place(age_days: int) -> Place:
    return Place(
        query="Hotel X, Rome", place_id="pid1", name="Hotel X", address="1 Via Roma",
        lat=41.9, lng=12.5, status="OPERATIONAL", maps_url="https://example.com/m",
        fetched_at=datetime.now(timezone.utc) - timedelta(days=age_days), match_ok=True,
    )


class _M(BaseModel):
    a: int


def test_run_roundtrip(tmp_path):
    backend = LocalStorageBackend(tmp_path)
    run = RunStore.create(backend)
    assert not run.has("a.json")
    run.save_json("a.json", {"x": 1})
    run.save_json("m.json", _M(a=2))
    run.save_bytes("b.bin", b"abc")
    assert run.load_json("a.json") == {"x": 1}
    assert run.load_json("m.json") == {"a": 2}
    assert run.load_bytes("b.bin") == b"abc"
    assert run.load_json("nope.json") is None
    assert run.load_bytes("nope.bin") is None
    assert run.has("a.json")
    assert RunStore.list_runs(backend) == [run.run_id]
    assert len(run.run_id) == len("20260101-120000-abcdef")


def test_list_runs_newest_first(tmp_path):
    backend = LocalStorageBackend(tmp_path)
    for rid in ("20260101-000000-aaaaaa", "20260301-000000-bbbbbb"):
        RunStore(backend, rid).save_json("x.json", {})
    assert RunStore.list_runs(backend) == ["20260301-000000-bbbbbb", "20260101-000000-aaaaaa"]


def test_cache_fresh_and_stale(tmp_path):
    cache = PlaceCache(LocalStorageBackend(tmp_path), max_age_days=30)
    cache.put("fresh", _place(10))
    cache.put("stale", _place(31))
    assert cache.get("fresh") == _place(10).model_copy(update={"fetched_at": cache.get("fresh").fetched_at})
    assert cache.get("stale") is None
    assert cache.get("missing") is None


def test_cache_accepts_naive_as_utc(tmp_path):
    cache = PlaceCache(LocalStorageBackend(tmp_path), max_age_days=30)
    p = _place(1).model_copy(update={"fetched_at": (datetime.now(timezone.utc) - timedelta(days=1)).replace(tzinfo=None)})
    cache.put("k", p)
    assert cache.get("k") is not None


def test_cache_never_touches_library(tmp_path):
    backend = LocalStorageBackend(tmp_path)
    PlaceCache(backend, 30).put("k", _place(1))
    RunStore.create(backend).save_json("a.json", {})
    assert not [p for p in tmp_path.rglob("*") if "library_db" in str(p.relative_to(tmp_path))]


def test_default_backend(tmp_path):
    b = default_backend(Settings(models={}, data_root=tmp_path))
    assert isinstance(b, LocalStorageBackend) and b.base_path == tmp_path
