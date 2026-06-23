# Hotel Options Document Generator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Hotel Options" tab to the Library QC web UI that accepts an internal hotel comparison Excel file, enriches hotels via Google Places, and produces a client-facing Word document.

**Architecture:** New `src/hotel_options/` package (models → codes → decoder → parser → enricher → generator), three FastAPI endpoints in `src/library/ui/api/hotel_options.py` orchestrated by a service, and a `HotelOptionsTab.tsx` React component wired into the existing tab layout.

**Tech Stack:** Python (openpyxl, httpx, python-docx, FastAPI), Google Places API, OpenAI-compatible AI via `src/common/ai_provider.py`, React + TypeScript.

## Global Constraints

- Storage key for codes: `hotel_options/hotel_codes.json` — read/write via `StorageBackend` from `src.library.ui.storage`
- Google Places key: `GOOGLE_MAPS_API_KEY` env var
- Letterhead: `input/BVBM Company Letterhead.docx` relative to cwd; configurable via `LETTERHEAD_PATH` env var; skip letterhead section if file not found
- AI client: `get_ai_client()` from `src.common.ai_provider`
- No admin gate — hotel_options router registered like `verify.router` (all authenticated users)
- Indian number format: ₹1,76,622 (not ₹176,622)
- Workbook opened with `data_only=True`; if formula cell is None, calculate from adjacent numeric cells
- Only the first sheet of the workbook is processed
- `total_b2b_price` is internal — never serialised in API responses
- `openpyxl` must be added to `requirements.txt`

---

### Task 1: Models and package scaffold

**Files:**
- Create: `src/hotel_options/__init__.py`
- Create: `src/hotel_options/models.py`
- Create: `tests/hotel_options/__init__.py`
- Create: `tests/hotel_options/test_models.py`

**Interfaces:**
- Produces:
  - `HotelRow(name, category, room_type, cancellation, meal_type, online_price)`
  - `PlanPricing(total_online_price, total_b2b_price, customer_discount, discounted_price, discount_pct)`
  - `Plan(label, hotels, pricing)`
  - `UnknownCode(code, hotel_name, plan_label)`
  - `ParseResult(plans, unknown_codes, not_found)` where `not_found` is `list[dict]` with keys `sheet_name`, `plan_label`
  - `EnrichedHotel(official_name, address, phone, rating, rating_count, maps_url, photo_bytes, description, cancellation, meal_type, category)`

- [ ] **Step 1: Write the failing test**

```python
# tests/hotel_options/test_models.py
from src.hotel_options.models import (
    HotelRow, PlanPricing, Plan, UnknownCode, ParseResult, EnrichedHotel,
)

def test_hotel_row_fields():
    h = HotelRow(
        name="Hilton London",
        category="5-Star",
        room_type="King Room",
        cancellation="Non-refundable",
        meal_type="Breakfast included",
        online_price=50000.0,
    )
    assert h.name == "Hilton London"
    assert h.online_price == 50000.0

def test_plan_pricing_fields():
    p = PlanPricing(
        total_online_price=100000.0,
        total_b2b_price=90000.0,
        customer_discount=5000.0,
        discounted_price=95000.0,
        discount_pct=5.0,
    )
    assert p.discounted_price == 95000.0

def test_parse_result_fields():
    r = ParseResult(plans=[], unknown_codes=[], not_found=[])
    assert r.plans == []

def test_enriched_hotel_photo_optional():
    e = EnrichedHotel(
        official_name="Hilton London Kensington",
        address="179 Holland Park Ave",
        phone="+44 20 7602 3355",
        rating=4.2,
        rating_count=1847,
        maps_url="https://maps.google.com/?cid=123",
        photo_bytes=None,
        description="A refined hotel.",
        cancellation="Non-refundable",
        meal_type="Breakfast included",
        category="5-Star",
    )
    assert e.photo_bytes is None
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/hotel_options/test_models.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.hotel_options'`

- [ ] **Step 3: Create package files**

`src/hotel_options/__init__.py` — empty file.

`tests/hotel_options/__init__.py` — empty file.

`src/hotel_options/models.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class HotelRow:
    name: str
    category: str
    room_type: str
    cancellation: str
    meal_type: str
    online_price: float


@dataclass
class PlanPricing:
    total_online_price: float
    total_b2b_price: float
    customer_discount: float
    discounted_price: float
    discount_pct: float


@dataclass
class Plan:
    label: str
    hotels: list[HotelRow]
    pricing: PlanPricing


@dataclass
class UnknownCode:
    code: str
    hotel_name: str
    plan_label: str


@dataclass
class ParseResult:
    plans: list[Plan]
    unknown_codes: list[UnknownCode]
    not_found: list[dict]


@dataclass
class EnrichedHotel:
    official_name: str
    address: str
    phone: str
    rating: float
    rating_count: int
    maps_url: str
    photo_bytes: bytes | None
    description: str
    cancellation: str
    meal_type: str
    category: str
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/hotel_options/test_models.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/__init__.py src/hotel_options/models.py tests/hotel_options/__init__.py tests/hotel_options/test_models.py
git commit -m "feat(hotel-options): models and package scaffold"
```

---

### Task 2: Code store

**Files:**
- Create: `src/hotel_options/codes.py`
- Create: `tests/hotel_options/test_codes.py`

**Interfaces:**
- Consumes: `StorageBackend` from `src.library.ui.storage`
- Produces: `CodeStore(storage)` with `.load() -> dict[str, str]` and `.save(codes: dict[str, str]) -> None`

**Notes:** Seed mappings (`nr`, `br`) are always present. User mappings in `hotel_codes.json` are merged on top of seeds on every load.

- [ ] **Step 1: Write the failing test**

```python
# tests/hotel_options/test_codes.py
from src.hotel_options.codes import CodeStore
from src.library.ui.storage import LocalStorageBackend


def test_load_returns_seeds_when_file_missing(tmp_path):
    store = CodeStore(LocalStorageBackend(tmp_path))
    codes = store.load()
    assert codes["nr"] == "Non-refundable"
    assert codes["br"] == "Breakfast included"


def test_save_and_reload(tmp_path):
    store = CodeStore(LocalStorageBackend(tmp_path))
    codes = store.load()
    codes["hb"] = "Half board included"
    store.save(codes)

    store2 = CodeStore(LocalStorageBackend(tmp_path))
    reloaded = store2.load()
    assert reloaded["hb"] == "Half board included"
    assert reloaded["nr"] == "Non-refundable"  # seed preserved


def test_save_does_not_lose_seeds(tmp_path):
    store = CodeStore(LocalStorageBackend(tmp_path))
    store.save({"hb": "Half board"})
    reloaded = store.load()
    assert reloaded["nr"] == "Non-refundable"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/hotel_options/test_codes.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.hotel_options.codes'`

- [ ] **Step 3: Implement CodeStore**

`src/hotel_options/codes.py`:
```python
from __future__ import annotations
from src.library.ui.storage import StorageBackend

_KEY = "hotel_options/hotel_codes.json"

_SEEDS: dict[str, str] = {
    "nr": "Non-refundable",
    "br": "Breakfast included",
}


class CodeStore:
    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    def load(self) -> dict[str, str]:
        saved = self._storage.read_json(_KEY) or {}
        return {**_SEEDS, **saved}

    def save(self, codes: dict[str, str]) -> None:
        # Persist only non-seed entries; seeds are re-applied at load time
        to_save = {k: v for k, v in codes.items() if k not in _SEEDS}
        self._storage.write_json(_KEY, to_save)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/hotel_options/test_codes.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/codes.py tests/hotel_options/test_codes.py
git commit -m "feat(hotel-options): code store with seed mappings"
```

---

### Task 3: Column H decoder

**Files:**
- Create: `src/hotel_options/decoder.py`
- Create: `tests/hotel_options/test_decoder.py`

**Interfaces:**
- Consumes: `codes: dict[str, str]` (from `CodeStore.load()`)
- Produces:
  - `DecodedCell(cancellation: str, meal_type: str, unknowns: list[str])`
  - `decode_col_h(value: str | None, codes: dict[str, str]) -> DecodedCell`

**Decoding logic:**
- Split raw cell value on `". "` to get segments (`"nr. br"` → `["nr", "br"]`; `"26 jun. br"` → `["26 jun", "br"]`)
- Date pattern `^\d{1,2}\s+[a-z]{3}$` (case-insensitive) → `cancellation = "Free cancellation till {segment.title()}"`
- Code `"nr"` → `cancellation` field; all other known codes → `meal_type` field
- Unrecognised token → appended to `unknowns`

- [ ] **Step 1: Write the failing test**

```python
# tests/hotel_options/test_decoder.py
from src.hotel_options.decoder import decode_col_h

CODES = {"nr": "Non-refundable", "br": "Breakfast included", "hb": "Half board included"}


def test_empty_value():
    r = decode_col_h(None, CODES)
    assert r.cancellation == ""
    assert r.meal_type == ""
    assert r.unknowns == []


def test_nr_only():
    r = decode_col_h("nr", CODES)
    assert r.cancellation == "Non-refundable"
    assert r.meal_type == ""


def test_br_only():
    r = decode_col_h("br", CODES)
    assert r.cancellation == ""
    assert r.meal_type == "Breakfast included"


def test_nr_dot_br():
    r = decode_col_h("nr. br", CODES)
    assert r.cancellation == "Non-refundable"
    assert r.meal_type == "Breakfast included"


def test_date_dot_br():
    r = decode_col_h("26 jun. br", CODES)
    assert r.cancellation == "Free cancellation till 26 Jun"
    assert r.meal_type == "Breakfast included"


def test_unknown_code():
    r = decode_col_h("xy", CODES)
    assert "xy" in r.unknowns


def test_user_defined_code_is_meal():
    r = decode_col_h("hb", CODES)
    assert r.meal_type == "Half board included"
    assert r.unknowns == []
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/hotel_options/test_decoder.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.hotel_options.decoder'`

- [ ] **Step 3: Implement decoder**

`src/hotel_options/decoder.py`:
```python
from __future__ import annotations
import re
from dataclasses import dataclass, field

_DATE_RE = re.compile(r'^\d{1,2}\s+[a-z]{3}$', re.IGNORECASE)
_CANCELLATION_CODES = {"nr"}


@dataclass
class DecodedCell:
    cancellation: str = ""
    meal_type: str = ""
    unknowns: list[str] = field(default_factory=list)


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

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/hotel_options/test_decoder.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/decoder.py tests/hotel_options/test_decoder.py
git commit -m "feat(hotel-options): column H decoder"
```

---

### Task 4: Excel parser

**Files:**
- Create: `src/hotel_options/parser.py`
- Create: `tests/hotel_options/test_parser.py`

**Interfaces:**
- Consumes: `decode_col_h` from `src.hotel_options.decoder`; models from `src.hotel_options.models`
- Produces:
  - `extract_filename_meta(filename: str) -> tuple[str, str]` → `(client_name, destination)`
  - `parse_excel(xlsx_bytes: bytes, codes: dict[str, str]) -> ParseResult`

**Row classification (columns 0-indexed in tuple):** col A=`row[0]`, col B=`row[1]`, col H=`row[7]`, col I=`row[8]`, col J=`row[9]`, col L=`row[11]`, col M=`row[12]`, col N=`row[13]`
- `plan_header`: col A matches `PLAN [A-Z]` (case-insensitive)
- `hotel_row`: col A is non-empty string (not plan pattern), col I is numeric, col A `font.strike` is not True
- `plan_summary`: col A is None/blank AND (col I is numeric OR col L is numeric)
- Everything else: ignored; rows before first plan header are also ignored

**Filename pattern:** `"DO NOT SHARE_ Bushan_Accommodation Options_London.xlsx"` → `("Bushan", "London")`. Regex: segment between first `_` (after optional `DO NOT SHARE_ ` prefix) and `_Accommodation Options_`; last `_`-segment before `.xlsx` for destination. Fall back to `("", last_segment)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/hotel_options/test_parser.py
import io
import openpyxl
from src.hotel_options.parser import extract_filename_meta, parse_excel

CODES = {"nr": "Non-refundable", "br": "Breakfast included"}


def make_sample_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "PLAN A"
    ws["A2"] = "Hilton London"
    ws["B2"] = "5-Star"
    ws["C2"] = "King Room"
    ws["H2"] = "nr. br"
    ws["I2"] = 50000.0
    ws["J2"] = 45000.0
    # Plan A summary: col A blank, totals in I/J/L/M/N
    ws["I3"] = 50000.0
    ws["J3"] = 45000.0
    ws["L3"] = 3000.0
    ws["M3"] = 47000.0
    ws["N3"] = 6.0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_filename_meta_standard():
    name, dest = extract_filename_meta("DO NOT SHARE_ Bushan_Accommodation Options_London.xlsx")
    assert name == "Bushan"
    assert dest == "London"


def test_extract_filename_meta_fallback():
    _, dest = extract_filename_meta("some_random_file.xlsx")
    assert dest == "file"


def test_parse_returns_one_plan():
    result = parse_excel(make_sample_xlsx(), CODES)
    assert len(result.plans) == 1
    assert result.plans[0].label == "Plan A"


def test_parse_hotel_decoded():
    result = parse_excel(make_sample_xlsx(), CODES)
    hotel = result.plans[0].hotels[0]
    assert hotel.name == "Hilton London"
    assert hotel.cancellation == "Non-refundable"
    assert hotel.meal_type == "Breakfast included"
    assert hotel.online_price == 50000.0


def test_parse_pricing():
    result = parse_excel(make_sample_xlsx(), CODES)
    pricing = result.plans[0].pricing
    assert pricing.total_online_price == 50000.0
    assert pricing.customer_discount == 3000.0
    assert pricing.discounted_price == 47000.0
    assert pricing.discount_pct == 6.0


def test_no_unknown_codes():
    result = parse_excel(make_sample_xlsx(), CODES)
    assert result.unknown_codes == []


def test_unknown_code_flagged():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "PLAN A"
    ws["A2"] = "Test Hotel"
    ws["B2"] = "3-Star"
    ws["C2"] = "Double"
    ws["H2"] = "xy"
    ws["I2"] = 10000.0
    ws["J2"] = 9000.0
    ws["I3"] = 10000.0
    ws["J3"] = 9000.0
    ws["L3"] = 0.0
    ws["M3"] = 10000.0
    ws["N3"] = 0.0
    buf = io.BytesIO()
    wb.save(buf)
    result = parse_excel(buf.getvalue(), CODES)
    assert len(result.unknown_codes) == 1
    assert result.unknown_codes[0].code == "xy"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/hotel_options/test_parser.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.hotel_options.parser'`

- [ ] **Step 3: Implement parser**

`src/hotel_options/parser.py`:
```python
from __future__ import annotations
import io
import re

import openpyxl

from src.hotel_options.decoder import decode_col_h
from src.hotel_options.models import (
    HotelRow, PlanPricing, Plan, UnknownCode, ParseResult,
)

_PLAN_RE = re.compile(r'^PLAN\s+[A-Z]$', re.IGNORECASE)
_FILENAME_RE = re.compile(
    r'(?:DO NOT SHARE_\s*)?([^_]+)_Accommodation Options_([^_.]+)\.xlsx$',
    re.IGNORECASE,
)


def extract_filename_meta(filename: str) -> tuple[str, str]:
    m = _FILENAME_RE.search(filename)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    stem = filename.rsplit(".", 1)[0]
    parts = stem.split("_")
    return "", parts[-1].strip() if parts else ""


def _numeric(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    return None


def parse_excel(xlsx_bytes: bytes, codes: dict[str, str]) -> ParseResult:
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    ws = wb.active

    plans: list[Plan] = []
    unknown_codes: list[UnknownCode] = []

    current_label: str | None = None
    current_hotels: list[HotelRow] = []
    running_online = 0.0
    running_b2b = 0.0

    def _flush(summary_row) -> None:
        nonlocal current_label, current_hotels, running_online, running_b2b
        if current_label is None:
            return
        col_i = _numeric(summary_row[8].value) if len(summary_row) > 8 else None
        col_j = _numeric(summary_row[9].value) if len(summary_row) > 9 else None
        col_l = _numeric(summary_row[11].value) if len(summary_row) > 11 else None
        col_m = _numeric(summary_row[12].value) if len(summary_row) > 12 else None
        col_n = _numeric(summary_row[13].value) if len(summary_row) > 13 else None

        total_online = col_i if col_i is not None else running_online
        total_b2b = col_j if col_j is not None else running_b2b
        discount = col_l or 0.0
        discounted = col_m if col_m is not None else (total_online - discount)
        pct = col_n if col_n is not None else (discount / total_online * 100 if total_online else 0.0)

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
        ))
        current_label = None
        current_hotels = []
        running_online = 0.0
        running_b2b = 0.0

    past_first_plan = False

    for row in ws.iter_rows():
        cell_a = row[0]
        val_a = cell_a.value
        str_a = str(val_a).strip() if val_a is not None else ""

        if val_a and _PLAN_RE.match(str_a):
            past_first_plan = True
            current_label = str_a.title()  # "PLAN A" → "Plan A"
            current_hotels = []
            running_online = 0.0
            running_b2b = 0.0
            continue

        if not past_first_plan:
            continue

        col_i_val = row[8].value if len(row) > 8 else None
        col_l_val = row[11].value if len(row) > 11 else None

        # Plan summary: col A blank, col I or col L numeric
        if not val_a and (_numeric(col_i_val) is not None or _numeric(col_l_val) is not None):
            _flush(row)
            continue

        # Hotel row: col A non-empty, col I numeric, no strikethrough
        if val_a and _numeric(col_i_val) is not None:
            if cell_a.font and cell_a.font.strike:
                continue

            col_h_val = row[7].value if len(row) > 7 else None
            decoded = decode_col_h(str(col_h_val) if col_h_val is not None else None, codes)

            for unk in decoded.unknowns:
                unknown_codes.append(UnknownCode(
                    code=unk,
                    hotel_name=str_a,
                    plan_label=current_label or "",
                ))

            online = _numeric(col_i_val) or 0.0
            b2b = _numeric(row[9].value) if len(row) > 9 else None
            running_online += online
            running_b2b += (b2b or 0.0)

            current_hotels.append(HotelRow(
                name=str_a,
                category=str(row[1].value).strip() if row[1].value else "",
                room_type=str(row[2].value).strip() if row[2].value else "",
                cancellation=decoded.cancellation,
                meal_type=decoded.meal_type,
                online_price=online,
            ))

    return ParseResult(plans=plans, unknown_codes=unknown_codes, not_found=[])
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/hotel_options/test_parser.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/parser.py tests/hotel_options/test_parser.py
git commit -m "feat(hotel-options): Excel parser"
```

---

### Task 5: Google Places enricher

**Files:**
- Create: `src/hotel_options/enricher.py`
- Create: `tests/hotel_options/test_enricher.py`

**Interfaces:**
- Consumes: `HotelRow`, `EnrichedHotel` from models; AI client from `src.common.ai_provider`; `httpx`
- Produces:
  - `check_hotels_exist(hotel_names: list[str], destination: str, api_key: str) -> dict[str, str | None]`
  - `place_id_from_maps_url(url: str) -> str | None`
  - `enrich_hotel(hotel: HotelRow, place_id: str, destination: str, api_key: str, ai_client) -> EnrichedHotel`

**Before implementing:** Check `src/common/ai_provider.py` for the exact method to call on `AIClient` (look at how `verify_service.py` calls it) and use the same pattern.

- [ ] **Step 1: Write the failing test**

```python
# tests/hotel_options/test_enricher.py
from unittest.mock import patch, MagicMock
from src.hotel_options.enricher import place_id_from_maps_url, check_hotels_exist, enrich_hotel
from src.hotel_options.models import HotelRow


def test_place_id_from_maps_url_found():
    url = "https://maps.google.com/?cid=123&place_id=ChIJAbCdEfGh1234567890"
    assert place_id_from_maps_url(url) == "ChIJAbCdEfGh1234567890"


def test_place_id_from_maps_url_not_found():
    assert place_id_from_maps_url("https://maps.google.com/") is None


def _mock_text_search(results):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"results": results}
    return mock_resp


def test_check_hotels_exist_found():
    with patch("httpx.get", return_value=_mock_text_search([{"place_id": "ChIJ123"}])):
        result = check_hotels_exist(["Hilton London"], "London", "fake_key")
    assert result["Hilton London"] == "ChIJ123"


def test_check_hotels_exist_not_found():
    with patch("httpx.get", return_value=_mock_text_search([])):
        result = check_hotels_exist(["Unknown Hotel"], "London", "fake_key")
    assert result["Unknown Hotel"] is None


def test_enrich_hotel_builds_enriched():
    details_resp = MagicMock()
    details_resp.raise_for_status = MagicMock()
    details_resp.json.return_value = {
        "result": {
            "name": "Hilton London Kensington",
            "formatted_address": "179 Holland Park Ave",
            "international_phone_number": "+44 20 7602 3355",
            "rating": 4.2,
            "user_ratings_total": 1847,
            "photos": [{"photo_reference": "ref123"}],
        }
    }
    photo_resp = MagicMock()
    photo_resp.raise_for_status = MagicMock()
    photo_resp.content = b"JPEG_BYTES"

    ai_client = MagicMock()
    # complete() is the method used in this codebase — verify against ai_provider.py
    ai_client.complete.return_value = "A fine hotel."

    hotel = HotelRow(
        name="Hilton London",
        category="5-Star",
        room_type="King Room",
        cancellation="Non-refundable",
        meal_type="Breakfast included",
        online_price=50000.0,
    )

    with patch("httpx.get", side_effect=[details_resp, photo_resp]):
        result = enrich_hotel(hotel, "ChIJ123", "London", "fake_key", ai_client)

    assert result.official_name == "Hilton London Kensington"
    assert result.rating == 4.2
    assert result.photo_bytes == b"JPEG_BYTES"
    assert result.description == "A fine hotel."
    assert result.cancellation == "Non-refundable"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/hotel_options/test_enricher.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.hotel_options.enricher'`

- [ ] **Step 3: Implement enricher**

`src/hotel_options/enricher.py`:
```python
from __future__ import annotations
import re
import httpx

from src.hotel_options.models import HotelRow, EnrichedHotel

_PLACES_BASE = "https://maps.googleapis.com/maps/api/place"
_PLACE_ID_RE = re.compile(r'ChIJ[A-Za-z0-9_\-]+')

_DESCRIPTION_PROMPT = """\
Write 2-3 sentences about this hotel in warm travel-agency tone for a client document.
Hotel: {name}
Category: {category}
Address: {address}
Rating: {rating} ({rating_count} reviews)
Cancellation: {cancellation}
Meal: {meal_type}

Output only the description sentences, nothing else."""


def place_id_from_maps_url(url: str) -> str | None:
    m = _PLACE_ID_RE.search(url)
    return m.group(0) if m else None


def check_hotels_exist(
    hotel_names: list[str], destination: str, api_key: str
) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in hotel_names:
        resp = httpx.get(
            f"{_PLACES_BASE}/textsearch/json",
            params={"query": f"{name} {destination}", "key": api_key},
        )
        resp.raise_for_status()
        hits = resp.json().get("results", [])
        result[name] = hits[0]["place_id"] if hits else None
    return result


def enrich_hotel(
    hotel: HotelRow,
    place_id: str,
    destination: str,
    api_key: str,
    ai_client,
) -> EnrichedHotel:
    # Place Details
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

    official_name = detail.get("name", hotel.name)
    address = detail.get("formatted_address", "")
    phone = detail.get("international_phone_number", "")
    rating = float(detail.get("rating", 0))
    rating_count = int(detail.get("user_ratings_total", 0))
    maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

    # Photo
    photo_bytes: bytes | None = None
    photos = detail.get("photos", [])
    if photos:
        photo_ref = photos[0]["photo_reference"]
        photo_resp = httpx.get(
            "https://maps.googleapis.com/maps/api/place/photo",
            params={"maxwidth": 800, "photo_reference": photo_ref, "key": api_key},
            follow_redirects=True,
        )
        photo_resp.raise_for_status()
        photo_bytes = photo_resp.content

    # AI description
    prompt = _DESCRIPTION_PROMPT.format(
        name=official_name,
        category=hotel.category,
        address=address,
        rating=rating,
        rating_count=rating_count,
        cancellation=hotel.cancellation or "Not specified",
        meal_type=hotel.meal_type or "Not specified",
    )
    description = ai_client.complete(prompt)

    return EnrichedHotel(
        official_name=official_name,
        address=address,
        phone=phone,
        rating=rating,
        rating_count=rating_count,
        maps_url=maps_url,
        photo_bytes=photo_bytes,
        description=description,
        cancellation=hotel.cancellation,
        meal_type=hotel.meal_type,
        category=hotel.category,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/hotel_options/test_enricher.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/enricher.py tests/hotel_options/test_enricher.py
git commit -m "feat(hotel-options): Google Places enricher"
```

---

### Task 6: Document generator

**Files:**
- Create: `src/hotel_options/generator.py`
- Create: `tests/hotel_options/test_generator.py`

**Interfaces:**
- Consumes: `Plan`, `EnrichedHotel` from models; `python-docx`
- Produces:
  - `format_indian_number(amount: float) -> str` — `176622.0` → `"₹1,76,622"`
  - `build_document(plans, enriched_map, client_name, destination, letterhead_path) -> bytes`

**Document structure:**
1. Letterhead paragraphs copied from `letterhead_path` (skipped if file not found)
2. Thin horizontal rule
3. Title: `"Accommodation Options — {destination}"` bold 16pt
4. Sub-line: `"Prepared for: {client_name}"` 12pt (omitted if client_name is empty)
5. For each plan: page break → bold 16pt plan label → hotel cards (separated by thin rule) → pricing table

**Hotel card:** photo (5.5in centred) or `"[Photo not available]"`, hotel name hyperlinked to maps_url (bold 14pt), rating line (11pt), address+phone line (11pt), cancellation+meal line (11pt, omit empty segments), description (11pt).

**Pricing table:** borderless 2-col 3-row table. Row 0: "Best Online Price" / formatted total. Row 1 (bold): "Our Best Price" / formatted discounted price. Row 2: "Your Savings" / `"{amount} · {pct:.1f}% off"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/hotel_options/test_generator.py
import io
from docx import Document
from src.hotel_options.generator import format_indian_number, build_document
from src.hotel_options.models import Plan, PlanPricing, HotelRow, EnrichedHotel


def test_format_indian_number():
    assert format_indian_number(176622.0) == "₹1,76,622"
    assert format_indian_number(191022.0) == "₹1,91,022"
    assert format_indian_number(3000.0) == "₹3,000"
    assert format_indian_number(100.0) == "₹100"


def _make_plan() -> Plan:
    hotel = HotelRow(
        name="Test Hotel", category="4-Star", room_type="Double",
        cancellation="Non-refundable", meal_type="Breakfast included", online_price=50000.0,
    )
    pricing = PlanPricing(
        total_online_price=50000.0, total_b2b_price=45000.0,
        customer_discount=3000.0, discounted_price=47000.0, discount_pct=6.0,
    )
    return Plan(label="Plan A", hotels=[hotel], pricing=pricing)


def _make_enriched() -> EnrichedHotel:
    return EnrichedHotel(
        official_name="Test Hotel Official", address="123 Test St, London",
        phone="+44 20 1234 5678", rating=4.1, rating_count=500,
        maps_url="https://maps.google.com/?cid=1", photo_bytes=None,
        description="A great hotel.", cancellation="Non-refundable",
        meal_type="Breakfast included", category="4-Star",
    )


def test_build_document_returns_bytes():
    doc_bytes = build_document(
        plans=[_make_plan()],
        enriched_map={"Test Hotel": _make_enriched()},
        client_name="Alice",
        destination="London",
        letterhead_path="/nonexistent/letterhead.docx",
    )
    assert isinstance(doc_bytes, bytes)
    assert len(doc_bytes) > 0


def test_build_document_contains_plan_and_destination():
    doc_bytes = build_document(
        plans=[_make_plan()],
        enriched_map={"Test Hotel": _make_enriched()},
        client_name="Alice",
        destination="London",
        letterhead_path="/nonexistent/letterhead.docx",
    )
    doc = Document(io.BytesIO(doc_bytes))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Plan A" in full_text
    assert "London" in full_text
    assert "Alice" in full_text
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/hotel_options/test_generator.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.hotel_options.generator'`

- [ ] **Step 3: Implement generator**

`src/hotel_options/generator.py`:
```python
from __future__ import annotations
import io
from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from src.hotel_options.models import Plan, EnrichedHotel


def format_indian_number(amount: float) -> str:
    n = int(round(amount))
    s = str(n)
    if len(s) <= 3:
        return f"₹{s}"
    last3 = s[-3:]
    rest = s[:-3]
    groups: list[str] = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return f"₹{','.join(groups)},{last3}"


def _add_hyperlink(paragraph, text: str, url: str) -> None:
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    run_elem = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    style_elem = OxmlElement("w:rStyle")
    style_elem.set(qn("w:val"), "Hyperlink")
    rpr.append(style_elem)
    bold_elem = OxmlElement("w:b")
    rpr.append(bold_elem)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "28")  # 14pt = 28 half-points
    rpr.append(sz)
    run_elem.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    run_elem.append(t)
    hyperlink.append(run_elem)
    paragraph._p.append(hyperlink)


def _add_horizontal_rule(doc: Document) -> None:
    p = doc.add_paragraph()
    ppr = p._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "auto")
    pbdr.append(bottom)
    ppr.append(pbdr)


def _add_page_break(doc: Document) -> None:
    p = doc.add_paragraph()
    run = p.add_run()
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    run._r.append(br)


def _remove_table_borders(table) -> None:
    tbl = table._tbl
    tbl_pr = tbl.tblPr
    tbl_borders = OxmlElement("w:tblBorders")
    for name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = OxmlElement(f"w:{name}")
        border.set(qn("w:val"), "none")
        tbl_borders.append(border)
    tbl_pr.append(tbl_borders)


def _copy_letterhead(doc: Document, letterhead_path: str | Path) -> None:
    path = Path(letterhead_path)
    if not path.exists():
        return
    src = Document(str(path))
    for src_para in src.paragraphs:
        if not src_para.text.strip() and not src_para.runs:
            continue
        dst_para = doc.add_paragraph()
        dst_para.alignment = src_para.alignment
        for src_run in src_para.runs:
            dst_run = dst_para.add_run(src_run.text)
            dst_run.bold = src_run.bold
            dst_run.italic = src_run.italic
            if src_run.font.name:
                dst_run.font.name = src_run.font.name
            if src_run.font.size:
                dst_run.font.size = src_run.font.size


def _add_hotel_card(doc: Document, enriched: EnrichedHotel) -> None:
    if enriched.photo_bytes:
        img_para = doc.add_paragraph()
        img_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        img_para.add_run().add_picture(io.BytesIO(enriched.photo_bytes), width=Inches(5.5))
    else:
        p = doc.add_paragraph("[Photo not available]")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    name_para = doc.add_paragraph()
    _add_hyperlink(name_para, enriched.official_name, enriched.maps_url)

    rating_para = doc.add_paragraph(f"⭐ {enriched.rating} · {enriched.rating_count:,} reviews")
    if rating_para.runs:
        rating_para.runs[0].font.size = Pt(11)

    addr_parts = []
    if enriched.address:
        addr_parts.append(f"📍 {enriched.address}")
    if enriched.phone:
        addr_parts.append(f"📞 {enriched.phone}")
    if addr_parts:
        addr_para = doc.add_paragraph("  ·  ".join(addr_parts))
        if addr_para.runs:
            addr_para.runs[0].font.size = Pt(11)

    info_parts = []
    if enriched.cancellation:
        info_parts.append(f"🗓 {enriched.cancellation}")
    if enriched.meal_type:
        info_parts.append(f"🍳 {enriched.meal_type}")
    if info_parts:
        info_para = doc.add_paragraph("  ·  ".join(info_parts))
        if info_para.runs:
            info_para.runs[0].font.size = Pt(11)

    desc_para = doc.add_paragraph(enriched.description)
    if desc_para.runs:
        desc_para.runs[0].font.size = Pt(11)


def _add_pricing_table(doc: Document, plan: Plan) -> None:
    p = plan.pricing
    table = doc.add_table(rows=3, cols=2)
    _remove_table_borders(table)

    table.rows[0].cells[0].text = "Best Online Price"
    table.rows[0].cells[1].text = format_indian_number(p.total_online_price)

    table.rows[1].cells[0].text = "Our Best Price"
    table.rows[1].cells[1].text = format_indian_number(p.discounted_price)
    for cell in table.rows[1].cells:
        for para in cell.paragraphs:
            for run in para.runs:
                run.bold = True

    savings = f"{format_indian_number(p.customer_discount)} · {p.discount_pct:.1f}% off"
    table.rows[2].cells[0].text = "Your Savings"
    table.rows[2].cells[1].text = savings


def build_document(
    plans: list[Plan],
    enriched_map: dict[str, EnrichedHotel],
    client_name: str,
    destination: str,
    letterhead_path: str | Path,
) -> bytes:
    doc = Document()

    _copy_letterhead(doc, letterhead_path)
    _add_horizontal_rule(doc)

    title = doc.add_paragraph()
    title_run = title.add_run(f"Accommodation Options — {destination}")
    title_run.bold = True
    title_run.font.size = Pt(16)

    if client_name:
        sub = doc.add_paragraph(f"Prepared for: {client_name}")
        if sub.runs:
            sub.runs[0].font.size = Pt(12)

    for plan in plans:
        _add_page_break(doc)

        heading = doc.add_paragraph()
        h_run = heading.add_run(plan.label)
        h_run.bold = True
        h_run.font.size = Pt(16)

        for i, hotel in enumerate(plan.hotels):
            if i > 0:
                _add_horizontal_rule(doc)
            enriched = enriched_map.get(hotel.name)
            if enriched:
                _add_hotel_card(doc, enriched)
            else:
                doc.add_paragraph(f"[{hotel.name} — enrichment not available]")

        _add_pricing_table(doc, plan)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/hotel_options/test_generator.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/generator.py tests/hotel_options/test_generator.py
git commit -m "feat(hotel-options): document generator"
```

---

### Task 7: API endpoints and service

**Files:**
- Create: `src/library/ui/api/hotel_options.py`
- Create: `src/library/ui/services/hotel_options_service.py`
- Create: `tests/hotel_options/test_api.py`

**Interfaces:**
- Consumes: all `src/hotel_options/` functions; `request.app.state.storage_backend`; `GOOGLE_MAPS_API_KEY` and `LETTERHEAD_PATH` env vars
- Produces:
  - `POST /api/hotel-options/parse` → JSON: `{client_name, destination, plans, unknown_codes, not_found}`
  - `POST /api/hotel-options/generate` → `.docx` bytes as attachment
  - `POST /api/hotel-options/codes` → `{"ok": true}`

**`parse_file` flow:** load codes → parse_excel → extract_filename_meta → check_hotels_exist → build not_found list → return dict (omitting `total_b2b_price` and `online_price`).

**`generate_doc` flow:** merge+save resolved_codes → reload codes → parse_excel → extract_filename_meta → check_hotels_exist → resolve overrides via place_id_from_maps_url → enrich each hotel → build_document → return bytes.

- [ ] **Step 1: Write the failing test**

```python
# tests/hotel_options/test_api.py
import io
import json
from unittest.mock import patch, MagicMock
import openpyxl
import pytest
from fastapi.testclient import TestClient
from src.library.ui import create_app
from src.library.ui.storage import LocalStorageBackend

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def make_xlsx_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "PLAN A"
    ws["A2"] = "Hilton London"
    ws["B2"] = "5-Star"
    ws["C2"] = "King Room"
    ws["H2"] = "nr. br"
    ws["I2"] = 50000.0
    ws["J2"] = 45000.0
    ws["I3"] = 50000.0
    ws["J3"] = 45000.0
    ws["L3"] = 3000.0
    ws["M3"] = 47000.0
    ws["N3"] = 6.0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def client(tmp_path):
    storage = LocalStorageBackend(tmp_path)
    app = create_app(storage_backend=storage)
    return TestClient(app)


def test_parse_returns_plans(client):
    with patch("src.hotel_options.enricher.check_hotels_exist",
               return_value={"Hilton London": "ChIJ123"}):
        resp = client.post(
            "/api/hotel-options/parse",
            files={"file": ("Bushan_Accommodation Options_London.xlsx",
                            make_xlsx_bytes(), XLSX_MIME)},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["client_name"] == "Bushan"
    assert data["destination"] == "London"
    assert len(data["plans"]) == 1
    assert data["plans"][0]["label"] == "Plan A"
    assert data["not_found"] == []


def test_parse_flags_not_found(client):
    with patch("src.hotel_options.enricher.check_hotels_exist",
               return_value={"Hilton London": None}):
        resp = client.post(
            "/api/hotel-options/parse",
            files={"file": ("Bushan_Accommodation Options_London.xlsx",
                            make_xlsx_bytes(), XLSX_MIME)},
        )
    data = resp.json()
    assert len(data["not_found"]) == 1
    assert data["not_found"][0]["sheet_name"] == "Hilton London"


def test_save_code(client):
    resp = client.post("/api/hotel-options/codes", json={"code": "hb", "meaning": "Half board"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_generate_returns_docx(client):
    mock_enriched = MagicMock()
    mock_enriched.official_name = "Hilton London"
    mock_enriched.address = "London"
    mock_enriched.phone = ""
    mock_enriched.rating = 4.0
    mock_enriched.rating_count = 100
    mock_enriched.maps_url = "https://maps.google.com"
    mock_enriched.photo_bytes = None
    mock_enriched.description = "Nice hotel."
    mock_enriched.cancellation = "Non-refundable"
    mock_enriched.meal_type = "Breakfast included"
    mock_enriched.category = "5-Star"

    with (
        patch("src.hotel_options.enricher.check_hotels_exist",
              return_value={"Hilton London": "ChIJ123"}),
        patch("src.hotel_options.enricher.enrich_hotel", return_value=mock_enriched),
    ):
        resp = client.post(
            "/api/hotel-options/generate",
            data={"resolved_codes": "{}", "overrides": "{}"},
            files={"file": ("Bushan_Accommodation Options_London.xlsx",
                            make_xlsx_bytes(), XLSX_MIME)},
        )
    assert resp.status_code == 200
    assert "openxmlformats" in resp.headers.get("content-type", "")
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/hotel_options/test_api.py -v
```
Expected: 404 or ImportError — endpoints don't exist yet.

- [ ] **Step 3: Implement service**

`src/library/ui/services/hotel_options_service.py`:
```python
from __future__ import annotations
import os
from dataclasses import asdict
from pathlib import Path

from src.hotel_options.codes import CodeStore
from src.hotel_options.enricher import check_hotels_exist, enrich_hotel, place_id_from_maps_url
from src.hotel_options.generator import build_document
from src.hotel_options.models import Plan
from src.hotel_options.parser import parse_excel, extract_filename_meta
from src.common.ai_provider import get_ai_client
from src.library.ui.storage import StorageBackend

_LETTERHEAD = Path(os.getenv("LETTERHEAD_PATH", "input/BVBM Company Letterhead.docx"))


def _plan_to_dict(plan: Plan) -> dict:
    return {
        "label": plan.label,
        "hotels": [
            {
                "name": h.name,
                "category": h.category,
                "room_type": h.room_type,
                "cancellation": h.cancellation,
                "meal_type": h.meal_type,
            }
            for h in plan.hotels
        ],
        "pricing": {
            "total_online_price": plan.pricing.total_online_price,
            "customer_discount": plan.pricing.customer_discount,
            "discounted_price": plan.pricing.discounted_price,
            "discount_pct": plan.pricing.discount_pct,
        },
    }


def parse_file(
    xlsx_bytes: bytes,
    filename: str,
    storage: StorageBackend,
    api_key: str,
) -> dict:
    codes = CodeStore(storage).load()
    result = parse_excel(xlsx_bytes, codes)
    client_name, destination = extract_filename_meta(filename)

    unique_names = list({h.name for plan in result.plans for h in plan.hotels})
    existence_map = check_hotels_exist(unique_names, destination, api_key)

    not_found = []
    for name, place_id in existence_map.items():
        if place_id is None:
            plan_label = next(
                (p.label for p in result.plans if any(h.name == name for h in p.hotels)),
                "",
            )
            not_found.append({"sheet_name": name, "plan_label": plan_label})

    return {
        "client_name": client_name,
        "destination": destination,
        "plans": [_plan_to_dict(p) for p in result.plans],
        "unknown_codes": [asdict(u) for u in result.unknown_codes],
        "not_found": not_found,
    }


def generate_doc(
    xlsx_bytes: bytes,
    filename: str,
    resolved_codes: dict[str, str],
    overrides: dict[str, str],
    storage: StorageBackend,
    api_key: str,
) -> bytes:
    store = CodeStore(storage)
    if resolved_codes:
        existing = store.load()
        existing.update(resolved_codes)
        store.save(existing)

    codes = store.load()
    result = parse_excel(xlsx_bytes, codes)
    client_name, destination = extract_filename_meta(filename)

    unique_names = list({h.name for plan in result.plans for h in plan.hotels})
    existence_map = check_hotels_exist(unique_names, destination, api_key)

    for name in list(existence_map):
        if existence_map[name] is None and name in overrides:
            existence_map[name] = place_id_from_maps_url(overrides[name])

    ai_client = get_ai_client()
    enriched_map = {}
    for plan in result.plans:
        for hotel in plan.hotels:
            if hotel.name in enriched_map:
                continue
            place_id = existence_map.get(hotel.name)
            if place_id:
                enriched_map[hotel.name] = enrich_hotel(
                    hotel, place_id, destination, api_key, ai_client
                )

    return build_document(result.plans, enriched_map, client_name, destination, _LETTERHEAD)
```

- [ ] **Step 4: Implement API router**

`src/library/ui/api/hotel_options.py`:
```python
from __future__ import annotations
import json
import os

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from src.library.ui.services.hotel_options_service import parse_file, generate_doc

router = APIRouter()

_XLSX_MAGIC = b"PK"


def _api_key() -> str:
    key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not key:
        raise HTTPException(status_code=500, detail="GOOGLE_MAPS_API_KEY not configured")
    return key


@router.post("/hotel-options/parse")
async def parse_hotel_options(request: Request, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are accepted")
    content = await file.read()
    if len(content) < 2 or content[:2] != _XLSX_MAGIC:
        raise HTTPException(status_code=400, detail="File does not appear to be a valid Excel file")
    try:
        return parse_file(content, file.filename, request.app.state.storage_backend, _api_key())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse failed: {e}")


@router.post("/hotel-options/generate")
async def generate_hotel_options(
    request: Request,
    file: UploadFile = File(...),
    resolved_codes: str = Form(default="{}"),
    overrides: str = Form(default="{}"),
):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are accepted")
    content = await file.read()
    try:
        codes_dict = json.loads(resolved_codes)
        overrides_dict = json.loads(overrides)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in form fields: {e}")
    try:
        docx_bytes = generate_doc(
            content, file.filename, codes_dict, overrides_dict,
            request.app.state.storage_backend, _api_key(),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=hotel_options.docx"},
    )


@router.post("/hotel-options/codes")
async def save_hotel_code(request: Request, payload: dict):
    code = str(payload.get("code", "")).strip()
    meaning = str(payload.get("meaning", "")).strip()
    if not code or not meaning:
        raise HTTPException(status_code=400, detail="code and meaning are required")
    from src.hotel_options.codes import CodeStore
    store = CodeStore(request.app.state.storage_backend)
    codes = store.load()
    codes[code.lower()] = meaning
    store.save(codes)
    return {"ok": True}
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/hotel_options/test_api.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/library/ui/api/hotel_options.py src/library/ui/services/hotel_options_service.py tests/hotel_options/test_api.py
git commit -m "feat(hotel-options): API endpoints and service"
```

---

### Task 8: Register router and update requirements

**Files:**
- Modify: `src/library/ui/__init__.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add openpyxl to requirements.txt**

In `requirements.txt`, after the `# Document Generation` block, add:
```
openpyxl>=3.1.0
```

- [ ] **Step 2: Register the router in `src/library/ui/__init__.py`**

Change:
```python
from .api import tree, city, country, review, sweep, audit, ingest, verify
```
To:
```python
from .api import tree, city, country, review, sweep, audit, ingest, verify, hotel_options
```

After:
```python
    app.include_router(verify.router, prefix="/api")  # all authenticated users
```
Add:
```python
    app.include_router(hotel_options.router, prefix="/api")  # all authenticated users
```

- [ ] **Step 3: Run the full hotel_options test suite**

```
pytest tests/hotel_options/ -v
```
Expected: all tests pass.

- [ ] **Step 4: Verify route is registered**

```bash
python -c "from src.library.ui import create_app; app = create_app(); routes = [r.path for r in app.routes]; assert any('hotel-options' in r for r in routes), routes"
```
Expected: no assertion error.

- [ ] **Step 5: Commit**

```bash
git add src/library/ui/__init__.py requirements.txt
git commit -m "feat(hotel-options): register router, add openpyxl dependency"
```

---

### Task 9: Frontend types and API client

**Files:**
- Modify: `ui-frontend/src/types.ts`
- Modify: `ui-frontend/src/api/client.ts`

- [ ] **Step 1: Append hotel options types to `ui-frontend/src/types.ts`**

```typescript
// --- Hotel Options types ---

export interface HotelOptionsHotel {
  name: string;
  category: string;
  room_type: string;
  cancellation: string;
  meal_type: string;
}

export interface HotelOptionsPricing {
  total_online_price: number;
  customer_discount: number;
  discounted_price: number;
  discount_pct: number;
}

export interface HotelOptionsPlan {
  label: string;
  hotels: HotelOptionsHotel[];
  pricing: HotelOptionsPricing;
}

export interface HotelOptionsUnknownCode {
  code: string;
  hotel_name: string;
  plan_label: string;
}

export interface HotelOptionsNotFound {
  sheet_name: string;
  plan_label: string;
}

export interface HotelOptionsParseResult {
  client_name: string;
  destination: string;
  plans: HotelOptionsPlan[];
  unknown_codes: HotelOptionsUnknownCode[];
  not_found: HotelOptionsNotFound[];
}
```

- [ ] **Step 2: Add API methods to `ui-frontend/src/api/client.ts`**

Inside the `api` object, before the closing `};`, add:

```typescript
  parseHotelOptions: async (file: File): Promise<import("../types").HotelOptionsParseResult> => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${BASE}/hotel-options/parse`, { method: "POST", body: formData });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Parse failed: ${res.status} ${text}`);
    }
    return res.json();
  },

  generateHotelOptions: async (
    file: File,
    resolvedCodes: Record<string, string>,
    overrides: Record<string, string>
  ): Promise<Blob> => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("resolved_codes", JSON.stringify(resolvedCodes));
    formData.append("overrides", JSON.stringify(overrides));
    const res = await fetch(`${BASE}/hotel-options/generate`, { method: "POST", body: formData });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Generation failed: ${res.status} ${text}`);
    }
    return res.blob();
  },

  saveHotelCode: (code: string, meaning: string): Promise<{ ok: boolean }> =>
    request("/hotel-options/codes", {
      method: "POST",
      body: JSON.stringify({ code, meaning }),
    }),
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd ui-frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add ui-frontend/src/types.ts ui-frontend/src/api/client.ts
git commit -m "feat(hotel-options): frontend types and API client methods"
```

---

### Task 10: HotelOptionsTab component

**Files:**
- Create: `ui-frontend/src/components/HotelOptionsTab.tsx`

**States:** `upload` → (after parse) `preview` → (on generate) `generating` → `done` | `error`

- [ ] **Step 1: Create the component**

`ui-frontend/src/components/HotelOptionsTab.tsx`:
```tsx
import { useRef, useState } from "react";
import { api } from "../api/client";
import type {
  HotelOptionsParseResult,
  HotelOptionsUnknownCode,
  HotelOptionsNotFound,
} from "../types";

type TabState = "upload" | "preview" | "generating" | "done" | "error";

export function HotelOptionsTab() {
  const [state, setState] = useState<TabState>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [parseResult, setParseResult] = useState<HotelOptionsParseResult | null>(null);
  const [resolvedCodes, setResolvedCodes] = useState<Record<string, string>>({});
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [docBlob, setDocBlob] = useState<Blob | null>(null);
  const [error, setError] = useState<string>("");
  const [parsing, setParsing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const allResolved =
    parseResult !== null &&
    parseResult.unknown_codes.every((u) => resolvedCodes[u.code]?.trim()) &&
    parseResult.not_found.every((nf) => overrides[nf.sheet_name]?.trim());

  function reset() {
    setState("upload");
    setFile(null);
    setParseResult(null);
    setResolvedCodes({});
    setOverrides({});
    setDocBlob(null);
    setError("");
  }

  async function handleParse(f: File) {
    setParsing(true);
    setError("");
    try {
      const result = await api.parseHotelOptions(f);
      setParseResult(result);
      setState("preview");
    } catch (e: any) {
      setError(e.message || "Parse failed");
      setState("error");
    } finally {
      setParsing(false);
    }
  }

  async function handleGenerate() {
    if (!file || !parseResult) return;
    setState("generating");
    try {
      const blob = await api.generateHotelOptions(file, resolvedCodes, overrides);
      setDocBlob(blob);
      setState("done");
    } catch (e: any) {
      setError(e.message || "Generation failed");
      setState("error");
    }
  }

  function handleCodeBlur(code: string, meaning: string) {
    if (!meaning.trim()) return;
    api.saveHotelCode(code, meaning).catch(() => {});
  }

  function downloadDoc() {
    if (!docBlob || !parseResult) return;
    const url = URL.createObjectURL(docBlob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Hotel Options - ${parseResult.destination || "document"}.docx`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (state === "upload" || (state === "error" && !parseResult)) {
    return (
      <div className="max-w-xl mx-auto py-16 space-y-4">
        <h2 className="text-lg font-semibold text-slate-800">Hotel Options Generator</h2>
        <div
          className="border-2 border-dashed border-slate-300 rounded-xl p-12 text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition-colors"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files[0];
            if (f) { setFile(f); handleParse(f); }
          }}
        >
          <p className="text-slate-500 text-sm">
            {parsing
              ? "Parsing…"
              : "Drop your hotel comparison .xlsx here, or click to browse"}
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) { setFile(f); handleParse(f); }
            }}
          />
        </div>
        {error && <p className="text-red-600 text-sm">{error}</p>}
      </div>
    );
  }

  if (state === "generating") {
    return (
      <div className="max-w-xl mx-auto py-16 text-center">
        <p className="text-slate-500 text-sm animate-pulse">
          Enriching hotels and building document…
        </p>
      </div>
    );
  }

  if (state === "done") {
    return (
      <div className="max-w-xl mx-auto py-16 text-center space-y-4">
        <p className="text-green-600 font-medium">Document ready!</p>
        <button
          onClick={downloadDoc}
          className="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm font-medium"
        >
          Download .docx
        </button>
        <div>
          <button onClick={reset} className="text-sm text-slate-500 hover:text-slate-700 underline">
            Start over
          </button>
        </div>
      </div>
    );
  }

  if (state === "error" && parseResult) {
    return (
      <div className="max-w-xl mx-auto py-16 space-y-4">
        <p className="text-red-600 text-sm">{error}</p>
        <button
          onClick={() => setState("preview")}
          className="px-4 py-2 bg-slate-100 rounded text-sm hover:bg-slate-200"
        >
          Try again
        </button>
        <button onClick={reset} className="ml-4 text-sm text-slate-500 underline">
          Start over
        </button>
      </div>
    );
  }

  // Preview state
  const result = parseResult!;
  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-800">
          {result.client_name ? `${result.client_name} — ` : ""}
          {result.destination}
        </h2>
        <button onClick={reset} className="text-sm text-blue-500 hover:text-blue-700 underline">
          Upload a different file
        </button>
      </div>

      {result.plans.map((plan) => (
        <div key={plan.label} className="bg-white border border-slate-200 rounded-xl p-4">
          <h3 className="font-semibold text-slate-700 mb-2">{plan.label}</h3>
          <ul className="text-sm text-slate-600 space-y-0.5 mb-3">
            {plan.hotels.map((h) => (
              <li key={h.name}>{h.name} — {h.category}</li>
            ))}
          </ul>
          <p className="text-xs text-slate-500">
            Online: ₹{plan.pricing.total_online_price.toLocaleString("en-IN")} ·{" "}
            Our price: ₹{plan.pricing.discounted_price.toLocaleString("en-IN")}
          </p>
        </div>
      ))}

      {result.unknown_codes.length > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-4 space-y-3">
          <p className="text-sm font-medium text-yellow-800">
            Unknown codes — please define them:
          </p>
          {result.unknown_codes.map((u: HotelOptionsUnknownCode) => (
            <div key={`${u.plan_label}-${u.code}`} className="flex items-center gap-3">
              <span className="text-sm text-slate-700 w-32 shrink-0">
                <code className="bg-yellow-100 px-1 rounded">{u.code}</code>
                <span className="text-xs text-slate-400 ml-1">({u.plan_label})</span>
              </span>
              <input
                type="text"
                placeholder={`What does "${u.code}" mean?`}
                className="flex-1 text-sm border border-slate-300 rounded px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
                value={resolvedCodes[u.code] || ""}
                onChange={(e) =>
                  setResolvedCodes((prev) => ({ ...prev, [u.code]: e.target.value }))
                }
                onBlur={(e) => handleCodeBlur(u.code, e.target.value)}
              />
            </div>
          ))}
        </div>
      )}

      {result.not_found.length > 0 && (
        <div className="bg-orange-50 border border-orange-200 rounded-xl p-4 space-y-3">
          <p className="text-sm font-medium text-orange-800">
            Hotels not found on Google — paste their Maps links:
          </p>
          {result.not_found.map((nf: HotelOptionsNotFound) => (
            <div key={`${nf.plan_label}-${nf.sheet_name}`} className="flex items-center gap-3">
              <span
                className="text-sm text-slate-700 w-48 shrink-0 truncate"
                title={nf.sheet_name}
              >
                {nf.sheet_name}
              </span>
              <input
                type="text"
                placeholder="Paste Google Maps link…"
                className="flex-1 text-sm border border-slate-300 rounded px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
                value={overrides[nf.sheet_name] || ""}
                onChange={(e) =>
                  setOverrides((prev) => ({ ...prev, [nf.sheet_name]: e.target.value }))
                }
              />
            </div>
          ))}
        </div>
      )}

      <button
        onClick={handleGenerate}
        disabled={!allResolved}
        className={`w-full py-3 rounded-xl font-medium text-sm transition-colors ${
          allResolved
            ? "bg-blue-600 text-white hover:bg-blue-700"
            : "bg-slate-200 text-slate-400 cursor-not-allowed"
        }`}
      >
        Generate Document
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd ui-frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add ui-frontend/src/components/HotelOptionsTab.tsx
git commit -m "feat(hotel-options): HotelOptionsTab component"
```

---

### Task 11: Wire into App.tsx and Layout.tsx

**Files:**
- Modify: `ui-frontend/src/App.tsx`
- Modify: `ui-frontend/src/components/Layout.tsx`

- [ ] **Step 1: Update `Layout.tsx`**

Change the `Mode` type:
```typescript
type Mode = "city" | "sweep" | "ingest" | "history" | "audit" | "verify" | "hotel_options";
```

Change `NO_SIDEBAR_MODES`:
```typescript
const NO_SIDEBAR_MODES: Mode[] = ["ingest", "history", "audit", "verify", "hotel_options"];
```

After `<Tab label="Verify AIG" active={mode === "verify"} onClick={() => onModeChange("verify")} />`, add:
```tsx
<Tab label="Hotel Options" active={mode === "hotel_options"} onClick={() => onModeChange("hotel_options")} />
```

- [ ] **Step 2: Update `App.tsx`**

Change the `Mode` type:
```typescript
type Mode = "city" | "sweep" | "ingest" | "history" | "audit" | "verify" | "hotel_options";
```

Add import:
```typescript
import { HotelOptionsTab } from "./components/HotelOptionsTab";
```

After `{mode === "verify" && <VerifyTab />}`, add:
```tsx
{mode === "hotel_options" && <HotelOptionsTab />}
```

- [ ] **Step 3: Build the frontend**

```bash
cd ui-frontend && npm run build
```
Expected: build succeeds with no TypeScript errors.

- [ ] **Step 4: Manual smoke test**

Start the backend:
```bash
python -m src.library serve --db library_db
```
Open `http://localhost:8765`. Confirm:
- "Hotel Options" tab appears in the header after "Verify AIG"
- Clicking it shows the upload dropzone with no sidebar
- Dropping a non-xlsx file shows an error (handled by the backend 400 response)

- [ ] **Step 5: Commit**

```bash
git add ui-frontend/src/App.tsx ui-frontend/src/components/Layout.tsx
git commit -m "feat(hotel-options): wire tab into App and Layout"
```

---

## Self-Review

**Spec coverage:**
- ✅ Excel parsing: Plans, hotel rows, strikethrough skip, column H decode, summary rows, filename meta
- ✅ Code store: seeds + user-defined codes persisted to `hotel_options/hotel_codes.json`
- ✅ `/parse`: Text Search existence check; `not_found` and `unknown_codes` in response
- ✅ `/generate`: Place Details + photo + AI description per hotel; resolved_codes saved before generate
- ✅ Override flow: Maps URL → place_id extraction via regex
- ✅ Document: letterhead copy (skipped if missing), title, per-plan sections, hotel cards, pricing table
- ✅ Indian number format implemented and tested
- ✅ Pricing table rows: Best Online Price / Our Best Price (bold) / Your Savings
- ✅ Hotel card: photo or placeholder, hyperlinked name, rating, address+phone, cancellation+meal, description
- ✅ `total_b2b_price` never serialised in API responses
- ✅ No admin gate
- ✅ Frontend: upload → preview → generating → done/error flow
- ✅ Generate button disabled until all codes and overrides resolved
- ✅ Code saved on blur via `/api/hotel-options/codes`
- ✅ `openpyxl` added to requirements.txt
- ✅ `hotel_options` mode in `NO_SIDEBAR_MODES`

**One implementation note for Task 5:** `ai_client.complete(prompt)` assumes that method name. Before coding Task 5, read `src/common/ai_provider.py` to find the correct method — look at how `verify_service.py` calls `AIClient` and use the same pattern.
