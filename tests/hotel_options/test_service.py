import io
import openpyxl
import pytest
from unittest.mock import MagicMock, patch
from src.library.ui.services.hotel_options_service import (
    _normalize_section_labels,
    _plan_to_dict,
    _infer_destination_from_labels,
)
from src.hotel_options.models import HotelRow, PlanPricing, Plan


def test_normalize_section_labels_happy_path():
    """AI returns clean labels — use them as-is."""
    mock_client = MagicMock()
    mock_client.complete.return_value = '["London (Jul 1 - Jul 5)", "Paris (Jul 6 - Jul 10)"]'
    result = _normalize_section_labels(["London (Jul 1 - Jul 5)", "Paris (Jul 6 - Jul 10)"], mock_client)
    assert result == ["London (Jul 1 - Jul 5)", "Paris (Jul 6 - Jul 10)"]


def test_normalize_section_labels_ai_fixes_spacing():
    """AI cleans hyphen spacing in date ranges."""
    mock_client = MagicMock()
    mock_client.complete.return_value = '["Wimbledon (Jun 28 - Jul 4)", "Central London (Jul 1 - Jul 4)"]'
    result = _normalize_section_labels(["Wimbledon (Jun 28- Jul 4)", "Central London (Jul 1- Jul 4)"], mock_client)
    assert result == ["Wimbledon (Jun 28 - Jul 4)", "Central London (Jul 1 - Jul 4)"]


def test_normalize_section_labels_fallback_on_ai_failure():
    """AI throws — fall back to regex fixing hyphen spacing, keeping dates."""
    mock_client = MagicMock()
    mock_client.complete.side_effect = RuntimeError("API error")
    result = _normalize_section_labels(["London (Jun 28- Jul 5)", "Paris (Jul 6 - Jul 10)"], mock_client)
    assert result == ["London (Jun 28 - Jul 5)", "Paris (Jul 6 - Jul 10)"]


def test_normalize_section_labels_empty():
    mock_client = MagicMock()
    result = _normalize_section_labels([], mock_client)
    assert result == []


def test_normalize_section_labels_ai_wrong_length_falls_back():
    """AI returns wrong-length list — fall back to regex."""
    mock_client = MagicMock()
    mock_client.complete.return_value = '["Only One"]'
    result = _normalize_section_labels(["London (Jun 28- Jul 1)", "Paris (Jul 6)"], mock_client)
    assert result == ["London (Jun 28 - Jul 1)", "Paris (Jul 6)"]


def _make_plan_with_pricing() -> Plan:
    hotel = HotelRow(
        name="Hotel Alpha", category="4-Star", room_type="Double",
        cancellation="Free", meal_type="Breakfast",
        online_price=100000.0, customer_discount=5000.0,
        discounted_price=95000.0, discount_pct=5.0,
    )
    pricing = PlanPricing(
        total_online_price=100000.0, total_b2b_price=90000.0,
        customer_discount=5000.0, discounted_price=95000.0, discount_pct=5.0,
    )
    return Plan(label="London (Jul 1 - Jul 5)", hotels=[hotel], pricing=pricing)


def test_plan_to_dict_includes_per_hotel_pricing():
    """_plan_to_dict must include online_price, customer_discount, discounted_price, discount_pct per hotel."""
    plan = _make_plan_with_pricing()
    d = _plan_to_dict(plan)
    hotel_d = d["hotels"][0]
    assert hotel_d["online_price"] == 100000.0
    assert hotel_d["customer_discount"] == 5000.0
    assert hotel_d["discounted_price"] == 95000.0
    assert hotel_d["discount_pct"] == 5.0


def test_infer_destination_from_labels_ai_path():
    """AI returns city name from neighbourhood-level section headers."""
    mock_client = MagicMock()
    mock_client.complete.return_value = "London"
    result = _infer_destination_from_labels(
        ["Wimbledon (Jun 28 - Jul 4)", "Central London (Jul 5 - Jul 8)"],
        mock_client,
    )
    assert result == "London"


def test_infer_destination_from_labels_regex_fallback():
    """AI fails — strip date ranges and return first unique location."""
    mock_client = MagicMock()
    mock_client.complete.side_effect = RuntimeError("API error")
    result = _infer_destination_from_labels(
        ["Paris (Jul 1 - Jul 5)", "Paris (Jul 6 - Jul 10)"],
        mock_client,
    )
    assert result == "Paris"


def test_plan_to_dict_plan_fields_intact():
    """_plan_to_dict still includes label, pricing, and basic hotel fields."""
    plan = _make_plan_with_pricing()
    d = _plan_to_dict(plan)
    assert d["label"] == "London (Jul 1 - Jul 5)"
    assert d["pricing"]["total_online_price"] == 100000.0
    assert d["hotels"][0]["name"] == "Hotel Alpha"
    assert d["hotels"][0]["cancellation"] == "Free"


from src.library.ui.services.hotel_options_service import _group_hotels


def _hr(name: str) -> HotelRow:
    return HotelRow(
        name=name, category="4-Star", room_type="Double",
        cancellation="Free", meal_type="Breakfast", online_price=100000.0,
    )


def test_group_hotels_single_entries():
    hotels = [_hr("Hotel A"), _hr("Hotel B"), _hr("Hotel C")]
    groups = _group_hotels(hotels)
    assert len(groups) == 3
    assert groups[0] == [hotels[0]]
    assert groups[1] == [hotels[1]]
    assert groups[2] == [hotels[2]]


def test_group_hotels_consecutive_same_name():
    hotels = [_hr("Resort X"), _hr("Resort X"), _hr("Hotel B")]
    groups = _group_hotels(hotels)
    assert len(groups) == 2
    assert len(groups[0]) == 2
    assert groups[0][0].name == "Resort X"
    assert groups[1][0].name == "Hotel B"


def test_group_hotels_non_consecutive_same_name_not_merged():
    hotels = [_hr("Hotel A"), _hr("Hotel B"), _hr("Hotel A")]
    groups = _group_hotels(hotels)
    assert len(groups) == 3


def test_group_hotels_empty():
    assert _group_hotels([]) == []
