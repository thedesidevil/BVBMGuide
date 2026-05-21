# src/aig/sections/health_vaccination.py
from src.aig.context import AIGContext
from src.aig.sections._fallback import library_or_ai

_PROMPT = """\
Provide health and vaccination guidance for Indian travellers visiting {city}.
Distinguish required vs recommended vaccines. Include food/water precautions and
any destination-specific health advice. Keep it practical, not alarmist.
Return a JSON array of strings. No markdown fences."""


def build(context: AIGContext) -> dict:
    cities = []
    for city, _lib in context.library.items():
        tips, ai_generated = library_or_ai(
            context, city, "health_tips", _PROMPT.format(city=city)
        )
        cities.append({"city": city, "tips": tips, "ai_generated": ai_generated})
    return {"cities": cities}
