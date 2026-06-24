import pytest
from unittest.mock import MagicMock, patch
from src.library.ui.services.hotel_options_service import _normalize_section_labels


def test_normalize_section_labels_happy_path():
    """AI returns clean labels — use them."""
    mock_client = MagicMock()
    mock_client.complete.return_value = '["London", "Paris"]'
    result = _normalize_section_labels(["London (Jul 1 - Jul 5)", "Paris (Jul 6 - Jul 10)"], mock_client)
    assert result == ["London", "Paris"]


def test_normalize_section_labels_fallback_on_ai_failure():
    """AI throws — fall back to regex stripping date parenthetical."""
    mock_client = MagicMock()
    mock_client.complete.side_effect = RuntimeError("API error")
    result = _normalize_section_labels(["London (Jul 1 - Jul 5)", "Paris (Jul 6 - Jul 10)"], mock_client)
    assert result == ["London", "Paris"]


def test_normalize_section_labels_empty():
    mock_client = MagicMock()
    result = _normalize_section_labels([], mock_client)
    assert result == []


def test_normalize_section_labels_ai_wrong_length_falls_back():
    """AI returns wrong-length list — fall back to regex."""
    mock_client = MagicMock()
    mock_client.complete.return_value = '["Only One"]'
    result = _normalize_section_labels(["London (Jul 1)", "Paris (Jul 6)"], mock_client)
    assert result == ["London", "Paris"]
