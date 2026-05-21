import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.aig.context import AIGContext, CityLibraryData
from src.aig.day_builder import (
    _match_attraction, _compute_chain, _is_cruise_day,
)
from src.common.models import TripFacts, TripDay, TripHotel


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


class TestComputeChain:
    def test_first_activity_departs_from_hotel(self):
        chain = _compute_chain(
            ["See Eiffel Tower", "Visit Louvre"],
            hotel_name="Hotel Ibis Paris",
        )
        assert chain[0] == "Hotel Ibis Paris"

    def test_second_activity_departs_from_previous(self):
        chain = _compute_chain(
            ["See Eiffel Tower", "Visit Louvre"],
            hotel_name="Hotel Ibis Paris",
        )
        assert chain[1] == "See Eiffel Tower"

    def test_reset_on_return_to_hotel(self):
        chain = _compute_chain(
            ["Anne Frank House", "Return to hotel to freshen up", "Vondelpark"],
            hotel_name="Hotel V",
        )
        # After "Return to hotel..." resets, next departs from hotel
        assert chain[2] == "Hotel V"

    def test_no_reset_on_regular_activity(self):
        chain = _compute_chain(
            ["Anne Frank House", "Rijksmuseum", "Vondelpark"],
            hotel_name="Hotel V",
        )
        assert chain[0] == "Hotel V"
        assert chain[1] == "Anne Frank House"
        assert chain[2] == "Rijksmuseum"


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


import json as _json
from src.aig.day_builder import _enrich_activities_with_ai


AI_RESPONSE = _json.dumps([
    {
        "name": "Visit Anne Frank House",
        "vivid_description": "A house that stood still while time moved on around it.",
        "travel_leg": {
            "from_location": "Hotel V Nesplein",
            "mode": "walk",
            "duration": "~18 min",
            "tip": "Follow Prinsengracht canal north"
        }
    },
    {
        "name": "Walk to Rijksmuseum",
        "vivid_description": "Centuries of Dutch mastery hang in gilded frames.",
        "travel_leg": {
            "from_location": "Visit Anne Frank House",
            "mode": "walk",
            "duration": "~20 min",
            "tip": None
        }
    },
])


class TestEnrichActivitiesWithAI:
    def test_returns_enriched_list_in_order(self):
        mock_ai = MagicMock()
        mock_ai.complete.return_value = AI_RESPONSE
        activities = [
            {"name": "Visit Anne Frank House", "from_location": "Hotel V Nesplein",
             "hours": "9:00 AM TO 10:00 PM", "entry_fee": "€16"},
            {"name": "Walk to Rijksmuseum", "from_location": "Visit Anne Frank House",
             "hours": "9 AM – 6 PM", "entry_fee": "€22"},
        ]
        result = _enrich_activities_with_ai(activities, "Amsterdam", "Public Transport", mock_ai)
        assert len(result) == 2
        assert result[0]["name"] == "Visit Anne Frank House"
        assert result[0]["vivid_description"] != ""
        assert result[0]["travel_leg"]["mode"] == "walk"

    def test_order_preserved_even_if_ai_reorders(self):
        # AI returns items in wrong order — we re-sort by original index
        mock_ai = MagicMock()
        reversed_response = _json.dumps([
            {"name": "Walk to Rijksmuseum", "vivid_description": "Museums.", "travel_leg": None},
            {"name": "Visit Anne Frank House", "vivid_description": "House.", "travel_leg": None},
        ])
        mock_ai.complete.return_value = reversed_response
        activities = [
            {"name": "Visit Anne Frank House", "from_location": "Hotel V"},
            {"name": "Walk to Rijksmuseum", "from_location": "Visit Anne Frank House"},
        ]
        result = _enrich_activities_with_ai(activities, "Amsterdam", "Public Transport", mock_ai)
        assert result[0]["name"] == "Visit Anne Frank House"
        assert result[1]["name"] == "Walk to Rijksmuseum"

    def test_falls_back_gracefully_on_bad_ai_response(self):
        mock_ai = MagicMock()
        mock_ai.complete.return_value = "not json {{{"
        activities = [{"name": "Anne Frank House", "from_location": "Hotel V"}]
        result = _enrich_activities_with_ai(activities, "Amsterdam", "walk", mock_ai)
        assert len(result) == 1
        assert result[0]["name"] == "Anne Frank House"
        assert result[0].get("vivid_description", "") == ""
