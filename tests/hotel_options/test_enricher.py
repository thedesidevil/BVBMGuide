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


from src.hotel_options.enricher import enrich_hotel_multi_segment


def test_enrich_hotel_multi_segment_builds_segments():
    details_resp = MagicMock()
    details_resp.raise_for_status = MagicMock()
    details_resp.json.return_value = {
        "result": {
            "name": "Adaaran Select Hudhuranfushi",
            "formatted_address": "North Male Atoll, Maldives",
            "international_phone_number": "+960 664 0088",
            "rating": 4.5,
            "user_ratings_total": 1200,
            "photos": [
                {"photo_reference": "ref_beach"},
                {"photo_reference": "ref_ocean"},
            ],
        }
    }

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.status_code = 200
        params = kwargs.get("params", {})
        ref = params.get("photo_reference", "")
        resp.content = f"PHOTO_{ref}".encode()
        resp.json.return_value = {}
        return resp

    ai_client = MagicMock()
    ai_client.complete.return_value = "A stunning overwater resort."

    hotels = [
        HotelRow(
            name="Adaaran Select Hudhuranfushi", category="4-Star",
            room_type="Beach Villa", cancellation="Free cancellation",
            meal_type="All Inclusive", online_price=1178668.0,
            dates="Dec 22-25", inclusions="Airport transfer", exclusions="Visa fees",
        ),
        HotelRow(
            name="Adaaran Select Hudhuranfushi", category="4-Star",
            room_type="Ocean Villa", cancellation="Free cancellation",
            meal_type="All Inclusive", online_price=451983.0,
            dates="Dec 25-26", inclusions="", exclusions="",
        ),
    ]

    with patch("src.hotel_options.enricher.httpx.get", side_effect=[details_resp,
                MagicMock(status_code=200, content=b"PHOTO_beach"),
                MagicMock(status_code=200, content=b"PHOTO_ocean")]):
        result = enrich_hotel_multi_segment(hotels, "ChIJ_test", "Maldives", "fake_key", ai_client)

    assert result.official_name == "Adaaran Select Hudhuranfushi"
    assert result.rating == 4.5
    assert result.photo_bytes is None         # superseded by segments
    assert len(result.room_segments) == 2
    assert result.room_segments[0].room_type == "Beach Villa"
    assert result.room_segments[0].dates == "Dec 22-25"
    assert result.room_segments[0].online_price == 1178668.0
    assert result.room_segments[0].inclusions == "Airport transfer"
    assert result.room_segments[0].exclusions == "Visa fees"
    assert result.room_segments[1].room_type == "Ocean Villa"
    assert result.room_segments[1].dates == "Dec 25-26"
    assert result.description == "A stunning overwater resort."


def test_enrich_hotel_multi_segment_photo_fallback_single_photo():
    """When gallery has 1 photo but there are 2 segments, both get photo_bytes from the same photo."""
    details_resp = MagicMock()
    details_resp.raise_for_status = MagicMock()
    details_resp.json.return_value = {
        "result": {
            "name": "Adaaran Select Hudhuranfushi",
            "formatted_address": "North Male Atoll, Maldives",
            "international_phone_number": "+960 664 0088",
            "rating": 4.5,
            "user_ratings_total": 1200,
            "photos": [
                {"photo_reference": "ref_only"},
            ],
        }
    }

    ai_client = MagicMock()
    ai_client.complete.return_value = "A stunning overwater resort."

    hotels = [
        HotelRow(
            name="Adaaran Select Hudhuranfushi", category="4-Star",
            room_type="Beach Villa", cancellation="Free cancellation",
            meal_type="All Inclusive", online_price=1178668.0,
            dates="Dec 22-25",
        ),
        HotelRow(
            name="Adaaran Select Hudhuranfushi", category="4-Star",
            room_type="Ocean Villa", cancellation="Free cancellation",
            meal_type="All Inclusive", online_price=451983.0,
            dates="Dec 25-26",
        ),
    ]

    # 1 photo reference → photo fetch is called twice (once per segment),
    # both times using the same ref (last-photo fallback).
    with patch("src.hotel_options.enricher.httpx.get", side_effect=[
        details_resp,
        MagicMock(status_code=200, content=b"PHOTO_only"),
        MagicMock(status_code=200, content=b"PHOTO_only"),
    ]):
        result = enrich_hotel_multi_segment(hotels, "ChIJ_test", "Maldives", "fake_key", ai_client)

    assert len(result.room_segments) == 2
    assert result.room_segments[0].photo_bytes == b"PHOTO_only"
    assert result.room_segments[1].photo_bytes == b"PHOTO_only"
