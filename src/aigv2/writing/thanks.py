import re
from typing import Optional

from pydantic import BaseModel

from src.aigv2.writing.title import _EMOJI
from src.aigv2.writing.voice import VOICE_RULE

SIGN_OFF = "With love,"
SIGNATURE = "Bon Voyage by Marina"
MAX_PARAGRAPH_CHARS = 320
_WE = re.compile(r"(?<![\w'’-])(?:we|we['’](?:d|ll|re|ve)|our|ours|us)(?![\w'’-])", re.I)
_NUMBERISH = re.compile(r"(?:https?://|www\.|@\w|[$€£₹]|\+?\d[\d\s().-]{6,}\d)", re.I)

_EXAMPLE = (
    "Style example (copy the voice, not the facts): "
    "'Thank you for the opportunity to plan your holiday. May this journey to Bali be filled with unforgettable "
    "experiences, beautiful memories and seamless travel moments.' "
    "'Please remember that Bon Voyage by Marina is just a message or a call away for anything you need, before, "
    "during or after your trip.'"
)
_SYSTEM = (
    "You are luna, the writer for Bon Voyage by Marina travel guides. Respond with a single JSON object "
    "{\"paragraphs\": [str, ...]}. Write the closing Thank You note of the guide: one or two short paragraphs "
    f"(each at most {MAX_PARAGRAPH_CHARS} characters) addressed to the client. Thank them for the opportunity to plan "
    "the trip, wish them a wonderful journey to the destination, and say Bon Voyage by Marina is a message or call away "
    "before, during or after the trip. No emojis, no prices, no phone numbers, no links. " + VOICE_RULE + " " + _EXAMPLE
)

FALLBACK = [
    "It has been a pleasure to plan this journey to {destination}. May it be filled with unforgettable experiences, "
    "beautiful memories and seamless travel moments.",
    "Whether before, during or after the trip, a message or call to Bon Voyage by Marina is all it takes for help "
    "with anything that comes up.",
]


class ThankYouText(BaseModel):
    paragraphs: list[str]
    sign_off: str = SIGN_OFF


class _Out(BaseModel):
    paragraphs: list[str]
    sign_off: str = ""


def _names(trip, countries: Optional[dict[str, str]]) -> tuple[list[str], list[str]]:
    cities = list(dict.fromkeys(h.city for h in trip.hotels) or dict.fromkeys(d.city for d in trip.days))
    extra = list(dict.fromkeys(c for c in (countries or {}).values() if c))
    return cities, extra


def destination_text(trip, countries: Optional[dict[str, str]] = None) -> str:
    cities, extra = _names(trip, countries)
    if len(extra) == 1:
        return extra[0]
    return ", ".join(cities) or "your destination"


def fallback_text(trip, countries: Optional[dict[str, str]] = None) -> ThankYouText:
    dest = destination_text(trip, countries)
    return ThankYouText(paragraphs=[p.format(destination=dest) for p in FALLBACK])


def _validator(names: list[str]):
    def validate(out: _Out) -> list[str]:
        problems = []
        paras = [p.strip() for p in out.paragraphs]
        if not 1 <= len(paras) <= 2:
            problems.append("write one or two paragraphs")
        for p in paras:
            if not p:
                problems.append("paragraphs must not be empty")
            if len(p) > MAX_PARAGRAPH_CHARS:
                problems.append(f"each paragraph must be at most {MAX_PARAGRAPH_CHARS} characters")
        text = " ".join(paras)
        if _WE.search(text):
            problems.append("never use we, our or us; address the client as 'you'")
        if names and not any(n.casefold() in text.casefold() for n in names):
            problems.append(f"mention the destination by name ({', '.join(names)})")
        if _EMOJI.search(text):
            problems.append("no emojis")
        if _NUMBERISH.search(text):
            problems.append("no prices, phone numbers or links")
        return problems
    return validate


def write_thank_you(trip, llm, countries: Optional[dict[str, str]] = None) -> ThankYouText:
    cities, extra = _names(trip, countries)
    first = ", ".join(trip.client_names) or "the client"
    children = bool(trip.travellers.kids_ages or trip.travellers.child_counts)
    prompt = (f"Destination cities in order: {', '.join(cities)}\nCountry: {', '.join(extra) or 'unknown'}\n"
              f"Client first name(s): {first}\nOccasion: {trip.occasion or 'none'}\n"
              f"Travellers: {trip.travellers.adults} adults, children travelling: {'yes' if children else 'no'}")
    try:
        out = llm.run_json("thanks", _SYSTEM, prompt, _Out, validate=_validator(cities + extra))
    except Exception:
        return fallback_text(trip, countries)
    return ThankYouText(paragraphs=[p.strip() for p in out.paragraphs])
