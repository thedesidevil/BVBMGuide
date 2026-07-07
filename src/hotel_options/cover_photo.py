from __future__ import annotations
import re
import httpx

_MONTH_TO_SEASON = {
    1: "winter", 2: "winter", 3: "spring",
    4: "spring", 5: "spring", 6: "summer",
    7: "summer", 8: "summer", 9: "autumn",
    10: "autumn", 11: "autumn", 12: "winter",
}

_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_MONTH_LABELS = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}


def _infer_month(travel_dates: list[str]) -> int | None:
    earliest = None
    for d in travel_dates:
        for abbr, num in _MONTH_NAMES.items():
            if abbr in d.lower():
                if earliest is None or num < earliest:
                    earliest = num
    return earliest


def _build_query(destination: str, travel_dates: list[str], ai_client) -> str:
    month_num = _infer_month(travel_dates)
    season = _MONTH_TO_SEASON.get(month_num, "landscape") if month_num else "landscape"
    month_name = _MONTH_LABELS.get(month_num, "")
    prompt = (
        f"Generate a short Unsplash photo search query (under 8 words) for a travel cover image "
        f"for {destination} in {month_name or season}. "
        f"Focus on landscapes, nature, and iconic scenery — no people, no interiors. "
        f"Reply with only the search query, nothing else."
    )
    try:
        return ai_client.complete(prompt, max_tokens=30).strip().strip('"')
    except Exception:
        return f"{destination} {season} landscape"


def _fetch_unsplash(query: str, key: str) -> bytes | None:
    try:
        resp = httpx.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "orientation": "landscape", "per_page": 1},
            headers={"Authorization": f"Client-ID {key}"},
            timeout=10,
        )
        results = resp.json().get("results", [])
        if not results:
            return None
        url = results[0]["urls"]["regular"]
        photo = httpx.get(url, timeout=15, follow_redirects=True)
        return photo.content if photo.status_code == 200 else None
    except Exception:
        return None


def _fetch_pexels(query: str, key: str) -> bytes | None:
    try:
        resp = httpx.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "orientation": "landscape", "per_page": 1},
            headers={"Authorization": key},
            timeout=10,
        )
        photos = resp.json().get("photos", [])
        if not photos:
            return None
        url = photos[0]["src"]["large2x"]
        photo = httpx.get(url, timeout=15, follow_redirects=True)
        return photo.content if photo.status_code == 200 else None
    except Exception:
        return None


def fetch_cover_photo(
    destination: str,
    travel_dates: list[str],
    ai_client,
    unsplash_key: str = "",
    pexels_key: str = "",
) -> bytes | None:
    """Fetch a season-appropriate landscape photo for the destination cover page."""
    query = _build_query(destination, travel_dates, ai_client)
    if unsplash_key:
        result = _fetch_unsplash(query, unsplash_key)
        if result:
            return result
    if pexels_key:
        result = _fetch_pexels(query, pexels_key)
        if result:
            return result
    return None
