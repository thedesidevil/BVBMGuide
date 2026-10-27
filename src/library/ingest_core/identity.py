"""Item identity keys used to de-duplicate library entries."""

import re
import unicodedata

IDENTITY_FIELDS: dict[str, list[tuple[str, ...]]] = {
    "restaurants": [("name",)],
    "attractions": [("name",)],
    "hotels": [("name",)],
    "local_dishes": [("name",)],
    "souvenirs": [("item",)],
    "phrases": [("english",), ("local",)],
    "connectivity_tips": [("provider", "kind"), ("provider",), ("tip",)],
    "emergency_contacts": [("service", "number"), ("number",), ("service",)],
    "transport_options": [("mode", "recommended_pass"), ("mode", "description"), ("mode",)],
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
    "embassies": [("name", "city"), ("name",)],
    "route_guides": [("from", "to"), ("from",)],
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
