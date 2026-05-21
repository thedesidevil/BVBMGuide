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
