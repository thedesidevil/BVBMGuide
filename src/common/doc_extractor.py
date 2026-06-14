"""Shared AIG document extraction utilities.

Used by both the library builder (full structured extraction) and the
verify service (lightweight meal-venue extraction for rule checks).
"""

import json
import re
from typing import Optional

from src.common.ai_provider import AIClient


SINGLE_PASS_LIMIT = 120_000
CHUNK_OVERLAP = 2_000

_UNSAFE_UNICODE_RE = re.compile(r'[\U0001FA00-\U0001FFFF\U000E0000-\U000EFFFF\U000F0000-\U0010FFFF]')


def sanitize_text(text: str) -> str:
    """Remove newer/private-use Unicode characters that API gateways may reject."""
    return _UNSAFE_UNICODE_RE.sub('', text)


def repair_truncated_json(text: str) -> Optional[dict]:
    """Attempt to recover a valid JSON object from a truncated AI response.

    Walks the string tracking nesting depth; closes any open containers at the
    end and retries the parse. Falls back to the last known-good position.
    """
    depth: list[str] = []
    in_string = False
    escape = False
    last_safe_pos = 0

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            depth.append(ch)
        elif ch in ('}', ']'):
            if depth:
                depth.pop()
            if not depth:
                last_safe_pos = i + 1

    if in_string:
        text = text + '"'
    if text.rstrip().endswith(':'):
        text = text.rstrip() + ' null'
    closes = {'[': ']', '{': '}'}
    text = text + ''.join(closes[c] for c in reversed(depth))

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    if last_safe_pos > 0:
        candidate = text[:last_safe_pos]
        if not candidate.startswith('{'):
            return None
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return None


def call_and_parse(client: AIClient, prompt: str, label: str) -> Optional[dict]:
    """Send prompt to AI in JSON mode and return the parsed dict, or None on failure."""
    try:
        raw = client.complete_json(prompt, max_tokens=32000)
        raw = raw.strip()
        # Strip markdown fences in case the model wraps JSON anyway
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            result = repair_truncated_json(raw)
            if not result:
                print(f"[doc_extractor] JSON parse failed for {label}")
            return result
    except Exception as e:
        print(f"[doc_extractor] AI call failed for {label}: {e}")
        return None


def split_into_chunks(
    text: str,
    max_chunk_size: int = SINGLE_PASS_LIMIT,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Split text into chunks at paragraph boundaries with optional overlap."""
    if len(text) <= max_chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break
        split_zone_start = end - 5000
        split_zone = text[split_zone_start:end]
        last_para = split_zone.rfind("\n\n")
        if last_para != -1:
            end = split_zone_start + last_para
        else:
            last_nl = split_zone.rfind("\n")
            if last_nl != -1:
                end = split_zone_start + last_nl
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


_DEDUP_KEYS = {
    "restaurants":       "name",
    "attractions":       "name",
    "hotels":            "name",
    "local_dishes":      "name",
    "phrases":           "english",
    "safety_tips":       "tip",
    "souvenirs":         "item",
    "emergency_contacts":"number",
    "connectivity_tips": "tip",
    "transport_options": "mode",
    "health_tips":       "tip",
}


def merge_extraction_results(results: list[dict]) -> dict:
    """Merge multiple chunk extraction results, deduplicating by field-specific keys.

    Works for both the full library schema and the lightweight verify schema —
    any field not in _DEDUP_KEYS is unioned as a plain list.
    """
    merged: dict = {}

    # covered_cities: union
    all_cities: list[str] = []
    for r in results:
        for city in (r.get("covered_cities") or []):
            if city not in all_cities:
                all_cities.append(city)
    if all_cities:
        merged["covered_cities"] = all_cities

    # Fields with known dedup keys
    all_fields = set()
    for r in results:
        all_fields.update(r.keys())
    all_fields.discard("covered_cities")

    for field in all_fields:
        key = _DEDUP_KEYS.get(field)
        combined: list = []
        seen: set[str] = set()
        for r in results:
            for item in (r.get(field) or []):
                if not isinstance(item, dict):
                    continue
                if key:
                    if field == "transport_options":
                        dedup_val = (item.get("city", "").lower().strip() + "|" +
                                     item.get(key, "").lower().strip())
                    else:
                        dedup_val = item.get(key, "").lower().strip()
                    if dedup_val and dedup_val in seen:
                        continue
                    if dedup_val:
                        seen.add(dedup_val)
                combined.append(item)
        if combined:
            merged[field] = combined

    return merged


def extract_from_text(client: AIClient, text: str, prompt_template: str) -> dict:
    """Run AI extraction on text, handling chunking and merging automatically.

    Args:
        client: AIClient instance
        text: Document text (already extracted from DOCX/PDF)
        prompt_template: Prompt with a `{text}` placeholder

    Returns:
        Merged extraction result dict (empty dict on total failure).
    """
    text = sanitize_text(text)
    if len(text) < 50:
        return {}

    if len(text) <= SINGLE_PASS_LIMIT:
        return call_and_parse(client, prompt_template.format(text=text), "document") or {}

    chunks = split_into_chunks(text)
    results = []
    for i, chunk in enumerate(chunks):
        result = call_and_parse(client, prompt_template.format(text=chunk), f"chunk {i+1}/{len(chunks)}")
        if result:
            results.append(result)

    if not results:
        return {}
    if len(results) == 1:
        return results[0]
    return merge_extraction_results(results)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

LIBRARY_EXTRACTION_PROMPT = """\
Extract structured travel information from this All Inclusive Guide document.

DOCUMENT:
{text}

Return a JSON object with exactly this structure:
{{
  "covered_cities": ["City1", "City2"],
  "restaurants": [
    {{
      "name": "Restaurant Name",
      "city": "Paris",
      "cuisine_type": ["Local", "Italian"],
      "price_range": "budget/mid-range/luxury or ₹/₹₹/₹₹₹",
      "hours": "Opening hours",
      "ambience": "Brief description of atmosphere",
      "area": "Neighbourhood or district where the restaurant is located",
      "nearby_landmarks": ["Eiffel Tower, Paris", "Louvre, Paris"],
      "highlights": ["Known for crispy prawns", "Has vegan options", "Popular for happy hour"],
      "must_try_dishes": ["Dish 1", "Dish 2"],
      "best_for": ["romantic", "family", "casual"],
      "vegetarian_friendly": true
    }}
  ],
  "attractions": [
    {{
      "name": "Attraction Name",
      "city": "Paris",
      "description": "Brief description",
      "hours": "Opening hours",
      "entry_fee": "Cost",
      "recommended_duration": "X hours"
    }}
  ],
  "hotels": [
    {{
      "name": "Hotel Name",
      "city": "Paris",
      "location": "Area/neighbourhood"
    }}
  ],
  "local_dishes": [
    {{
      "name": "Dish Name",
      "city": "Paris",
      "description": "What it is",
      "vegetarian": true,
      "where_to_try": "Restaurant or place name"
    }}
  ],
  "phrases": [
    {{
      "city": "France",
      "english": "Hello",
      "local": "Bonjour",
      "category": "greeting/polite/food/emergency"
    }}
  ],
  "safety_tips": [{{"cities": ["France"], "tip": "Tip text"}}],
  "souvenirs": [
    {{
      "item": "Souvenir name or type",
      "city": "Paris",
      "category": "Category (e.g. Food, Fashion, Artisan crafts, Antiques)",
      "where_to_buy": ["Shop name or market", "Area or street"]
    }}
  ],
  "emergency_contacts": [
    {{
      "city": "France",
      "service": "Police",
      "number": "17",
      "notes": "Optional extra info e.g. English-speaking, non-urgent only"
    }}
  ],
  "connectivity_tips": [{{"cities": ["France", "Switzerland"], "tip": "Tip text"}}],
  "transport_options": [
    {{
      "city": "Paris",
      "mode": "Metro",
      "description": "Brief description of the transport mode",
      "recommended_pass": "Pass or card name if applicable",
      "cost": "Price info if mentioned"
    }}
  ],
  "health_tips": [{{"cities": ["France"], "tip": "Tip text"}}]
}}

Rules:
- covered_cities: list every city, town, or tourist area this guide covers (e.g. ["Florence", "Siena", "Pisa"])
- city: REQUIRED on restaurants, attractions, hotels, local_dishes, souvenirs, emergency_contacts, transport_options, and phrases. Set to the specific city or country the item belongs to (e.g. "Paris", "Geneva", "France"). Determine from section headings like "Restaurants in Zurich", "Day 3 – Florence", or explicit mentions in the text. Never leave blank
- cities: REQUIRED on safety_tips, connectivity_tips, and health_tips. A LIST of every city or country the tip applies to. If a tip says "this SIM card works in France, Switzerland and Italy" set cities to ["France", "Switzerland", "Italy"]. If a tip is country-wide for one country set cities to that country name alone e.g. ["France"]. Never leave empty
- Extract ALL restaurants mentioned, not just a few
- Include all details provided (hours, prices, dishes)
- area: the neighbourhood, district, or zone where the restaurant is located. Infer from: (1) section headings like "Dinner Options in Chamonix Town Centre" or "Restaurants near the Louvre"; (2) explicit mentions like "located in Gare de Lyon station", "in the Marais district". Omit if no area context is available
- nearby_landmarks: list of specific attractions, monuments, or landmarks mentioned in proximity to this restaurant. Extract from phrases like "near Eiffel Tower", "5 mins walk from Monet Garden", "option before/after Sacre Coeur", "opposite the Louvre". Only include landmarks explicitly stated — do not infer. Always append the city name when it can be determined from context — e.g. "Eiffel Tower, Paris" or "Monet Garden, Giverny" or "Colosseum, Rome". This is especially important for multi-city guides
- highlights: short factual callouts about the restaurant itself — e.g. "Known for seafood", "Has vegan options", "Good for happy hour", "Serves veg and non-veg buffet", "Only open for dinner". Only include facts about the restaurant explicitly stated in the text. NEVER include any travel time, distance, or directions of any kind (e.g. "5 min walk", "15 min metro ride", "10 min from X", "2 km away", "close to the hotel") — a highlight describes the restaurant, not how to reach it
- vegetarian_friendly: set to true ONLY if the document explicitly states the restaurant has vegetarian or vegan options (e.g. "veg-friendly", "vegan options", "serves vegetarian", "has veg menu"). If the document does not mention it, omit this field entirely — do not set it to false, as that implies we checked and it is not vegetarian-friendly when we simply do not know. NEVER infer from cuisine type
- entry_fee: only include actual costs payable at the venue (e.g. "200 KZT", "$10 USD"). Omit if the value says "included in tour/package", "already included", "tickets are covered", "already booked", "pre-booked", or similar — those are client-specific and not reusable
- souvenirs: extract from any souvenir or shopping section regardless of format — (1) old tabular format with columns "Type of souvenir", "Category", "Where to buy"; (2) new heading-based format with sections like "What to Buy", "Where to Buy", or combined "What to Buy and from where". Map each item to the item/category/where_to_buy fields. where_to_buy should be a list of shop names, markets, streets, or areas mentioned
- emergency_contacts: extract every emergency number explicitly stated — police, ambulance, fire, tourist police, coast guard, embassy hotline. Include service name, number, and any notes (e.g. "English-speaking", "for non-urgent matters"). Omit this field entirely if no numbers are stated
- connectivity_tips: extract tips about local SIM cards, eSIM options, mobile data plans, WiFi availability, recommended providers, and approximate costs. One tip per list item. Omit if no connectivity info is present
- transport_options: extract each mode of transport mentioned (metro, bus, tram, taxi, tuk-tuk, ferry, ride-share app). Include description, recommended pass or card name (e.g. "Navigo card", "Oyster card"), and cost if stated. Omit recommended_pass and cost fields if not mentioned
- health_tips: extract vaccination requirements, recommended vaccinations, health precautions, travel insurance advice, and medical facility information. One tip per list item. Omit if no health info is present
- If a field is not present, omit it or use null
- Return ONLY valid JSON, no explanation"""


VERIFY_EXTRACTION_PROMPT = """\
Extract all meal venue recommendations from this All Inclusive Guide document.

DOCUMENT:
{text}

Return a JSON object with exactly this structure:
{{
  "restaurants": [
    {{
      "name": "Venue name exactly as written",
      "meal_section": "Breakfast" | "Lunch" | "Dinner",
      "opening_hours": "Exact hours string, e.g. 10:30 AM – 5:00 PM or 11 AM–3 PM | 5 PM–10 PM",
      "walk_minutes": 15,
      "travel_minutes": 35
    }}
  ]
}}

Rules:
- Extract EVERY restaurant/café/eatery listed under Breakfast, Lunch, or Dinner headings
- meal_section: exactly one of Breakfast, Lunch, Dinner — infer from the section heading the venue appears under
- opening_hours: copy the exact hours string from the document, including split-session formats like "11 AM–3 PM | 5 PM–10 PM". Omit if not stated
- name: copy the venue name exactly as it appears — do not normalise or translate
- walk_minutes: integer — extract only if the document explicitly states a walking time to this venue (e.g. "15 min walk", "approx. 20 minutes on foot"). Omit if not stated
- travel_minutes: integer — extract only if the document states a travel time by taxi, transit, car, bus, or any non-walking mode (e.g. "25 min by taxi", "30 min metro ride"). Omit if not stated
- Return ONLY valid JSON, no explanation"""
