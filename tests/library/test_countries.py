import json
from datetime import date

import pytest

from src.aigv2.library import Library
from src.library.ingest_core.countries import canonical_country
from src.library.ingest_core.merge import FileMeta, merge_extraction
from src.library.ui.services.db_service import LibraryDBService
from src.library.ui.storage import LocalStorageBackend


@pytest.mark.parametrize("raw,want", [
    ("United States", "USA"), ("United States of America", "USA"), ("US", "USA"), (" usa ", "USA"),
    ("United Kingdom", "UK"), ("England", "UK"), ("Scotland", "UK"), ("Great Britain", "UK"),
    ("UAE", "United Arab Emirates"), ("Turkey", "Türkiye"), ("Turkiye", "Türkiye"),
    ("Republic of Korea", "South Korea"), ("Korea", "South Korea"), ("Czech Republic", "Czechia"),
    ("Holland", "Netherlands"), ("Viet Nam", "Vietnam"), ("Burma", "Myanmar"),
    ("Italy", "Italy"), ("  Narnia ", "Narnia"), ("", ""),
])
def test_canonical_country(raw, want):
    assert canonical_country(raw) == want


def _meta():
    return FileMeta(source_file="f/a.docx", order_date=date(2025, 1, 1), fmt="new", folder="f")


@pytest.fixture
def db(tmp_path):
    return LibraryDBService(LocalStorageBackend(tmp_path))


@pytest.mark.parametrize("raw,lookup", [
    ("United States", ["USA"]), ("Turkey", ["Türkiye"]), ("United Kingdom", ["UK"]),
    ("UAE", ["United Arab Emirates"]), ("Korea", ["South Korea"]),
])
def test_v2_library_resolves_merged_country(db, tmp_path, raw, lookup):
    merge_extraction(db, {"country_content": [{"country": raw, "currency": "XXX",
                                               "tipping": [{"tip": "Fake tip"}]}]}, _meta())
    for name in lookup:
        assert Library(tmp_path).country(name)["tipping"][0]["tip"] == "Fake tip"
    assert len(list((tmp_path / "_country").glob("*.json"))) == 1


def test_two_aliases_land_in_same_shard(db, tmp_path):
    merge_extraction(db, {"country_content": [{"country": "United States", "tipping": [{"tip": "a"}]}]}, _meta())
    merge_extraction(db, {"country_content": [{"country": "USA", "tipping": [{"tip": "b"}]}]}, _meta())
    assert [p.stem for p in (tmp_path / "_country").glob("*.json")] == ["USA"]
    assert len(Library(tmp_path).country("USA")["tipping"]) == 2


def test_blocklist_with_alias_key_still_blocks(db, tmp_path):
    db.set_blocklist([{"city": "_country/United States", "list": "tipping", "key": "fake tip"}])
    s = merge_extraction(db, {"country_content": [{"country": "United States",
                                                   "tipping": [{"tip": "Fake tip"}]}]}, _meta())
    assert s.blocked == 1 and s.added == 0


def test_city_countries_currency_copy_uses_canonical(db):
    db.save_city_data("Rome", {"restaurants": []})
    merge_extraction(db, {"city_countries": {"Rome": "Turkey"},
                          "country_content": [{"country": "Türkiye", "currency": "TRY"}]}, _meta())
    assert db.get_city_data("Rome")["currency"] == "TRY"
