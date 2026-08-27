"""Tests for src/aig/prep.py — pure functions only."""
import json
from pathlib import Path
import pytest

from src.aig.prep import PrepContext, extract_trip_context, _build_prep_context_from_itinerary_data


# ---------------------------------------------------------------------------
# extract_trip_context: trip_facts.json path
# ---------------------------------------------------------------------------

def test_extract_from_trip_facts_json(tmp_path):
    """extract_trip_context loads trip_facts.json when it exists alongside the input file."""
    # Arrange
    docx_file = tmp_path / "input.docx"
    docx_file.write_bytes(b"fake")
    trip_facts = {
        "client_names": ["Alice"],
        "destinations": ["Paris", "Rome"],
        "trip_start_date": "2026-09-01",
        "trip_end_date": "2026-09-10",
        "hotels": [
            {"city": "Paris", "hotel_name": "Hotel Lutetia", "check_in": "2026-09-01", "check_out": "2026-09-05"},
            {"city": "Rome", "hotel_name": "Hotel Eden", "check_in": "2026-09-05", "check_out": "2026-09-10"},
        ],
        "local_transport": "Public Transport",
        "dietary_restrictions": ["vegetarian"],
        "food_allergies": [],
        "cuisine_preferences": ["Italian"],
        "transport_modes": [],
        "departure_city": None,
        "num_guests": 2,
        "days": [],
    }
    (tmp_path / "trip_facts.json").write_text(json.dumps(trip_facts), encoding="utf-8")

    # Act
    ctx = extract_trip_context(docx_file)

    # Assert
    assert ctx.client_name == "Alice"
    assert ctx.cities == ["Paris", "Rome"]
    assert ctx.date_range == "1 Sep 2026 – 10 Sep 2026"
    assert ctx.hotels == {"Paris": "Hotel Lutetia", "Rome": "Hotel Eden"}
    assert ctx.transport_mode == "Public Transport"
    assert "vegetarian" in ctx.dietary_notes
    assert "Italian" in ctx.dietary_notes


def test_extract_missing_optional_fields(tmp_path):
    """Missing optional fields yield empty strings / dicts, not errors."""
    docx_file = tmp_path / "input.docx"
    docx_file.write_bytes(b"fake")
    trip_facts = {
        "client_names": [],
        "destinations": ["Bali"],
        "trip_start_date": None,
        "trip_end_date": None,
        "hotels": [],
        "local_transport": None,
        "dietary_restrictions": [],
        "food_allergies": [],
        "cuisine_preferences": [],
        "transport_modes": [],
        "departure_city": None,
        "num_guests": None,
        "days": [],
    }
    (tmp_path / "trip_facts.json").write_text(json.dumps(trip_facts), encoding="utf-8")

    ctx = extract_trip_context(docx_file)

    assert ctx.client_name == ""
    assert ctx.cities == ["Bali"]
    assert ctx.date_range == ""
    assert ctx.hotels == {}
    assert ctx.dietary_notes == ""
    assert ctx.transport_mode == ""


def test_generate_library_context_known_city(tmp_path):
    """Known city with restaurants and local dishes renders correct markdown."""
    # Build a minimal library DB
    db = tmp_path / "library_db"
    db.mkdir()
    index = {
        "_folder_coverage": {"England and Scotland": ["London"]},
        "version": 1,
        "built_at": "2026-01-01",
        "_processed_files": [],
        "_review_status": {},
    }
    (db / "_index.json").write_text(json.dumps(index), encoding="utf-8")

    city_data = {
        "restaurants": [
            {
                "name": "Borough Market",
                "city": "London",
                "cuisine_type": ["Food market"],
                "area": "Borough",
                "hours": "Tue-Sat 10am-5pm",
                "vegetarian_friendly": False,
                "must_try_dishes": ["Oysters", "fish and chips"],
                "source_files": [],
            }
        ],
        "local_dishes": [
            {
                "name": "Fish and Chips",
                "city": "London",
                "description": "Classic British dish",
                "vegetarian": False,
                "where_to_try": "Pubs",
                "source_files": [],
            }
        ],
        "souvenirs": [],
        "transport_options": [],
        "safety_tips": [],
        "connectivity_tips": [],
        "emergency_contacts": [],
        "health_tips": [],
        "source_files": [],
    }
    (db / "London.json").write_text(json.dumps(city_data), encoding="utf-8")

    from src.aig.prep import generate_library_context

    ctx = PrepContext(
        client_name="Bhushan",
        destination_label="London",
        cities=["London"],
        date_range="28 Jun 2026 – 4 Jul 2026",
        hotels={"London": "Hilton Kensington"},
        dietary_notes="vegetarian",
        transport_mode="Public Transport",
    )

    result = generate_library_context(ctx, db)

    assert "# BVM Library Context: London" in result
    assert "## London, United Kingdom" in result
    assert "Borough Market" in result
    assert "Fish and Chips" in result
    # Souvenirs section is empty → should not appear
    assert "Souvenir Shopping" not in result


def test_generate_library_context_unknown_city(tmp_path):
    """City not in library emits a placeholder note."""
    db = tmp_path / "library_db"
    db.mkdir()
    (db / "_index.json").write_text(json.dumps({
        "_folder_coverage": {},
        "version": 1, "built_at": "", "_processed_files": [], "_review_status": {},
    }), encoding="utf-8")

    from src.aig.prep import generate_library_context

    ctx = PrepContext(
        client_name="Silky",
        destination_label="Mussoorie",
        cities=["Mussoorie"],
        date_range="",
        hotels={},
        dietary_notes="",
        transport_mode="",
    )

    result = generate_library_context(ctx, db)

    assert "## Mussoorie" in result
    assert "No BVM library data available" in result


def test_client_profile_full():
    """All fields populated: no [fill in] placeholders except optional ones."""
    from src.aig.prep import generate_client_profile

    ctx = PrepContext(
        client_name="Bhushan",
        destination_label="London",
        cities=["London"],
        date_range="28 Jun 2026 – 4 Jul 2026",
        hotels={"London": "Hilton Kensington"},
        dietary_notes="vegetarian, chicken, seafood",
        transport_mode="Public Transport",
    )

    result = generate_client_profile(ctx)

    assert "# Client Profile: Bhushan" in result
    assert "28 Jun 2026 – 4 Jul 2026" in result
    assert "Hilton Kensington" in result
    assert "vegetarian, chicken, seafood" in result
    assert "Public Transport" in result
    # Manual fields still present
    assert "[fill in" in result


def test_client_profile_sparse():
    """Missing fields show [fill in] for dietary and transport."""
    from src.aig.prep import generate_client_profile

    ctx = PrepContext(
        client_name="",
        destination_label="Mussoorie",
        cities=["Mussoorie"],
        date_range="",
        hotels={},
        dietary_notes="",
        transport_mode="",
    )

    result = generate_client_profile(ctx)

    assert "Mussoorie" in result
    # All variable fields fall back to [fill in]
    assert result.count("[fill in") >= 4


def test_run_prep_writes_two_files(tmp_path):
    """run_prep writes library_context.md and client_profile.md."""
    from src.aig.prep import run_prep

    # Set up minimal library DB
    db = tmp_path / "library_db"
    db.mkdir()
    (db / "_index.json").write_text(json.dumps({
        "_folder_coverage": {}, "version": 1, "built_at": "",
        "_processed_files": [], "_review_status": {},
    }), encoding="utf-8")

    # Set up input file with sibling trip_facts.json
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    docx_file = input_dir / "notes.docx"
    docx_file.write_bytes(b"fake")
    trip_facts = {
        "client_names": ["Naren"],
        "destinations": ["Lima"],
        "trip_start_date": "2026-10-01",
        "trip_end_date": "2026-10-08",
        "hotels": [{"city": "Lima", "hotel_name": "Pullman Lima", "check_in": None, "check_out": None}],
        "local_transport": None,
        "dietary_restrictions": [],
        "food_allergies": [],
        "cuisine_preferences": [],
        "transport_modes": [],
        "departure_city": None,
        "num_guests": 1,
        "days": [],
    }
    (input_dir / "trip_facts.json").write_text(json.dumps(trip_facts), encoding="utf-8")

    context_path, profile_path = run_prep(docx_file, db, output_dir=tmp_path / "out")

    assert context_path.exists()
    assert profile_path.exists()
    assert context_path.name.endswith("_library_context.md")
    assert profile_path.name.endswith("_client_profile.md")
    assert "Lima" in context_path.read_text(encoding="utf-8")
    assert "Naren" in profile_path.read_text(encoding="utf-8")
