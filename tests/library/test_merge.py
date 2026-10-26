import copy
from datetime import date

import pytest

from src.library.ingest_core.merge import (
    FileMeta,
    MergeStats,
    merge_extraction,
    resolve_city_shard,
)
from src.library.ingest_core.prompt import CITY_LISTS, COUNTRY_LISTS


def _meta(name="italy/a.docx", d=date(2025, 1, 1), fmt="new", folder="italy"):
    return FileMeta(source_file=name, order_date=d, fmt=fmt, folder=folder)


def _rest(name, city="Rome", **kw):
    return {"name": name, "city": city, **kw}


def _data(**lists):
    return {"covered_cities": ["Rome"], "city_countries": {"Rome": "Italy"}, **lists}


# (a)
def test_newer_file_replaces_and_sets_replaced_from(memory_db):
    merge_extraction(memory_db, _data(restaurants=[_rest("Roscioli", hours="9-5")]),
                     _meta("italy/a.docx", date(2024, 1, 1)))
    stats = merge_extraction(memory_db, _data(restaurants=[_rest("Roscioli", hours="10-6")]),
                             _meta("italy/b.docx", date(2025, 1, 1)))
    shard = memory_db.get_city_data("Rome")
    assert len(shard["restaurants"]) == 1
    item = shard["restaurants"][0]
    assert item["hours"] == "10-6"
    assert item["_source_file"] == "italy/b.docx"
    assert item["_source_date"] == "2025-01-01"
    assert item["_source_format"] == "new"
    assert item["_replaced_from"] == "italy/a.docx"
    assert stats.replaced == 1 and stats.added == 0


# (b)
def test_old_format_after_new_format_is_skipped(memory_db):
    merge_extraction(memory_db, _data(restaurants=[_rest("Roscioli", hours="new")]),
                     _meta("italy/new.docx", date(2020, 1, 1), "new"))
    stats = merge_extraction(memory_db, _data(restaurants=[_rest("Roscioli", hours="old")]),
                             _meta("italy/old.docx", date(2026, 1, 1), "old"))
    assert stats.skipped_older == 1
    item = memory_db.get_city_data("Rome")["restaurants"][0]
    assert item["hours"] == "new"
    assert "_replaced_from" not in item


# (c)
def test_manual_item_untouched_and_conflict_recorded(memory_db):
    manual = {"name": "Roscioli", "city": "Rome", "hours": "hand", "_manual": True,
              "_manual_by": "marina", "_manual_at": "2026-01-01"}
    memory_db.save_city_data("Rome", {"restaurants": [manual]})
    stats = merge_extraction(memory_db, _data(restaurants=[_rest("Roscioli", hours="ai")]),
                             _meta("italy/b.docx"))
    shard = memory_db.get_city_data("Rome")
    assert shard["restaurants"] == [manual]
    assert stats.protected == 1
    assert len(shard["_conflicts"]) == 1
    c = shard["_conflicts"][0]
    assert c["list"] == "restaurants"
    assert c["key"] == "roscioli"
    assert c["incoming"]["hours"] == "ai"
    assert c["source_file"] == "italy/b.docx"


def test_manual_conflict_not_duplicated_on_rerun(memory_db):
    manual = {"name": "Roscioli", "city": "Rome", "hours": "hand", "_manual": True}
    memory_db.save_city_data("Rome", {"restaurants": [manual]})
    data = _data(restaurants=[_rest("Roscioli", hours="ai")])
    merge_extraction(memory_db, data, _meta("italy/b.docx"))
    merge_extraction(memory_db, data, _meta("italy/b.docx"))
    assert len(memory_db.get_city_data("Rome")["_conflicts"]) == 1


def test_manual_identical_content_records_no_conflict(memory_db):
    manual = {"name": "Roscioli", "city": "Rome", "hours": "x", "_manual": True}
    memory_db.save_city_data("Rome", {"restaurants": [manual]})
    stats = merge_extraction(memory_db, _data(restaurants=[_rest("Roscioli", hours="x")]),
                             _meta("italy/b.docx"))
    assert stats.protected == 1
    assert "_conflicts" not in memory_db.get_city_data("Rome")


# (d)
def test_same_file_twice_is_idempotent(memory_db, memory_backend):
    data = _data(
        restaurants=[_rest("Roscioli"), _rest("Armando")],
        safety_tips=[{"cities": ["Rome"], "tip": "Watch for pickpockets"}],
        country_content=[{"country": "Italy", "currency": "EUR",
                          "tipping": [{"tip": "Tipping is not expected"}]}],
    )
    s1 = merge_extraction(memory_db, copy.deepcopy(data), _meta())
    snapshot = dict(memory_backend.files)
    writes_before = len(memory_backend.writes)
    s2 = merge_extraction(memory_db, copy.deepcopy(data), _meta())
    assert memory_backend.files == snapshot
    assert s1.added == 4
    assert s2.unchanged == 4 and s2.added == 0 and s2.replaced == 0
    # nothing changed -> no shard written (index may not be written either)
    shard_writes = [k for k in memory_backend.writes[writes_before:] if k != "_index.json"]
    assert shard_writes == []


def test_same_file_changed_content_replaces_without_replaced_from(memory_db):
    merge_extraction(memory_db, _data(restaurants=[_rest("Roscioli", hours="a")]), _meta())
    stats = merge_extraction(memory_db, _data(restaurants=[_rest("Roscioli", hours="b")]), _meta())
    item = memory_db.get_city_data("Rome")["restaurants"][0]
    assert item["hours"] == "b"
    assert "_replaced_from" not in item
    assert stats.replaced == 1


# (e)
def test_city_name_variants_share_one_shard(memory_db):
    data = {
        "covered_cities": ["São Paulo"],
        "restaurants": [_rest("A", "São Paulo"), _rest("B", "Sao Paulo"), _rest("C", "sao paulo ")],
    }
    merge_extraction(memory_db, data, _meta())
    shards = memory_db.list_city_shards()
    assert shards == ["São Paulo"]
    assert len(memory_db.get_city_data("São Paulo")["restaurants"]) == 3
    assert resolve_city_shard(memory_db, "SAO PAULO") == "São Paulo"


def test_resolve_city_shard_new_name(memory_db):
    assert resolve_city_shard(memory_db, "  new   york ") == "New York"


# (f)
def test_blocklisted_item_not_added(memory_db):
    memory_db.set_blocklist([{"city": "Rome", "list": "restaurants", "key": "roscioli"}])
    stats = merge_extraction(memory_db, _data(restaurants=[_rest("Roscioli"), _rest("Armando")]),
                             _meta())
    names = [r["name"] for r in memory_db.get_city_data("Rome")["restaurants"]]
    assert names == ["Armando"]
    assert stats.blocked == 1 and stats.added == 1


# (g)
def test_multi_country_esim_lands_in_both_country_shards(memory_db):
    esim = {"provider": "Airalo", "kind": "esim", "coverage_countries": ["France", "Italy"]}
    data = {
        "covered_cities": ["Rome", "Paris"],
        "city_countries": {"Rome": "Italy", "Paris": "France"},
        "country_content": [
            {"country": "Italy", "connectivity_tips": [dict(esim)]},
            {"country": "France", "connectivity_tips": [dict(esim)]},
        ],
    }
    stats = merge_extraction(memory_db, data, _meta())
    for country in ("Italy", "France"):
        shard = memory_db.get_country_data(country)
        assert len(shard["connectivity_tips"]) == 1
        assert shard["connectivity_tips"][0]["provider"] == "Airalo"
        assert shard["connectivity_tips"][0]["_source_file"] == "italy/a.docx"
    assert stats.by_city["_country/Italy"]["added"] == 1
    assert stats.by_city["_country/France"]["added"] == 1


def test_country_name_variants_share_existing_shard(memory_db, memory_backend):
    merge_extraction(memory_db, {"country_content": [{"country": "Italy", "plugs": [{"type": "F"}]}]},
                     _meta())
    merge_extraction(memory_db, {"country_content": [{"country": "italy ", "plugs": [{"type": "L"}]}]},
                     _meta("italy/b.docx"))
    assert [k for k in memory_backend.files if k.startswith("_country/")] == ["_country/Italy.json"]
    assert len(memory_db.get_country_data("Italy")["plugs"]) == 2


# (h)
def test_currency_reaches_country_and_matching_city_shard(memory_db):
    data = {
        "covered_cities": ["Rome", "Paris"],
        "city_countries": {"Rome": "Italy", "Paris": "France"},
        "restaurants": [_rest("Roscioli"), _rest("Chez X", "Paris")],
        "country_content": [{"country": "Italy", "currency": "EUR"}],
    }
    merge_extraction(memory_db, data, _meta())
    assert memory_db.get_country_data("Italy")["currency"] == "EUR"
    assert memory_db.get_city_data("Rome")["currency"] == "EUR"
    assert "currency" not in memory_db.get_city_data("Paris")


def test_currency_older_file_does_not_overwrite(memory_db):
    def d(cur):
        return {"covered_cities": ["Rome"], "city_countries": {"Rome": "Italy"},
                "restaurants": [_rest("R")],
                "country_content": [{"country": "Italy", "currency": cur}]}
    merge_extraction(memory_db, d("EUR"), _meta("italy/new.docx", date(2025, 1, 1), "new"))
    merge_extraction(memory_db, d("ITL"), _meta("italy/old.docx", date(2026, 1, 1), "old"))
    assert memory_db.get_country_data("Italy")["currency"] == "EUR"
    assert memory_db.get_city_data("Rome")["currency"] == "EUR"


# (i)
def test_tip_items_with_same_normalised_text_dedupe(memory_db):
    data = _data(safety_tips=[
        {"cities": ["Rome", "Florence"], "tip": "Watch for pickpockets."},
        {"cities": ["Rome"], "tip": "watch for  PICKPOCKETS"},
    ])
    merge_extraction(memory_db, data, _meta())
    assert len(memory_db.get_city_data("Rome")["safety_tips"]) == 1
    assert len(memory_db.get_city_data("Florence")["safety_tips"]) == 1
    # a later file with the same normalised text replaces rather than adds
    stats = merge_extraction(memory_db, _data(safety_tips=[{"cities": ["Rome"], "tip": "WATCH FOR PICKPOCKETS"}]),
                             _meta("italy/b.docx", date(2026, 1, 1)))
    assert len(memory_db.get_city_data("Rome")["safety_tips"]) == 1
    assert stats.replaced == 1


# --- rulings and edge cases ---

def test_equal_rank_incoming_wins(memory_db):
    merge_extraction(memory_db, _data(restaurants=[_rest("R", hours="a")]),
                     _meta("italy/a.docx", None, "new"))
    stats = merge_extraction(memory_db, _data(restaurants=[_rest("R", hours="b")]),
                             _meta("italy/b.docx", None, "new"))
    assert stats.replaced == 1
    item = memory_db.get_city_data("Rome")["restaurants"][0]
    assert item["hours"] == "b" and item["_source_date"] is None


def test_older_date_same_format_is_skipped(memory_db):
    merge_extraction(memory_db, _data(restaurants=[_rest("R", hours="a")]),
                     _meta("italy/a.docx", date(2025, 6, 1)))
    stats = merge_extraction(memory_db, _data(restaurants=[_rest("R", hours="b")]),
                             _meta("italy/b.docx", date(2024, 6, 1)))
    assert stats.skipped_older == 1


def test_unprovenanced_existing_is_lowest_rank(memory_db):
    memory_db.save_city_data("Rome", {"restaurants": [{"name": "R", "city": "Rome", "hours": "legacy"}]})
    stats = merge_extraction(memory_db, _data(restaurants=[_rest("R", hours="b")]),
                             _meta("italy/b.docx", None, "old"))
    assert stats.replaced == 1
    item = memory_db.get_city_data("Rome")["restaurants"][0]
    assert item["hours"] == "b" and item["_replaced_from"] is None


def test_new_format_replaces_old_format_even_if_older_date(memory_db):
    merge_extraction(memory_db, _data(restaurants=[_rest("R", hours="old")]),
                     _meta("italy/old.docx", date(2026, 1, 1), "old"))
    stats = merge_extraction(memory_db, _data(restaurants=[_rest("R", hours="new")]),
                             _meta("italy/new.docx", date(2020, 1, 1), "new"))
    assert stats.replaced == 1


def test_empty_key_items_skipped(memory_db):
    stats = merge_extraction(memory_db, _data(restaurants=[{"city": "Rome", "hours": "x"}]), _meta())
    assert stats == MergeStats()
    assert memory_db.get_city_data("Rome") is None


def test_new_city_shard_shape_and_source_files(memory_db):
    merge_extraction(memory_db, _data(restaurants=[_rest("R")]), _meta())
    merge_extraction(memory_db, _data(restaurants=[_rest("R")]), _meta())
    shard = memory_db.get_city_data("Rome")
    for name in CITY_LISTS:
        assert isinstance(shard[name], list)
    assert shard["source_files"] == ["italy/a.docx"]


def test_new_country_shard_shape(memory_db):
    merge_extraction(memory_db, {"country_content": [{"country": "Italy", "plugs": [{"type": "F"}]}]},
                     _meta())
    shard = memory_db.get_country_data("Italy")
    for name in COUNTRY_LISTS:
        assert isinstance(shard[name], list)


def test_by_city_counts_and_iadd(memory_db):
    merge_extraction(memory_db, _data(restaurants=[_rest("R")]), _meta("italy/a.docx", date(2025, 1, 1)))
    stats = merge_extraction(memory_db, _data(restaurants=[_rest("R", hours="x"), _rest("S"),
                                                           _rest("T", "Florence")]),
                             _meta("italy/b.docx", date(2026, 1, 1)))
    assert stats.by_city["Rome"] == {"added": 1, "replaced": 1, "unchanged": 0,
                                     "skipped_older": 0, "protected": 0, "blocked": 0}
    assert stats.by_city["Florence"]["added"] == 1
    total = MergeStats()
    total += stats
    total += stats
    assert total.added == 4 and total.replaced == 2
    assert total.by_city["Rome"]["added"] == 2
    assert stats.by_city["Rome"]["added"] == 1  # iadd does not mutate the operand


def test_review_status_pending_for_changed_city_only(memory_db):
    memory_db.save_city_data("Paris", {"restaurants": []})
    memory_db.set_review_status("Paris", "reviewed", "marina")
    merge_extraction(memory_db, _data(restaurants=[_rest("R")]), _meta())
    status = memory_db.get_review_status()
    assert status["Rome"]["status"] == "pending"
    assert status["Paris"]["status"] == "reviewed"


def test_exception_mid_file_writes_nothing(memory_db, memory_backend, monkeypatch):
    import src.library.ingest_core.merge as merge_mod
    real = merge_mod.item_key
    calls = {"n": 0}

    def boom(list_name, item):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(list_name, item)

    monkeypatch.setattr(merge_mod, "item_key", boom)
    with pytest.raises(RuntimeError):
        merge_extraction(memory_db, _data(restaurants=[_rest("R"), _rest("S")]), _meta())
    assert memory_backend.files == {}


def test_db_helpers(memory_db, memory_backend):
    memory_db.save_city_data("Rome", {})
    memory_db.save_country_data("Italy", {})
    memory_backend.write_json("_audit.json", {})
    assert memory_db.list_city_shards() == ["Rome"]
    memory_db.add_folder_coverage("italy", ["Rome", "Florence"])
    memory_db.add_folder_coverage("italy", ["Rome", "Milan"])
    assert memory_db.get_folder_coverage()["italy"] == ["Rome", "Florence", "Milan"]
    memory_db.record_processed_file("italy/a.docx", {"text_hash": "h"})
    assert "_index.json" not in memory_backend.files
    memory_db.save_index()
    idx = memory_backend.read_json("_index.json")
    assert idx["_processed_files"]["italy/a.docx"] == {"text_hash": "h"}
    memory_db.set_blocklist([{"city": "Rome", "list": "restaurants", "key": "x"}])
    assert memory_db.get_blocklist() == [{"city": "Rome", "list": "restaurants", "key": "x"}]
    assert memory_backend.read_json("_index.json")["_blocklist"][0]["key"] == "x"


# --- fix round 1 ---

def test_same_file_new_order_date_refreshes_provenance(memory_db, memory_backend):
    data = _data(restaurants=[_rest("R", hours="a")])
    merge_extraction(memory_db, copy.deepcopy(data), _meta("italy/a.docx", date(2024, 1, 1)))
    before = len(memory_backend.writes)
    stats = merge_extraction(memory_db, copy.deepcopy(data), _meta("italy/a.docx", date(2025, 3, 4), "old"))
    item = memory_db.get_city_data("Rome")["restaurants"][0]
    assert item["_source_date"] == "2025-03-04"
    assert item["_source_format"] == "old"
    assert "_replaced_from" not in item
    assert stats.unchanged == 1 and stats.replaced == 0
    assert "Rome.json" in memory_backend.writes[before:]


def test_same_file_identical_meta_zero_writes(memory_db, memory_backend):
    data = _data(restaurants=[_rest("R", hours="a")])
    merge_extraction(memory_db, copy.deepcopy(data), _meta())
    before = len(memory_backend.writes)
    stats = merge_extraction(memory_db, copy.deepcopy(data), _meta())
    assert stats.unchanged == 1
    assert memory_backend.writes[before:] == []


def test_currency_never_creates_stub_city_shard(memory_db, memory_backend):
    data = {
        "covered_cities": ["Florence"],
        "city_countries": {"Firenze": "Italy"},
        "restaurants": [_rest("Za Za", "Florence")],
        "country_content": [{"country": "Italy", "currency": "EUR"}],
    }
    merge_extraction(memory_db, data, _meta())
    assert "Firenze.json" not in memory_backend.files
    assert "currency" not in memory_db.get_city_data("Florence")
    assert memory_db.get_country_data("Italy")["currency"] == "EUR"


def test_currency_reaches_existing_shard_via_name_variant(memory_db):
    memory_db.save_city_data("São Paulo", {"restaurants": []})
    data = {"city_countries": {"sao paulo": "Brazil"},
            "country_content": [{"country": "Brazil", "currency": "BRL"}]}
    merge_extraction(memory_db, data, _meta())
    assert memory_db.get_city_data("São Paulo")["currency"] == "BRL"
    assert memory_db.list_city_shards() == ["São Paulo"]


def test_currency_skips_city_whose_items_were_all_blocked(memory_db, memory_backend):
    memory_db.set_blocklist([{"city": "Rome", "list": "restaurants", "key": "r"}])
    merge_extraction(memory_db, _data(restaurants=[_rest("R")],
                                      country_content=[{"country": "Italy", "currency": "EUR"}]),
                     _meta())
    assert "Rome.json" not in memory_backend.files


def test_country_blocklist_entry_blocks_country_item(memory_db):
    memory_db.set_blocklist([
        {"city": "_country/Italy", "list": "tipping", "key": "tipping is not expected"},
        {"city": "Rome", "list": "restaurants", "key": "r"},
    ])
    stats = merge_extraction(memory_db, _data(
        restaurants=[_rest("R"), _rest("S")],
        country_content=[{"country": "italy", "tipping": [{"tip": "Tipping is not expected"},
                                                          {"tip": "Round up taxi fares"}]}],
    ), _meta())
    tips = [t["tip"] for t in memory_db.get_country_data("italy")["tipping"]]
    assert tips == ["Round up taxi fares"]
    assert stats.by_city["_country/italy"]["blocked"] == 1
    assert stats.by_city["Rome"]["blocked"] == 1
    assert stats.blocked == 2 and stats.added == 2


def test_tip_with_empty_cities_falls_back_to_city(memory_db):
    stats = merge_extraction(memory_db, _data(safety_tips=[
        {"cities": [], "city": "Rome", "tip": "Watch for pickpockets"},
        {"cities": ["  "], "city": "Rome", "tip": "Avoid unlicensed taxis"},
    ]), _meta())
    assert stats.added == 2
    assert len(memory_db.get_city_data("Rome")["safety_tips"]) == 2


def test_tip_with_no_usable_city_is_skipped(memory_db, memory_backend):
    stats = merge_extraction(memory_db, _data(safety_tips=[
        {"cities": [], "tip": "Watch for pickpockets"},
        {"cities": [" "], "city": "  ", "tip": "Avoid unlicensed taxis"},
    ]), _meta())
    assert stats == MergeStats()
    assert memory_backend.files == {}


def test_duplicate_key_within_one_file_first_wins_and_idempotent(memory_db, memory_backend):
    data = _data(restaurants=[_rest("Roscioli", hours="first"), _rest("roscioli", hours="second")])
    s1 = merge_extraction(memory_db, copy.deepcopy(data), _meta())
    shard = memory_db.get_city_data("Rome")
    assert [r["hours"] for r in shard["restaurants"]] == ["first"]
    assert s1.added == 1
    snapshot = dict(memory_backend.files)
    s2 = merge_extraction(memory_db, copy.deepcopy(data), _meta())
    assert memory_backend.files == snapshot
    assert s2.unchanged == 1 and s2.replaced == 0
