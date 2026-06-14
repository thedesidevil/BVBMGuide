import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.aig.context import AIGContext, CityLibraryData
from src.aig.day_builder import (
    _match_attraction,
    _is_cruise_day,
    _city_matches,
    _filter_sectionable,
    _extract_meal_location,
    _build_flight_details,
    build_day,
)
from src.common.models import TripFacts, TripDay, TripHotel, TransportLeg


AMSTERDAM_LIBRARY = CityLibraryData(
    city="Amsterdam",
    attractions=[
        {"name": "Anne Frank House", "hours": "9:00 AM TO 10:00 PM",
         "entry_fee": "€16", "recommended_duration": "2 hours"},
        {"name": "Rijksmuseum", "hours": "9 AM – 6 PM",
         "entry_fee": "€22", "recommended_duration": "2-3 hours"},
    ],
    restaurants=[
        {"name": "Pancake Bakery", "nearby_landmarks": ["Anne Frank House"],
         "area": "Jordaan", "hours": "9am-8:30pm", "vegetarian_friendly": True,
         "must_try_dishes": ["Dutch pancake"], "cuisine_type": ["Dutch"]},
        {"name": "Broodje Bert", "nearby_landmarks": ["Rijksmuseum"],
         "area": "Museumplein", "hours": "11am-9pm", "vegetarian_friendly": False,
         "must_try_dishes": ["Broodje"], "cuisine_type": ["Dutch"]},
    ],
)

FACTS = TripFacts(
    client_names=["Ana"],
    destinations=["Amsterdam"],
    trip_start_date="2026-04-19",
    trip_end_date="2026-04-22",
    local_transport="Public Transport",
    hotels=[TripHotel(city="Amsterdam", hotel_name="Hotel V Nesplein")],
    days=[TripDay(
        day_number=1,
        date="2026-04-19",
        title="Amsterdam Highlights",
        overnight_city="Amsterdam",
        overnight_hotel="Hotel V Nesplein",
        activities=[
            "Visit Anne Frank House",
            "Walk to Rijksmuseum",
            "Return to hotel to freshen up",
            "Evening stroll at Vondelpark",
            "Early dinner near Museumplein",
        ],
    )],
    dietary_restrictions=[],
    food_allergies=[],
)


class TestMatchAttraction:
    def test_exact_name_match(self):
        result = _match_attraction("Anne Frank House", AMSTERDAM_LIBRARY.attractions)
        assert result is not None
        assert result["hours"] == "9:00 AM TO 10:00 PM"

    def test_partial_name_match(self):
        result = _match_attraction("Visit Anne Frank House", AMSTERDAM_LIBRARY.attractions)
        assert result is not None
        assert result["name"] == "Anne Frank House"

    def test_no_match_returns_none(self):
        result = _match_attraction("Some Unknown Place", AMSTERDAM_LIBRARY.attractions)
        assert result is None


class TestIsCruiseDay:
    def test_overnight_city_none_is_cruise(self):
        day = TripDay(day_number=8, activities=["At Sea | Enjoy Cruise"], overnight_city=None)
        assert _is_cruise_day(day) is True

    def test_city_with_hotel_is_not_cruise(self):
        day = TripDay(day_number=1, activities=["Check in"], overnight_city="Amsterdam")
        assert _is_cruise_day(day) is False

    def test_at_sea_in_title_is_cruise(self):
        day = TripDay(day_number=9, activities=["At Sea | Relax"], overnight_city=None,
                      title="At Sea | Relax Day")
        assert _is_cruise_day(day) is True

    def test_canal_cruise_is_not_cruise_day(self):
        day = TripDay(day_number=1, activities=["Evening Canal Cruise"], overnight_city="Amsterdam")
        assert _is_cruise_day(day) is False


class TestCityMatches:
    def test_exact_match(self):
        assert _city_matches("Amsterdam", "Amsterdam") is True

    def test_case_insensitive(self):
        assert _city_matches("amsterdam", "Amsterdam") is True

    def test_partial_terminal_name(self):
        assert _city_matches("Amsterdam Schiphol", "Amsterdam") is True

    def test_no_match(self):
        assert _city_matches("Paris", "Amsterdam") is False

    def test_empty_strings(self):
        assert _city_matches("", "Amsterdam") is False


class TestFilterSectionable:
    def test_removes_arrival_activities(self):
        activities = ["Arrival and hotel check-in", "Visit Rijksmuseum"]
        result = _filter_sectionable(activities)
        assert result == ["Visit Rijksmuseum"]

    def test_removes_meal_activities(self):
        activities = ["Visit Rijksmuseum", "Lunch near canal", "Evening stroll"]
        result = _filter_sectionable(activities)
        assert "Lunch near canal" not in result
        assert "Visit Rijksmuseum" in result

    def test_keeps_canal_cruise(self):
        activities = ["Evening Canal Cruise", "Check in"]
        result = _filter_sectionable(activities)
        assert "Evening Canal Cruise" in result
        assert "Check in" not in result

    def test_empty_list(self):
        assert _filter_sectionable([]) == []


class TestExtractMealLocation:
    def test_extracts_near_location(self):
        activities = ["Arrival", "Early dinner near canals"]
        result = _extract_meal_location(activities)
        assert result == "canals"

    def test_returns_none_when_no_meal(self):
        activities = ["Visit museum", "Walk in park"]
        result = _extract_meal_location(activities)
        assert result is None

    def test_returns_none_when_no_near(self):
        activities = ["Early dinner at the hotel"]
        result = _extract_meal_location(activities)
        assert result is None


class TestBuildFlightDetails:
    def _make_legs(self):
        return [
            TransportLeg(
                from_city="Mumbai", to_city="Doha", mode="flight",
                operator="Qatar Airways", ticket_number="QR557",
                departure_time="04:10", arrival_time="05:45",
                from_terminal="Mumbai T2", to_terminal="Doha HIA",
                booking_reference="ABC123",
            ),
            TransportLeg(
                from_city="Doha", to_city="Amsterdam", mode="flight",
                operator="Qatar Airways", ticket_number="QR273",
                departure_time="07:50", arrival_time="14:55",
                from_terminal="Doha HIA", to_terminal="Amsterdam Schiphol",
                booking_reference="ABC123",
            ),
        ]

    def test_returns_flight_details_for_arrival_city(self):
        legs = self._make_legs()
        result = _build_flight_details(legs, "Amsterdam")
        assert result is not None
        assert result.airline == "Qatar Airways"
        assert len(result.sectors) == 2

    def test_sectors_labeled_correctly(self):
        legs = self._make_legs()
        result = _build_flight_details(legs, "Amsterdam")
        assert result.sectors[0].label == "Sector 1"
        assert result.sectors[1].label == "Sector 2"

    def test_sector_terminals_correct(self):
        legs = self._make_legs()
        result = _build_flight_details(legs, "Amsterdam")
        assert result.sectors[0].from_terminal == "Mumbai T2"
        assert result.sectors[1].to_terminal == "Amsterdam Schiphol"

    def test_returns_none_for_non_arrival_city(self):
        legs = self._make_legs()
        result = _build_flight_details(legs, "Paris")
        assert result is None


class TestBuildDay:
    def _make_mock_ai(self):
        mock_ai = MagicMock()
        # sections enrichment
        mock_ai.complete.side_effect = [
            json.dumps([
                {"section_title": "🌄 Morning- Anne Frank House", "place_name": "Anne Frank House",
                 "travel_info": "⏱️ ~18 mins walk from hotel", "hours": "9:00 AM - 10:00 PM",
                 "cost": "₹1,400 per person", "description": "A profound journey."},
                {"section_title": "☀️ Afternoon- Rijksmuseum", "place_name": "Rijksmuseum",
                 "travel_info": "⏱️ ~20 mins walk from Anne Frank House", "hours": "9 AM - 6 PM",
                 "cost": "₹1,800 per person", "description": "Dutch masters."},
            ]),
            # return instructions
            json.dumps({"instructions": "Head back to hotel.", "travel_note": "⏱️ ~15 mins 💡 Trams run late."}),
            # restaurant enrichment
            json.dumps([
                {"name": "Pancake Bakery", "ambience": "Cozy Dutch.", "price_inr": "₹800-1,200 per person", "travel_note": "~5 mins walk"},
            ]),
        ]
        return mock_ai

    def test_saves_day_json_to_input_days(self, tmp_path):
        mock_ai = self._make_mock_ai()
        ctx = AIGContext(
            facts=FACTS,
            library={"Amsterdam": AMSTERDAM_LIBRARY},
            db_path=tmp_path,
            ai_client=mock_ai,
        )
        build_day(ctx, day_number=1, input_dir=tmp_path)
        day_file = tmp_path / "days" / "day_01.json"
        assert day_file.exists()
        data = json.loads(day_file.read_text())
        assert data["day_number"] == 1

    def test_output_has_sections_not_activities(self, tmp_path):
        mock_ai = self._make_mock_ai()
        ctx = AIGContext(
            facts=FACTS,
            library={"Amsterdam": AMSTERDAM_LIBRARY},
            db_path=tmp_path,
            ai_client=mock_ai,
        )
        build_day(ctx, day_number=1, input_dir=tmp_path)
        data = json.loads((tmp_path / "days" / "day_01.json").read_text())
        assert "sections" in data
        assert "activities" not in data

    def test_cruise_day_has_no_sections_or_restaurants(self, tmp_path):
        cruise_facts = TripFacts(
            client_names=["Ana"],
            destinations=["Mediterranean"],
            trip_start_date="2026-04-26",
            trip_end_date="2026-04-27",
            hotels=[],
            days=[TripDay(
                day_number=8,
                title="At Sea | Relax",
                overnight_city=None,
                activities=["Relax on deck", "Spa treatment"],
            )],
        )
        mock_ai = MagicMock()
        ctx = AIGContext(
            facts=cruise_facts, library={}, db_path=tmp_path, ai_client=mock_ai,
        )
        build_day(ctx, day_number=8, input_dir=tmp_path)
        data = json.loads((tmp_path / "days" / "day_08.json").read_text())
        assert data["is_cruise_day"] is True
        assert data["sections"] == []
        assert data["dinner"] == []
        mock_ai.complete.assert_not_called()
