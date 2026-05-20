import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from docx import Document

from src.aig.folder_parser import FolderParser
from src.common.models import TripFacts


MINIMAL_FACTS_DICT = {
    "client_names": ["Ana"],
    "num_guests": "2 adults",
    "departure_city": "Mumbai",
    "destinations": ["Paris"],
    "trip_start_date": "2025-06-01",
    "trip_end_date": "2025-06-07",
    "hotels": [{"city": "Paris", "hotel_name": "Hotel Paris",
                "check_in": "2025-06-01", "check_out": "2025-06-07"}],
    "transport_modes": [{"from_city": "Mumbai", "to_city": "Paris",
                         "mode": "flight", "date": "2025-06-01"}],
    "days": [{"day_number": 1, "date": "2025-06-01", "title": "Arrival",
              "overnight_city": "Paris", "overnight_hotel": "Hotel Paris",
              "activities": ["Check-in"]}],
    "dietary_restrictions": [],
    "food_allergies": [],
    "cuisine_preferences": [],
}


@pytest.fixture
def mock_ai():
    client = MagicMock()
    client.complete.return_value = json.dumps(MINIMAL_FACTS_DICT)
    return client


@pytest.fixture
def parser(mock_ai):
    return FolderParser(ai_client=mock_ai)


class TestFindFiles:
    def test_finds_pdf_and_docx(self, tmp_path, parser):
        (tmp_path / "itinerary.pdf").write_bytes(b"fake")
        (tmp_path / "hotel.docx").write_bytes(b"fake")
        (tmp_path / "notes.txt").write_text("ignore")
        names = {f.name for f in parser._find_files(tmp_path)}
        assert "itinerary.pdf" in names
        assert "hotel.docx" in names
        assert "notes.txt" not in names

    def test_returns_sorted_by_name(self, tmp_path, parser):
        (tmp_path / "z_last.pdf").write_bytes(b"fake")
        (tmp_path / "a_first.pdf").write_bytes(b"fake")
        files = parser._find_files(tmp_path)
        assert files[0].name == "a_first.pdf"
        assert files[1].name == "z_last.pdf"

    def test_empty_folder_returns_empty_list(self, tmp_path, parser):
        assert parser._find_files(tmp_path) == []


class TestExtractText:
    def test_extract_docx_text(self, tmp_path, parser):
        doc = Document()
        doc.add_paragraph("Hello Amsterdam")
        doc.add_paragraph("Day 1: Arrival")
        path = tmp_path / "trip.docx"
        doc.save(str(path))
        text = parser._extract_text(path)
        assert text is not None
        assert "Hello Amsterdam" in text
        assert "Day 1: Arrival" in text

    def test_returns_none_on_corrupt_pdf(self, tmp_path, parser):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"not a real pdf")
        assert parser._extract_text(bad) is None

    def test_returns_none_on_nonexistent_file(self, tmp_path, parser):
        assert parser._extract_text(tmp_path / "ghost.pdf") is None
