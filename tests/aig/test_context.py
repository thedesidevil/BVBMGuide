import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.aig.context import (
    CityLibraryData, AIGContext, build_context, write_back_to_library,
)
from src.common.models import TripFacts, TripHotel, TripDay


AMSTERDAM_DATA = {
    "restaurants": [{"name": "Pancake Bakery", "city": "Amsterdam", "nearby_landmarks": ["Anne Frank House"]}],
    "attractions": [{"name": "Anne Frank House", "city": "Amsterdam", "hours": "9:00 AM TO 10:00 PM"}],
    "local_dishes": [{"name": "Stroopwafel"}],
    "souvenirs": [{"item": "Delft pottery"}],
    "transport_options": [{"mode": "metro", "tip": "Use OV-chipkaart"}],
    "emergency_contacts": [],
    "phrases": [],
    "safety_tips": [],
    "connectivity_tips": [],
    "health_tips": [],
}

FACTS = TripFacts(
    client_names=["Ana"],
    destinations=["Amsterdam"],
    trip_start_date="2026-04-19",
    trip_end_date="2026-04-22",
    hotels=[TripHotel(city="Amsterdam", hotel_name="Hotel V")],
    days=[TripDay(day_number=1, activities=["Visit Anne Frank House"])],
)


class TestCityLibraryData:
    def test_loads_from_dict(self):
        data = CityLibraryData(city="Amsterdam", **{
            k: AMSTERDAM_DATA.get(k, []) for k in [
                "restaurants", "attractions", "local_dishes", "souvenirs",
                "transport_options", "emergency_contacts", "phrases",
                "safety_tips", "connectivity_tips", "health_tips",
            ]
        })
        assert len(data.restaurants) == 1
        assert len(data.attractions) == 1

    def test_defaults_to_empty_lists(self):
        data = CityLibraryData(city="Rome")
        assert data.restaurants == []
        assert data.phrases == []


class TestBuildContext:
    def test_loads_library_for_each_city(self):
        mock_db = MagicMock()
        mock_db.get_city_data.return_value = AMSTERDAM_DATA
        mock_ai = MagicMock()

        with patch("src.aig.context.LibraryDatabase", return_value=mock_db):
            ctx = build_context(FACTS, Path("library_db"), mock_ai)

        assert "Amsterdam" in ctx.library
        assert len(ctx.library["Amsterdam"].restaurants) == 1

    def test_missing_city_not_in_library(self):
        mock_db = MagicMock()
        mock_db.get_city_data.return_value = {}
        mock_ai = MagicMock()

        with patch("src.aig.context.LibraryDatabase", return_value=mock_db):
            ctx = build_context(FACTS, Path("library_db"), mock_ai)

        assert "Amsterdam" not in ctx.library

    def test_hotel_coords_empty_without_geocoding(self):
        mock_db = MagicMock()
        mock_db.get_city_data.return_value = AMSTERDAM_DATA
        mock_ai = MagicMock()

        with patch("src.aig.context.LibraryDatabase", return_value=mock_db):
            ctx = build_context(FACTS, Path("library_db"), mock_ai)

        assert ctx.hotel_coords == {}

    def test_facts_stored_on_context(self):
        mock_db = MagicMock()
        mock_db.get_city_data.return_value = {}
        mock_ai = MagicMock()

        with patch("src.aig.context.LibraryDatabase", return_value=mock_db):
            ctx = build_context(FACTS, Path("library_db"), mock_ai)

        assert ctx.facts.client_names == ["Ana"]


class TestWriteBackToLibrary:
    def test_writes_field_and_audit_entry(self, tmp_path):
        city_file = tmp_path / "Amsterdam.json"
        city_file.write_text(json.dumps({"restaurants": [], "phrases": []}))

        write_back_to_library(tmp_path, "Amsterdam", "phrases", ["Alsjeblieft"], "AI test")

        data = json.loads(city_file.read_text())
        assert data["phrases"] == ["Alsjeblieft"]
        assert len(data["_audit"]) == 1
        assert data["_audit"][0]["updated_by"] == "AI test"
        assert data["_audit"][0]["field"] == "phrases"

    def test_no_op_when_city_file_missing(self, tmp_path):
        write_back_to_library(tmp_path, "Nowhere", "phrases", ["Hello"], "AI test")
        # Should not raise

    def test_appends_to_existing_audit_log(self, tmp_path):
        city_file = tmp_path / "Rome.json"
        city_file.write_text(json.dumps({"_audit": [{"updated_by": "prior"}]}))

        write_back_to_library(tmp_path, "Rome", "health_tips", ["Stay hydrated"], "AI test 2")

        data = json.loads(city_file.read_text())
        assert len(data["_audit"]) == 2
