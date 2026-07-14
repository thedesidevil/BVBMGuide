# Hotel Options — Multi-Format & Multi-Segment Support

**Date:** 2026-07-14
**Status:** Approved

## Problem

The hotel options parser was designed for one specific Excel format (PLAN A/B markers, col H short codes, blank-col-A summary rows). A second format has emerged — same price column (col I), but different plan header labels, plain-text col H, extra rows to skip, hotel names that embed dates, and two new client-facing columns (Inclusions, Exclusions). When a hotel has two room types for different date spans, both rows belong to the same property and should render as one card with multiple room segments.

## Goals

1. Parse both Excel formats without separate code paths.
2. Detect and skip internal-only rows ("Transfers").
3. Strip dates from hotel names; group same-hotel rows within a plan into one card.
4. Surface Inclusions/Exclusions to the client document.
5. Show room-specific photos for each segment of a multi-segment hotel card.
6. Filename fallback handles ` - ` separators alongside `_`.

## Non-Goals

- The no-plans path (`_parse_no_plans`) is unchanged.
- The grouped-by-sections layout is unchanged.
- No changes to the AIG pipeline.

---

## Changes by File

### `parser.py`

#### 1. Plan header regex — widen to match `X-Star Plan`, `X Plan`, etc.

```python
_PLAN_RE = re.compile(
    r'^(?:PLAN\s+\w+|.*\bPlan)(?:\s*\(recommended\))?\s*$',
    re.IGNORECASE,
)
```

Matches: `PLAN A`, `4-Star Plan`, `5-Star Plan`, `Budget Plan`. Does not match section headers like `Dubai (Jun 28 - Jul 4)` or `Beachfront Hotels`. The label is taken as-is — no change to how `current_label` is set.

#### 2. Skip "Transfers" rows

In `parse_excel`, before all other row classification, add:

```python
if str_a.lower() == "transfers":
    continue
```

Apply in both the preamble and post-first-plan sections.

#### 3. "Total" in col A triggers plan flush

Current summary detection: `not val_a and (_numeric(col_i_val) is not None ...)`.

Add: also flush when `str_a.lower() == "total"` and col I is numeric. Before flushing, read the plan-level inclusions from col S (index 18) of the Total row:

```python
if str_a.lower() == "total" and _numeric(col_i_val) is not None:
    if len(row) > 18 and row[18].value:
        current_plan_inclusions = str(row[18].value).strip()
    _flush(row)
    continue
```

`current_plan_inclusions` is reset to `""` when `current_label` is reset in `_flush`.

#### 4. Hotel name date extraction

When reading a hotel row, strip `(dates)` suffix from col A:

```python
_NAME_DATE_RE = re.compile(r'^(.+?)\s*\(([^)]+)\)\s*$')

m = _NAME_DATE_RE.match(str_a)
if m:
    hotel_name = m.group(1).strip()
    inline_dates = m.group(2).strip()
else:
    hotel_name = str_a
    inline_dates = ""
```

`inline_dates` overrides the `preamble_dates` / `current_section_dates` lookup for that row.

#### 5. New columns on hotel rows

```python
inclusions = str(row[18].value).strip() if len(row) > 18 and row[18].value else ""
exclusions = str(row[19].value).strip() if len(row) > 19 and row[19].value else ""
```

Stored on `HotelRow`.

#### 6. Filename fallback — handle ` - ` separators

In `extract_filename_meta`, after the strict regex fails, the fallback currently splits on `_`. Add a second attempt splitting on ` - ` (or ` – `):

```python
# existing underscore split
parts = [p.strip() for p in stem.split("_") if p.strip()]

# if that gives only one part (no underscores), try dash split
if len(parts) <= 1:
    parts = [p.strip() for p in re.split(r'\s[-–]\s', stem) if p.strip()]
```

Then clean the `DO NOT SHARE` prefix from `parts[0]` as before. For `DO NOT SHARE- Vinay- Maldives`, this yields `["Vinay", "Maldives"]` → client=`Vinay`, dest=`Maldives`.

---

### `decoder.py`

#### Plain-text fallback when col H contains no known codes

After the existing `. `-split / code-lookup loop, if the result has no cancellation, no meal type, and at least one unknown segment, try the plain-text path:

```python
_CANCELLATION_KEYWORDS = {"cancellation", "cancel", "refund", "free cancel"}
_MEAL_KEYWORDS = {
    "all inclusive", "full board", "half board",
    "breakfast", "bed and breakfast", "room only", "ai", "fb", "hb",
}

def _plain_text_fallback(value: str) -> DecodedCell:
    result = DecodedCell()
    segments = [s.strip() for s in value.split(",") if s.strip()]
    for seg in segments:
        lower = seg.lower()
        if any(kw in lower for kw in _CANCELLATION_KEYWORDS):
            result.cancellation = seg
        elif any(kw in lower for kw in _MEAL_KEYWORDS):
            result.meal_type = seg
    return result
```

Invoke `_plain_text_fallback` only when the primary decode produced all unknowns and no useful fields. This preserves exact existing behaviour for old-format files.

---

### `models.py`

#### `HotelRow` — two new fields

```python
inclusions: str = ""
exclusions: str = ""
```

#### `Plan` — plan-level inclusions

```python
inclusions: str = ""   # e.g. "With airport transfer - Shared Speedboat"
```

#### New `RoomSegment` dataclass

```python
@dataclass
class RoomSegment:
    room_type: str
    dates: str
    online_price: float
    photo_bytes: bytes | None = None
    inclusions: str = ""
    exclusions: str = ""
```

#### `EnrichedHotel` — room segments

```python
room_segments: list[RoomSegment] = field(default_factory=list)
```

When `room_segments` is non-empty, the top-level `room_type`, `dates`, and `photo_bytes` fields on `EnrichedHotel` are unused by the generator (the segments supersede them). Single-segment hotels continue to use those fields as before.

---

### `enricher.py`

#### Grouping (called from service, not enricher directly)

The service groups `HotelRow` entries within a plan by **base hotel name** (name after stripping the date suffix). Groups with one row go through `enrich_hotel` unchanged. Groups with two or more rows go through a new `enrich_hotel_multi_segment`.

#### `enrich_hotel_multi_segment`

```python
def enrich_hotel_multi_segment(
    hotels: list[HotelRow],   # all share the same base hotel name
    place_id: str,
    destination: str,
    api_key: str,
    ai_client,
) -> EnrichedHotel:
```

Steps:
1. Fetch Place Details (same as `enrich_hotel`) — one API call for address, rating, phone, and **all photo references**.
2. For each segment (`hotels[i]`): take `photos[i]` if available, else `photos[-1]` (last available), and fetch it. This distributes photos from the hotel's gallery across segments rather than all showing the same image.
3. Build `RoomSegment` for each row, storing `photo_bytes`, `room_type`, `dates`, `online_price`, `inclusions`, `exclusions`.
4. Generate one AI description for the hotel (not per-segment).
5. Return `EnrichedHotel` with `room_segments` populated and top-level `photo_bytes=None` (the cover photo is segment[0].photo_bytes for fallback display).

---

### `generator.py`

#### Deduplication in both layout paths

`plan.hotels` may contain multiple rows for the same hotel (same `hotel.name`). Both the detail section and executive summary must deduplicate:

```python
rendered = set()
for hotel in plan.hotels:
    if hotel.name in rendered:
        continue
    rendered.add(hotel.name)
    # ... render card
```

The `EnrichedHotel` (keyed by the shared base name) carries all segment info via `room_segments`.

#### Multi-segment hotel card (`_add_hotel_card`)

When `enriched.room_segments` is non-empty, render:

```
[Hotel name (hyperlinked) + star rating + RECOMMENDED badge if applicable]
─────────────────────────────────────────────────────
[Segment 1 photo — 4.5" wide]
  🛏️ Room: 4x Beach Villa
  📅 Dec 22 – 25 (3 nights)
  Online price: ₹11,78,668

[Segment 2 photo — 4.5" wide]
  🛏️ Room: 4x Sunrise Ocean Villa
  📅 Dec 25 – 26 (1 night)
  Online price: ₹4,51,983

✓ Inclusions: [text if present]
✗ Exclusions: [text if present]

[AI hotel description]
[Why we recommend — if present]
```

For single-segment hotels, the card layout is unchanged. Inclusions/Exclusions are rendered below the facts block for both single and multi-segment cards (only when non-empty).

#### Plan-level inclusions

In the plan-layout path, below the plan heading and before the first hotel card:

```
📋 Includes: With airport transfer - Shared Speedboat
```

Rendered as a small italic line in `_GREY` if `plan.inclusions` is non-empty.

#### Executive summary — multi-segment hotels

In `_build_exec_summary_by_plan`, the Hotels column currently lists bullet points per `hotel.name`. For a grouped hotel (multiple segments), list the base name once with room types as sub-bullets:

```
• Adaaran Select Hudhuranfushi (4*)
  – 4x Beach Villa (Dec 22–25)
  – 4x Sunrise Ocean Villa (Dec 25–26)
```

---

### `hotel_options_service.py`

Add a `_group_hotels(hotels: list[HotelRow]) -> list[list[HotelRow]]` helper that groups **consecutive** rows sharing the same `hotel.name`. Non-consecutive rows with the same name are treated as separate entries (this matches natural Excel structure where related rows are adjacent).

The service's enrichment loop:
1. Collects unique hotel names for `check_hotels_exist` (deduplicated set, not raw list).
2. Groups `plan.hotels` per plan using `_group_hotels`.
3. Calls `enrich_hotel` for single-item groups and `enrich_hotel_multi_segment` for multi-item groups.
4. Keys `enriched_map` by `hotel.name` (the base name after date stripping) — same for all segments of the same property.

`plan.hotels` is **not modified** — it still contains one `HotelRow` per Excel row. The generator is responsible for deduplication when rendering (see generator section below).

---

## Data flow summary

```
parse_excel(xlsx_bytes, codes)
  → ParseResult { plans: [Plan { hotels: [HotelRow] }] }
        ↓
_group_hotels(plan.hotels)  [service]
  → list[list[HotelRow]]
        ↓
enrich_hotel / enrich_hotel_multi_segment  [enricher]
  → dict[base_name → EnrichedHotel { room_segments? }]
        ↓
build_document(plans, enriched_map, ...)
  → .docx bytes
```

---

## Backwards Compatibility

- All changes are additive (new fields default to `""` / `[]`).
- Old-format files: plan regex widens but old `PLAN A` labels still match; decoder primary path unchanged; new fields are empty; no multi-segment groups form; generator render path unchanged.
- No-plans files: unaffected (their path is separate).
- Existing tests pass without modification.
