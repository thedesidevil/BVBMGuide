import re

from pydantic import BaseModel

_SYSTEM = (
    "You are luna, the writer for Bon Voyage by Marina travel guides. Respond with a single JSON object "
    "{\"title\": str}. Write a creative, destination-specific title of 2 to 5 words in American English. "
    "Never use the phrase 'All Inclusive Guide'. No emojis, no quotes."
)
_GENERIC = {"your", "my", "our", "the", "a", "an", "of", "to", "and", "trip", "travel", "guide", "holiday",
            "vacation", "journey", "adventure", "adventures", "itinerary", "tour", "tours", "plan", "travels"}
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")


class TitleOut(BaseModel):
    title: str


def _validate(out: TitleOut) -> list[str]:
    t = out.title.strip()
    words = t.split()
    problems = []
    if not 2 <= len(words) <= 5:
        problems.append("title must be 2 to 5 words")
    if "all inclusive guide" in t.casefold():
        problems.append("title must not contain 'All Inclusive Guide'")
    if _EMOJI.search(t):
        problems.append("title must not contain emojis")
    if words and all(re.sub(r"\W", "", w).casefold() in _GENERIC for w in words):
        problems.append("title is generic; make it destination-specific")
    return problems


def write_title(trip, llm) -> str:
    cities = list(dict.fromkeys(h.city for h in trip.hotels))
    prompt = (f"Destinations in order: {', '.join(cities)}\nScope: {trip.trip_scope}\n"
              f"Occasion: {trip.occasion or 'none'}\nTravellers: {trip.travellers.adults} adults, "
              f"children ages {trip.travellers.kids_ages or 'none'}")
    out = llm.run_json("title", _SYSTEM, prompt, TitleOut, validate=_validate)
    return out.title.strip()
