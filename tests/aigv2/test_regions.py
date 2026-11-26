from datetime import date

from src.aigv2 import regions as R
from src.aigv2.models import DayPlan, Diet, HotelStay, Traveller, TripPlan
from src.aigv2.writing.sections import _library_named


def _trip(modes=("private_driver",)):
    return TripPlan(client_names=["A"], travellers=Traveller(adults=2), diet=Diet(), travel_modes=list(modes),
                    hotels=[HotelStay(city="Wayanad", hotel="Pepper Trail", check_in=date(2026, 12, 1),
                                      check_out=date(2026, 12, 7), source="voucher")],
                    transport=[], bookings=[], open_choices=[], vague_days=[], commentary_removed=[],
                    trip_scope="domestic", days=[DayPlan(date=date(2026, 12, 1), title="t", city="Wayanad", items=[])])


def _cities():
    return [{"city": "Wayanad", "country": "India", "state": "Kerala"}]


def test_town_maps_to_its_state():
    assert R.state_of("Wayanad") == "Kerala"
    assert R.state_of("Pepper Trail", "Chulliyode, Keralam 673592, India") == "Kerala"
    assert R.state_of("Tokyo") is None


def test_phrase_language():
    assert R.phrase_language("Athe") == "Malayalam"
    assert R.phrase_language("Idu elli ide?") == "Kannada"
    assert R.phrase_language("Illa") is None


def test_off_trip_city_entries_dropped():
    items = [{"city": "Goa", "mode": "Self drive car hire"}, {"city": "Darjeeling", "mode": "Toy Train"},
             {"city": "Kerala", "mode": "Houseboat"}, {"mode": "Taxi"}]
    kept = R.drop_off_trip_city(items, {"wayanad", "kerala", "india"})
    assert [x["mode"] for x in kept] == ["Houseboat", "Taxi"]


def test_india_pool_narrowed_to_the_trips_region():
    phrases = [{"english": "Hello", "local": "Azu / Hello", "_source_file": "Northeast India/x.docx"},
               {"english": "Goodbye", "local": "Aavjo", "_source_file": "Gujarat/x.docx"},
               {"english": "Yes", "local": "Athe", "_source_file": "Karnataka, Kerala and Tamil Nadu/x.docx"},
               {"english": "Yes", "local": "Haudu", "_source_file": "Karnataka, Kerala and Tamil Nadu/x.docx"}]
    out = R.region_entries("phrases", phrases, {"Kerala"})
    assert [p["local"] for p in out] == ["Athe"]


def test_dos_drop_other_regions_and_packing_tips():
    tips = [{"tip": "Do not litter in Mawlynnong", "_source_file": "Northeast India/x"},
            {"tip": "Carry swimwear", "_source_file": "Karnataka, Kerala and Tamil Nadu/x"},
            {"tip": "Dress modestly at temples", "_source_file": "Karnataka, Kerala and Tamil Nadu/x"},
            {"tip": "Remove shoes before entering homes", "_source_file": "Rajasthan/x"},
            {"tip": "Permits for Nathula Pass", "_source_file": "Rajasthan/x"}]
    out = [t["tip"] for t in R.region_entries("dos_donts", tips, {"Kerala"})]
    assert "Dress modestly at temples" in out and "Remove shoes before entering homes" in out
    assert not any("Mawlynnong" in t or "Nathula" in t or "swimwear" in t for t in out)


def test_getting_around_private_driver_never_shows_self_drive_or_other_cities():
    cd = [{"country": "India", "transport_options": [
        {"city": "Goa", "mode": "Self drive car hire", "description": "Automatic Baleno"},
        {"city": "Darjeeling", "mode": "Toy Train", "description": "Joy ride"}]}]
    named = _library_named("getting_around", _cities(), cd, trip=_trip(), countries=["India"])
    modes = [x["mode"] for x in named["transport_options"]]
    assert modes == ["Private transfer"]


def test_self_drive_client_keeps_self_drive_only_when_on_the_trip():
    cd = [{"country": "India", "transport_options": [{"city": "Wayanad", "mode": "Self drive car hire"}]}]
    named = _library_named("getting_around", _cities(), cd, trip=_trip(("self_drive",)), countries=["India"])
    assert [x["mode"] for x in named["transport_options"]] == ["Self drive car hire"]


def test_stay_town_without_souvenirs_is_not_filled_from_the_gateway_city_and_is_marked():
    from types import SimpleNamespace as NS
    from src.aigv2.pipeline import _section_inputs

    class Lib:
        def city(self, c, region=True):
            return {"Mysore": {"souvenirs": [{"item": "Silk"}]}, "Kerala": {"local_dishes": [{"name": "Sadya"}]}}.get(c, {})

        def country(self, c):
            return {}

    state = NS(trip=_trip(), days=[NS(city="Wayanad"), NS(city="Mysore")], countries={"Wayanad": "India", "Mysore": "India"},
               places={})
    city_data, _ = _section_inputs(state, Lib())
    assert [c["city"] for c in city_data] == ["Wayanad"] and not city_data[0].get("souvenirs")
    assert city_data[0]["local_dishes"] == [{"name": "Sadya"}]
