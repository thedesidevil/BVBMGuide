import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_library_for_v2.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("check_library_for_v2", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _db(tmp_path, countries: dict, coverage: dict | None = None, cities: dict | None = None):
    (tmp_path / "_country").mkdir()
    for name, data in countries.items():
        (tmp_path / "_country" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "_index.json").write_text(json.dumps({"_folder_coverage": coverage or {}}), encoding="utf-8")
    for name, data in (cities or {}).items():
        (tmp_path / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


FULL = {"currency": "EXA", "tipping": [{"tip": "t"}], "money": [{"tip": "m"}],
        "connectivity_tips": [{"provider": "P", "kind": "sim"}]}


def test_country_with_content_shows_tick_and_exits_0(check, tmp_path, capsys):
    db = _db(tmp_path, {"Examplia": FULL}, {"Examplia": ["Testville"]},
             {"Testville": {"local_dishes": [{"name": "Fake Stew"}]}})
    assert check.main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "Examplia" in out and "✓" in out and "–" in out


def test_gap_folder_without_country_shard_is_reported_but_exit_0(check, tmp_path, capsys):
    db = _db(tmp_path, {"Examplia": FULL}, {"Examplia": ["Testville"], "Lostland": ["Nowhere"]})
    assert check.main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "Lostland" in out and "no country" in out.lower()


def test_empty_or_missing_db_exits_1(check, tmp_path):
    assert check.main(["--db", str(tmp_path / "missing")]) == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    assert check.main(["--db", str(empty)]) == 1


def test_unreadable_shard_exits_1(check, tmp_path):
    db = _db(tmp_path, {"Examplia": FULL})
    (db / "_index.json").write_text("{not json", encoding="utf-8")
    assert check.main(["--db", str(db)]) == 1


def test_strict_exits_1_for_empty_country_shard(check, tmp_path):
    db = _db(tmp_path, {"Examplia": FULL, "Hollowland": {}})
    assert check.main(["--db", str(db)]) == 0
    assert check.main(["--db", str(db), "--strict"]) == 1
