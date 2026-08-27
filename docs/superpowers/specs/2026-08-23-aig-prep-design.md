# AIG Prep: Library Context & Client Profile Generation

**Date:** 2026-08-23  
**Branch:** aigbootstrap  
**Status:** Approved — ready for implementation planning

---

## Problem

When Marina submits an itinerary to ChatGPT to generate an All Inclusive Guide, ChatGPT has no access to BVM's curated library. It generates restaurant recommendations, local dishes, transport tips, and safety contacts from its generic training data — not from the years of vetted picks in the library. The result: guides that don't reflect BVM's actual recommendations.

Two specific gaps:
1. **Library knowledge never reaches ChatGPT.** The input files (notes or service vouchers) are itinerary/booking data only. The library DB with 48 London restaurants, 14 Cusco restaurants, local dishes, transport tips, etc. is never included.
2. **Client profile is inconsistent.** Notes files sometimes contain dietary preferences inline; service vouchers have none at all. ChatGPT has to guess.

---

## Solution

A new `aig prep` command (and corresponding UI panel) that reads an input file, queries the library, and generates two companion `.md` files ready to upload to ChatGPT alongside the original input:

- **`[Name]_library_context.md`** — BVM's curated data for every destination city in the trip (restaurants, dishes, shopping, transport, safety, connectivity, emergency contacts, health tips). Includes an instruction header telling ChatGPT to prefer these over its own knowledge.
- **`[Name]_client_profile.md`** — Auto-filled with what can be extracted from the input (client name, dates, hotels, dietary preferences). Blank `[fill in]` placeholders for fields Marina must complete (travel style, occasion, group size, special requirements).

---

## Architecture

### New module: `src/aig/prep.py`

**`PrepContext` dataclass:**
```python
@dataclass
class PrepContext:
    client_name: str
    destination_label: str        # e.g. "London" or "Peru (Lima, Cusco, Sacred Valley)"
    cities: list[str]             # e.g. ["London"] or ["Lima", "Cusco", "Sacred Valley", "Machu Picchu"]
    date_range: str               # e.g. "28 June – 4 July 2026"
    hotels: dict[str, str]        # city → hotel name
    dietary_notes: str            # raw text extracted, e.g. "vegetarian, chicken, seafood"
    transport_mode: str           # e.g. "Public transport" or ""
```

**`extract_trip_context(input_path: Path) -> PrepContext`**

Reuses the existing `ItineraryParser` / `folder_parser` to extract structured data. Falls back gracefully — if dietary prefs aren't found, `dietary_notes` is empty string. If a hotel isn't found for a city, the entry is omitted from `hotels`.

**`generate_library_context(prep_context: PrepContext, db_path: Path) -> str`**

Returns a markdown string. For each city in `prep_context.cities`:
1. Opens `library_db/{city}.json`
2. Renders 8 sections (see format below)
3. If `{city}.json` doesn't exist: emits a note — "No BVM library data available for [City] — ChatGPT will use general knowledge."

Sections included per city:
- Curated Restaurants
- Must-Try Local Dishes
- Souvenir Shopping
- Getting Around (transport options)
- Safety Tips
- Mobile Connectivity
- Emergency Contacts
- Health & Vaccination

Sections explicitly excluded: Attractions, Hotels (already in the itinerary).

**`generate_client_profile(prep_context: PrepContext) -> str`**

Returns a markdown string with auto-filled fields and `[fill in]` placeholders. See format below.

**`run_prep(input_path: Path, db_path: Path, output_dir: Path | None = None) -> tuple[Path, Path]`**

Orchestrates the above three functions and writes the two `.md` files. Output directory defaults to the same directory as the input file. Returns paths to the two generated files.

---

### CLI: `src/aig/__main__.py`

Add `prep` subcommand alongside existing `parse` and `generate`:

```
python -m src.aig prep <input_file_or_dir> [--db library_db] [--output <dir>]
```

- `<input_file_or_dir>`: path to a `.docx` notes file, service voucher, or a directory containing one or more such files
- `--db`: library DB path (default: `library_db`)
- `--output`: where to write generated files (default: same directory as input)

---

### API endpoint: `POST /api/aig/prep`

Accepts a multipart upload of a `.docx` file. Returns JSON:

```json
{
  "library_context": "# BVM Library Context...",
  "client_profile": "# Client Profile...",
  "filename_base": "Bhushan_London"
}
```

The frontend uses `filename_base` to name the download files.

Error responses:
- 400 if file is not `.docx`
- 500 with `{ "error": "..." }` if parsing or library lookup fails

---

### Frontend: `AIGTab.tsx` (new, replaces `VerifyTab` as page root)

`App.tsx` change: `{mode === "verify" && <VerifyTab />}` → `{mode === "verify" && <AIGTab />}`

`Layout.tsx` change: section tab label `"AIG Verification"` → `"AIG"` (label only, mode key stays `"verify"`)

**`AIGTab.tsx` layout:**

Two equal-width panels in a flex row, each independently stateful (upload → loading → results/downloads).

```
┌─────────────────────────────┬─────────────────────────────┐
│  Generate Context           │  AIG Verification           │
│                             │                             │
│  [drop zone: .docx input]   │  [drop zone: .docx guide]   │
│                             │                             │
│  [Generate Context] button  │  [Run Verification] button  │
│                             │                             │
│  ↓ results state:           │  ↓ results state:           │
│  📥 library_context.md      │  RED / YELLOW / PASSED      │
│  📥 client_profile.md       │  findings + narratives      │
└─────────────────────────────┴─────────────────────────────┘
```

Each panel has its own idle/loading/results states. The right panel (`VerifyPanel`) is the current `VerifyTab` content extracted as a component; it does not change functionally.

**Download behaviour**: browser `<a download>` with a `Blob` URL created from the markdown string returned in the API response. Two separate download links/buttons, one per file.

**Error state**: shown inline within the left panel (same style as existing VerifyTab error display).

---

## Output File Formats

### `[Name]_library_context.md`

```markdown
# BVM Library Context: [Destination Label]

> **Instructions for ChatGPT:** The sections below contain BVM's curated
> recommendations for this trip. Prioritise these restaurants, dishes, and
> facts when generating the guide. Use your own knowledge only to fill gaps
> where BVM data is absent or insufficient (fewer than 3 restaurants for a
> meal slot, missing a section entirely, etc.).

---

## [City], [Country]

### Curated Restaurants
*Use these in Day-wise Itinerary restaurant recommendations.*

| Name | Cuisine | Area | Hours | Veg-friendly | Must-Try Dishes |
|------|---------|------|-------|:------------:|-----------------|
| Borough Market | Food market | Borough | Tue–Sat 10am–5pm | No | Oysters, fish & chips, sticky toffee pudding |
| Dishoom Carnaby | Indian | Carnaby | 8am–11pm | No | House Black Daal, Chicken Ruby |
| ... | | | | | |

### Must-Try Local Dishes
*Use in the "Must-Try Local Dishes" section.*

- **Fish and Chips** — Classic breaded fish with fried potatoes. Best at: pubs and food markets.
- **Yorkshire Pudding** — Traditional egg-flour-milk bake, served with gravy. Best at: pubs.

### Souvenir Shopping
*Use in the "Souvenir Shopping Guide" section.*

- **Fortnum & Mason Tea** — Where to buy: Fortnum & Mason, supermarkets across UK.
- **Cadbury Chocolate** — Where to buy: supermarkets across UK.

### Getting Around
*Use in the "Getting Around" section.*

- **Oyster Card** — Cheapest way to travel on bus, Tube, tram, DLR, London Overground and most National Rail services. Cost: £7 refundable deposit.

### Safety Tips
*Use in the "Safety & Emergency Contacts" section.*

- Major spots like Borough Market and Covent Garden can be busy — stay aware in pickpocket-prone areas.

### Mobile Connectivity
*Use in the "Mobile Connectivity Guide" section.*

- Three is recommended as SIM Card provider. Best place to buy: airport kiosks.

### Emergency Contacts
*Use in the "Safety & Emergency Contacts" section.*

- Embassy Emergency: 00 44 (0)7768765035

### Health & Vaccination
*Use in the "Health & Vaccination Guidance" section.*

*(No BVM data available — ChatGPT will generate from general knowledge.)*

---

## [Next City, Country]
...
```

---

### `[Name]_client_profile.md`

```markdown
# Client Profile: [Client Name] — [Destination Label]

> **Instructions for ChatGPT:** Use this profile to personalise the guide.
> Fields marked [fill in] were not found in the input file — please complete
> these before sending to ChatGPT.

## Trip Details
- **Client Name:** Bhushan
- **Destination(s):** London
- **Travel Dates:** 28 June – 4 July 2026
- **Hotels:**
  - London: Hilton London Kensington

## Dietary Preferences
- **Restrictions / Preferences:** Vegetarian, chicken, seafood *(extracted from input)*

## Travel Profile
- **Travel Style:** [fill in: budget / mid-range / luxury]
- **Occasion:** [fill in: leisure / honeymoon / anniversary / family / business / other]
- **Group Composition:** [fill in: solo / couple / family with kids / group of friends / other]
- **Transport Mode:** Public transport *(noted in input)*

## Special Requirements
- [fill in: any specific requests, accessibility needs, must-see places, etc.]

---
*Generated automatically from input file. Review and complete [fill in] fields before sending to ChatGPT.*
```

---

## Handling Edge Cases

| Situation | Behaviour |
|-----------|-----------|
| City not in library | Section header + "No BVM library data available — ChatGPT will use general knowledge." |
| Library category empty (e.g. no local dishes) | Omit that sub-section silently |
| Dietary prefs not found in input | `dietary_notes` = `""`, client profile shows `[fill in]` for that field |
| Multi-country Europe trip | One file with `## City, Country` headers for each city |
| Input directory (multiple files) | Generate one pair of context+profile files per input file found |

---

## Out of Scope

- Enriching the library DB from generated guides (separate future effort)
- Filtering library restaurants by dietary preference (let ChatGPT do this using the client profile)
- Generating the AIG itself (existing `generate` command, separate scope)
- Past AIG PDF injection (deferred — library should become sufficient over time)
