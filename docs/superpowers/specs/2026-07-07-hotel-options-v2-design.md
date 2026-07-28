# Hotel Options Document — V2 Design

**Date:** 2026-07-07  
**Branch:** hotelredesign  
**Reference:** `input/Hotel Options - new design.docx`

## Overview

Full rewrite of `src/hotel_options/generator.py` to match the Copilot-designed reference document. New `src/hotel_options/cover_photo.py` for Unsplash/Pexels cover image fetching.

---

## Color System

Two themes cycle by plan index (0-based), regardless of recommendation status. Even index = navy, odd index = gold.

| Property | Navy (`#1F3A5F`) | Gold (`#8A6D2F`) |
|---|---|---|
| Header bg | `#1F3A5F` | `#8A6D2F` |
| Card light bg | `#F3F7FB` | `#FBF6EA` |
| Marina's Take bg | `#F3F7FB` | `#FFFDF7` |
| Primary text | `#1F3A5F` | `#8A6D2F` |
| Secondary text | `#5E789A` | `#C77800` |
| Badge/accent | `#2E86C1` | `#C77800` |

For grouped-by-sections layout: theme index resets to 0 (navy) at each new section, increments per hotel within section.

Shared constants: green `#2E7D32`, savings bg `#EAF4EA`, recommendation banner bg `#FBF6EA`.

---

## Cover Page

- **Cover photo**: Fetched from Unsplash (primary) or Pexels (fallback) via `src/hotel_options/cover_photo.py`
  - Query: AI-generated from destination + month (e.g. "Japan cherry blossoms Mount Fuji spring")
  - Season inferred from earliest hotel date in spreadsheet
  - Full-width 6.5", centered
- Rest of cover page unchanged (title, subtitle, "Prepared Exclusively For", Trip Snapshot, advisor note, letterhead)
- Trip Snapshot table: 4-column horizontal layout (DESTINATION | TRAVELLERS | ROOMS | PREFERENCES)
  - Header: `#1F3A5F` bg, 10pt white, 7.2pt margins
  - Data cells: alternating `#F7F3EA` / `#FFFFFF`, label 9pt `#8A6D2F` bold, value 9pt `#2D2D2D`

---

## Executive Summary

- Subtitle: "A client-ready comparison…" in 11pt `#1F3A5F`
- **Recommended choice banner** (plans layout only, if any plan is recommended):
  - Full-width 1-col table, `#FBF6EA` bg, 6pt cell margins
  - `"Recommended choice: {plan_label}."` bold `#1F3A5F` + `why_recommend` text regular `#1F3A5F`
- Summary table: 5 cols, header `#1F3A5F` bg, 10pt white bold
  - Col widths: 0.74" | 3.32" | 1.07" | 0.94" | 0.93"
  - Hotel names in `#1F3A5F`, plan labels in `#1F3A5F` bold
  - ★ RECOMMENDED badge: amber `#C77800` (plans) or theme accent (grouped)
  - You Save: green `#2E7D32`
  - Hotels cell: 10pt, spBefore 10pt per line, SINGLE line spacing

---

## Hotel Card Structure (Plans Layout)

Each hotel on its own page. Within the page:

### 1. Name card table
- Full-width, 1-col, 6pt cell margins, theme light bg
- Line 1: Georgia 14pt bold, theme primary color — hotel name
- Line 2: 10pt theme secondary color — `"• City • X-star"`, spAfter 2pt

### 2. Hotel photo
- Full-width (6.5") from Google Places API, centered, no paragraph gap above/below

### 3. Hotel details table
- 2 equal cols (~3.625" each), full-width
- Header row (merged): `"HOTEL DETAILS"` 10pt white on theme header bg, 7.2pt cell margins
- Content row left col (top/bottom margin 0, L/R 5.4pt, 1.5× line spacing):
  - Para 0 spBefore 10pt: `Stay:` regular + dates
  - Para 1: `Rating:` regular + X/5 from N reviews  
  - Para 2: `Flexibility:` regular + cancellation policy
  - Para 3 spAfter 10pt: `Includes:` regular + meal plan
- Content row right col (same margins, same line spacing):
  - Para 0 spBefore 10pt: `Room:` **bold** + room type
  - Para 1: `Address:` **bold** + formatted address
  - Para 2 spAfter 10pt: `Phone:` **bold** + phone number

### 4. Marina's Take table
- Full-width, 1-col, 6pt cell margins, theme Marina's Take bg
- `"Marina's Take: "` bold theme primary + description 10pt theme primary, spAfter 2pt

---

## Plan Price Summary (Plans Layout)

One page per plan, after all hotel pages. 3-col equal-width table (~2.41" each):

- **Header** (merged): `"PLAN X PRICE SUMMARY"` (+ `"• RECOMMENDED"` if applicable), 12pt white on theme header bg, spBefore/After 10pt, centered
- **BEST ONLINE PRICE** col: theme light bg; label 9pt not-bold spAfter 3pt; amount 15pt not-bold; both centered
- **OUR PRICE** col: white bg; label 9pt bold spAfter 3pt; amount 18pt bold; both centered, theme primary color
- **YOU SAVE** col: `#EAF4EA` bg; label 9pt bold spBefore 10pt spAfter 3pt; amount 18pt bold; pct 9pt bold spAfter 10pt; all centered, `#2E7D32`

**Why we recommend box** (if plan.why_recommend is set): rendered as a transition BEFORE that plan's heading (after previous plan's price summary). Full-width 1-col, `#FBF6EA` bg, 6pt margins. `"Why we recommend {plan_label}:"` bold `#1F3A5F` + text regular `#1F3A5F`, spAfter 0.

---

## Grouped-by-Sections Layout

Same table structures as plans layout. Theme index resets at each section, increments per hotel. Each hotel gets its own page. After Marina's Take:

- **Why we recommend this hotel** box (if hotel.why_recommend set): full-width 1-col, theme light bg, 6pt margins. `"Why we recommend this hotel:"` bold theme primary + text regular theme primary.

Per-section price summary: same 3-col table structure (section label as plan label, no "RECOMMENDED" suffix), using the section's base theme (navy, since it's always the first/even index for the section header itself).

Executive summary: no recommended choice banner. Header `#1F3A5F`. Otherwise same structure.

---

## Cover Photo Module (`src/hotel_options/cover_photo.py`)

```
fetch_cover_photo(destination, travel_dates, ai_client, env) -> bytes | None
```

1. Infer season from earliest date in travel_dates
2. Use AI to generate Unsplash search query (destination + season + landscape)
3. Try Unsplash API (`UNSPLASH_ACCESS_KEY`): `GET /search/photos?query=...&orientation=landscape`
4. Fallback: Pexels API (`PEXELS_API_KEY`): `GET /v1/search?query=...&orientation=landscape`
5. Return first photo bytes, or None if both fail

---

## Files Changed

- `src/hotel_options/generator.py` — full rewrite
- `src/hotel_options/cover_photo.py` — new module
- `src/library/ui/services/hotel_options_service.py` — pass travel dates to cover photo fetch; pass `why_recommend` from recommended plan to executive summary banner
