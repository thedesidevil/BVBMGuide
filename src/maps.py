"""Google Maps URL utilities. No API key required."""

import urllib.parse


def maps_url(name: str, city: str = "") -> str:
    """Generate a Google Maps search URL for a place."""
    query = f"{name} {city}".strip()
    encoded = urllib.parse.quote_plus(query)
    return f"https://www.google.com/maps/search/?api=1&query={encoded}"
