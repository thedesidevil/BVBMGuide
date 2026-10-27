"""Per-country folder coverage for multi-country guides."""

from src.aigv2.library import Library
from src.aigv2.pipeline import _library_country
from src.library.ingest_core.clean import clean_extraction
from src.library.ingest_core.merge import country_coverage
from src.library.ui.services.db_service import LibraryDBService

from .test_entrypoints_parity import _ui_persist, _doc


def _two_country():
    return {
        "covered_cities": ["Zurich", "Rome"],
        "city_countries": {"Zurich": "Switzerland", "Rome": "Italy"},
        "restaurants": [{"name": "Kronenhalle", "city": "Zurich"},
                        {"name": "Roscioli", "city": "Rome"}],
    }


def test_two_countries_grouped_in_first_seen_order():
    assert country_coverage(_two_country()) == {"Switzerland": ["Zurich"], "Italy": ["Rome"]}


def test_single_country_guide_adds_nothing():
    data = {"covered_cities": ["Rome", "Florence"],
            "city_countries": {"Rome": "Italy", "Florence": "Italy"}}
    assert country_coverage(data) == {}


def test_city_without_country_is_skipped_only():
    data = _two_country()
    data["covered_cities"].append("Atlantis")
    assert country_coverage(data) == {"Switzerland": ["Zurich"], "Italy": ["Rome"]}


def test_aliases_count_as_one_country():
    data = {"covered_cities": ["Boston", "Miami"],
            "city_countries": {"Boston": "United States", "Miami": "USA"}}
    assert country_coverage(data) == {}
    data["covered_cities"].append("Rome")
    data["city_countries"]["Rome"] = "Italy"
    assert country_coverage(data) == {"USA": ["Boston", "Miami"], "Italy": ["Rome"]}


def test_city_match_is_case_tolerant_and_dedupes():
    data = {"covered_cities": ["zurich", "Zurich", "Rome"],
            "city_countries": {"Zurich": "Switzerland", "ROME": "Italy"}}
    assert country_coverage(data) == {"Switzerland": ["zurich"], "Italy": ["Rome"]}


def test_malformed_input_is_empty():
    assert country_coverage({}) == {}
    assert country_coverage({"covered_cities": "x", "city_countries": []}) == {}


def test_persist_records_country_coverage_idempotently(tmp_path, memory_backend):
    path = _doc(tmp_path / "trip.docx")
    _ui_persist(memory_backend, path, "Europe", _two_country())
    cov = memory_backend.read_json("_index.json")["_folder_coverage"]
    assert cov == {"Europe": ["Zurich", "Rome"], "Switzerland": ["Zurich"], "Italy": ["Rome"]}
    # same file again: a fresh service over the same backend, no duplicates
    _ui_persist(memory_backend, path, "Europe", _two_country())
    assert memory_backend.read_json("_index.json")["_folder_coverage"] == cov


def test_single_country_persist_adds_no_extra_entries(tmp_path, memory_backend):
    data = {"covered_cities": ["Rome"], "city_countries": {"Rome": "Italy"},
            "restaurants": [{"name": "Roscioli", "city": "Rome"}]}
    _ui_persist(memory_backend, _doc(tmp_path / "t.docx"), "Italy", data)
    assert memory_backend.read_json("_index.json")["_folder_coverage"] == {"Italy": ["Rome"]}


def test_clean_extraction_keeps_what_country_coverage_needs():
    cleaned, _ = clean_extraction(_two_country())
    assert country_coverage(cleaned) == {"Switzerland": ["Zurich"], "Italy": ["Rome"]}


def test_v2_library_resolves_known_country_over_continent(tmp_path, memory_backend):
    _ui_persist(memory_backend, _doc(tmp_path / "t.docx"), "Europe", _two_country())
    db = tmp_path / "db"
    from src.library.ui.storage import LocalStorageBackend
    local = LocalStorageBackend(db)
    for key in memory_backend.list_keys(""):
        local.write_json(key, memory_backend.read_json(key))
    library = Library(db)
    assert library.coverage()["Switzerland"] == ["Zurich"]
    assert _library_country(library, "Zurich") == "Switzerland"
    assert _library_country(library, "Rome") == "Italy"
