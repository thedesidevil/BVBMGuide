from unittest.mock import patch, MagicMock
from src.hotel_options.enricher import place_id_from_maps_url, check_hotels_exist, enrich_hotel
from src.hotel_options.models import HotelRow


def test_place_id_from_maps_url_found():
    url = "https://maps.google.com/?cid=123&place_id=ChIJAbCdEfGh1234567890"
    assert place_id_from_maps_url(url) == "ChIJAbCdEfGh1234567890"


def test_place_id_from_maps_url_not_found():
    assert place_id_from_maps_url("https://maps.google.com/") is None


def _mock_text_search(results):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"results": results}
    return mock_resp


def test_check_hotels_exist_found():
    with patch("httpx.get", return_value=_mock_text_search([{"place_id": "ChIJ123"}])):
        result = check_hotels_exist(["Hilton London"], "London", "fake_key")
    assert result["Hilton London"] == "ChIJ123"


def test_check_hotels_exist_not_found():
    with patch("httpx.get", return_value=_mock_text_search([])):
        result = check_hotels_exist(["Unknown Hotel"], "London", "fake_key")
    assert result["Unknown Hotel"] is None


def test_enrich_hotel_builds_enriched():
    details_resp = MagicMock()
    details_resp.raise_for_status = MagicMock()
    details_resp.json.return_value = {
        "result": {
            "name": "Hilton London Kensington",
            "formatted_address": "179 Holland Park Ave",
            "international_phone_number": "+44 20 7602 3355",
            "rating": 4.2,
            "user_ratings_total": 1847,
            "photos": [{"photo_reference": "ref123"}],
        }
    }
    photo_resp = MagicMock()
    photo_resp.raise_for_status = MagicMock()
    photo_resp.content = b"JPEG_BYTES"

    ai_client = MagicMock()
    # complete() is the method used in this codebase — verify against ai_provider.py
    ai_client.complete.return_value = "A fine hotel."

    hotel = HotelRow(
        name="Hilton London",
        category="5-Star",
        room_type="King Room",
        cancellation="Non-refundable",
        meal_type="Breakfast included",
        online_price=50000.0,
    )

    with patch("httpx.get", side_effect=[details_resp, photo_resp]):
        result = enrich_hotel(hotel, "ChIJ123", "London", "fake_key", ai_client)

    assert result.official_name == "Hilton London Kensington"
    assert result.rating == 4.2
    assert result.photo_bytes == b"JPEG_BYTES"
    assert result.description == "A fine hotel."
    assert result.cancellation == "Non-refundable"
