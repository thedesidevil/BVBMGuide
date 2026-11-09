"""Look up a stop in the library by name (no fuzzy matching), and tell generic category names from real places.

Deterministic and conservative: names must match exactly (after folding); a generic name such as
'Coffee Plantation' is never sent to a place search unless the library has exactly one attraction by that name.
"""
import re
from typing import Optional

from src.aigv2.library import norm_name
from src.aigv2.writing.voice import first_person_problems

_PAREN = re.compile(r"\s*\([^)]*\)")
_CATEGORY = {"plantation", "farm", "market", "markets", "temple", "temples", "beach", "beaches", "waterfall",
             "waterfalls", "viewpoint", "view", "point", "lookout", "stop", "village", "shop", "shops", "shopping",
             "cafe", "mall", "sightseeing", "city"}
_GENERIC_MODIFIERS = {"coffee", "tea", "spice", "local", "traditional", "scenic", "free", "time", "city", "tour",
                      "visit", "a", "the", "and", "of", "stop"}
_HARD_WARNING = re.compile(r"not permitted|prohibited|\bmust\b|warning|cliff|strict", re.I)
MAX_GOOD_TO_KNOW = 4


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _PAREN.sub("", norm_name(text)).replace("&", " "))


def core_name(name: str) -> str:
    return " ".join(_tokens(name))


def is_generic_name(name: str) -> bool:
    """A bare category phrase ('Coffee Plantation', 'Local Market'): no proper-noun token to identify one place."""
    toks = [t for t in _tokens(name) if t not in ("visit", "tour")]
    return bool(toks) and all(t in _CATEGORY or t in _GENERIC_MODIFIERS for t in toks) \
        and any(t in _CATEGORY for t in toks)


def match_attraction(name: str, records: list[dict]) -> Optional[tuple[dict, bool]]:
    """(record, exact) for the library attraction with this name, or None. No fuzzy matching: the name must equal a
    library name after case/space folding (exact=True) or after dropping a trailing parenthetical such as
    '(Viewpoint & Scenic Cafe)' (exact=False). Unmatched stays unmatched and is flagged for the team."""
    named = [r for r in records if isinstance(r, dict) and isinstance(r.get("name"), str)]
    key = norm_name(name)
    for r in named:
        if norm_name(r["name"]) == key:
            return r, True
    core = core_name(name)
    if core and core != key and not is_generic_name(name):
        same = [r for r in named if core_name(r["name"]) == core]
        if len({norm_name(r["name"]) for r in same}) == 1:
            return same[0], False
    return None


def lookup(name: str, city_records: list[dict], region_records: list[dict]) -> Optional[tuple[dict, bool]]:
    """City shard first, then the wider region (same exact-name rule), only when a single record carries the name.
    A generic name ('Coffee Plantation') matches only a single same-named record."""
    hit = match_attraction(name, city_records)
    if hit:
        return hit
    same = []
    for r in region_records:
        h = match_attraction(name, [r])
        if h:
            same.append(r)
    return (same[0], True) if len({json_key(r) for r in same}) == 1 else None


def json_key(r: dict) -> str:
    return norm_name(str(r.get("city", ""))) + "|" + norm_name(str(r.get("name", "")))


def good_to_know(lib: dict, limit: int = MAX_GOOD_TO_KNOW) -> list[str]:
    """Library tips, copied verbatim: de-duplicated, no first-person lines, hard warnings first, at most `limit`."""
    raw = lib.get("tips")
    items = [raw] if isinstance(raw, str) else [t for t in raw if isinstance(t, str)] if isinstance(raw, list) else []
    seen, out = set(), []
    for t in items:
        t = t.strip()
        k = re.sub(r"[\s.]+$", "", norm_name(t))
        if not t or k in seen or first_person_problems("tip", t):
            continue
        seen.add(k)
        out.append(t)
    warnings = [t for t in out if _HARD_WARNING.search(t)]
    return (warnings + [t for t in out if t not in warnings])[:max(limit, len(warnings))] if len(warnings) > limit \
        else (warnings + [t for t in out if t not in warnings])[:limit]


def parse_minutes(text) -> Optional[int]:
    """Upper bound of a library duration such as '30-45 minutes' or '1-1.5 Hours'; None when unreadable."""
    if not isinstance(text, str):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)(?:\s*[-–to]+\s*(\d+(?:\.\d+)?))?\s*(hours?|hrs?|h|minutes?|mins?|m)\b", text, re.I)
    if not m:
        return None
    n = float(m.group(2) or m.group(1))
    return round(n * 60) if m.group(3).lower().startswith("h") else round(n)


_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?)\b", re.I)


def _segment_minutes(seg: str) -> Optional[int]:
    total, found = 0.0, False
    for n, unit in _UNIT.findall(seg):
        found = True
        total += float(n) * (60 if unit.lower().startswith("h") else 1)
    return round(total) if found else None


def airport_transfer_minutes(options: list[dict], city: str) -> Optional[int]:
    """Airport-to-city road time from the library's own transport_options text: used only when every airport entry
    for the city gives the same figure (the upper end of a range); otherwise None and the VERIFY marker stays."""
    vals = set()
    for o in options:
        if not isinstance(o, dict) or norm_name(str(o.get("city", ""))) != norm_name(city):
            continue
        text = str(o.get("description") or "")
        if "airport" not in text.lower():
            continue
        for clause in re.split(r";|,\s|\.\s+(?=[A-Z])", text):
            c = clause.lower()
            if norm_name(city) in c and "airport" in c.replace("dps", "airport") and "harbour" not in c:
                parts = [_segment_minutes(x) for x in re.split(r"\s*[\u2013\u2014]\s*", clause)]
                parts = [x for x in parts if x]
                if parts:
                    vals.add(max(parts))
    return vals.pop() if len(vals) == 1 else None
