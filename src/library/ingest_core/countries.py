"""Canonical country shard names.

AIG v2 looks a country shard up with ``Library.country(<country>)`` where
``<country>`` is the last part of the Google address (``pipeline._city_country``):
"USA", "UK", "Türkiye", "United Arab Emirates", "South Korea", "Czechia" ...
(or the library folder name). The ingester must therefore name country shards
with the spelling Google gives, not whatever the model wrote. Each canonical
spelling below is also one v2 recognises (``pipeline._TZ`` or
``money._COUNTRY_CURRENCY``); Myanmar is in neither, Google writes "Myanmar (Burma)".
"""

from .identity import norm_key

_GROUPS: dict[str, tuple[str, ...]] = {
    "USA": ("usa", "us", "u s a", "u s", "united states", "united states of america", "america"),
    "UK": ("uk", "u k", "united kingdom", "england", "scotland", "wales", "northern ireland",
           "great britain", "britain"),
    "United Arab Emirates": ("uae", "u a e", "united arab emirates", "emirates"),
    "Türkiye": ("turkey", "türkiye", "turkiye"),
    "South Korea": ("south korea", "republic of korea", "korea", "korea south", "rok"),
    "Czechia": ("czechia", "czech republic"),
    "Netherlands": ("netherlands", "the netherlands", "holland"),
    "Vietnam": ("vietnam", "viet nam"),
    "Myanmar": ("myanmar", "burma", "myanmar burma"),
}
_ALIAS: dict[str, str] = {norm_key(a): canon for canon, aliases in _GROUPS.items() for a in aliases}


def canonical_country(raw: str) -> str:
    """The one spelling ``Library.country()`` resolves for ``raw``; unknown names are stripped only."""
    stripped = (raw or "").strip()
    return _ALIAS.get(norm_key(stripped), stripped)
