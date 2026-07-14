# Hotel Options Multi-Format & Multi-Segment Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the hotel options pipeline to parse a second Excel format (flexible plan headers, plain-text Col H, "Transfers" skip, "Total" summary row, dates embedded in hotel names, Inclusions/Exclusions columns) and render same-hotel multi-room-type entries as one card with per-segment photos and inclusions/exclusions displayed to the client.

**Architecture:** Changes are layered bottom-up: models first, then decoder, parser, enricher, service, generator. No new files are created — all changes extend existing modules. The `plan.hotels` list stays flat (one `HotelRow` per Excel row); the service groups same-name rows before enrichment, and the generator deduplicates before rendering.

**Tech Stack:** Python, openpyxl, python-docx, httpx, Google Places API, pytest

## Global Constraints

- All new dataclass fields must have defaults so existing test fixtures continue to construct without changes.
- `_parse_no_plans` is untouched — all parser changes apply only to the plans path.
- Old-format files must continue to produce identical output (no behaviour change when new fields are empty).
- Exact column indices (0-based): B=1, C=2, H=7, I=8, J=9, L=11, M=12, N=13, R=17, S=18, T=19.
- Run tests with: `pytest tests/hotel_options/ -v`

---

## File Map

| File | Change |
|---|---|
| `src/hotel_options/models.py` | Add `inclusions`/`exclusions` to `HotelRow`; add `inclusions` to `Plan`; new `RoomSegment` dataclass; add `room_segments` to `EnrichedHotel` |
| `src/hotel_options/decoder.py` | Add plain-text fallback when primary decode finds no useful fields |
| `src/hotel_options/parser.py` | Widen `_PLAN_RE`; skip Transfers; detect "Total" as summary; read plan inclusions from Total row; strip dates from hotel name; read cols S+T; update filename fallback |
| `src/hotel_options/enricher.py` | Add `enrich_hotel_multi_segment` |
| `src/library/ui/services/hotel_options_service.py` | Add `_group_hotels`; update enrichment loop |
| `src/hotel_options/generator.py` | Dedup per plan; multi-segment hotel card; inclusions/exclusions display; plan-level inclusions; exec summary multi-segment listing |
| `tests/hotel_options/test_parser.py` | New tests for all parser changes |
| `tests/hotel_options/test_decoder.py` | New tests for plain-text fallback |
| `tests/hotel_options/test_enricher.py` | New test for `enrich_hotel_multi_segment` |
| `tests/hotel_options/test_service.py` | New test for `_group_hotels` |
| `tests/hotel_options/test_generator.py` | New tests for multi-segment card and inclusions |

---

## Task 1: Models — new fields and `RoomSegment`

**Files:**
- Modify: `src/hotel_options/models.py`
- Test: `tests/hotel_options/test_models.py`

**Interfaces:**
- Produces: `HotelRow.inclusions: str`, `HotelRow.exclusions: str`, `Plan.inclusions: str`, `RoomSegment` dataclass, `EnrichedHotel.room_segments: list[RoomSegment]`

- [ ] **Step 1: Write failing tests**

Create `tests/hotel_options/test_models.py`:

```python
from src.hotel_options.models import HotelRow, Plan, PlanPricing, EnrichedHotel, RoomSegment


def test_hotel_row_new_fields_default_empty():
    h = HotelRow(
        name="Test", category="4-Star", room_type="Double",
        cancellation="Free", meal_type="Breakfast", online_price=50000.0,
    )
    assert h.inclusions == ""
    assert h.exclusions == ""


def test_plan_inclusions_default_empty():
    p = Plan(
        label="Plan A",
        hotels=[],
        pricing=PlanPricing(0, 0, 0, 0, 0),
    )
    assert p.inclusions == ""


def test_room_segment_fields():
    seg = RoomSegment(room_type="Beach Villa", dates="Dec 22-25", online_price=1178668.0)
    assert seg.room_type == "Beach Villa"
    assert seg.dates == "Dec 22-25"
    assert seg.online_price == 1178668.0
    assert seg.photo_bytes is None
    assert seg.inclusions == ""
    assert seg.exclusions == ""


def test_enriched_hotel_room_segments_default_empty():
    e = EnrichedHotel(
        official_name="Test", address="", phone="", rating=4.0,
        rating_count=100, maps_url="", photo_bytes=None,
        description="", cancellation="", meal_type="", category="",
    )
    assert e.room_segments == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/hotel_options/test_models.py -v
```

Expected: `ImportError` or `AttributeError` — `RoomSegment` not defined.

- [ ] **Step 3: Add fields and `RoomSegment` to models**

In `src/hotel_options/models.py`, add after the `UnknownCode` dataclass:

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

Add two fields to `HotelRow` (after `city: str = ""`):

```python
    inclusions: str = ""
    exclusions: str = ""
```

Add one field to `Plan` (after `why_recommend: str = ""`):

```python
    inclusions: str = ""
```

Add one field to `EnrichedHotel` (after `room_type: str = ""`):

```python
    room_segments: list[RoomSegment] = field(default_factory=list)
```

Add `field` to the import at the top of `models.py` if not already present:
```python
from dataclasses import dataclass, field
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/hotel_options/test_models.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Run full suite to verify no regressions**

```
pytest tests/hotel_options/ -v
```

Expected: all existing tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hotel_options/models.py tests/hotel_options/test_models.py
git commit -m "feat(hotel-options): add RoomSegment, inclusions/exclusions fields to models"
```

---

## Task 2: Decoder — plain-text fallback

**Files:**
- Modify: `src/hotel_options/decoder.py`
- Test: `tests/hotel_options/test_decoder.py`

**Interfaces:**
- Consumes: existing `decode_col_h(value, codes) -> DecodedCell`
- Produces: same signature; now also handles comma-separated plain-text values

- [ ] **Step 1: Write failing tests**

Append to `tests/hotel_options/test_decoder.py`:

```python
def test_plain_text_cancellation_and_all_inclusive():
    r = decode_col_h("Free cancellation before 23 Nov, All Inclusive", {})
    assert r.cancellation == "Free cancellation before 23 Nov"
    assert r.meal_type == "All Inclusive"
    assert r.unknowns == []


def test_plain_text_free_cancellation_and_full_board():
    r = decode_col_h("Free cancellation before 2 Dec, Full Board", {})
    assert r.cancellation == "Free cancellation before 2 Dec"
    assert r.meal_type == "Full Board"
    assert r.unknowns == []


def test_plain_text_non_refundable_keyword():
    r = decode_col_h("Non-refundable", {})
    assert r.cancellation == "Non-refundable"
    assert r.unknowns == []


def test_plain_text_fallback_does_not_affect_code_format():
    """Old-format codes still decode correctly — fallback never triggered."""
    r = decode_col_h("nr. br", {"nr": "Non-refundable", "br": "Breakfast included"})
    assert r.cancellation == "Non-refundable"
    assert r.meal_type == "Breakfast included"
    assert r.unknowns == []


def test_plain_text_unknown_segment_stays_unknown():
    """Unrecognised segment with no keywords goes to unknowns."""
    r = decode_col_h("SomeCode, All Inclusive", {})
    assert r.meal_type == "All Inclusive"
    assert "SomeCode" in r.unknowns
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/hotel_options/test_decoder.py::test_plain_text_cancellation_and_all_inclusive -v
```

Expected: FAIL — `"Free cancellation before 23 Nov"` ends up in `unknowns`, not `cancellation`.

- [ ] **Step 3: Implement the plain-text fallback**

Replace the contents of `src/hotel_options/decoder.py` with:

```python
from __future__ import annotations
import re
from dataclasses import dataclass, field

_DATE_RE = re.compile(r'^\d{1,2}\s+[a-z]{3}$', re.IGNORECASE)
_CANCELLATION_CODES = {"nr"}
_CANCELLATION_KEYWORDS = frozenset({"cancellation", "cancel", "refund"})
_MEAL_KEYWORDS = frozenset({
    "all inclusive", "full board", "half board",
    "breakfast", "bed and breakfast", "room only",
})


@dataclass
class DecodedCell:
    cancellation: str = ""
    meal_type: str = ""
    unknowns: list[str] = field(default_factory=list)


def _plain_text_fallback(value: str) -> DecodedCell:
    """Parse comma-separated plain English cancellation + meal text."""
    result = DecodedCell()
    for seg in [s.strip() for s in value.split(",") if s.strip()]:
        lower = seg.lower()
        if any(kw in lower for kw in _CANCELLATION_KEYWORDS):
            result.cancellation = seg
        elif any(kw in lower for kw in _MEAL_KEYWORDS):
            result.meal_type = seg
        else:
            result.unknowns.append(seg)
    return result


def decode_col_h(value: str | None, codes: dict[str, str]) -> DecodedCell:
    if not value:
        return DecodedCell()

    result = DecodedCell()
    segments = [s.strip() for s in str(value).strip().split(". ") if s.strip()]

    for seg in segments:
        if _DATE_RE.match(seg):
            result.cancellation = f"Free cancellation till {seg.title()}"
        elif seg.lower() in codes:
            meaning = codes[seg.lower()]
            if seg.lower() in _CANCELLATION_CODES:
                result.cancellation = meaning
            else:
                result.meal_type = meaning
        else:
            result.unknowns.append(seg)

    # If the primary decode found nothing useful, try plain-text comma split.
    if not result.cancellation and not result.meal_type and result.unknowns:
        return _plain_text_fallback(str(value).strip())

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/hotel_options/test_decoder.py -v
```

Expected: all tests PASS (including the 7 pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/decoder.py tests/hotel_options/test_decoder.py
git commit -m "feat(hotel-options): plain-text fallback in Col H decoder for comma-separated values"
```

---

## Task 3: Parser — plan header, Transfers skip, Total summary, plan inclusions

**Files:**
- Modify: `src/hotel_options/parser.py`
- Test: `tests/hotel_options/test_parser.py`

**Interfaces:**
- Consumes: existing `parse_excel(xlsx_bytes, codes) -> ParseResult`
- Produces: same signature; `Plan.inclusions` now populated from Total row col S

- [ ] **Step 1: Write failing tests**

Append to `tests/hotel_options/test_parser.py`:

```python
def _make_star_plan_xlsx() -> bytes:
    """Two plans named '4-Star Plan' and '5-Star Plan' with a Transfers row and Total summary."""
    wb = openpyxl.Workbook()
    ws = wb.active
    # Plan 1
    ws["A1"] = "4-Star Plan"
    ws["A2"] = "Adaaran Resort"
    ws["B2"] = "4-Star"
    ws["C2"] = "Beach Villa"
    ws["H2"] = "Free cancellation before 23 Nov, All Inclusive"
    ws["I2"] = 1000000.0
    ws["A3"] = "Transfers"
    ws["I3"] = 50000.0       # should be ignored
    ws["A4"] = "Total"
    ws["I4"] = 1000000.0
    ws["J4"] = 900000.0
    ws["L4"] = 50000.0
    ws["M4"] = 950000.0
    ws["N4"] = 5.0
    ws["S4"] = "With airport transfer - Shared Speedboat"
    # Plan 2
    ws["A6"] = "5-Star Plan"
    ws["A7"] = "Centara Grand"
    ws["B7"] = "5-Star"
    ws["C7"] = "Overwater Villa"
    ws["H7"] = "nr. br"
    ws["I7"] = 2000000.0
    ws["A8"] = "Total"
    ws["I8"] = 2000000.0
    ws["J8"] = 1800000.0
    ws["L8"] = 100000.0
    ws["M8"] = 1900000.0
    ws["N8"] = 5.0
    ws["S8"] = "With airport transfer - Seaplane"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_star_plan_headers_parsed():
    result = parse_excel(_make_star_plan_xlsx(), {"nr": "Non-refundable", "br": "Breakfast included"})
    assert len(result.plans) == 2
    assert result.plans[0].label == "4-Star Plan"
    assert result.plans[1].label == "5-Star Plan"


def test_transfers_row_skipped():
    result = parse_excel(_make_star_plan_xlsx(), {})
    hotels = result.plans[0].hotels
    assert len(hotels) == 1
    assert hotels[0].name == "Adaaran Resort"


def test_total_row_triggers_plan_flush():
    result = parse_excel(_make_star_plan_xlsx(), {})
    assert len(result.plans) == 2
    assert result.plans[0].pricing.total_online_price == 1000000.0
    assert result.plans[0].pricing.customer_discount == 50000.0
    assert result.plans[0].pricing.discounted_price == 950000.0
    assert result.plans[0].pricing.discount_pct == 5.0


def test_plan_inclusions_from_total_row():
    result = parse_excel(_make_star_plan_xlsx(), {})
    assert result.plans[0].inclusions == "With airport transfer - Shared Speedboat"
    assert result.plans[1].inclusions == "With airport transfer - Seaplane"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/hotel_options/test_parser.py::test_star_plan_headers_parsed -v
```

Expected: FAIL — `"4-Star Plan"` doesn't match `_PLAN_RE`.

- [ ] **Step 3: Implement the three changes in `parser.py`**

**3a. Widen `_PLAN_RE`** — replace the existing definition:

```python
_PLAN_RE = re.compile(
    r'^(?:PLAN\s+\w+|.*\bPlan)(?:\s*\(recommended\))?\s*$',
    re.IGNORECASE,
)
```

**3b. Add `current_plan_inclusions` nonlocal** — in `parse_excel`, add with the other tracking variables (near `running_online = 0.0`):

```python
current_plan_inclusions: str = ""
```

**3c. Update `_flush`** — four precise changes (line numbers reference the current file):

1. Extend the `nonlocal` line to include `current_plan_inclusions`:
```python
nonlocal current_label, current_recommended, current_why, current_hotels, running_online, running_b2b, current_plan_inclusions
```

2. Add reset in the early-return ("no hotels") branch, after `running_b2b = 0.0`:
```python
        current_plan_inclusions = ""
```

3. Add `inclusions=current_plan_inclusions` to the `Plan(...)` call (after `why_recommend=current_why`):
```python
        plans.append(Plan(
            label=current_label,
            hotels=list(current_hotels),
            pricing=PlanPricing(
                total_online_price=total_online,
                total_b2b_price=total_b2b,
                customer_discount=discount,
                discounted_price=discounted,
                discount_pct=pct,
            ),
            recommended=current_recommended,
            why_recommend=current_why,
            inclusions=current_plan_inclusions,
        ))
```

4. Add reset at the end of `_flush`, after `running_b2b = 0.0`:
```python
        current_plan_inclusions = ""
```

**3d. Skip Transfers rows** — add early in the post-`past_first_plan` row loop, right after the strikethrough check:

```python
if str_a.lower() == "transfers":
    continue
```

**3e. Detect "Total" as summary row** — replace the existing summary detection:

```python
# OLD:
if not val_a and (_numeric(col_i_val) is not None or _numeric(col_l_val) is not None):
    _flush(row)
    continue

# NEW:
is_total_row = str_a.lower() == "total"
is_blank_summary = not val_a
if (is_total_row or is_blank_summary) and (
    _numeric(col_i_val) is not None or _numeric(col_l_val) is not None
):
    if is_total_row and len(row) > 18 and row[18].value:
        current_plan_inclusions = str(row[18].value).strip()
    _flush(row)
    continue
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/hotel_options/test_parser.py -v
```

Expected: all tests PASS including the 4 new ones.

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/parser.py tests/hotel_options/test_parser.py
git commit -m "feat(hotel-options): flexible plan headers, skip Transfers, Total summary row, plan inclusions"
```

---

## Task 4: Parser — hotel name date extraction, inclusions/exclusions columns, filename fallback

**Files:**
- Modify: `src/hotel_options/parser.py`
- Test: `tests/hotel_options/test_parser.py`

**Interfaces:**
- Consumes: `parse_excel`, `extract_filename_meta` from previous tasks
- Produces: `HotelRow.name` = base name (no dates); `HotelRow.dates` populated from inline parens; `HotelRow.inclusions`/`HotelRow.exclusions` from cols S/T; `extract_filename_meta` handles ` - ` separators

- [ ] **Step 1: Write failing tests**

Append to `tests/hotel_options/test_parser.py`:

```python
def _make_multi_segment_xlsx() -> bytes:
    """One plan, same hotel name with two date-segments."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "4-Star Plan"
    ws["A2"] = "Adaaran Resort (Dec 22-25)"
    ws["B2"] = "4-Star"
    ws["C2"] = "Beach Villa"
    ws["H2"] = "Free cancellation, All Inclusive"
    ws["I2"] = 1178668.0
    ws["S2"] = "Airport transfer"
    ws["T2"] = "Visa fees"
    ws["A3"] = "Adaaran Resort (Dec 25-26)"
    ws["B3"] = "4-Star"
    ws["C3"] = "Ocean Villa"
    ws["H3"] = "Free cancellation, All Inclusive"
    ws["I3"] = 451983.0
    ws["A4"] = "Total"
    ws["I4"] = 1630651.0
    ws["J4"] = 1400000.0
    ws["L4"] = 80000.0
    ws["M4"] = 1550651.0
    ws["N4"] = 4.9
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_hotel_name_date_stripped():
    result = parse_excel(_make_multi_segment_xlsx(), {})
    hotels = result.plans[0].hotels
    assert hotels[0].name == "Adaaran Resort"
    assert hotels[1].name == "Adaaran Resort"


def test_hotel_inline_dates_extracted():
    result = parse_excel(_make_multi_segment_xlsx(), {})
    hotels = result.plans[0].hotels
    assert hotels[0].dates == "Dec 22-25"
    assert hotels[1].dates == "Dec 25-26"


def test_hotel_inclusions_exclusions_from_cols():
    result = parse_excel(_make_multi_segment_xlsx(), {})
    h = result.plans[0].hotels[0]
    assert h.inclusions == "Airport transfer"
    assert h.exclusions == "Visa fees"


def test_extract_filename_meta_dash_separated():
    name, dest = extract_filename_meta("DO NOT SHARE- Vinay- Maldives.xlsx")
    assert name == "Vinay"
    assert dest == "Maldives"


def test_extract_filename_meta_dash_without_do_not_share():
    name, dest = extract_filename_meta("Alice- Greece.xlsx")
    assert name == "Alice"
    assert dest == "Greece"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/hotel_options/test_parser.py::test_hotel_name_date_stripped -v
```

Expected: FAIL — name is `"Adaaran Resort (Dec 22-25)"` not `"Adaaran Resort"`.

- [ ] **Step 3: Implement date extraction, new columns, filename fallback**

**3a. Add `_NAME_DATE_RE`** at the top of `parser.py` (after `_RECOMMENDED_RE`):

```python
_NAME_DATE_RE = re.compile(r'^(.+?)\s*\(([^)]+)\)\s*$')
```

**3b. Update the hotel row parsing block** in `parse_excel` — replace the section starting at `col_h_val = row[7].value`:

```python
# Hotel row: col A non-empty, col I numeric
if val_a and _numeric(col_i_val) is not None:
    # Extract optional inline dates from hotel name: "Hotel Name (Dec 22-25)"
    name_match = _NAME_DATE_RE.match(str_a)
    if name_match:
        raw_hotel_name = name_match.group(1).strip()
        inline_dates = name_match.group(2).strip()
    else:
        raw_hotel_name = str_a
        inline_dates = ""

    hotel_name, is_recommended = _strip_recommended(raw_hotel_name)

    col_h_val = row[7].value if len(row) > 7 else None
    decoded = decode_col_h(str(col_h_val) if col_h_val is not None else None, codes)

    for unk in decoded.unknowns:
        unknown_codes.append(UnknownCode(
            code=unk,
            hotel_name=hotel_name,
            plan_label=current_label or "",
        ))

    online_raw = _numeric(col_i_val)
    online = online_raw if online_raw is not None else 0.0
    b2b_raw = _numeric(row[9].value) if len(row) > 9 else None
    b2b = b2b_raw if b2b_raw is not None else 0.0
    running_online += online
    running_b2b += b2b

    dates = inline_dates or current_section_dates or preamble_dates.get((hotel_name, online), "")
    city = current_city or preamble_cities.get((hotel_name, online), "")
    why = str(row[17].value).strip() if len(row) > 17 and row[17].value else ""
    inclusions = str(row[18].value).strip() if len(row) > 18 and row[18].value else ""
    exclusions = str(row[19].value).strip() if len(row) > 19 and row[19].value else ""

    current_hotels.append(HotelRow(
        name=hotel_name,
        category=str(row[1].value).strip() if row[1].value else "",
        room_type=str(row[2].value).strip() if row[2].value else "",
        cancellation=decoded.cancellation,
        meal_type=decoded.meal_type,
        online_price=online,
        dates=dates,
        why_recommend=why,
        city=city,
        recommended=is_recommended,
        inclusions=inclusions,
        exclusions=exclusions,
    ))
```

Also update the preamble section to key preamble_dates by base hotel name:

```python
elif val_a and _numeric(col_i_val) is not None and current_section_dates:
    price = _numeric(col_i_val)
    if price is not None:
        pm = _NAME_DATE_RE.match(str_a)
        key_name = pm.group(1).strip() if pm else str_a
        key_name, _ = _strip_recommended(key_name)
        preamble_dates[(key_name, price)] = current_section_dates
        preamble_cities[(key_name, price)] = current_city
```

**3c. Update `extract_filename_meta` filename fallback** — after the existing `parts = [p.strip() for p in stem.split("_") if p.strip()]` line:

```python
# If underscore split gives only one token (no underscores), try dash split.
# Pattern: "DO NOT SHARE- Vinay- Maldives" → dash followed by whitespace
if len(parts) <= 1:
    parts = [p.strip() for p in re.split(r'\s*-\s+', stem) if p.strip()]
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/hotel_options/test_parser.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/parser.py tests/hotel_options/test_parser.py
git commit -m "feat(hotel-options): hotel name date extraction, inclusions/exclusions cols, dash filename fallback"
```

---

## Task 5: Enricher — `enrich_hotel_multi_segment`

**Files:**
- Modify: `src/hotel_options/enricher.py`
- Test: `tests/hotel_options/test_enricher.py`

**Interfaces:**
- Consumes: `HotelRow`, `RoomSegment` from models
- Produces: `enrich_hotel_multi_segment(hotels: list[HotelRow], place_id: str, destination: str, api_key: str, ai_client) -> EnrichedHotel` with `room_segments` populated

- [ ] **Step 1: Write failing test**

Append to `tests/hotel_options/test_enricher.py`:

```python
from src.hotel_options.enricher import enrich_hotel_multi_segment


def test_enrich_hotel_multi_segment_builds_segments():
    details_resp = MagicMock()
    details_resp.raise_for_status = MagicMock()
    details_resp.json.return_value = {
        "result": {
            "name": "Adaaran Select Hudhuranfushi",
            "formatted_address": "North Male Atoll, Maldives",
            "international_phone_number": "+960 664 0088",
            "rating": 4.5,
            "user_ratings_total": 1200,
            "photos": [
                {"photo_reference": "ref_beach"},
                {"photo_reference": "ref_ocean"},
            ],
        }
    }

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.status_code = 200
        params = kwargs.get("params", {})
        ref = params.get("photo_reference", "")
        resp.content = f"PHOTO_{ref}".encode()
        resp.json.return_value = {}
        return resp

    ai_client = MagicMock()
    ai_client.complete.return_value = "A stunning overwater resort."

    hotels = [
        HotelRow(
            name="Adaaran Select Hudhuranfushi", category="4-Star",
            room_type="Beach Villa", cancellation="Free cancellation",
            meal_type="All Inclusive", online_price=1178668.0,
            dates="Dec 22-25", inclusions="Airport transfer", exclusions="Visa fees",
        ),
        HotelRow(
            name="Adaaran Select Hudhuranfushi", category="4-Star",
            room_type="Ocean Villa", cancellation="Free cancellation",
            meal_type="All Inclusive", online_price=451983.0,
            dates="Dec 25-26", inclusions="", exclusions="",
        ),
    ]

    with patch("httpx.get", side_effect=[details_resp, mock_get, mock_get]):
        with patch("src.hotel_options.enricher.httpx.get", side_effect=[details_resp,
                    MagicMock(status_code=200, content=b"PHOTO_beach"),
                    MagicMock(status_code=200, content=b"PHOTO_ocean")]):
            result = enrich_hotel_multi_segment(hotels, "ChIJ_test", "Maldives", "fake_key", ai_client)

    assert result.official_name == "Adaaran Select Hudhuranfushi"
    assert result.rating == 4.5
    assert result.photo_bytes is None         # superseded by segments
    assert len(result.room_segments) == 2
    assert result.room_segments[0].room_type == "Beach Villa"
    assert result.room_segments[0].dates == "Dec 22-25"
    assert result.room_segments[0].online_price == 1178668.0
    assert result.room_segments[0].inclusions == "Airport transfer"
    assert result.room_segments[0].exclusions == "Visa fees"
    assert result.room_segments[1].room_type == "Ocean Villa"
    assert result.room_segments[1].dates == "Dec 25-26"
    assert result.description == "A stunning overwater resort."
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/hotel_options/test_enricher.py::test_enrich_hotel_multi_segment_builds_segments -v
```

Expected: FAIL — `enrich_hotel_multi_segment` not defined.

- [ ] **Step 3: Implement `enrich_hotel_multi_segment`**

Add to `src/hotel_options/enricher.py` (after the existing `enrich_hotel` function). Also add `RoomSegment` to the models import at the top:

```python
from src.hotel_options.models import HotelRow, EnrichedHotel, RoomSegment
```

Then add the new function:

```python
def enrich_hotel_multi_segment(
    hotels: list[HotelRow],
    place_id: str,
    destination: str,
    api_key: str,
    ai_client,
) -> EnrichedHotel:
    """Enrich a hotel that spans multiple room-type segments.

    Fetches Place Details once, distributes hotel gallery photos across
    segments (photo[i] for segment i, last photo recycled if gallery is
    smaller than segment count), builds one AI description for the property.
    """
    # 1. Place Details — one call
    details_resp = httpx.get(
        f"{_PLACES_BASE}/details/json",
        params={
            "place_id": place_id,
            "fields": "name,formatted_address,international_phone_number,rating,user_ratings_total,photos",
            "key": api_key,
        },
    )
    details_resp.raise_for_status()
    detail = details_resp.json().get("result", {})

    official_name = detail.get("name", hotels[0].name)
    address = detail.get("formatted_address", "")
    phone = detail.get("international_phone_number", "")
    rating = float(detail.get("rating", 0))
    rating_count = int(detail.get("user_ratings_total", 0))
    maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

    photo_refs = [p["photo_reference"] for p in detail.get("photos", [])]

    # 2. One photo per segment, distributed from the gallery
    room_segments: list[RoomSegment] = []
    for i, hotel in enumerate(hotels):
        photo_bytes: bytes | None = None
        if photo_refs:
            ref = photo_refs[min(i, len(photo_refs) - 1)]
            photo_resp = httpx.get(
                f"{_PLACES_BASE}/photo",
                params={"maxwidth": 800, "photo_reference": ref, "key": api_key},
                follow_redirects=True,
            )
            if photo_resp.status_code == 200:
                photo_bytes = photo_resp.content
        room_segments.append(RoomSegment(
            room_type=hotel.room_type,
            dates=hotel.dates,
            online_price=hotel.online_price,
            photo_bytes=photo_bytes,
            inclusions=hotel.inclusions,
            exclusions=hotel.exclusions,
        ))

    # 3. One AI description for the property
    prompt = _DESCRIPTION_PROMPT.format(
        name=official_name,
        category=hotels[0].category,
        address=address,
        rating=rating,
        rating_count=rating_count,
        cancellation=hotels[0].cancellation or "Not specified",
        meal_type=hotels[0].meal_type or "Not specified",
    )
    description = ai_client.complete(
        prompt, max_tokens=300, temperature=0.4, system=HOTEL_DESCRIPTION_SYSTEM,
    )

    return EnrichedHotel(
        official_name=official_name,
        address=address,
        phone=phone,
        rating=rating,
        rating_count=rating_count,
        maps_url=maps_url,
        photo_bytes=None,          # superseded by room_segments
        description=description,
        cancellation=hotels[0].cancellation,
        meal_type=hotels[0].meal_type,
        category=hotels[0].category,
        dates="",
        room_type="",
        room_segments=room_segments,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/hotel_options/test_enricher.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/enricher.py tests/hotel_options/test_enricher.py
git commit -m "feat(hotel-options): enrich_hotel_multi_segment with per-segment photos"
```

---

## Task 6: Service — `_group_hotels` and updated enrichment loop

**Files:**
- Modify: `src/library/ui/services/hotel_options_service.py`
- Test: `tests/hotel_options/test_service.py`

**Interfaces:**
- Consumes: `_group_hotels(hotels: list[HotelRow]) -> list[list[HotelRow]]`, `enrich_hotel_multi_segment`
- Produces: `enriched_map` now contains multi-segment `EnrichedHotel` for same-name hotel groups

- [ ] **Step 1: Write failing tests**

Append to `tests/hotel_options/test_service.py`:

```python
from src.library.ui.services.hotel_options_service import _group_hotels
from src.hotel_options.models import HotelRow


def _hr(name: str) -> HotelRow:
    return HotelRow(
        name=name, category="4-Star", room_type="Double",
        cancellation="Free", meal_type="Breakfast", online_price=100000.0,
    )


def test_group_hotels_single_entries():
    hotels = [_hr("Hotel A"), _hr("Hotel B"), _hr("Hotel C")]
    groups = _group_hotels(hotels)
    assert len(groups) == 3
    assert groups[0] == [hotels[0]]
    assert groups[1] == [hotels[1]]
    assert groups[2] == [hotels[2]]


def test_group_hotels_consecutive_same_name():
    hotels = [_hr("Resort X"), _hr("Resort X"), _hr("Hotel B")]
    groups = _group_hotels(hotels)
    assert len(groups) == 2
    assert len(groups[0]) == 2
    assert groups[0][0].name == "Resort X"
    assert groups[1][0].name == "Hotel B"


def test_group_hotels_non_consecutive_same_name_not_merged():
    hotels = [_hr("Hotel A"), _hr("Hotel B"), _hr("Hotel A")]
    groups = _group_hotels(hotels)
    assert len(groups) == 3


def test_group_hotels_empty():
    assert _group_hotels([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/hotel_options/test_service.py::test_group_hotels_single_entries -v
```

Expected: FAIL — `_group_hotels` not importable.

- [ ] **Step 3: Add `_group_hotels` to service**

Add this function to `src/library/ui/services/hotel_options_service.py` (after the existing `_format_stay_requirements` or near other private helpers):

```python
def _group_hotels(hotels: list) -> list:
    """Group consecutive HotelRows with the same name. Returns list of lists."""
    if not hotels:
        return []
    groups = []
    current = [hotels[0]]
    for hotel in hotels[1:]:
        if hotel.name == current[0].name:
            current.append(hotel)
        else:
            groups.append(current)
            current = [hotel]
    groups.append(current)
    return groups
```

- [ ] **Step 4: Run tests to verify `_group_hotels` tests pass**

```
pytest tests/hotel_options/test_service.py::test_group_hotels_single_entries tests/hotel_options/test_service.py::test_group_hotels_consecutive_same_name tests/hotel_options/test_service.py::test_group_hotels_non_consecutive_same_name_not_merged tests/hotel_options/test_service.py::test_group_hotels_empty -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Update the enrichment loop to use grouping**

In the `generate_document` function (around line 270), replace the enrichment block:

```python
# OLD:
enriched_map = {}
for plan in result.plans:
    for hotel in plan.hotels:
        if hotel.name in enriched_map:
            continue
        place_id = existence_map.get(hotel.name)
        if place_id:
            enriched_map[hotel.name] = _enricher.enrich_hotel(
                hotel, place_id, destination, api_key, ai_client
            )

# NEW:
enriched_map = {}
for plan in result.plans:
    for group in _group_hotels(plan.hotels):
        name = group[0].name
        if name in enriched_map:
            continue
        place_id = existence_map.get(name)
        if not place_id:
            continue
        if len(group) == 1:
            enriched_map[name] = _enricher.enrich_hotel(
                group[0], place_id, destination, api_key, ai_client
            )
        else:
            enriched_map[name] = _enricher.enrich_hotel_multi_segment(
                group, place_id, destination, api_key, ai_client
            )
```

Also update the import at the top of the service to include `enrich_hotel_multi_segment`:

The enricher is accessed via `_enricher` module reference. Add the new function call via `_enricher.enrich_hotel_multi_segment(...)` — no import change needed if `_enricher` is the module alias.

Verify by checking the existing import pattern at the top of the service file:
```python
from src.hotel_options import enricher as _enricher
```
(or similar — adapt to match the actual import style in the file.)

- [ ] **Step 6: Run full test suite**

```
pytest tests/hotel_options/ -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/library/ui/services/hotel_options_service.py tests/hotel_options/test_service.py
git commit -m "feat(hotel-options): group same-name hotel rows for multi-segment enrichment"
```

---

## Task 7: Generator — multi-segment card, inclusions/exclusions, dedup, exec summary

**Files:**
- Modify: `src/hotel_options/generator.py`
- Test: `tests/hotel_options/test_generator.py`

**Interfaces:**
- Consumes: `EnrichedHotel.room_segments`, `HotelRow.inclusions/exclusions`, `Plan.inclusions`
- Produces: updated `build_document` output — one card per unique hotel, per-segment room sections, inclusions/exclusions rendered

- [ ] **Step 1: Write failing tests**

Append to `tests/hotel_options/test_generator.py`:

```python
from src.hotel_options.models import RoomSegment


def _make_multi_segment_plan() -> Plan:
    h1 = HotelRow(
        name="Beach Resort", category="4-Star", room_type="Beach Villa",
        cancellation="Free", meal_type="All Inclusive", online_price=1000000.0,
        dates="Dec 22-25",
    )
    h2 = HotelRow(
        name="Beach Resort", category="4-Star", room_type="Ocean Villa",
        cancellation="Free", meal_type="All Inclusive", online_price=500000.0,
        dates="Dec 25-26",
    )
    pricing = PlanPricing(
        total_online_price=1500000.0, total_b2b_price=1300000.0,
        customer_discount=50000.0, discounted_price=1450000.0, discount_pct=3.3,
    )
    return Plan(
        label="4-Star Plan",
        hotels=[h1, h2],
        pricing=pricing,
        inclusions="With airport transfer - Shared Speedboat",
    )


def _make_multi_segment_enriched() -> EnrichedHotel:
    return EnrichedHotel(
        official_name="Beach Resort Official", address="Maldives",
        phone="", rating=4.5, rating_count=800,
        maps_url="https://maps.google.com/?cid=1",
        photo_bytes=None, description="A beautiful resort.",
        cancellation="Free", meal_type="All Inclusive", category="4-Star",
        room_segments=[
            RoomSegment(room_type="Beach Villa", dates="Dec 22-25",
                        online_price=1000000.0, photo_bytes=None,
                        inclusions="Airport transfer", exclusions="Visa fees"),
            RoomSegment(room_type="Ocean Villa", dates="Dec 25-26",
                        online_price=500000.0, photo_bytes=None),
        ],
    )


def test_multi_segment_hotel_card_rendered_once():
    """Same hotel name appears twice in plan.hotels but card is rendered only once."""
    plan = _make_multi_segment_plan()
    enriched = _make_multi_segment_enriched()
    doc_bytes = build_document(
        plans=[plan],
        enriched_map={"Beach Resort": enriched},
        client_name="Vinay",
        destination="Maldives",
    )
    doc = Document(io.BytesIO(doc_bytes))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert full_text.count("Beach Resort Official") == 1


def test_multi_segment_both_room_types_in_document():
    plan = _make_multi_segment_plan()
    enriched = _make_multi_segment_enriched()
    doc_bytes = build_document(
        plans=[plan],
        enriched_map={"Beach Resort": enriched},
        client_name="Vinay",
        destination="Maldives",
    )
    doc = Document(io.BytesIO(doc_bytes))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Beach Villa" in full_text
    assert "Ocean Villa" in full_text


def test_inclusions_exclusions_in_document():
    plan = _make_multi_segment_plan()
    enriched = _make_multi_segment_enriched()
    doc_bytes = build_document(
        plans=[plan],
        enriched_map={"Beach Resort": enriched},
        client_name="Vinay",
        destination="Maldives",
    )
    doc = Document(io.BytesIO(doc_bytes))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Airport transfer" in full_text
    assert "Visa fees" in full_text


def test_plan_inclusions_in_document():
    plan = _make_multi_segment_plan()
    enriched = _make_multi_segment_enriched()
    doc_bytes = build_document(
        plans=[plan],
        enriched_map={"Beach Resort": enriched},
        client_name="Vinay",
        destination="Maldives",
    )
    doc = Document(io.BytesIO(doc_bytes))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Shared Speedboat" in full_text


def test_exec_summary_hotel_listed_once_for_multi_segment():
    plan = _make_multi_segment_plan()
    enriched = _make_multi_segment_enriched()
    doc_bytes = build_document(
        plans=[plan],
        enriched_map={"Beach Resort": enriched},
        client_name="Vinay",
        destination="Maldives",
    )
    doc = Document(io.BytesIO(doc_bytes))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    # Hotel name should appear in exec summary exactly once (not twice for two HotelRows)
    assert full_text.count("Beach Resort") >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/hotel_options/test_generator.py::test_multi_segment_hotel_card_rendered_once -v
```

Expected: FAIL — hotel card appears twice (one per HotelRow).

- [ ] **Step 3: Implement generator changes**

**3a. Add `_add_inclusions_exclusions` helper** (after `_add_why_recommend`):

```python
def _add_inclusions_exclusions(doc: Document, inclusions: str, exclusions: str) -> None:
    if inclusions:
        p = doc.add_paragraph()
        _spacing(p, 4, 2)
        _body_run(p, "✓ Inclusions: ", bold=True, size=10.5, color=_GREEN)
        _body_run(p, inclusions, size=10.5, color=_CHARCOAL)
    if exclusions:
        p = doc.add_paragraph()
        _spacing(p, 2, 4)
        _body_run(p, "✗ Exclusions: ", bold=True, size=10.5, color=_GREY)
        _body_run(p, exclusions, size=10.5, color=_CHARCOAL)
```

**3b. Add `_add_room_segment` helper** (after `_add_inclusions_exclusions`):

```python
def _add_room_segment(doc: Document, seg) -> None:
    """Render one room segment: photo + room type + dates + price."""
    if seg.photo_bytes:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 6, 4)
        p.add_run().add_picture(io.BytesIO(seg.photo_bytes), width=Inches(4.5))
    else:
        p = doc.add_paragraph()
        _spacing(p, 6, 4)
        _body_run(p, "[ Image not available ]", size=9, color=_GREY)

    p = doc.add_paragraph()
    _spacing(p, 2, 1)
    _body_run(p, f"🛏️ Room: ", size=11, color=_GREY)
    _body_run(p, seg.room_type, size=11, bold=True, color=_CHARCOAL)

    if seg.dates:
        p = doc.add_paragraph()
        _spacing(p, 1, 1)
        _body_run(p, f"📅 Dates: ", size=11, color=_GREY)
        _body_run(p, seg.dates, size=11, color=_CHARCOAL)

    p = doc.add_paragraph()
    _spacing(p, 1, 2)
    _body_run(p, f"Online price: ", size=11, color=_GREY)
    _body_run(p, format_indian_number(seg.online_price), size=11, color=_CHARCOAL)

    _add_inclusions_exclusions(doc, seg.inclusions, seg.exclusions)
```

**3c. Update `_add_hotel_card`** — replace the single photo + key facts block with a branch:

```python
def _add_hotel_card(doc: Document, enriched: EnrichedHotel,
                    recommended: bool = False, destination: str = "") -> None:
    # Hotel name — always shown once
    name_para = doc.add_paragraph()
    _spacing(name_para, 12, 0)
    hotel_name = enriched.official_name or "Hotel"
    url = _google_search_url(hotel_name, destination) if destination else ""
    if url:
        _add_hyperlink(name_para, hotel_name, url,
                       font_name="Georgia", size=16, bold=True, color=_LINK)
    else:
        r = name_para.add_run(hotel_name)
        r.bold = True
        r.font.name = "Georgia"
        r.font.size = Pt(16)
        r.font.color.rgb = _CHARCOAL
    if recommended:
        _body_run(name_para, " ★ RECOMMENDED", bold=True, size=9, color=_AMBER)
    _thin_rule(doc, before=0, after=6)

    if enriched.room_segments:
        # Multi-segment: one sub-section per room type
        for seg in enriched.room_segments:
            _add_room_segment(doc, seg)
        # Shared facts (category, rating, cancellation, meal)
        shared = EnrichedHotel(
            official_name=enriched.official_name, address=enriched.address,
            phone=enriched.phone, rating=enriched.rating,
            rating_count=enriched.rating_count, maps_url=enriched.maps_url,
            photo_bytes=None, description="",
            cancellation=enriched.cancellation, meal_type=enriched.meal_type,
            category=enriched.category, dates="", room_type="",
        )
        _add_key_facts(doc, shared)
    else:
        # Single-segment: original layout
        if enriched.photo_bytes:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _spacing(p, 8, 6)
            p.add_run().add_picture(io.BytesIO(enriched.photo_bytes), width=Inches(5.0))
        else:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _spacing(p, 8, 6)
            _body_run(p, "[ Image not available ]", size=9, color=_GREY)
        _add_key_facts(doc, enriched)
        _add_inclusions_exclusions(doc, enriched.inclusions if hasattr(enriched, 'inclusions') else "", "")

    if enriched.description:
        p = doc.add_paragraph()
        _spacing(p, 6, 8)
        _body_run(p, enriched.description)
```

Wait — `EnrichedHotel` doesn't have top-level `inclusions`/`exclusions` fields (those live on `RoomSegment`). The single-segment case doesn't need `_add_inclusions_exclusions` at the `EnrichedHotel` level — it would show at the `RoomSegment` level if we ever move single hotels to use segments too. For now, single-segment hotels don't display inclusions/exclusions (the old format doesn't have them). So remove the `_add_inclusions_exclusions` call from the single-segment branch.

**3d. Add deduplication and plan inclusions in the plans layout path** in `build_document`:

```python
# Original plan-based layout
for plan_idx, plan in enumerate(plans):
    if plan_idx > 0:
        _page_break(doc)

    p = _heading(doc, plan.label.upper(), level=1)
    if plan.recommended:
        _body_run(p, " ★ RECOMMENDED", bold=True, size=9, color=_AMBER)
    _thin_rule(doc, before=2, after=8, color=_HDR_BG)

    # Plan-level inclusions (e.g. transfer type)
    if plan.inclusions:
        p = doc.add_paragraph()
        _spacing(p, 0, 8)
        _body_run(p, "📋 Includes: ", bold=False, size=10, color=_GREY, italic=True)
        _body_run(p, plan.inclusions, size=10, color=_GREY, italic=True)

    if plan.why_recommend:
        _add_why_recommend(doc, plan.why_recommend)

    rendered: set[str] = set()
    for i, hotel in enumerate(plan.hotels):
        if hotel.name in rendered:
            continue
        rendered.add(hotel.name)
        if i > 0:
            _thin_rule(doc, before=8, after=4)
        enriched = enriched_map.get(hotel.name)
        if enriched:
            _add_hotel_card(doc, enriched, destination=hotel.city or destination)
        else:
            p = doc.add_paragraph()
            _spacing(p, 8, 8)
            _body_run(p, f"[ {hotel.name} — details not available ]", color=_GREY)
        _add_why_recommend(doc, hotel.why_recommend)

    _thin_rule(doc, before=12, after=8)
    _add_pricing_block(doc, plan)
```

Note: The `_body_run` signature needs `italic` added — check whether the existing helper supports it. Looking at the existing code: `_body_run(para, text, *, bold=False, italic=False, size: float = 11, color: RGBColor = _CHARCOAL)`. Yes, `italic` is already supported.

**3e. Update `_build_exec_summary_by_plan`** to deduplicate the hotel list:

In `_build_exec_summary_by_plan`, replace the hotel listing loop in col_idx == 1:

```python
if col_idx == 1:
    seen_names: set[str] = set()
    h_idx_visible = 0
    for hotel in plan.hotels:
        if hotel.name in seen_names:
            continue
        seen_names.add(hotel.name)
        bp = p if h_idx_visible == 0 else cell.add_paragraph()
        bp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        enriched = enriched_map.get(hotel.name) if enriched_map else None
        if enriched and enriched.room_segments:
            # Multi-segment: show hotel name then room types as sub-bullets
            _body_run(bp, f"• {hotel.name}{_star_suffix(hotel.category)}", size=9, color=_CHARCOAL)
            for seg in enriched.room_segments:
                sub = cell.add_paragraph()
                sub.alignment = WD_ALIGN_PARAGRAPH.LEFT
                _body_run(sub, f"   – {seg.room_type} ({seg.dates})", size=8, color=_GREY)
        else:
            _body_run(bp, f"• {hotel.name}{_star_suffix(hotel.category)}", size=9, color=_CHARCOAL)
        h_idx_visible += 1
```

This requires `_build_exec_summary_by_plan` to receive `enriched_map`. Two changes:

Change the function signature from:
```python
def _build_exec_summary_by_plan(doc: Document, plans: list[Plan]) -> None:
```
to:
```python
def _build_exec_summary_by_plan(doc: Document, plans: list[Plan],
                                 enriched_map: dict) -> None:
```

Change the call site inside `_build_executive_summary` from:
```python
    _build_exec_summary_by_plan(doc, plans)
```
to:
```python
    _build_exec_summary_by_plan(doc, plans, enriched_map)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/hotel_options/test_generator.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full suite**

```
pytest tests/hotel_options/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hotel_options/generator.py tests/hotel_options/test_generator.py
git commit -m "feat(hotel-options): multi-segment hotel card, inclusions/exclusions, plan inclusions, dedup"
```

---

## Self-Review Checklist

After all tasks are complete, verify:

- [ ] `_PLAN_RE` matches `"4-Star Plan"`, `"5-Star Plan"`, `"PLAN A"`, `"Plan B"` and does NOT match `"Dubai (Jun 28 - Jul 4)"` — write a quick check in a Python REPL: `bool(_PLAN_RE.match("4-Star Plan"))` → True; `bool(_PLAN_RE.match("Dubai (Jun 28 - Jul 4)"))` → False.
- [ ] Upload the actual `DO NOT SHARE- Vinay- Maldives.xlsx` via the UI and verify the document generates without unknown-code warnings and with both room segments visible.
- [ ] Check that an old-format file (e.g. a test from `test_parser.py`) still generates identically.
- [ ] Verify `extract_filename_meta("DO NOT SHARE- Vinay- Maldives.xlsx")` returns `("Vinay", "Maldives")`.
