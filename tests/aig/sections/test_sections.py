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
