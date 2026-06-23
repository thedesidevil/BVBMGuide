from __future__ import annotations
import re
import httpx

from src.hotel_options.models import HotelRow, EnrichedHotel

_PLACES_BASE = "https://maps.googleapis.com/maps/api/place"
_PLACE_ID_RE = re.compile(r'ChIJ[A-Za-z0-9_\-]+')

_DESCRIPTION_PROMPT = """\
Write 2-3 sentences about this hotel in warm travel-agency tone for a client document.
Hotel: {name}
Category: {category}
Address: {address}
Rating: {rating} ({rating_count} reviews)
Cancellation: {cancellation}
Meal: {meal_type}

Output only the description sentences, nothing else."""


def place_id_from_maps_url(url: str) -> str | None:
    m = _PLACE_ID_RE.search(url)
    return m.group(0) if m else None


def check_hotels_exist(
    hotel_names: list[str], destination: str, api_key: str
) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in hotel_names:
        resp = httpx.get(
            f"{_PLACES_BASE}/textsearch/json",
            params={"query": f"{name} {destination}", "key": api_key},
        )
        resp.raise_for_status()
        hits = resp.json().get("results", [])
        result[name] = hits[0]["place_id"] if hits else None
    return result


def enrich_hotel(
    hotel: HotelRow,
    place_id: str,
    destination: str,
    api_key: str,
    ai_client,
) -> EnrichedHotel:
    # Place Details
    details_resp = httpx.get(
        f"{_PLACES_BASE}/details/json",
        params={
            "place_id": place_id,
            "fields": "name,formatted_address,international_phone_number,rating,user_ratings_total,photos",
            "key": api_key,
        },
    )
    details_resp.raise_for_status()
    detail = details_resp.json().get("result", {})

    official_name = detail.get("name", hotel.name)
    address = detail.get("formatted_address", "")
    phone = detail.get("international_phone_number", "")
    rating = float(detail.get("rating", 0))
    rating_count = int(detail.get("user_ratings_total", 0))
    maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

    # Photo
    photo_bytes: bytes | None = None
    photos = detail.get("photos", [])
    if photos:
        photo_ref = photos[0]["photo_reference"]
        photo_resp = httpx.get(
            "https://maps.googleapis.com/maps/api/place/photo",
            params={"maxwidth": 800, "photo_reference": photo_ref, "key": api_key},
            follow_redirects=True,
        )
        photo_resp.raise_for_status()
        photo_bytes = photo_resp.content

    # AI description
    prompt = _DESCRIPTION_PROMPT.format(
        name=official_name,
        category=hotel.category,
        address=address,
        rating=rating,
        rating_count=rating_count,
        cancellation=hotel.cancellation or "Not specified",
        meal_type=hotel.meal_type or "Not specified",
    )
    description = ai_client.complete(prompt)

    return EnrichedHotel(
        official_name=official_name,
        address=address,
        phone=phone,
        rating=rating,
        rating_count=rating_count,
        maps_url=maps_url,
        photo_bytes=photo_bytes,
        description=description,
        cancellation=hotel.cancellation,
        meal_type=hotel.meal_type,
        category=hotel.category,
    )
