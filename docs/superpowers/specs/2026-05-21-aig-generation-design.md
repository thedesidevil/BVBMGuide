# AIG Generation Pipeline — Design Spec

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Generate a complete, client-ready All Inclusive Guide (DOCX) from `trip_facts.json` and the BVBM library, with per-day regeneration and Google Places verification.

**Supersedes:** `docs/REQUIREMENTS.md`, `docs/AIG_STRUCTURE.md`, `docs/AIG_QC_CHECK.md`, `docs/CUSTOMGPT_INSTRUCTIONS.md`, `docs/INSTRUCTION_ANALYSIS.md`

---

## Output Contract

- Format: `.docx` built from a committed `src/aig/template.dotx` style template
- No letterhead — Marina pastes output into her letterhead template
- No Table of Contents — Marina builds it in Google Docs after pasting
- Sections generated in mandatory order (see Section Order below)
- Every venue (hotel, attraction, restaurant, pharmacy, grocery, hospital) has a Google Maps link using `https://www.google.com/maps/search/?api=1&query=PLACE+NAME`

---

## CLI Commands

```bash
# Full build: context → all days → all sections → assemble DOCX
python -m src.aig generate input/

# Full build with Google Places library verification
python -m src.aig generate input/ --verify

# Regenerate one day (e.g. Day 3 with taxi override), then reassemble
python -m src.aig redo-day input/ --day 3 --note "client wants taxis today"

# Reassemble DOCX from existing day/section JSONs (no AI, formatting only)
python -m src.aig assemble input/

# Regenerate one supplementary section, then reassemble
python -m src.aig redo-section input/ --section packing-list

# Build the .dotx style template (run once, or after style changes)
python -m src.aig build-template
```

---

## Three-Phase Architecture

### Phase 1 — Build AIGContext
Run once per guide session. Loads all data needed by every section builder.

**Steps:**
1. Load `trip_facts.json` → `TripFacts`
2. Extract unique destination cities from `TripFacts.destinations` and `hotels`
3. Load library DB records for each city: restaurants, attractions, local_dishes, souvenirs, transport_options, emergency_contacts, cultural_etiquette, connectivity_tips, health_tips, safety_tips
4. Geocode each hotel: `hotel_name + ", " + city` → (lat, lng) via Geocoding API
5. Run Google Places Nearby Search for Important Places per hotel (see Important Places section)
6. If `--verify` flag: verify library restaurants and attractions against Google Places Details API; update DB records and write audit entries where data has changed

**Output:** `AIGContext` dataclass stored in memory for the session.

```python
@dataclass
class CityLibraryData:
    restaurants: list[dict]
    attractions: list[dict]
    local_dishes: list[dict]
    souvenirs: list[dict]
    transport_options: list[dict]
    emergency_contacts: list[dict]
    cultural_etiquette: str | None    # None if not yet in library
    connectivity_tips: str | None
    safety_tips: str | None
    health_tips: str | None

@dataclass
class AIGContext:
    facts: TripFacts
    library: dict[str, CityLibraryData]   # keyed by city name
    hotel_coords: dict[str, tuple[float, float]]  # hotel_name → (lat, lng)
    important_places: dict[str, ImportantPlacesData]  # hotel_name → places
```

### Phase 2 — Generate Content (per day + per section)
Each piece of content is generated independently and saved as JSON in `input/days/` or `input/sections/`. Content can be regenerated in isolation without rebuilding the whole guide.

**File layout after a full build:**
```
input/
  trip_facts.json
  days/
    day_01.json
    day_02.json
    ...
    day_17.json
  sections/
    client_info.json
    important_places.json
    souvenir_guide.json
    must_try_dishes.json
    getting_around.json
    cultural_etiquette.json
    packing_list.json
    mobile_connectivity.json
    safety_contacts.json
    health_vaccination.json
    cover.json
```

### Phase 3 — Assemble DOCX
Pure rendering step. No AI calls. Reads all JSONs, applies `.dotx` styles, writes final DOCX. Sections rendered in mandatory order. Fast and repeatable.

---

## Day Generation Detail

Entry point: `build_day(context: AIGContext, day_number: int, overrides: dict | None = None) -> DayContent`

Saves result to `input/days/day_{N:02d}.json`.

### Step 1 — Load activities in order
Read `TripFacts.days[day_number - 1].activities`. This list is **immutable and ordered** — activities must appear in the guide in exactly this sequence. Never reorder, never skip.

Also read from the same `TripDay`:
- `date`, `title`, `overnight_city`, `overnight_hotel`
- `transport_note` (day-specific override, e.g. "Transfer to Eindhoven Airport")

### Step 2 — Enrich each activity from library
For each activity string, fuzzy-match against `context.library[city].attractions` by name. If matched:
- Use stored `hours`, `entry_fee`, `recommended_duration`
- Flag: `source: "library"`

If no library match:
- AI fills in `hours`, `entry_fee`, `recommended_duration`
- Flag: `source: "ai_estimated"` — rendered with a subtle marker so Marina can spot-check

### Step 3 — Build travel chain (AI call)
Send one AI prompt containing:
- Ordered activity list with enriched facts
- Hotel name + city (starting point for Day 1 activity and any post-rest activity)
- Effective transport mode: `overrides.get("transport") or TripDay.transport_note or TripFacts.local_transport`
- Rule for chain: *"Depart from hotel for the first activity. Each subsequent activity departs from the previous one. If an activity contains 'return to hotel', 'rest', 'freshen up', 'check in', or 'nap' — reset the departure point to the hotel for all following activities."*
- Instruction: *"For each travel leg, suggest the most practical transport mode. If two locations are within 500m, suggest walking regardless of the default mode. Provide estimated travel time, transport mode, and one practical tip per leg."*

AI returns per-activity: `vivid_description` (2–3 immersive sentences), and per-leg: `from`, `to`, `mode`, `duration`, `tip`.

### Step 4 — Select restaurants
**Effective city:** `TripDay.overnight_city` (or cruise port city for port days)

**Lunch (3 options):**
- Find restaurants in `context.library[city].restaurants` whose `nearby_landmarks` or `area` matches attractions visited in the first half of the day
- Filter by `TripFacts.dietary_restrictions` and `food_allergies`
- Apply rotation: same restaurant must not appear in lunch or dinner within the preceding 2 days
- If library has fewer than 3 matching options: AI curates remaining picks (marked `source: "ai_curated"`)

**Dinner (3 options):**
- Find restaurants near the overnight hotel (match `nearby_landmarks` to hotel name, or `area` to hotel neighbourhood)
- Same filters and rotation rules
- AI curates shortfall if needed

**Cruise ship days / "At Sea" days:**
- No library restaurant lookup — note reads "Enjoy onboard dining"
- Lunch and dinner sections are omitted or replaced with a short note about onboard options

### Step 5 — Save
Write `DayContent` as `input/days/day_{N:02d}.json`.

---

## Supplementary Sections

### Client Information Page
Source: assembled from `TripFacts`, no AI.

Content:
- Client names, num_guests, departure city, dietary preferences
- Trip summary table (one row per hotel): City | Dates | Hotel (Maps link) | Transport summary

### Cover
Source: AI.

Content: AI generates a creative, destination-specific title (e.g. *"Windmills, Renaissance & Mediterranean Dreams"*) and a subtitle summarising the trip. One prompt, trip-level.

### Important Places Around Your Stay
Source: Google Places Nearby Search per hotel. No library, no AI generation.

Per hotel, run three searches using hotel coordinates from `AIGContext.hotel_coords`:

| Type | Initial radius | Expansion sequence | Max attempts |
|---|---|---|---|
| `pharmacy` | 1 km | 1 km → 2 km → 4 km | 3 |
| `grocery_or_supermarket` | 1 km | 1 km → 2 km → 4 km | 3 |
| `hospital` | 5 km | 5 km → 10 km → 25 km | 3 |

Ranking:
- Pharmacy / grocery: sort by walking distance ascending; break ties by longest opening hours
- Hospital: must be open 24/7 with emergency capability; take nearest qualifying result

If nothing found after 3 attempts: leave section blank with placeholder text for Marina to fill in.

### Must-Try Local Dishes
Source: `context.library[city].local_dishes`. No AI. One section per destination city. Grouped by type (street food, mains, drinks/desserts).

### Souvenir Shopping Guide
Source: `context.library[city].souvenirs`. No AI. One section per destination city.

### Getting Around
Source: `context.library[city].transport_options`. No AI. Covers ticketing method, apps, pass recommendations, practical tips.

### Cultural Etiquette & Local Phrases
Source: library first (`cultural_etiquette` field), AI fallback if empty, write back to library.

Content: 4–5 practical local phrases, tipping customs, dress codes, greeting norms. One section per destination country (not per city — etiquette is country-level).

Write-back: if AI generated, save to library with `updated_by: "AI while building {client_names} guide {date}"`.

### Tailored Packing List
Source: AI only (trip-specific, not reusable).

Context passed to AI: trip dates (to infer season), destination cities, activity types from days (beach, hiking, formal dining, religious sites), dietary/cultural notes. Produces a packing list specific to this trip — not generic.

### Mobile Connectivity Guide
Source: library first (`connectivity_tips` field per city/country), AI fallback if empty, write back to library.

Content: SIM and eSIM providers, where to buy, documents needed, cost expectations, coverage quality.

### Safety & Emergency Contacts
Source: library first (`safety_tips` + `emergency_contacts` per city), AI fallback if empty, write back to library.

Content: Indian embassy details, police/ambulance/fire numbers, common scams to avoid, practical safety tips for the destination.

### Health & Vaccination Guidance
Source: library first (`health_tips` per country), AI fallback if empty, write back to library.

Content: Required vs optional vaccines, food/water precautions, mosquito repellent advice, first-aid items. Not alarmist — only what's relevant to the destination.

### Thank You Page
Source: static template text ("Thank you for choosing Bon Voyage by Marina…"). No AI, no library. Fixed content.

---

## Section Order in Generated DOCX

Mandatory order (TOC and letterhead excluded — Marina adds those):

1. Cover (title + subtitle)
2. Client Information + Trip Summary
3. Day-wise Itinerary (Day 1 → Day N)
4. Important Places Around Your Stay
5. Souvenir Shopping Guide
6. Must-Try Local Dishes
7. Getting Around
8. Cultural Etiquette & Local Phrases
9. Tailored Packing List
10. Mobile Connectivity Guide
11. Safety & Emergency Contacts
12. Health & Vaccination Guidance
13. Thank You Page

---

## DOCX Template Styles

Template file: `src/aig/template.dotx` — built by `python -m src.aig build-template`, committed to repo.

| Style name | Used for |
|---|---|
| `AIG Title` | Cover page trip title |
| `AIG Subtitle` | Cover page subtitle / trip dates summary |
| `AIG Day Heading` | `Day 3: Wednesday, 23 Apr — Florence Highlights` |
| `AIG Section Heading` | Supplementary section headers |
| `AIG Subsection` | Meal type headers, time-of-day headers |
| `AIG Body` | Activity descriptions, narrative text |
| `AIG Restaurant Name` | Bold restaurant name (hyperlinked to Maps) |
| `AIG Detail` | Hours / fee / travel time line |
| `AIG Bullet` | Bullet-point activity items |
| `AIG Table` | Client info trip summary table |
| `AIG Overnight` | ✅ Overnight in [City] line |
| `AIG Note` | AI-estimated / AI-curated markers for Marina's review |

Day heading format: `Day X: DayOfWeek, DD Mon — Title`
Example: `Day 1: Sunday, 19 Apr — Arrival in Amsterdam`

---

## Google Places Verification (--verify)

When `--verify` is passed to `generate`:

For each restaurant and attraction in the library records used by this guide:
1. Call Place Details API (`fields: name,opening_hours,business_status`)
2. Compare `opening_hours.weekday_text` and `business_status` against stored library values
3. If different: update the library DB record, write audit entry:
   ```json
   { "updated_by": "AI while building Agarwal guide 2026-05-21",
     "field": "hours",
     "old": "9am-6pm",
     "new": "10am-8pm (Mon-Sat), closed Sun" }
   ```
4. If `business_status` is `CLOSED_PERMANENTLY`: flag the record as inactive; do not include in future recommendations

Places API SKUs used:
- Geocoding: `$0.005/req`, 10,000 free/month
- Nearby Search Pro: `$0.032/req`, 5,000 free/month
- Place Details Pro: `$0.017/req`, 5,000 free/month

Estimated cost per guide: <$0.01 for Important Places; ~$1.40 with `--verify`. Both within free tier for typical monthly volume.

---

## Library Write-Back Pattern

Any section that uses "library first, AI fallback" follows this pattern:

```python
def get_or_generate(library_data, city, field, generate_fn, context):
    value = library_data.get(field)
    if value:
        return value
    value = generate_fn(context, city)
    update_library(city, field, value, updated_by=f"AI while building {context.facts.client_names[0]} guide {date.today()}")
    return value
```

Fields that use this pattern: `cultural_etiquette`, `connectivity_tips`, `safety_tips`, `emergency_contacts`, `health_tips`.

---

## Activity Description Format (per day)

Each activity renders as:

```
📍 [Activity Name] ([Maps link])
[2–3 vivid immersive sentences — AI generated]
⏰ [Hours from library or AI-estimated]
💰 [Entry fee from library or AI-estimated]  
⏱ [Travel time and mode from hotel/previous attraction — AI generated]
[Any booking note, e.g. "Pre-booked — tickets already arranged"]
```

Travel time line examples:
- `🚇 ~25 min by metro from hotel (take Line 52 from Centraal Station)`
- `🚶 ~7 min walk from Duomo`
- `🚖 ~15 min by taxi from Ponte Vecchio (~€8)`

---

## Restaurant Card Format (per day)

```
[Restaurant Name] ([Maps link])
[Ambience label — 1 sentence]
🍴 Must try: [dish 1], [dish 2]
⏰ [Hours]  💰 [Price range per person]
🚗 [Travel time and mode from nearest attraction or hotel]
```

Lunch cards include: `📍 Located near [Attraction]`
Dinner cards include: `📍 [Distance/time] from your hotel`

---

## Constraints and Rules

- **Activity order is immutable.** Never reorder or merge activities from `trip_facts.json`.
- **Dietary filter is strict.** Never recommend a restaurant that conflicts with `dietary_restrictions` or `food_allergies`.
- **Rotation rule.** Same restaurant must not appear in any meal slot within the preceding 2 consecutive days.
- **Minimum 3 restaurant options per meal slot** where library allows; AI curates shortfall (marked as curated).
- **All Maps links required** on every hotel, attraction, restaurant, pharmacy, grocery store, hospital.
- **AI-estimated facts are marked** with `AIG Note` style so Marina can spot-check before sending.
- **Cruise / At Sea days** skip restaurant lookup; replace meal section with onboard dining note.
- **Port stop days** (Santorini, Kusadasi, etc.) use that port city for attraction and restaurant lookup; library coverage may be sparse, AI curates as needed.
