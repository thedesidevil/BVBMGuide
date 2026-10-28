import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "merge_legacy_library.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("merge_legacy_library", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _write(root: Path, key: str, data):
    p = root / key
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _read(root: Path, key: str):
    return json.loads((root / key).read_text(encoding="utf-8"))


def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def libs(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _write(new, "_index.json", {"_folder_coverage": {"Paris": ["Paris"]}, "_blocklist": []})
    _write(old, "_index.json", {"_folder_coverage": {"Paris": ["Paris", "Lyon"], "Rome": ["Rome"]}})
    return old, new


def run(mod, old, new, tmp_path, *extra):
    return mod.main(["--old", str(old), "--new", str(new), "--report", str(tmp_path / "r.md"), *extra])


def test_dedup_and_markers(mod, libs, tmp_path):
    old, new = libs
    _write(new, "Paris.json", {"restaurants": [{"name": "Le Cafe", "x": 1}], "source_files": []})
    _write(old, "Paris.json", {"restaurants": [
        {"name": "le cafe", "x": 2},
        {"name": "Chez Paul", "_source_file": "Paris/a.pdf", "_source_mtime": 1772384349.1, "rating": 4},
        {"name": "Chez Paul"},
    ], "source_files": []})
    assert run(mod, old, new, tmp_path, "--apply") == 0
    rs = _read(new, "Paris.json")["restaurants"]
    assert [r["name"] for r in rs] == ["Le Cafe", "Chez Paul"]
    assert rs[0] == {"name": "Le Cafe", "x": 1}
    added = rs[1]
    assert added["_legacy"] is True and added["_needs_verification"] is True
    assert added["_legacy_from"] == "library_db backup 2026-10-28"
    assert added["_legacy_shard"] == "Paris"
    assert added["_source_format"] == "old"
    assert added["_source_date"] == "2026-03-01"
    assert added["_source_file"] == "Paris/a.pdf" and added["_source_mtime"] == 1772384349.1
    assert added["rating"] == 4
    assert "_manual" not in added
    assert "_legacy_note" not in added


def test_source_date_null_and_manual_never_set(mod, libs, tmp_path):
    old, new = libs
    _write(new, "Paris.json", {"restaurants": [], "source_files": []})
    _write(old, "Paris.json", {"restaurants": [{"name": "A", "_manual": True}], "source_files": []})
    run(mod, old, new, tmp_path, "--apply")
    a = _read(new, "Paris.json")["restaurants"][0]
    assert a["_source_date"] is None and "_manual" not in a


def test_old_only_city_creates_shard_and_note(mod, libs, tmp_path):
    old, new = libs
    _write(new, "Paris.json", {"restaurants": [{"name": "Shared Spot"}], "source_files": []})
    _write(old, "lyon.json", {"restaurants": [{"name": "Shared Spot"}, {"name": "Bouchon"}], "source_files": []})
    run(mod, old, new, tmp_path, "--apply")
    d = _read(new, "Lyon.json")
    assert d["source_files"] == [] and d["hotels"] == [] and d["route_guides"] == []
    by = {r["name"]: r for r in d["restaurants"]}
    assert by["Shared Spot"]["_legacy_note"] == "same name also exists in Paris"
    assert "_legacy_note" not in by["Bouchon"]
    assert "same name" not in json.dumps(_read(new, "Paris.json"))


def test_city_name_matches_existing_shard_by_norm_key(mod, libs, tmp_path):
    old, new = libs
    _write(new, "Zürich.json", {"restaurants": [], "source_files": []})
    _write(old, "Zurich.json", {"restaurants": [{"name": "X"}], "source_files": []})
    run(mod, old, new, tmp_path, "--apply")
    assert not (new / "Zurich.json").exists()
    assert _read(new, "Zürich.json")["restaurants"][0]["name"] == "X"


def test_country_canonical_regional_and_multi(mod, libs, tmp_path):
    old, new = libs
    _write(new, "_country/Türkiye.json", {"tipping": [{"tip": "Existing"}]})
    _write(new, "_country/India.json", {"tipping": []})
    _write(new, "_country/Malaysia.json", {"safety_tips": []})
    _write(old, "_country/Turkey.json", {"safety_tips": [{"tip": "Drink bottled"}, {"tip": "Existing"}]})
    _write(old, "_country/North India.json", {"safety_tips": [{"tip": "Mind the heat"}]})
    _write(old, "_country/Singapore and Malaysia.json", {
        "safety_tips": [{"cities": ["Langkawi"], "tip": "L tip"}, {"cities": ["Singapore"], "tip": "S tip"},
                        {"cities": ["Atlantis"], "tip": "Odd tip"}, {"tip": "No city"}],
        "phrases": [{"city": "Penang", "english": "Hi", "local": "Hai"}],
    })
    run(mod, old, new, tmp_path, "--apply")
    tr = [t["tip"] for t in _read(new, "_country/Türkiye.json")["safety_tips"]]
    assert tr == ["Drink bottled", "Existing"]
    assert _read(new, "_country/India.json")["safety_tips"][0]["_legacy_shard"] == "_country/North India"
    my = _read(new, "_country/Malaysia.json")
    assert [t["tip"] for t in my["safety_tips"]] == ["L tip"]
    assert my["phrases"][0]["english"] == "Hi"
    sg = _read(new, "_country/Singapore.json")
    assert [t["tip"] for t in sg["safety_tips"]] == ["S tip"]
    assert sg["plugs"] == [] and sg["season_notes"] == []
    un = _read(new, "_country/Singapore and Malaysia.json")
    assert sorted(t["tip"] for t in un["safety_tips"]) == ["No city", "Odd tip"]
    assert not (new / "_country" / "North India.json").exists()
    assert not (new / "_country" / "Turkey.json").exists()


def test_blocklist_and_no_identity(mod, libs, tmp_path):
    old, new = libs
    _write(new, "_index.json", {"_folder_coverage": {}, "_blocklist": [
        {"city": "Paris", "list": "restaurants", "key": "bad place"},
        {"city": "_country/India", "list": "safety_tips", "key": "blocked tip"}]})
    _write(new, "Paris.json", {"restaurants": [], "source_files": []})
    _write(new, "_country/India.json", {"safety_tips": []})
    _write(old, "Paris.json", {"restaurants": [{"name": "Bad Place"}, {"rating": 5}, {"name": "Good"}],
                               "source_files": []})
    _write(old, "_country/Goa.json", {"safety_tips": [{"tip": "Blocked tip"}, {"tip": "ok"}]})
    run(mod, old, new, tmp_path, "--apply")
    assert [r["name"] for r in _read(new, "Paris.json")["restaurants"]] == ["Good"]
    assert [t["tip"] for t in _read(new, "_country/India.json")["safety_tips"]] == ["ok"]
    rep = (tmp_path / "r.md").read_text()
    assert "| restaurants | 3 | 0 | 1 | 1 | 1 |" in rep


def test_dry_run_writes_nothing_and_apply_idempotent(mod, libs, tmp_path):
    old, new = libs
    _write(new, "Paris.json", {"restaurants": [], "source_files": []})
    _write(old, "Paris.json", {"restaurants": [{"name": "A"}], "source_files": []})
    _write(old, "Lyon.json", {"restaurants": [{"name": "B"}], "source_files": []})
    before = _snapshot(new)
    assert run(mod, old, new, tmp_path) == 0
    assert _snapshot(new) == before
    assert (tmp_path / "r.md").exists()
    assert run(mod, old, new, tmp_path, "--apply") == 0
    after = _snapshot(new)
    assert after != before and "Lyon.json" in after
    assert run(mod, old, new, tmp_path, "--apply") == 0
    assert _snapshot(new) == after


def test_refusals(mod, libs, tmp_path, capsys):
    old, new = libs
    assert run(mod, old, old, tmp_path) == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run(mod, old, empty, tmp_path) == 1
    live = Path(mod.__file__).resolve().parents[1] / "library_db"
    assert run(mod, old, live, tmp_path) == 1
    assert run(mod, old, live / "_country", tmp_path) == 1
    assert "live" in capsys.readouterr().err


def test_index_coverage_union_keeps_existing(mod, libs, tmp_path):
    old, new = libs
    _write(new, "_index.json", {"_folder_coverage": {"Paris": ["Paris"], "Keep": ["Z"]},
                                "_blocklist": [], "_review_status": {"a": 1}, "_processed_files": {"f": {}}})
    _write(old, "_index.json", {"_folder_coverage": {"Paris": ["Paris", "Lyon"], "Rome": ["Rome"]},
                                "_processed_files": {"old": {}}})
    run(mod, old, new, tmp_path, "--apply")
    idx = _read(new, "_index.json")
    assert idx["_folder_coverage"] == {"Paris": ["Paris", "Lyon"], "Keep": ["Z"], "Rome": ["Rome"]}
    assert idx["_processed_files"] == {"f": {}} and idx["_review_status"] == {"a": 1}
