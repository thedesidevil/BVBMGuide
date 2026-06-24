import pytest
from unittest.mock import MagicMock, patch
from src.library.ui.services.hotel_options_service import _normalize_section_labels


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
