# src/aig/sections/safety_contacts.py
from src.aig.context import AIGContext
from src.aig.sections._fallback import library_or_ai

_PROMPT = """\
Provide safety tips and emergency contacts for Indian travellers in {city}.
Include: Indian embassy details, police/ambulance numbers, common scams, practical safety advice.
Return a JSON array of strings. No markdown fences."""


def build(context: AIGContext) -> dict:
    cities = []
    for city, _lib in context.library.items():
        tips, ai_generated = library_or_ai(
            context, city, "safety_tips", _PROMPT.format(city=city)
        )
        cities.append({"city": city, "tips": tips, "ai_generated": ai_generated})
    return {"cities": cities}
