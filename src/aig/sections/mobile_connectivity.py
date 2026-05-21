# src/aig/sections/mobile_connectivity.py
from src.aig.context import AIGContext
from src.aig.sections._fallback import library_or_ai

_PROMPT = """\
Provide mobile connectivity tips for Indian travellers visiting {city}.
Cover: SIM and eSIM providers, where to buy, approximate cost, and coverage quality.
Return a JSON array of strings (one tip per item). No markdown fences."""


def build(context: AIGContext) -> dict:
    cities = []
    for city, _lib in context.library.items():
        tips, ai_generated = library_or_ai(
            context, city, "connectivity_tips", _PROMPT.format(city=city)
        )
        cities.append({"city": city, "tips": tips, "ai_generated": ai_generated})
    return {"cities": cities}
