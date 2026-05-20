import json
import pytest
from src.common.models import TripFacts, TripDay, TripHotel, TransportLeg


class TestTripFacts:
    def test_json_roundtrip_full(self):
        facts = TripFacts(
            client_names=["Divya", "Rahul"],
            num_guests="2 adults",
            departure_city="Mumbai",
            destinations=["Amsterdam", "Florence"],
            trip_start_date="2025-04-19",
            trip_end_date="2025-05-05",
            hotels=[TripHotel(city="Amsterdam", hotel_name="Marriott Amsterdam",
                              check_in="2025-04-19", check_out="2025-04-23")],
            transport_modes=[TransportLeg(from_city="Amsterdam", to_city="Florence",
                                          mode="flight", date="2025-04-23")],
            days=[TripDay(day_number=1, date="2025-04-19", title="Arrival",
                          overnight_city="Amsterdam", overnight_hotel="Marriott Amsterdam",
                          activities=["Check-in", "Canal walk"])],
            dietary_restrictions=["vegetarian"],
            food_allergies=[],
            cuisine_preferences=["local"],
        )
        data = json.loads(facts.model_dump_json())
        restored = TripFacts.model_validate(data)
        assert restored.client_names == ["Divya", "Rahul"]
        assert restored.hotels[0].hotel_name == "Marriott Amsterdam"
        assert restored.days[0].activities == ["Check-in", "Canal walk"]
        assert restored.transport_modes[0].from_city == "Amsterdam"

    def test_num_guests_is_string(self):
        facts = TripFacts(num_guests="2 adults, 2 kids (ages 10, 8)")
        assert isinstance(facts.num_guests, str)
        assert "kids" in facts.num_guests

    def test_num_guests_nullable(self):
        facts = TripFacts()
        assert facts.num_guests is None

    def test_missing_required_all_empty(self):
        missing = TripFacts().missing_required()
        assert "client_names" in missing
        assert "destinations" in missing
        assert "trip_start_date" in missing
        assert "trip_end_date" in missing
        assert "days" in missing
        assert "hotels" in missing

    def test_missing_required_all_present(self):
        facts = TripFacts(
            client_names=["Ana"],
            destinations=["Paris"],
            trip_start_date="2025-06-01",
            trip_end_date="2025-06-07",
            days=[TripDay(day_number=1, activities=[])],
            hotels=[TripHotel(city="Paris", hotel_name="Hotel de Ville")],
        )
        assert facts.missing_required() == []

    def test_missing_required_optional_fields_not_included(self):
        facts = TripFacts(
            client_names=["Ana"],
            destinations=["Paris"],
            trip_start_date="2025-06-01",
            trip_end_date="2025-06-07",
            days=[TripDay(day_number=1, activities=[])],
            hotels=[TripHotel(city="Paris", hotel_name="Hotel de Ville")],
        )
        missing = facts.missing_required()
        assert "num_guests" not in missing
        assert "departure_city" not in missing
        assert "dietary_restrictions" not in missing

    def test_is_ready_for_generation_false_when_empty(self):
        assert TripFacts().is_ready_for_generation() is False

    def test_is_ready_for_generation_true_when_complete(self):
        facts = TripFacts(
            client_names=["Ana"],
            destinations=["Paris"],
            trip_start_date="2025-06-01",
            trip_end_date="2025-06-07",
            days=[TripDay(day_number=1, activities=[])],
            hotels=[TripHotel(city="Paris", hotel_name="Hotel de Ville")],
        )
        assert facts.is_ready_for_generation() is True

    def test_missing_required_partial_state(self):
        facts = TripFacts(
            client_names=["Ana"],
            destinations=["Paris"],
            # trip_start_date, trip_end_date, days, hotels intentionally absent
        )
        missing = facts.missing_required()
        assert "client_names" not in missing
        assert "destinations" not in missing
        assert "trip_start_date" in missing
        assert "trip_end_date" in missing
        assert "days" in missing
        assert "hotels" in missing
        assert len(missing) == 4

    def test_num_guests_rejects_int(self):
        with pytest.raises(Exception):
            TripFacts(num_guests=2)
