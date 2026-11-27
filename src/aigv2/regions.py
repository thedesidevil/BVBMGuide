"""Regional context for reference sections (dishes, souvenirs, etiquette, phrases, getting around).

India differs by state, so a small town the library has no shard for (Wayanad) borrows its state's shard (Kerala), and
country-level India facts are kept only when they come from the trip's own region. Extend the tables below as the
library grows; nothing here is guessed from the model."""
import re
from typing import Optional

from src.aigv2.textnorm import fold

# town / district -> state (library shard name). Lower-case, accent-folded keys.
TOWN_STATE = {
    "wayanad": "Kerala", "sultan bathery": "Kerala", "sulthan bathery": "Kerala", "kalpetta": "Kerala",
    "vythiri": "Kerala", "mananthavady": "Kerala", "chulliyode": "Kerala", "meppadi": "Kerala",
    "mysore": "Karnataka", "mysuru": "Karnataka", "srirangapatna": "Karnataka", "bandipur": "Karnataka",
    "kabini": "Karnataka", "coorg": "Karnataka", "madikeri": "Karnataka", "hampi": "Karnataka",
    "bangalore": "Karnataka", "bengaluru": "Karnataka",
    "munnar": "Kerala", "thekkady": "Kerala", "alleppey": "Kerala", "alappuzha": "Kerala", "kumarakom": "Kerala",
    "kochi": "Kerala", "cochin": "Kerala", "fort kochi": "Kerala", "kovalam": "Kerala",
    "thiruvananthapuram": "Kerala", "athirappilly": "Kerala", "varkala": "Kerala",
}
STATE_ALIASES = {"keralam": "Kerala", "kerala": "Kerala", "karnataka": "Karnataka", "tamil nadu": "Tamil Nadu"}

# language spoken in each state (only where the phrase lexicon below can tell the languages apart)
STATE_LANGUAGE = {"Kerala": "Malayalam", "Karnataka": "Kannada", "Tamil Nadu": "Tamil"}

# library source folder (first path part of _source_file) -> the states its guides covered
FOLDER_STATES = {
    "karnataka, kerala and tamil nadu": {"Kerala", "Karnataka", "Tamil Nadu"},
}

_MALAYALAM = {"namaskaaram", "namaskaram", "nanni", "dayavaayi", "dayavayi", "athe", "kshamikkanam", "njaan", "ithu",
              "sukhamano", "sukhamaano", "enikku", "ivide", "ithinte", "vila", "ethra", "pokanam", "airportilekku"}
_KANNADA = {"namaskara", "dhanyavaadagalu", "haudu", "howdu", "dayavittu", "idu", "elli", "ide", "eshtu", "nanage",
            "gothilla", "neeru", "oota", "beku", "swalpa", "kodi", "heli", "yavaga", "agatte", "parvagilla",
            "chennagide", "hegiddira", "hogi", "banni", "maadi"}

# places that mark an etiquette tip as written for another region (used only to top up a thin regional list)
OTHER_REGION_WORDS = (
    "sikkim", "meghalaya", "mawlynnong", "nagaland", "kohima", "assam", "darjeeling", "gangtok", "tsomgo", "nathula",
    "shillong", "gujarat", "rajasthan", "ladakh", "himachal", "kashmir", "goa", "andaman", "punjab", "bengal",
    "mizoram", "manipur", "arunachal", "tripura", "monastery", "monasteries", "rann", "kutch",
)


def canonical_state(text: str) -> Optional[str]:
    return STATE_ALIASES.get(fold(text or "").strip())


def state_of(city: str, address: str = "") -> Optional[str]:
    """The state a town belongs to: the town table first, else the state named in a Google address ('..., Keralam 673592, India')."""
    s = TOWN_STATE.get(fold(city or "").strip())
    if s:
        return s
    for part in reversed([p.strip() for p in re.split(r",", address or "")]):
        st = canonical_state(re.sub(r"[\d-]+", "", part))
        if st:
            return st
    return canonical_state(city)


def folder_states(source_file: str) -> set[str]:
    folder = (source_file or "").split("/")[0].strip().casefold()
    return set(FOLDER_STATES.get(folder, set()))


def phrase_language(local: str) -> Optional[str]:
    """Malayalam / Kannada when the phrase's words say so, else None."""
    words = set(re.findall(r"[a-z]+", fold(local or "")))
    m, k = len(words & _MALAYALAM), len(words & _KANNADA)
    if m > k:
        return "Malayalam"
    if k > m:
        return "Kannada"
    return None


_SELF_DRIVE = re.compile(r"self[- ]?drive|car (?:hire|rental)|rent(?:al)? a car|rental car", re.I)
_PACKING_TIP = re.compile(r"^\s*(?:carry|pack|bring)\b", re.I)
FILL_KEYS = ("local_dishes", "souvenirs", "phrases", "safety_tips", "emergency_contacts", "health_tips",
             "connectivity_tips", "transport_options", "season_notes")
_CITY_TAGGED = ("transport_options", "souvenirs", "local_dishes")
MIN_REGIONAL_DOS = 6


def is_self_drive(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    return bool(_SELF_DRIVE.search(f"{entry.get('mode', '')} {entry.get('description', '')}"))


def drop_off_trip_city(items: list, allowed: set[str]) -> list:
    """Country-level library entries tagged with a city the trip never visits (a Goa car hire, the Darjeeling toy train)
    are dropped. Entries with no city tag, or a tag the trip (or its country / state) covers, stay."""
    if not allowed:
        return items
    out = []
    for e in items:
        city = fold(e.get("city") or "").strip() if isinstance(e, dict) else ""
        if city and city not in allowed:
            continue
        out.append(e)
    return out


def _source(e: dict) -> str:
    return (e.get("_source_file") or "").split("/")[0].strip().casefold()


def _other_region(tip: str) -> bool:
    t = fold(tip)
    return any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", t) for w in OTHER_REGION_WORDS)


def region_entries(name: str, items: list, states: set[str]) -> list:
    """Country-level phrases and dos/don'ts from the trip's own region. India's pool mixes every state's guides: the
    entries that came from a guide of the trip's states are kept, phrases are narrowed to the trip's languages, and a
    thin etiquette list is topped up only with tips that name no other region and are not packing advice."""
    if not states or name not in ("phrases", "dos_donts"):
        return items
    folders = {f for f, s in FOLDER_STATES.items() if s & states}
    regional = [e for e in items if isinstance(e, dict) and _source(e) in folders]
    if not folders or not regional:
        return items
    if name == "phrases":
        langs = {STATE_LANGUAGE[s] for s in states if s in STATE_LANGUAGE}
        keep = [e for e in regional if not langs or phrase_language(e.get("local", "")) in (*langs, None)]
        return [{**e, "language": phrase_language(e.get("local", "")) or ""} for e in keep]
    regional = [e for e in regional if not _PACKING_TIP.match(e.get("tip", ""))]  # the packing list covers these
    if len(regional) >= MIN_REGIONAL_DOS:
        return regional
    rest = [e for e in items if isinstance(e, dict) and e not in regional and not _other_region(e.get("tip", ""))
            and not _PACKING_TIP.match(e.get("tip", ""))]
    return regional + rest
