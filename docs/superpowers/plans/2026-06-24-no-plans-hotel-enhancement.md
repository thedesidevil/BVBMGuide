# No-Plans Hotel Enhancement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the Excel workbook has no `PLAN X` markers, group hotels by the section header rows (e.g., "Wimbledon (Jun 28– Jul 4)") instead of skipping them. Each section becomes a Plan whose label is AI-cleaned to a presentable location name. If no section headers exist either, all hotels land in one "All Hotels" plan.

**Context:**
- `src/hotel_options/parser.py` — contains `parse_excel()`. Currently sets `past_first_plan = False`; all rows before the first PLAN header are collected only for preamble dates, and if there are NO plan headers the result is empty plans.
- `src/hotel_options/models.py` — `ParseResult` dataclass
- `src/library/ui/services/hotel_options_service.py` — `parse_file()` and `generate_doc()` call `parse_excel()`; already has `get_ai_client()` available in `generate_doc()`

## Global Constraints

- TDD required: write the failing test first, then implement
- `ParseResult` gets a new field `grouped_by_sections: bool = False` — True when plans were derived from section headers rather than PLAN markers
- AI normalization uses `get_ai_client()` from `src.common.ai_provider`; must fall back to regex if AI call fails
- Section header regex fallback: strip `\s*\([^)]+\)` (parenthesised date ranges) and `.strip()` the result
- Flat-list fallback (no sections either): one plan with label `"All Hotels"`
- Pricing rollup in no-plans mode: sum `online_price` per hotel → `total_online_price`; `total_b2b_price` = 0; `customer_discount` = 0; `discounted_price = total_online_price`; `discount_pct = 0`
- Normalise labels in **both** `parse_file()` and `generate_doc()` so the UI preview and the generated document show clean labels
- `plan.label` is mutated in-place after normalization (Plan is a dataclass, not frozen)
- Do not alter any existing logic for workbooks that DO have PLAN markers

---

### Task 1: ParseResult model + no-plans parser path

**Files to modify:**
- `src/hotel_options/models.py`
- `src/hotel_options/parser.py`
- `tests/hotel_options/test_parser.py`

**Step 1: Write failing tests**

Add to `tests/hotel_options/test_parser.py`:

```python
# Helper to build a minimal in-memory workbook for testing
def _make_wb_no_plans_with_sections():
    """Two section headers, two hotels each, no PLAN markers."""
    wb = openpyxl.Workbook()
    ws = wb.active
    # Row 1: requirements in A1
    ws.cell(1, 1).value = "Breakfast Included"
    # Row 2: section header  (col A text, col I blank)
    ws.cell(2, 1).value = "London (Jul 1 - Jul 5)"
    # Row 3 & 4: hotel rows under London
    ws.cell(3, 1).value = "Hotel Alpha"
    ws.cell(3, 2).value = "4-Star"
    ws.cell(3, 3).value = "Deluxe"
    ws.cell(3, 8).value = "nr"
    ws.cell(3, 9).value = 50000.0
    ws.cell(3, 10).value = 45000.0
    ws.cell(4, 1).value = "Hotel Beta"
    ws.cell(4, 2).value = "3-Star"
    ws.cell(4, 3).value = "Standard"
    ws.cell(4, 8).value = "br"
    ws.cell(4, 9).value = 40000.0
    ws.cell(4, 10).value = 36000.0
    # Row 5: section header
    ws.cell(5, 1).value = "Paris (Jul 6 - Jul 10)"
    # Row 6: hotel row under Paris
    ws.cell(6, 1).value = "Hotel Gamma"
    ws.cell(6, 2).value = "5-Star"
    ws.cell(6, 3).value = "Suite"
    ws.cell(6, 8).value = "nr"
    ws.cell(6, 9).value = 80000.0
    ws.cell(6, 10).value = 72000.0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_wb_no_plans_flat():
    """Hotels with no section headers and no PLAN markers — one group."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(1, 1).value = "Any requirement"
    for i, name in enumerate(["Hotel X", "Hotel Y", "Hotel Z"], start=2):
        ws.cell(i, 1).value = name
        ws.cell(i, 2).value = "4-Star"
        ws.cell(i, 3).value = "Double"
        ws.cell(i, 8).value = "nr"
        ws.cell(i, 9).value = 30000.0
        ws.cell(i, 10).value = 27000.0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_no_plans_with_sections_groups_by_section():
    result = parse_excel(_make_wb_no_plans_with_sections(), codes={})
    assert result.grouped_by_sections is True
    assert len(result.plans) == 2
    london = result.plans[0]
    paris = result.plans[1]
    assert london.label == "London (Jul 1 - Jul 5)"  # raw label before normalization
    assert paris.label == "Paris (Jul 6 - Jul 10)"
    assert len(london.hotels) == 2
    assert len(paris.hotels) == 1
    assert london.pricing.total_online_price == 90000.0
    assert paris.pricing.total_online_price == 80000.0
    assert london.pricing.customer_discount == 0.0
    assert london.pricing.discounted_price == 90000.0
    assert london.pricing.discount_pct == 0.0


def test_no_plans_flat_all_hotels_in_one_plan():
    result = parse_excel(_make_wb_no_plans_flat(), codes={})
    assert result.grouped_by_sections is True
    assert len(result.plans) == 1
    assert result.plans[0].label == "All Hotels"
    assert len(result.plans[0].hotels) == 3


def test_plans_present_grouped_by_sections_false():
    """Existing PLAN-marker workbooks should have grouped_by_sections=False."""
    # This test relies on the existing _make_minimal_workbook helper already
    # present in test_parser.py — just assert the new field is False.
    # (Add assertion to an existing test that uses a PLAN-marker workbook.)
    pass  # placeholder — add assertion in existing test
```

**Step 2: Add `grouped_by_sections` to `ParseResult`**

In `src/hotel_options/models.py`, add the field:
```python
@dataclass
class ParseResult:
    plans: list[Plan]
    unknown_codes: list[UnknownCode]
    not_found: list[dict]
    requirements: str = ""
    grouped_by_sections: bool = False
```

**Step 3: Add `_parse_no_plans()` helper in `parser.py`**

Add at module level (before `parse_excel`):

```python
def _parse_no_plans(ws, codes: dict) -> tuple[list[Plan], list[UnknownCode]]:
    """Group hotels by section headers when no PLAN markers found.
    Returns (plans, unknown_codes). If no section headers, one "All Hotels" plan."""
    all_plans: list[Plan] = []
    unknown_codes: list[UnknownCode] = []
    current_label: str | None = None
    current_hotels: list[HotelRow] = []
    running_online = 0.0
    running_b2b = 0.0

    def _flush():
        nonlocal current_label, current_hotels, running_online, running_b2b
        if not current_hotels:
            current_label = None
            current_hotels = []
            running_online = 0.0
            running_b2b = 0.0
            return
        pricing = PlanPricing(
            total_online_price=running_online,
            total_b2b_price=running_b2b,
            customer_discount=0.0,
            discounted_price=running_online,
            discount_pct=0.0,
        )
        all_plans.append(Plan(
            label=current_label if current_label is not None else "All Hotels",
            hotels=list(current_hotels),
            pricing=pricing,
        ))
        current_label = None
        current_hotels = []
        running_online = 0.0
        running_b2b = 0.0

    for row in ws.iter_rows():
        cell_a = row[0]
        row_dim = ws.row_dimensions.get(cell_a.row)
        if (cell_a.font and cell_a.font.strike) or (row_dim and row_dim.font and row_dim.font.strike):
            continue

        val_a = cell_a.value
        str_a = str(val_a).strip() if val_a is not None else ""
        col_i_val = row[8].value if len(row) > 8 else None

        # Section header: col A non-empty, col I blank, not a PLAN header, not A1
        if val_a and _numeric(col_i_val) is None and not _PLAN_RE.match(str_a) and cell_a.row > 1:
            _flush()
            current_label = str_a
            continue

        # Hotel row: col A non-empty, col I numeric
        if val_a and _numeric(col_i_val) is not None:
            col_h_val = row[7].value if len(row) > 7 else None
            decoded = decode_col_h(str(col_h_val) if col_h_val is not None else None, codes)
            for unk in decoded.unknowns:
                unknown_codes.append(UnknownCode(code=unk, hotel_name=str_a, plan_label=current_label or ""))
            online = _numeric(col_i_val) or 0.0
            b2b = (_numeric(row[9].value) if len(row) > 9 else None) or 0.0
            running_online += online
            running_b2b += b2b
            current_hotels.append(HotelRow(
                name=str_a,
                category=str(row[1].value).strip() if row[1].value else "",
                room_type=str(row[2].value).strip() if row[2].value else "",
                cancellation=decoded.cancellation,
                meal_type=decoded.meal_type,
                online_price=online,
                dates="",
            ))

    _flush()
    return all_plans, unknown_codes
```

**Step 4: Call `_parse_no_plans` at end of `parse_excel`**

In `parse_excel()`, replace the final return with:
```python
    # Flush the last open plan — it may have no trailing summary row
    _flush(_make_dummy_row())
    plans = [p for p in plans if p.hotels]

    grouped_by_sections = False
    if not plans:
        plans, extra_codes = _parse_no_plans(ws, codes)
        unknown_codes.extend(extra_codes)
        grouped_by_sections = bool(plans)

    return ParseResult(
        plans=plans,
        unknown_codes=unknown_codes,
        not_found=[],
        requirements=requirements,
        grouped_by_sections=grouped_by_sections,
    )
```

- [ ] **Step 1: Write the failing tests** (test_no_plans_with_sections_groups_by_section, test_no_plans_flat_all_hotels_in_one_plan, and add `grouped_by_sections is False` assertion to one existing test)
- [ ] **Step 2: Add `grouped_by_sections` field to `ParseResult`**
- [ ] **Step 3: Implement `_parse_no_plans()` in `parser.py`**
- [ ] **Step 4: Call `_parse_no_plans` in `parse_excel` when plans is empty**
- [ ] **Step 5: Run `python -m pytest tests/hotel_options/test_parser.py -v`** — all tests pass
- [ ] **Step 6: Commit** with message `feat(hotel-options): no-plans parser path groups by section headers`

---

### Task 2: Service — AI section label normalization

**Files to modify:**
- `src/library/ui/services/hotel_options_service.py`
- `tests/hotel_options/test_api.py` (or add `tests/hotel_options/test_service.py`)

**Step 1: Write failing tests**

```python
# tests/hotel_options/test_service.py  (create if not exists)
import pytest
from unittest.mock import MagicMock, patch
from src.library.ui.services.hotel_options_service import _normalize_section_labels


def test_normalize_section_labels_happy_path():
    """AI returns clean labels — use them."""
    mock_client = MagicMock()
    mock_client.complete.return_value = '["London", "Paris"]'
    result = _normalize_section_labels(["London (Jul 1 - Jul 5)", "Paris (Jul 6 - Jul 10)"], mock_client)
    assert result == ["London", "Paris"]


def test_normalize_section_labels_fallback_on_ai_failure():
    """AI throws — fall back to regex stripping date parenthetical."""
    mock_client = MagicMock()
    mock_client.complete.side_effect = RuntimeError("API error")
    result = _normalize_section_labels(["London (Jul 1 - Jul 5)", "Paris (Jul 6 - Jul 10)"], mock_client)
    assert result == ["London", "Paris"]


def test_normalize_section_labels_empty():
    mock_client = MagicMock()
    result = _normalize_section_labels([], mock_client)
    assert result == []


def test_normalize_section_labels_ai_wrong_length_falls_back():
    """AI returns wrong-length list — fall back to regex."""
    mock_client = MagicMock()
    mock_client.complete.return_value = '["Only One"]'
    result = _normalize_section_labels(["London (Jul 1)", "Paris (Jul 6)"], mock_client)
    assert result == ["London", "Paris"]
```

**Step 2: Add `_normalize_section_labels()` to service**

```python
import json as _json
import re as _re

_NORMALIZE_LABELS_PROMPT = """\
Below is a JSON array of raw section header strings from a hotel comparison spreadsheet.
Each string may contain a location name mixed with date ranges or other details.
Clean each one to just the location/area name: remove date ranges, parentheses, dashes, and extra whitespace.
Return ONLY a JSON array of strings in the same order, no other text.

Input: {labels}
"""

def _normalize_section_labels(raw_labels: list[str], ai_client) -> list[str]:
    """AI-clean raw section headers; fall back to regex on failure."""
    if not raw_labels:
        return []
    def _regex_fallback():
        return [_re.sub(r'\s*\([^)]+\)', '', label).strip() for label in raw_labels]
    try:
        prompt = _NORMALIZE_LABELS_PROMPT.format(labels=_json.dumps(raw_labels))
        resp = ai_client.complete(prompt).strip()
        start, end = resp.find('['), resp.rfind(']') + 1
        if start >= 0 and end > start:
            cleaned = _json.loads(resp[start:end])
            if isinstance(cleaned, list) and len(cleaned) == len(raw_labels):
                return [str(s).strip() for s in cleaned]
    except Exception:
        pass
    return _regex_fallback()
```

**Step 3: Apply normalization in `parse_file()` and `generate_doc()`**

In `parse_file()`, after `result = parse_excel(xlsx_bytes, codes)`:
```python
    if result.grouped_by_sections:
        norm_client = get_ai_client()
        cleaned = _normalize_section_labels([p.label for p in result.plans], norm_client)
        for plan, label in zip(result.plans, cleaned):
            plan.label = label
```

In `generate_doc()`, after `result = parse_excel(xlsx_bytes, codes)`:
```python
    if result.grouped_by_sections:
        cleaned = _normalize_section_labels([p.label for p in result.plans], ai_client)
        for plan, label in zip(result.plans, cleaned):
            plan.label = label
```
(In `generate_doc`, `ai_client` is already initialised later in the function — move `ai_client = get_ai_client()` to just after `result = parse_excel(...)` so it's available for normalization. The rest of the function uses it unchanged.)

- [ ] **Step 1: Write failing tests** in `tests/hotel_options/test_service.py`
- [ ] **Step 2: Add `_normalize_section_labels()` to `hotel_options_service.py`**
- [ ] **Step 3: Apply normalization in `parse_file()` and `generate_doc()`** — move `ai_client = get_ai_client()` to top of `generate_doc` body
- [ ] **Step 4: Run `python -m pytest tests/hotel_options/test_service.py -v`** — all tests pass
- [ ] **Step 5: Run full suite `python -m pytest tests/ -q`** to confirm no regressions
- [ ] **Step 6: Commit** with message `feat(hotel-options): AI-normalize section labels when no PLAN markers`
