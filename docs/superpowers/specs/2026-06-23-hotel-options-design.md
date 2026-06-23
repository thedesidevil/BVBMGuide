# Hotel Options Document Generator — Design Spec
_Date: 2026-06-23_

## Overview

A new "Hotel Options" tab in the existing Library QC web UI. Users upload an internally-prepared hotel comparison Excel sheet; the tool parses it, enriches each hotel via Google Places, and generates a professional Word document to send to clients.

The Excel sheet is built manually by the BVBM team. It compares hotel prices from OTA sites (Expedia, Booking.com, Agoda, MMT) against B2B portal rates (dmc, tbo). The output document presents the pre-selected Plans to the client with photos, hotel details, and combined pricing — without exposing any internal pricing or commission data.

---

## Architecture

New package `src/hotel_options/` parallel to `src/aig/` and `src/library/`:

```
src/hotel_options/
  __init__.py
  parser.py      — reads .xlsx, detects Plans, skips strikethrough rows, decodes col H
  enricher.py    — Google Places API: official name, address, phone, rating, photo
  generator.py   — builds DOCX from letterhead + enriched plan data

src/library/ui/
  api/hotel_options.py                  — three FastAPI endpoints: /parse, /generate, /codes
  services/hotel_options_service.py     — orchestrates parser → enricher → generator

ui-frontend/src/components/
  HotelOptionsTab.tsx                   — upload → preview → generate → download
```

`Layout.tsx` and `App.tsx` get a new `"hotel_options"` mode. The tab appears after "Verify AIG" in the header, visible to all users (same rule as Verify — no admin gate).

---

## Section 1: Excel Parsing (`parser.py`)

### Source columns

| Column | Content |
|--------|---------|
| A | Hotel name (also Plan headers, section headers) |
| B | Hotel category (e.g., "4-Star") |
| C | Room type |
| H | Shortcode: cancellation policy + meal type |
| I | Best online price (INR, numeric) |
| J | B2B price (INR, numeric) |
| L | Customer discount (INR) |
| M | Best discounted price — what client pays (formula or numeric) |
| N | Discount percentage (formula or numeric) |

**Column E and F are not used.** Column H is the authoritative source for both cancellation policy and meal type.

### Workbook loading

The workbook is opened with `data_only=True` so that formula cells (cols M, N, and summary row totals) return their last-computed values rather than formula strings. If a cell has never been computed (e.g., a freshly saved file), its value will be `None` — in that case fall back to calculating the value from adjacent cells that are numeric.

### Row classification

- **Plan header**: col A matches `PLAN [A-Z]` (case-insensitive, stripped) — marks start of a new plan
- **Hotel row**: col A is a non-empty string that does not match Plan/section patterns, and col I is numeric
- **Plan summary row**: col A is blank, col I is numeric (computed SUM) or col L has a numeric discount — this is the totals row for the plan
- **Section header rows** (e.g., "Wimbledon (Jun 28– Jul 4)", "Central London (Jul 1– Jul 4)"): col A is a string, col I is blank — ignored entirely
- **Exploratory matrix rows** above the first `PLAN` marker: ignored entirely

### Strikethrough detection

Using `openpyxl`, check `cell.font.strike is True` on col A. Struck-through rows are skipped entirely and do not appear in the output.

### Column H decoder

Col H encodes cancellation policy and meal type in a compact shortcode. Tokens are extracted by splitting on spaces and `.` characters.

**Seed mappings** (hardcoded defaults):
- `nr` → Non-refundable
- `br` → Breakfast included

**Date token** (`\d{1,2}\s+[a-z]{3}`, e.g., `26 jun`) → Free cancellation till {date}

**Compound examples:**
- `nr` → cancellation: "Non-refundable", meal: not specified
- `br` → cancellation: not specified, meal: "Breakfast included"
- `nr. br` → cancellation: "Non-refundable", meal: "Breakfast included"
- `26 jun. br` → cancellation: "Free cancellation till 26 Jun", meal: "Breakfast included"

**Unknown token handling:** Any token that is not a known keyword, not a date pattern, and not in `hotel_codes.json` is flagged as an unknown code. The `/parse` response includes `unknown_codes` — a list of `{code, hotel_name, plan_label}` entries. Generation is blocked until all unknown codes are resolved by the user.

### Persistent code store (`hotel_codes.json`)

Stored via the existing `storage.py` abstraction (local file or S3 key `hotel_options/hotel_codes.json`). Seeded with the two defaults above. Each time the user teaches the system a new code via the UI, the mapping is appended and saved immediately. On subsequent parses, the saved codes are loaded and applied silently.

### Data models

```python
@dataclass
class HotelRow:
    name: str           # as written in sheet — used for Google Places search
    category: str       # "4-Star", "3-Star", etc.
    room_type: str
    cancellation: str   # decoded from col H
    meal_type: str      # decoded from col H
    online_price: float # col I, INR

@dataclass
class PlanPricing:
    total_online_price: float   # col I sum
    total_b2b_price: float      # col J sum (internal, not shown to client)
    customer_discount: float    # col L
    discounted_price: float     # col M — what client pays
    discount_pct: float         # col N

@dataclass
class Plan:
    label: str                  # "Plan A"
    hotels: list[HotelRow]
    pricing: PlanPricing
```

### Client name and destination extraction

- **Client name**: parsed from the filename — segment between the first `_` and `_Accommodation` (e.g., `Bushan` from `DO NOT SHARE_ Bushan_Accommodation Options_London.xlsx`)
- **Destination**: last segment of the filename before `.xlsx`, after the last `_` (e.g., `London`)
- If the filename does not match this pattern, both default to empty string and the document title omits them

---

## Section 2: Google Places Enrichment (`enricher.py`)

Three sequential API calls per hotel, using `GOOGLE_MAPS_API_KEY` from `.env`.

### Two-phase enrichment

Enrichment is split across the two endpoints to preserve the fast parse → slow generate UX:

- **`/parse` phase** — Text Search only (one call per hotel). Determines existence. Fast.
- **`/generate` phase** — Place Details + photo download + AI description per hotel. Slow (3 calls + 1 AI call per hotel).

### Happy path (`/generate` phase)

1. **Text Search** — query: `"{hotel_name} {destination}"` → `place_id` + confirms official name (already done in `/parse`; result is re-used or re-run)
2. **Place Details** — fields: `name`, `formatted_address`, `international_phone_number`, `rating`, `user_ratings_total`, `photos`
3. **Photo download** — first `photo_reference` from Place Details → `GET /maps/api/place/photo?maxwidth=800&photo_reference=...&key=...` → JPEG bytes

### Not-found handling

If Text Search (in `/parse`) returns no results:
- Hotel is flagged in the `/parse` response: `not_found: [{sheet_name, plan_label}]`
- The preview UI shows an inline input: *"We couldn't find this hotel on Google. Please paste its Google Maps link."*
- The "Generate Document" button is disabled until all flagged hotels have a Maps link provided
- The Maps link is passed to `/generate` as an override

**Resolving a Maps link:**
1. Extract `place_id` (`ChIJ...`) from the URL via regex `ChIJ[A-Za-z0-9_\-]+`
2. If found: call Place Details directly with that `place_id`
3. If not parseable (some URL formats omit it): extract lat/lng from the URL, run a Nearby Search to resolve the `place_id`, then call Place Details

### AI description

After Place Details, one AI call per hotel via `src/common/ai_provider.py`:

**Prompt:** given hotel official name, star category, address, rating, cancellation, and meal type → generate 2–3 sentences in warm travel-agency tone. Example output: *"The Hilton London Kensington is a refined 4-star retreat nestled in one of London's most prestigious neighbourhoods. Guests enjoy spacious rooms, a well-regarded restaurant, and easy access to the Natural History Museum and Hyde Park."*

### Enriched data model

```python
@dataclass
class EnrichedHotel:
    # From Google Places
    official_name: str
    address: str
    phone: str
    rating: float           # e.g. 4.2
    rating_count: int       # e.g. 1847
    maps_url: str           # Google Maps deep link
    photo_bytes: bytes | None
    description: str        # AI-generated

    # Carried from sheet
    cancellation: str
    meal_type: str
    category: str           # "4-Star" etc.
```

---

## Section 3: Document Generation (`generator.py`)

### Page 1 — Letterhead + Title

Letterhead paragraphs are copied from `BVBM Company Letterhead.docx` by reading its paragraphs and re-writing them into the output document, preserving bold/font formatting. Not embedded as an image.

After the letterhead:
- Thin horizontal rule
- Title: **"Accommodation Options — {Destination}"** (bold, 16pt)
- Sub-line: *"Prepared for: {ClientName}"* (12pt, normal)

### Per-plan section

Each plan starts on a new page (Word page break paragraph).

**Plan heading:** `Plan A` — bold, 16pt

**Per-hotel card** (hotels separated by a thin horizontal rule):

1. **Photo** — embedded JPEG, full content width (~5.5 inches), centred. If `photo_bytes` is None, a placeholder line *"[Photo not available]"* is used instead.
2. **Hotel name** — hyperlinked to `maps_url`, bold, 14pt
3. **Star rating** — `⭐ 4.2 · 1,847 reviews` (11pt)
4. **Address + phone** — `📍 22 Courtfield Gardens, London  ·  📞 +44 20 7370 4111` (11pt)
5. **Cancellation + meal** — `🗓 Free cancellation till 26 Jun  ·  🍳 Breakfast Included` (11pt). If either is not present, omit that segment.
6. **Description** — AI-generated paragraph (11pt, normal weight)

**Plan pricing summary** (after all hotel cards, before the page break):

A borderless 2-column table:

| Best Online Price | ₹1,91,022 |
|---|---|
| **Our Best Price** | **₹1,76,622** |
| Your Savings | ₹14,400 · 7.5% off |

- "Our Best Price" row: bold
- Prices formatted in Indian number style (e.g., ₹1,76,622 not ₹176,622)
- "Our Best Price" = `discounted_price` from the plan summary row
- "Best Online Price" = `total_online_price`
- "Your Savings" = `customer_discount` and `discount_pct`

---

## Section 4: API (`api/hotel_options.py`)

### `POST /api/hotel-options/parse`

- Accepts: `.xlsx` file upload
- Returns:
```json
{
  "client_name": "Bushan",
  "destination": "London",
  "plans": [
    {
      "label": "Plan A",
      "hotels": [
        { "name": "Travelodge London Raynes Park", "category": "2-Star", "room_type": "Double Room", "cancellation": "Non-refundable", "meal_type": "Breakfast included" }
      ],
      "pricing": {
        "total_online_price": 181285.55,
        "customer_discount": 3000.0,
        "discounted_price": 178285.55,
        "discount_pct": 1.65
      }
    }
  ],
  "unknown_codes": [
    { "code": "hb", "hotel_name": "Hilton London", "plan_label": "Plan C" }
  ],
  "not_found": []
}
```

### `POST /api/hotel-options/generate`

- Accepts: multipart form with:
  - `file`: the `.xlsx`
  - `resolved_codes`: JSON object `{ "hb": "Half board included" }` (may be empty)
  - `overrides`: JSON object `{ "Hub By Premier Inn London Marylebone": "https://maps.google.com/..." }` (may be empty)
- Returns: `.docx` file download (`Content-Disposition: attachment`)
- Saves any `resolved_codes` entries to `hotel_options/hotel_codes.json` before generation

### `POST /api/hotel-options/codes`

- Accepts: JSON body `{ "code": "hb", "meaning": "Half board included" }`
- Saves the mapping to `hotel_options/hotel_codes.json` immediately
- Returns: `{ "ok": true }`
- Called on blur from the unknown-codes input in the preview UI, so the mapping is persisted even if the user abandons the flow before generating

---

## Section 5: Frontend (`HotelOptionsTab.tsx`)

Three UI states, no sidebar (added to `NO_SIDEBAR_MODES`).

### State 1 — Upload
- Drag-and-drop zone or file picker, `.xlsx` only
- "Parse" button → calls `/parse`

### State 2 — Preview
- Read-only plan list: plan label, hotel names, pricing summary per plan
- **Unknown codes panel** (if any): one input per unknown code — *"What does 'hb' mean?"* — saved to backend on blur via a small `POST /api/hotel-options/codes` endpoint
- **Not-found hotels panel** (if any): one input per hotel — *"Paste Google Maps link for {hotel name}"*
- "Generate Document" button — disabled until all unknown codes and not-found hotels are resolved
- "Upload a different file" link to reset

### State 3 — Generating / Done
- Spinner with label *"Enriching hotels and building document…"*
- On success: green download button for the `.docx`
- On error: red error message with retry option
- "Start over" link resets to State 1

---

## Out of Scope

- The exploratory hotel matrix (rows above the first `PLAN` marker) — ignored entirely
- Individual hotel prices within a plan — not shown to client; only combined plan pricing
- Commission, B2B prices, GST — internal fields, never appear in the output document
- Multi-sheet workbooks — only the first sheet is processed
