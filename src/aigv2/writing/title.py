from src.aigv2.textnorm import fold
import re

from src.aigv2.writing.voice import first_person_problems

from pydantic import BaseModel

_SYSTEM = (
    "You are luna, the writer for Bon Voyage by Marina travel guides. Respond with a single JSON object "
    "{\"title\": str}. Write a creative, destination-specific title of 2 to 5 words in American English. "
    "Never use 'we' or 'our'. Never use the phrase 'All Inclusive Guide'. No emojis, no quotes."
)
_GENERIC = {"your", "my", "our", "the", "a", "an", "of", "to", "and", "trip", "travel", "guide", "holiday",
            "vacation", "journey", "adventure", "adventures", "itinerary", "tour", "tours", "plan", "travels"}
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")


class TitleOut(BaseModel):
    title: str


def _clean(t: str) -> str:
    return t.strip().strip("\"'“”‘’`").strip()


def _validate(out: TitleOut) -> list[str]:
    t = _clean(out.title)
    words = t.split()
    problems = []
    if not 2 <= len(words) <= 5:
        problems.append("title must be 2 to 5 words")
    if re.search(r"all[\s-]*inclusive[\s-]*guide", t, re.I):
        problems.append("title must not contain 'All Inclusive Guide'")
    if _EMOJI.search(t):
        problems.append("title must not contain emojis")
    problems += first_person_problems("title", t)
    if words and all(re.sub(r"\W", "", fold(w)) in _GENERIC for w in words):
        problems.append("title is generic; make it destination-specific")
    return problems


def names_destination(title: str, places: list[str]) -> bool:
    """True when the title contains a trip city or country by name (the same test the QC title rule applies;
    'Parisian' alone does not count)."""
    low = " " + " ".join(re.findall(r"[^\W_]+", fold(title))) + " "
    return any(" " + " ".join(re.findall(r"[^\W_]+", fold(p))) + " " in low for p in places if p.strip())


def write_title(trip, llm, countries=()) -> str:
    cities = list(dict.fromkeys(h.city for h in trip.hotels))
    places = cities + [c for c in dict.fromkeys(countries) if c]

    def validate(out: TitleOut) -> list[str]:
        problems = _validate(out)
        if not names_destination(_clean(out.title), places):
            problems.append(f"title must name a destination: one of {', '.join(places)}")
        return problems

    prompt = (f"Destinations in order: {', '.join(cities)}\nScope: {trip.trip_scope}\n"
              f"Occasion: {trip.occasion or 'none'}\nTravellers: {trip.travellers.adults} adults, "
              f"children ages {trip.travellers.kids_ages or 'none'}")
    out = llm.run_json("title", _SYSTEM, prompt, TitleOut, validate=validate)
    return _clean(out.title)
