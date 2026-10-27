"""Golden-set harness: recorded extraction -> clean -> merge -> asserted items.

Every ``golden/<name>.extraction.json`` with a sibling ``<name>.expected.json``
is a case. No model calls. Zero real pairs is fine; only the synthetic pair
ships, real pairs recorded from the pilot just drop into ``golden/``.

``expected.json``: ``meta`` (FileMeta fields), ``present`` / ``absent``
(``{shard: {list: [item_key, ...]}}``, shard = city name or ``_country/<Country>``),
optional ``currency`` (``{shard: code}``) and ``dropped_reasons`` (exact counts).
"""

import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from src.library.ingest_core.clean import clean_extraction
from src.library.ingest_core.identity import item_key
from src.library.ingest_core.merge import FileMeta, merge_extraction

GOLDEN_DIR = Path(__file__).parent / "golden"


def discover(root: Path = GOLDEN_DIR) -> list[tuple[str, Path, Path]]:
    pairs = []
    for ext in sorted(Path(root).glob("*.extraction.json")):
        name = ext.name[: -len(".extraction.json")]
        exp = ext.with_name(f"{name}.expected.json")
        if exp.exists():
            pairs.append((name, ext, exp))
    return pairs


def _shard(db, name: str) -> dict:
    if name.startswith("_country/"):
        return db.get_country_data(name[len("_country/"):]) or {}
    return db.get_city_data(name) or {}


def _keys(shard: dict, list_name: str) -> set[str]:
    return {item_key(list_name, i) for i in shard.get(list_name, []) if isinstance(i, dict)}


def run_case(ext: Path, exp: Path, db) -> list[str]:
    """Run one pair against ``db``; return a list of problems (empty = pass)."""
    data = json.loads(ext.read_text(encoding="utf-8"))
    expected = json.loads(exp.read_text(encoding="utf-8"))
    m = expected["meta"]
    meta = FileMeta(source_file=m["source_file"],
                    order_date=date.fromisoformat(m["order_date"]) if m.get("order_date") else None,
                    fmt=m["fmt"], folder=m["folder"])
    cleaned, dropped = clean_extraction(data)
    merge_extraction(db, cleaned, meta)

    problems = []
    for shard_name, lists in expected.get("present", {}).items():
        shard = _shard(db, shard_name)
        for list_name, keys in lists.items():
            missing = sorted(set(keys) - _keys(shard, list_name))
            if missing:
                problems.append(f"missing in {shard_name}/{list_name}: {missing}")
    for shard_name, lists in expected.get("absent", {}).items():
        shard = _shard(db, shard_name)
        for list_name, keys in lists.items():
            unexpected = sorted(set(keys) & _keys(shard, list_name))
            if unexpected:
                problems.append(f"unexpected in {shard_name}/{list_name}: {unexpected}")
    for shard_name, code in expected.get("currency", {}).items():
        got = _shard(db, shard_name).get("currency")
        if got != code:
            problems.append(f"currency of {shard_name}: expected {code!r}, got {got!r}")
    if "dropped_reasons" in expected:
        got = dict(Counter(d["reason"] for d in dropped))
        if got != expected["dropped_reasons"]:
            problems.append(f"dropped reasons: expected {expected['dropped_reasons']}, got {got}")
    return problems


_PAIRS = discover()
_PARAMS = [pytest.param(e, x, id=n) for n, e, x in _PAIRS] or [
    pytest.param(None, None, id="no-golden-pairs",
                 marks=pytest.mark.skip(reason="no golden pairs recorded yet"))]


@pytest.mark.parametrize("ext,exp", _PARAMS)
def test_golden_pair(memory_db, ext, exp):
    problems = run_case(ext, exp, memory_db)
    assert not problems, "golden mismatch:\n  " + "\n  ".join(problems)


def test_harness_finds_synthetic_pair():
    assert "synthetic_a" in {n for n, _, _ in discover()}


def test_empty_golden_folder_discovers_nothing(tmp_path):
    assert discover(tmp_path) == []
    (tmp_path / "lonely.extraction.json").write_text("{}")  # no expected file
    assert discover(tmp_path) == []


def test_harness_reports_missing_and_unexpected(memory_db, tmp_path):
    ext = tmp_path / "x.extraction.json"
    exp = tmp_path / "x.expected.json"
    ext.write_text(json.dumps({"covered_cities": ["Testville"],
                               "restaurants": [{"name": "Cafe Dummy", "city": "Testville"}]}))
    exp.write_text(json.dumps({
        "meta": {"source_file": "x.docx", "order_date": None, "fmt": "old", "folder": "F"},
        "present": {"Testville": {"restaurants": ["nope"]}},
        "absent": {"Testville": {"restaurants": ["cafe dummy"]}},
        "dropped_reasons": {"marker": 2}}))
    problems = run_case(ext, exp, memory_db)
    assert len(problems) == 3
    assert any("missing" in p for p in problems) and any("unexpected" in p for p in problems)
