import pytest
from unittest.mock import MagicMock
from pathlib import Path

from src.aig.context import AIGContext, CityLibraryData
from src.common.models import TripFacts, TripHotel, TripDay
import src.aig.sections.must_try_dishes as must_try
import src.aig.sections.souvenir_guide as souvenirs
import src.aig.sections.getting_around as getting_around


def _make_context(library_overrides=None):
    lib_kwargs = dict(
        city="Amsterdam",
        local_dishes=[{"name": "Stroopwafel", "type": "Street Food", "description": "Caramel wafer"},
                      {"name": "Erwtensoep", "type": "Mains", "description": "Pea soup"}],
        souvenirs=[{"item": "Delft pottery", "where": "Delft shops", "tip": "Check for authenticity"}],
        transport_options=[{"mode": "metro", "tip": "Use OV-chipkaart", "where_to_buy": "Schiphol"}],
    )
    lib_kwargs.update(library_overrides or {})
    lib = CityLibraryData(**lib_kwargs)
    facts = TripFacts(
        client_names=["Ana"],
        destinations=["Amsterdam"],
        trip_start_date="2026-04-19",
        trip_end_date="2026-04-22",
        hotels=[TripHotel(city="Amsterdam", hotel_name="Hotel V")],
        days=[TripDay(day_number=1, activities=[])],
    )
    ctx = MagicMock(spec=AIGContext)
    ctx.facts = facts
    ctx.library = {"Amsterdam": lib}
    return ctx


class TestMustTryDishes:
    def test_returns_dict_with_cities(self):
        result = must_try.build(_make_context())
        assert "cities" in result
        assert len(result["cities"]) == 1
        assert result["cities"][0]["city"] == "Amsterdam"

    def test_dishes_included(self):
        result = must_try.build(_make_context())
        names = [d["name"] for d in result["cities"][0]["dishes"]]
        assert "Stroopwafel" in names

    def test_empty_library_returns_empty_cities(self):
        ctx = _make_context({"local_dishes": []})
        result = must_try.build(ctx)
        assert result["cities"][0]["dishes"] == []


class TestSouvenirGuide:
    def test_returns_dict_with_cities(self):
        result = souvenirs.build(_make_context())
        assert "cities" in result

    def test_souvenir_items_included(self):
        result = souvenirs.build(_make_context())
        items = [s["item"] for s in result["cities"][0]["items"]]
        assert "Delft pottery" in items


class TestGettingAround:
    def test_returns_dict_with_cities(self):
        result = getting_around.build(_make_context())
        assert "cities" in result

    def test_transport_options_included(self):
        result = getting_around.build(_make_context())
        modes = [t["mode"] for t in result["cities"][0]["options"]]
        assert "metro" in modes


import json as _json
from unittest.mock import patch
import src.aig.sections.cultural_etiquette as cult_etiquette
import src.aig.sections.mobile_connectivity as connectivity
import src.aig.sections.safety_contacts as safety
import src.aig.sections.health_vaccination as health


def _make_context_with_ai(library_field, library_value, ai_response):
    """Helper: context where one library field is set (or empty) and AI returns ai_response."""
    ctx = _make_context({library_field: library_value})
    ctx.ai_client = MagicMock()
    ctx.ai_client.complete.return_value = ai_response
    ctx.db_path = Path("/fake/db")
    return ctx


class TestCulturalEtiquette:
    def test_uses_library_when_available(self):
        ctx = _make_context_with_ai("phrases", [{"phrase": "Dank je", "meaning": "Thank you"}], "ignored")
        result = cult_etiquette.build(ctx)
        assert result["cities"][0]["phrases"] == [{"phrase": "Dank je", "meaning": "Thank you"}]
        ctx.ai_client.complete.assert_not_called()

    def test_calls_ai_when_library_empty(self, tmp_path):
        ctx = _make_context_with_ai("phrases", [], '["Dank je — Thank you", "Alsjeblieft — Please"]')
        ctx.db_path = tmp_path
        (tmp_path / "Amsterdam.json").write_text('{"phrases": []}')
        result = cult_etiquette.build(ctx)
        assert result["cities"][0]["ai_generated"] is True
        ctx.ai_client.complete.assert_called_once()

    def test_writes_back_to_library_when_ai_generated(self, tmp_path):
        ctx = _make_context_with_ai("phrases", [], '["Dank je — Thank you"]')
        ctx.db_path = tmp_path
        (tmp_path / "Amsterdam.json").write_text('{"phrases": []}')
        cult_etiquette.build(ctx)
        data = _json.loads((tmp_path / "Amsterdam.json").read_text())
        assert len(data.get("_audit", [])) == 1


class TestSafetyContacts:
    def test_uses_library_when_available(self):
        ctx = _make_context_with_ai(
            "safety_tips", ["Do not leave bags unattended"], "ignored"
        )
        result = safety.build(ctx)
        assert result["cities"][0]["tips"] == ["Do not leave bags unattended"]
        ctx.ai_client.complete.assert_not_called()

    def test_calls_ai_when_empty(self, tmp_path):
        ctx = _make_context_with_ai("safety_tips", [], '["Keep valuables hidden"]')
        ctx.db_path = tmp_path
        (tmp_path / "Amsterdam.json").write_text('{"safety_tips": []}')
        result = safety.build(ctx)
        assert result["cities"][0]["ai_generated"] is True


import json as _json2
import src.aig.sections.cover as cover
import src.aig.sections.packing_list as packing
import src.aig.sections.thank_you as thank_you


class TestCover:
    def test_returns_title_and_subtitle(self):
        ctx = _make_context()
        ctx.ai_client = MagicMock()
        ctx.ai_client.complete.return_value = _json2.dumps({
            "title": "Windmills and Canals",
            "subtitle": "A 3-Night Amsterdam Adventure"
        })
        result = cover.build(ctx)
        assert "title" in result
        assert "subtitle" in result
        assert result["title"] != ""

    def test_falls_back_on_bad_ai_response(self):
        ctx = _make_context()
        ctx.ai_client = MagicMock()
        ctx.ai_client.complete.return_value = "not json"
        result = cover.build(ctx)
        assert "title" in result  # fallback title generated from destinations


class TestPackingList:
    def test_calls_ai_with_trip_context(self):
        ctx = _make_context()
        ctx.ai_client = MagicMock()
        ctx.ai_client.complete.return_value = _json2.dumps(["Comfortable walking shoes", "Rain jacket"])
        result = packing.build(ctx)
        assert "items" in result
        assert len(result["items"]) >= 1
        prompt_used = ctx.ai_client.complete.call_args[0][0]
        assert "Amsterdam" in prompt_used

    def test_trip_dates_in_prompt(self):
        ctx = _make_context()
        ctx.ai_client = MagicMock()
        ctx.ai_client.complete.return_value = "[]"
        packing.build(ctx)
        prompt = ctx.ai_client.complete.call_args[0][0]
        assert "2026-04-19" in prompt


class TestThankYou:
    def test_returns_static_text(self):
        ctx = _make_context()
        result = thank_you.build(ctx)
        assert "text" in result
        assert "Bon Voyage by Marina" in result["text"]


import src.aig.sections.client_info as client_info


class TestClientInfo:
    def _make_multi_hotel_context(self):
        facts = TripFacts(
            client_names=["Ana", "Raj"],
            num_guests="2 adults",
            departure_city="Mumbai",
            destinations=["Amsterdam", "Florence"],
            trip_start_date="2026-04-19",
            trip_end_date="2026-04-25",
            local_transport="Public Transport",
            dietary_restrictions=["vegetarian"],
            hotels=[
                TripHotel(city="Amsterdam", hotel_name="Hotel V", check_in="2026-04-19", check_out="2026-04-22"),
                TripHotel(city="Florence", hotel_name="Hotel Alex", check_in="2026-04-22", check_out="2026-04-25"),
            ],
            days=[TripDay(day_number=1, activities=[])],
        )
        ctx = _make_context()
        ctx.facts = facts
        ctx.library = {}
        return ctx

    def test_client_names_in_result(self):
        result = client_info.build(self._make_multi_hotel_context())
        assert result["client_names"] == ["Ana", "Raj"]

    def test_one_row_per_hotel(self):
        result = client_info.build(self._make_multi_hotel_context())
        assert len(result["trip_summary"]) == 2

    def test_hotel_row_has_maps_link(self):
        result = client_info.build(self._make_multi_hotel_context())
        for row in result["trip_summary"]:
            assert row["hotel_maps_link"].startswith("https://www.google.com/maps")

    def test_transport_summary_from_local_transport(self):
        result = client_info.build(self._make_multi_hotel_context())
        for row in result["trip_summary"]:
            assert "Public Transport" in row["transport"]

    def test_dietary_preferences_included(self):
        result = client_info.build(self._make_multi_hotel_context())
        assert "vegetarian" in result["dietary_preferences"]
