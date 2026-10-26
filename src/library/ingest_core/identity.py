"""Item identity keys used to de-duplicate library entries."""

import re
import unicodedata

IDENTITY_FIELDS: dict[str, list[tuple[str, ...]]] = {
    "restaurants": [("name",)],
    "attractions": [("name",)],
    "hotels": [("name",)],
    "local_dishes": [("name",)],
    "souvenirs": [("item",)],
    "phrases": [("english",)],
    "connectivity_tips": [("provider", "kind"), ("tip",)],
    "emergency_contacts": [("service", "number"), ("number",)],
    "transport_options": [("mode",)],
    "safety_tips": [("tip",), ("text",)],
    "health_tips": [("tip",), ("text",)],
    "tipping": [("tip",), ("text",)],
    "dos_donts": [("tip",), ("text",)],
    "scams": [("tip",), ("text",)],
    "insurance": [("tip",), ("text",)],
    "money": [("tip",), ("text",)],
    "season_notes": [("tip",), ("text",)],
    "apps": [("name",)],
    "plugs": [("type",)],
    "embassies": [("name", "city")],
    "route_guides": [("from", "to")],
}


def norm_key(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s).casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w]+|_+", " ", s).strip()
    if s.startswith("the "):
        s = s[4:]
    return s.strip()


def item_key(list_name: str, item: dict) -> str:
    for fields in IDENTITY_FIELDS.get(list_name, []):
        parts = []
        for f in fields:
            v = item.get(f)
            if v is None or not str(v).strip():
                break
            parts.append(norm_key(v))
        else:
            if all(parts):
                return "|".join(parts)
    return ""


def city_shard_name(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.strip()).title()
