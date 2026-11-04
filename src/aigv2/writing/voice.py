"""The house voice shared by every writing prompt (modelled on the hand-curated guides)."""
import re

VOICE_RULE = (
    "VOICE: write in the Bon Voyage by Marina house voice. Be warm and descriptive. Describe the place or activity "
    "directly in the third person, or address the client as 'you' and 'your'. Give tips as short imperatives "
    "('Carry a hat and sunscreen.', 'Dress respectfully; shoulders and knees should be covered.'). "
    "NEVER use the words we, we'd, we'll, we're, we've, our, ours or us. Never write 'I'."
)

DAY_EXAMPLES = (
    "Style examples (copy the voice, not the facts): "
    "'Begin the day's sightseeing at Tegallalang Rice Terrace, one of Bali's signature agricultural landscapes. "
    "The terraces cascade down the valley in vivid layers of green.' "
    "'Enjoy a relaxed breakfast at the hotel and keep the morning free for some downtime.' "
    "Restaurants: 'A relaxed garden-style restaurant in central Ubud, offering a mix of Italian and American-inspired "
    "dishes in a cosy, greenery-filled setting.'"
)

SECTION_EXAMPLES = (
    "Style examples (copy the voice, not the facts): "
    "'Textiles are among the most beautiful souvenirs to bring home from Indonesia. Look for colourful batik, "
    "lightweight sarongs and handwoven fabrics.' "
    "'Keep these saved in your phone:' 'Carry a hat and sunscreen.' "
    "'Dress respectfully; shoulders and knees should be covered.' "
    "'Bali is a safe destination health-wise, but due to tropical weather and water-based activities in your "
    "itinerary, basic precautions are advisable.'"
)

TITLE_RULE = "Never address the reader as 'we' or 'our'."

# first-person plural; lower-case "us" only, so "US" (the country) is not flagged
_WE = re.compile(r"(?<![\w'’-])(?:(?i:we|we['’](?:d|ll|re|ve)|our|ours)|us)(?![\w'’-])")


def first_person_problems(label: str, text) -> list[str]:
    m = _WE.search(text) if isinstance(text, str) else None
    return [f"{label} uses '{m.group(0)}'; never write we, our or us; address the client as 'you'"] if m else []
