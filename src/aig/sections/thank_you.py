from src.aig.context import AIGContext

_THANK_YOU_TEXT = (
    "Thank you for choosing Bon Voyage by Marina. "
    "We hope this guide makes your journey seamless, joyful, and truly unforgettable. "
    "Should you need anything during your trip, don't hesitate to reach out.\n\n"
    "Bon Voyage By Marina — Crafting unforgettable journeys.\n"
    "📞 +91-86000-15316  |  ✉ hello@bonvoyagebymarina.com"
)


def build(context: AIGContext) -> dict:
    return {"text": _THANK_YOU_TEXT}
