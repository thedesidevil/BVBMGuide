# AIG Trip Facts Extraction — Design Spec

**Date:** 2026-05-20
**Milestone:** 1 — Extract facts from input folder, save for user review

---

## Goal

Parse all documents in the `input/` folder using AI, consolidate them into a structured `trip_facts.json` file, and print a found/missing summary so the user can review and edit before AIG generation begins.

---

## Facts Collected

The following 12 facts are extracted. All are nullable — missing facts are saved as `null` or `[]` and must be filled in by the user before generating.

| # | Field | Type | Required for generation |
|---|-------|------|------------------------|
| 1 | `client_names` | `string[]` | Yes |
| 2 | `num_guests` | `string \| null` | No |
| 3 | `departure_city` | `string \| null` | No |
| 4 | `destinations` | `string[]` | Yes |
| 5 | `trip_start_date` | `string \| null` (ISO `YYYY-MM-DD`) | Yes |
| 6 | `trip_end_date` | `string \| null` (ISO `YYYY-MM-DD`) | Yes |
| 7 | `days` | `Day[]` | Yes |
| 8 | `hotels` | `Hotel[]` | Yes |
| 9 | `transport_modes` | `TransportLeg[]` | No |
| 10 | `dietary_restrictions` | `string[]` | No |
| 11 | `food_allergies` | `string[]` | No |
| 12 | `cuisine_preferences` | `string[]` | No |

**Deferred (not collected in Milestone 1):** dining budget, dining style, special occasions — add after base AIG generation is working.

---

## trip_facts.json Schema

```json
{
  "client_names": ["Divya", "Rahul"],
  "num_guests": "2 adults, 2 kids (12 and 8 yrs old)",
  "departure_city": "Mumbai",
  "destinations": ["Amsterdam", "Florence", "Rome"],
  "trip_start_date": "2025-04-19",
  "trip_end_date": "2025-05-05",
  "hotels": [
    {
      "city": "Amsterdam",
      "hotel_name": "Marriott Amsterdam",
      "check_in": "2025-04-19",
      "check_out": "2025-04-23"
    }
  ],
  "transport_modes": [
    {
      "from_city": "Amsterdam",
      "to_city": "Florence",
      "mode": "flight",
      "date": "2025-04-23"
    }
  ],
  "days": [
    {
      "day_number": 1,
      "date": "2025-04-19",
      "title": "Arrival in Amsterdam",
      "overnight_city": "Amsterdam",
      "overnight_hotel": "Marriott Amsterdam",
      "activities": ["Check-in at hotel", "Visit Anne Frank House"]
    }
  ],
  "dietary_restrictions": [],
  "food_allergies": [],
  "cuisine_preferences": []
}
```

**Notes:**
- `num_guests` is a free-text string to capture rich composition (e.g. "2 adults, 2 senior citizens"). `null` if not found.
- Activities per day are plain strings — easier for users to read and edit.
- Dates use ISO `YYYY-MM-DD` format throughout.
- Missing required fields are `null`; missing optional list fields are `[]`.

---

## Extraction Flow

```
1. Scan input/ for all .pdf and .docx files

2. Per-file extraction (one AI call per file):
   - Extract raw text (pdfplumber for PDF, python-docx for DOCX)
   - Prompt: "Extract any travel facts you can find. Return only fields
     you can see — leave everything else null."
   - Returns partial TripFacts (most fields null)
   - Files that fail to parse are skipped with a terminal warning

3. AI merge call (one call, input = all partial TripFacts as JSON):
   - Prompt: "Merge these facts from N travel documents into one final
     fact sheet. For conflicts, prefer facts from the file with the most
     days (that is the itinerary). Deduplicate hotels and transport legs
     by meaning, not exact string match."
   - Returns final TripFacts

4. Validate required fields — note which are still null

5. Save → input/trip_facts.json (always overwrites)

6. Print found/missing summary to terminal
```

**Why per-file then merge (not concatenated single call):** Each file's extraction is focused. The merge input is small JSON objects, not raw document text. AI deduplication handles fuzzy matches (e.g. "Marriott Amsterdam" vs "Amsterdam Marriott").

---

## Terminal Output

```
Scanning input/ — 4 files found
  ✓ Final Itinerary for AIG.pdf
  ✓ Flight-Mumbai-Amsterdam-Sanvi.pdf
  ✓ Flight-Amsterdam-Florence.pdf
  ✓ Cruise-Rome to Rome.pdf

Extracting facts with AI...

✅ Found
  client_names      Divya and Rahul
  departure_city    Mumbai
  destinations      Amsterdam → Florence → Rome
  trip_start_date   2025-04-19
  trip_end_date     2025-05-05
  days              17 days extracted
  hotels            3 properties
  transport_modes   3 legs

⚠️  Missing — open trip_facts.json to fill these in:
  num_guests
  dietary_restrictions (saved as [])
  food_allergies (saved as [])
  cuisine_preferences (saved as [])

Saved → input/trip_facts.json
```

---

## CLI Changes

### `parse` command (extended)

```bash
python -m src.aig parse <input_dir>   # multi-file extraction
python -m src.aig parse <file.pdf>    # single-file (existing behaviour, unchanged)
```

When given a **directory**:
- Runs multi-file extraction flow above
- Saves `trip_facts.json` into the directory
- Always overwrites any existing `trip_facts.json`
- `--days` flag still works — prints day-by-day activity list after saving

When given a **single file**: existing behaviour unchanged (no `trip_facts.json` written).

### `generate` command (updated)

```bash
python -m src.aig generate <input_dir>
```

- Looks for `<input_dir>/trip_facts.json` first
- **Found:** loads it, shows summary, prompts go/abort
- **Not found:** prints `"Run 'parse <input_dir>' first to extract trip facts."` and exits
- Blocks generation if any required field (`client_names`, `destinations`, `trip_start_date`, `trip_end_date`, `days`, `hotels`) is null or empty

---

## New Code Modules

```
src/aig/
  folder_parser.py     — FolderParser class: scan → per-file extract → merge → TripFacts

src/common/
  models.py            — Add TripFacts, TripDay, TripHotel, TransportLeg Pydantic models
```

### `TripFacts` model (in `src/common/models.py`)

New Pydantic v2 models added alongside existing ones:

```python
class TripDay(BaseModel):
    day_number: int
    date: str | None
    title: str | None
    overnight_city: str | None
    overnight_hotel: str | None
    activities: list[str] = []

class TripHotel(BaseModel):
    city: str
    hotel_name: str
    check_in: str | None
    check_out: str | None

class TransportLeg(BaseModel):
    from_city: str
    to_city: str
    mode: str          # "flight", "train", "cruise", "bus", "car"
    date: str | None

class TripFacts(BaseModel):
    client_names: list[str] = []
    num_guests: str | None = None
    departure_city: str | None = None
    destinations: list[str] = []
    trip_start_date: str | None = None
    trip_end_date: str | None = None
    hotels: list[TripHotel] = []
    transport_modes: list[TransportLeg] = []
    days: list[TripDay] = []
    dietary_restrictions: list[str] = []
    food_allergies: list[str] = []
    cuisine_preferences: list[str] = []
```

### `FolderParser` (in `src/aig/folder_parser.py`)

```python
class FolderParser:
    def parse(self, folder: Path) -> tuple[TripFacts, list[str]]:
        """Returns (facts, warnings). warnings = files that failed to parse."""
```

Internally:
1. `_find_files(folder)` — glob for `*.pdf`, `*.docx`
2. `_extract_text(file)` — pdfplumber or python-docx
3. `_extract_facts_from_file(text, filename)` — AI call → partial TripFacts
4. `_merge_facts(partials)` — AI merge call → final TripFacts

---

## What's Out of Scope for Milestone 1

- No UI for editing (user edits `trip_facts.json` directly in their editor)
- No Google Maps links (added during AIG generation in Milestone 2+)
- No restaurant matching (Milestone 2+)
- No AIG section generation (Milestone 2+)
- Dining budget, dining style, special occasions (deferred)
