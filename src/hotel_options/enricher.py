from __future__ import annotations
import re
import httpx

from src.hotel_options.models import HotelRow, EnrichedHotel, RoomSegment
from src.common.brand_voice import HOTEL_DESCRIPTION_SYSTEM

_PLACES_BASE = "https://maps.googleapis.com/maps/api/place"
_PLACE_ID_RE = re.compile(r'ChIJ[A-Za-z0-9_\-]+')

_DESCRIPTION_PROMPT = """\
Write a hotel description for a client accommodation proposal.

Hotel: {name}
Category: {category}
Address: {address}
Rating: {rating}/5 ({rating_count} reviews)
Cancellation policy: {cancellation}
Meal plan: {meal_type}

Output only the description, nothing else."""


def place_id_from_maps_url(url: str) -> str | None:
    m = _PLACE_ID_RE.search(url)
    return m.group(0) if m else None


def fetch_destination_photo(destination: str, api_key: str) -> bytes | None:
    """Fetch a representative panoramic photo for the destination city."""
    try:
        resp = httpx.get(
            f"{_PLACES_BASE}/textsearch/json",
            params={"query": f"{destination} architecture street", "key": api_key},
            timeout=10,
        )
        results = resp.json().get("results", [])
        if not results:
            return None
        photos = results[0].get("photos", [])
        if not photos:
            return None
        ref = photos[0]["photo_reference"]
        photo_resp = httpx.get(
            f"{_PLACES_BASE}/photo",
            params={"maxwidth": 1200, "photo_reference": ref, "key": api_key},
            follow_redirects=True,
            timeout=10,
        )
        return photo_resp.content if photo_resp.status_code == 200 else None
    except Exception:
        return None


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
    description = ai_client.complete(
        prompt,
        max_tokens=300,
        temperature=0.4,
        system=HOTEL_DESCRIPTION_SYSTEM,
    )

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
        dates=hotel.dates,
        room_type=hotel.room_type,
    )


def enrich_hotel_multi_segment(
    hotels: list[HotelRow],
    place_id: str,
    destination: str,
    api_key: str,
    ai_client,
) -> EnrichedHotel:
    """Enrich a hotel that spans multiple room-type segments.

    Fetches Place Details once, distributes hotel gallery photos across
    segments (photo[i] for segment i, last photo recycled if gallery is
    smaller than segment count), builds one AI description for the property.
    """
    # 1. Place Details — one call
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

    official_name = detail.get("name", hotels[0].name)
    address = detail.get("formatted_address", "")
    phone = detail.get("international_phone_number", "")
    rating = float(detail.get("rating", 0))
    rating_count = int(detail.get("user_ratings_total", 0))
    maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

    photo_refs = [p["photo_reference"] for p in detail.get("photos", [])]

    # 2. One photo per segment, distributed from the gallery
    room_segments: list[RoomSegment] = []
    for i, hotel in enumerate(hotels):
        photo_bytes: bytes | None = None
        if photo_refs:
            ref = photo_refs[min(i, len(photo_refs) - 1)]
            photo_resp = httpx.get(
                f"{_PLACES_BASE}/photo",
                params={"maxwidth": 800, "photo_reference": ref, "key": api_key},
                follow_redirects=True,
            )
            if photo_resp.status_code == 200:
                photo_bytes = photo_resp.content
        room_segments.append(RoomSegment(
            room_type=hotel.room_type,
            dates=hotel.dates,
            online_price=hotel.online_price,
            photo_bytes=photo_bytes,
            inclusions=hotel.inclusions,
            exclusions=hotel.exclusions,
        ))

    # 3. One AI description for the property
    prompt = _DESCRIPTION_PROMPT.format(
        name=official_name,
        category=hotels[0].category,
        address=address,
        rating=rating,
        rating_count=rating_count,
        cancellation=hotels[0].cancellation or "Not specified",
        meal_type=hotels[0].meal_type or "Not specified",
    )
    description = ai_client.complete(
        prompt, max_tokens=300, temperature=0.4, system=HOTEL_DESCRIPTION_SYSTEM,
    )

    return EnrichedHotel(
        official_name=official_name,
        address=address,
        phone=phone,
        rating=rating,
        rating_count=rating_count,
        maps_url=maps_url,
        photo_bytes=None,          # superseded by room_segments
        description=description,
        cancellation=hotels[0].cancellation,
        meal_type=hotels[0].meal_type,
        category=hotels[0].category,
        dates="",
        room_type="",
        room_segments=room_segments,
    )
