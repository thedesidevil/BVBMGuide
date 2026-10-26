"""Extraction prompt for the redesigned library ingester.

One document pass returns city-level lists (each item tagged with its city)
and country-level content (``country_content``), so country shards are fed
directly from the same call.
"""

CITY_LISTS: tuple[str, ...] = (
    "restaurants",
    "attractions",
    "hotels",
    "local_dishes",
    "phrases",
    "safety_tips",
    "souvenirs",
    "emergency_contacts",
    "connectivity_tips",
    "transport_options",
    "health_tips",
    "route_guides",
    "season_notes",
)

COUNTRY_LISTS: tuple[str, ...] = (
    "plugs",
    "tipping",
    "dos_donts",
    "scams",
    "insurance",
    "apps",
    "money",
    "embassies",
    "season_notes",
    "phrases",
    "safety_tips",
    "emergency_contacts",
    "connectivity_tips",
    "health_tips",
    "transport_options",
)

# Lists whose city-level items carry ``cities: [..]`` instead of ``city``.
TIP_LISTS: tuple[str, ...] = ("safety_tips", "connectivity_tips", "health_tips")

EXTRACTION_PROMPT = """\
Extract reusable travel facts from this All Inclusive Guide so they can be reused for other clients.

DOCUMENT:
{text}

Return ONLY a JSON object with this structure (omit any list or field with no data):
{{
  "covered_cities": ["Florence", "Rome"],
  "city_countries": {{"Florence": "Italy", "Rome": "Italy"}},
  "restaurants": [{{"name": "", "city": "Florence", "cuisine_type": ["Tuscan"], "price_range": "", "hours": "", "ambience": "", "area": "", "nearby_landmarks": ["Duomo, Florence"], "highlights": [""], "must_try_dishes": [""], "best_for": ["family"], "vegetarian_friendly": true, "meal_slots": ["lunch"], "notes": ""}}],
  "attractions": [{{"name": "", "city": "", "description": "", "hours": "", "entry_fee": "", "recommended_duration": "", "dress_code": "", "tips": [""]}}],
  "hotels": [{{"name": "", "city": "", "location": ""}}],
  "local_dishes": [{{"name": "", "city": "", "description": "", "vegetarian": true, "where_to_try": ""}}],
  "phrases": [{{"city": "", "english": "Hello", "local": "Ciao", "category": "greeting"}}],
  "souvenirs": [{{"item": "", "city": "", "category": "", "where_to_buy": [""]}}],
  "emergency_contacts": [{{"city": "", "service": "", "number": "", "notes": ""}}],
  "transport_options": [{{"city": "", "mode": "Metro", "description": "", "recommended_pass": "", "cost": "", "how_to_use": "", "covers": ""}}],
  "route_guides": [{{"city": "", "from": "Florence", "to": "Siena", "stops": [{{"name": "", "minutes": 30, "suggested_stop": ""}}], "total_km": 75, "total_time": "1h 15m"}}],
  "season_notes": [{{"city": "", "tip": ""}}],
  "safety_tips": [{{"cities": ["Rome"], "tip": ""}}],
  "health_tips": [{{"cities": ["Rome"], "tip": ""}}],
  "connectivity_tips": [{{"cities": ["Rome"], "tip": ""}}],
  "country_content": [{{
    "country": "Italy",
    "currency": "EUR",
    "plugs": [{{"type": "F", "voltage": "230V"}}],
    "tipping": [{{"tip": ""}}],
    "dos_donts": [{{"tip": ""}}],
    "scams": [{{"tip": ""}}],
    "insurance": [{{"tip": ""}}],
    "apps": [{{"name": "", "purpose": ""}}],
    "money": [{{"tip": ""}}],
    "embassies": [{{"name": "", "address": "", "phone": "", "email": "", "after_hours": "", "city": ""}}],
    "season_notes": [{{"tip": ""}}],
    "phrases": [{{"english": "", "local": "", "category": ""}}],
    "safety_tips": [{{"tip": ""}}],
    "emergency_contacts": [{{"service": "", "number": "", "notes": ""}}],
    "connectivity_tips": [{{"provider": "", "kind": "esim", "price_text": "", "coverage_countries": ["Italy", "France"], "notes": ""}}],
    "health_tips": [{{"tip": ""}}],
    "transport_options": [{{"mode": "", "description": "", "recommended_pass": "", "cost": "", "how_to_use": "", "covers": ""}}]
  }}]
}}

Rules:
- Reusable facts only. Never copy client names, travel dates, booking references, confirmation numbers, day numbers, or client wording such as "your hotel", "your driver", "on Day 3". Rewrite a fact without them, or skip it.
- Skip any text containing ⚠, VERIFY, ADD RESTAURANT, PRICE UNKNOWN, WRITE PERSONAL LETTER or CHECK:, and any assistant chatter ("I would recommend", "Here are...").
- Table rows appear as cells joined by " | ". Read them as content: old-format guides put each day in a table row (with meals and sights in cells), and souvenir lists may be tables with columns such as Type of souvenir | Category | Where to buy.
- covered_cities: every city, town or tourist area the guide covers. city_countries: the country of each covered city.
- City level vs country level: put a fact under country_content when it applies to a whole country (tipping, plugs, national emergency numbers, SIM/eSIM, language phrases, visas/health, nationwide passes). Use the top-level lists only for facts tied to a specific city or area.
- city: required on every top-level item except safety_tips, health_tips and connectivity_tips, which carry cities: a list of every city the tip applies to.
- A country-level item that applies to several countries (e.g. a multi-country eSIM or rail pass) is repeated in each of those countries' country_content entries.
- currency: ISO 4217 code (EUR, JPY, AED). money: forex, cards, ATMs; never exchange rates.
- Tips and text items: one fact per item, short canonical wording (e.g. "Tipping is not expected in restaurants"), no lead-in phrases.
- restaurants: extract all. meal_slots: breakfast/lunch/dinner, only when a heading or table column the restaurant appears under states the meal; otherwise omit. notes: dietary or other facts about the venue (e.g. "Jain food on request"). highlights describe the venue, never travel time or distance. vegetarian_friendly only when the text says so; never false. nearby_landmarks: only landmarks stated, written "Landmark, City".
- attractions: entry_fee only for costs payable at the venue (omit "included", "pre-booked"); dress_code and tips (visit advice such as best time, queues) only when stated.
- transport_options: each mode or pass; how_to_use is the practical how-to (buying, validating, apps); covers is what the pass or ticket covers.
- connectivity_tips in country_content: provider, kind (sim/esim/wifi), price_text as written, coverage_countries, notes.
- route_guides: drive-day stop sequences with stops in order, minutes per leg, suggested_stop (what to do there), total_km and total_time when stated.
- Keep prices, provider names and hours as written. Omit missing fields; never invent.
- Return ONLY valid JSON, no explanation."""
