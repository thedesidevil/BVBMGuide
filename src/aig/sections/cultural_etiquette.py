# src/aig/sections/cultural_etiquette.py
from src.aig.context import AIGContext
from src.aig.sections._fallback import library_or_ai

_PROMPT = """\
List 5–8 essential cultural etiquette tips and useful local phrases for {city}.
Return a JSON array of strings, each item being either a phrase with translation
(e.g. "Dank je — Thank you") or a practical tip.
No markdown fences."""


def build(context: AIGContext) -> dict:
    cities = []
    for city, _lib in context.library.items():
        phrases, ai_generated = library_or_ai(
            context, city, "phrases", _PROMPT.format(city=city)
        )
        cities.append({"city": city, "phrases": phrases, "ai_generated": ai_generated})
    return {"cities": cities}
