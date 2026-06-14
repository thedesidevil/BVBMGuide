# AIG Generation Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full AIG generation pipeline that takes `trip_facts.json` + the BVBM library and produces a client-ready DOCX guide, with per-day regeneration and override support.

**Architecture:** Three phases — (1) build `AIGContext` (load library + facts), (2) generate day JSONs and section JSONs independently, (3) assemble DOCX from stored JSONs. Each phase is independently runnable. Google Places integration is a separate Plan 2.

**Tech Stack:** Python 3.11+, Pydantic v2, python-docx, typer, rich, existing `AIClient`, existing `LibraryDatabase`

**Spec:** `docs/superpowers/specs/2026-05-21-aig-generation-design.md`

---

## File Map

### New files
| File | Responsibility |
|---|---|
| `src/aig/context.py` | `CityLibraryData`, `TravelLeg`, `EnrichedActivity`, `RestaurantCard`, `DayContent`, `AIGContext`, `build_context()`, `write_back_to_library()` |
| `src/aig/styles.py` | `AIG_STYLES` constant + `ensure_styles(doc)` — adds all named paragraph styles to a Document |
| `src/aig/day_builder.py` | `build_day(context, day_number, overrides)` — enriches one day and saves `input/days/day_NN.json` |
| `src/aig/assembler.py` | `assemble(input_dir, output_path)` — renders all stored JSONs to DOCX |
| `src/aig/sections/client_info.py` | `build(context) -> dict` |
| `src/aig/sections/cover.py` | `build(context) -> dict` |
| `src/aig/sections/must_try_dishes.py` | `build(context) -> dict` |
| `src/aig/sections/souvenir_guide.py` | `build(context) -> dict` |
| `src/aig/sections/getting_around.py` | `build(context) -> dict` |
| `src/aig/sections/cultural_etiquette.py` | `build(context) -> dict` — library first, AI fallback, write-back |
| `src/aig/sections/mobile_connectivity.py` | `build(context) -> dict` — library first, AI fallback, write-back |
| `src/aig/sections/safety_contacts.py` | `build(context) -> dict` — library first, AI fallback, write-back |
| `src/aig/sections/health_vaccination.py` | `build(context) -> dict` — library first, AI fallback, write-back |
| `src/aig/sections/packing_list.py` | `build(context) -> dict` — AI only (trip-specific) |
| `src/aig/sections/thank_you.py` | `build(context) -> dict` — static content |
| `tests/aig/test_context.py` | Tests for `CityLibraryData`, `build_context()`, `write_back_to_library()` |
| `tests/aig/test_day_builder.py` | Tests for day builder (activity order, library match, AI enrichment, restaurant selection) |
| `tests/aig/test_assembler.py` | Tests for DOCX assembler |
| `tests/aig/sections/__init__.py` | Empty |
| `tests/aig/sections/test_sections.py` | Tests for all section builders |

### Modified files
| File | Change |
|---|---|
| `src/library/builder.py` | Add `get_city_data(city: str) -> dict` to `LibraryDatabase` (~line 828) |
| `src/aig/__main__.py` | Replace stub `generate` command; add `redo-day`, `redo-section`, `assemble`, `build-styles` commands |

---

## Task 1: LibraryDatabase.get_city_data + CityLibraryData + AIGContext

**Files:**
- Modify: `src/library/builder.py:828`
- Create: `src/aig/context.py`
- Create: `tests/aig/test_context.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/aig/test_context.py
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.aig.context import (
    CityLibraryData, AIGContext, build_context, write_back_to_library,
)
from src.common.models import TripFacts, TripHotel, TripDay


AMSTERDAM_DATA = {
    "restaurants": [{"name": "Pancake Bakery", "city": "Amsterdam", "nearby_landmarks": ["Anne Frank House"]}],
    "attractions": [{"name": "Anne Frank House", "city": "Amsterdam", "hours": "9:00 AM TO 10:00 PM"}],
    "local_dishes": [{"name": "Stroopwafel"}],
    "souvenirs": [{"item": "Delft pottery"}],
    "transport_options": [{"mode": "metro", "tip": "Use OV-chipkaart"}],
    "emergency_contacts": [],
    "phrases": [],
    "safety_tips": [],
    "connectivity_tips": [],
    "health_tips": [],
}

FACTS = TripFacts(
    client_names=["Ana"],
    destinations=["Amsterdam"],
    trip_start_date="2026-04-19",
    trip_end_date="2026-04-22",
    hotels=[TripHotel(city="Amsterdam", hotel_name="Hotel V")],
    days=[TripDay(day_number=1, activities=["Visit Anne Frank House"])],
)


class TestCityLibraryData:
    def test_loads_from_dict(self):
        data = CityLibraryData(city="Amsterdam", **{
            k: AMSTERDAM_DATA.get(k, []) for k in [
                "restaurants", "attractions", "local_dishes", "souvenirs",
                "transport_options", "emergency_contacts", "phrases",
                "safety_tips", "connectivity_tips", "health_tips",
            ]
        })
        assert len(data.restaurants) == 1
        assert len(data.attractions) == 1

    def test_defaults_to_empty_lists(self):
        data = CityLibraryData(city="Rome")
        assert data.restaurants == []
        assert data.phrases == []


class TestBuildContext:
    def test_loads_library_for_each_city(self):
        mock_db = MagicMock()
        mock_db.get_city_data.return_value = AMSTERDAM_DATA
        mock_ai = MagicMock()

        with patch("src.aig.context.LibraryDatabase", return_value=mock_db):
            ctx = build_context(FACTS, Path("library_db"), mock_ai)

        assert "Amsterdam" in ctx.library
        assert len(ctx.library["Amsterdam"].restaurants) == 1

    def test_missing_city_not_in_library(self):
        mock_db = MagicMock()
        mock_db.get_city_data.return_value = {}
        mock_ai = MagicMock()

        with patch("src.aig.context.LibraryDatabase", return_value=mock_db):
            ctx = build_context(FACTS, Path("library_db"), mock_ai)

        assert "Amsterdam" not in ctx.library

    def test_hotel_coords_empty_without_geocoding(self):
        mock_db = MagicMock()
        mock_db.get_city_data.return_value = AMSTERDAM_DATA
        mock_ai = MagicMock()

        with patch("src.aig.context.LibraryDatabase", return_value=mock_db):
            ctx = build_context(FACTS, Path("library_db"), mock_ai)

        assert ctx.hotel_coords == {}

    def test_facts_stored_on_context(self):
        mock_db = MagicMock()
        mock_db.get_city_data.return_value = {}
        mock_ai = MagicMock()

        with patch("src.aig.context.LibraryDatabase", return_value=mock_db):
            ctx = build_context(FACTS, Path("library_db"), mock_ai)

        assert ctx.facts.client_names == ["Ana"]


class TestWriteBackToLibrary:
    def test_writes_field_and_audit_entry(self, tmp_path):
        city_file = tmp_path / "Amsterdam.json"
        city_file.write_text(json.dumps({"restaurants": [], "phrases": []}))

        write_back_to_library(tmp_path, "Amsterdam", "phrases", ["Alsjeblieft"], "AI test")

        data = json.loads(city_file.read_text())
        assert data["phrases"] == ["Alsjeblieft"]
        assert len(data["_audit"]) == 1
        assert data["_audit"][0]["updated_by"] == "AI test"
        assert data["_audit"][0]["field"] == "phrases"

    def test_no_op_when_city_file_missing(self, tmp_path):
        write_back_to_library(tmp_path, "Nowhere", "phrases", ["Hello"], "AI test")
        # Should not raise

    def test_appends_to_existing_audit_log(self, tmp_path):
        city_file = tmp_path / "Rome.json"
        city_file.write_text(json.dumps({"_audit": [{"updated_by": "prior"}]}))

        write_back_to_library(tmp_path, "Rome", "health_tips", ["Stay hydrated"], "AI test 2")

        data = json.loads(city_file.read_text())
        assert len(data["_audit"]) == 2
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /path/to/BVBMGuide
python -m pytest tests/aig/test_context.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.aig.context'`

- [ ] **Step 3: Add `get_city_data` to `LibraryDatabase` in `src/library/builder.py`**

Add after the `get_restaurants` method (line ~828):

```python
def get_city_data(self, city: str) -> dict:
    """Return all library data for a city, or {} if not found."""
    if self._sharded:
        if self._index is None:
            self.load()
        # Direct city-named shard (primary path)
        city_file = self.db_path / f'{city}.json'
        if city_file.exists():
            return self._load_dest(city)
        # Fallback: folder coverage (city stored under a country shard)
        city_lower = city.lower()
        coverage = self._index.get('_folder_coverage', {})
        for folder, covered_cities in coverage.items():
            if any(c.lower() == city_lower for c in covered_cities):
                return self._load_dest(folder)
        return {}
    for dest, data in self.data.get('destinations', {}).items():
        if dest.lower() == city.lower():
            return data
    return {}
```

- [ ] **Step 4: Create `src/aig/context.py`**

```python
"""AIGContext — central data object for AIG generation."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from src.common.ai_provider import AIClient
from src.common.models import TripFacts
from src.library.builder import LibraryDatabase


class CityLibraryData(BaseModel):
    city: str
    restaurants: list = Field(default_factory=list)
    attractions: list = Field(default_factory=list)
    local_dishes: list = Field(default_factory=list)
    souvenirs: list = Field(default_factory=list)
    transport_options: list = Field(default_factory=list)
    emergency_contacts: list = Field(default_factory=list)
    phrases: list = Field(default_factory=list)
    safety_tips: list = Field(default_factory=list)
    connectivity_tips: list = Field(default_factory=list)
    health_tips: list = Field(default_factory=list)


@dataclass
class AIGContext:
    facts: TripFacts
    library: dict[str, CityLibraryData]          # city → data
    db_path: Path
    ai_client: AIClient
    hotel_coords: dict[str, tuple[float, float]] = field(default_factory=dict)


def build_context(
    facts: TripFacts,
    db_path: Path,
    ai_client: AIClient,
) -> AIGContext:
    db = LibraryDatabase(db_path)
    db.load()
    library: dict[str, CityLibraryData] = {}
    for city in _extract_cities(facts):
        raw = db.get_city_data(city)
        if raw:
            library[city] = CityLibraryData(
                city=city,
                **{k: raw.get(k, []) for k in CityLibraryData.model_fields if k != "city"},
            )
    return AIGContext(facts=facts, library=library, db_path=db_path, ai_client=ai_client)


def _extract_cities(facts: TripFacts) -> list[str]:
    cities: set[str] = set()
    for dest in facts.destinations:
        cities.add(dest.split("(")[0].split(",")[0].strip())
    for hotel in facts.hotels:
        cities.add(hotel.city)
    return sorted(cities)


def write_back_to_library(
    db_path: Path,
    city: str,
    field: str,
    value: list,
    updated_by: str,
) -> None:
    """Persist AI-generated content to the library DB with an audit entry."""
    city_file = db_path / f"{city}.json"
    if not city_file.exists():
        return
    data = json.loads(city_file.read_text(encoding="utf-8"))
    data[field] = value
    data.setdefault("_audit", []).append({
        "updated_by": updated_by,
        "field": field,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    city_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
python -m pytest tests/aig/test_context.py -v
```
Expected: all 8 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/library/builder.py src/aig/context.py tests/aig/test_context.py
git commit -m "feat(aig): AIGContext, CityLibraryData, LibraryDatabase.get_city_data"
```

---

## Task 2: DOCX Styles

**Files:**
- Create: `src/aig/styles.py`
- Create: `tests/aig/test_styles.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/aig/test_styles.py
from docx import Document
from src.aig.styles import ensure_styles, AIG_STYLES


def test_ensure_styles_adds_all_aig_styles():
    doc = Document()
    ensure_styles(doc)
    style_names = {s.name for s in doc.styles}
    for name, *_ in AIG_STYLES:
        assert name in style_names, f"Missing style: {name}"


def test_ensure_styles_idempotent():
    doc = Document()
    ensure_styles(doc)
    ensure_styles(doc)  # second call must not raise
    style_names = {s.name for s in doc.styles}
    aig_names = [name for name, *_ in AIG_STYLES]
    assert len([n for n in aig_names if n in style_names]) == len(AIG_STYLES)


def test_aig_title_is_bold_and_large():
    doc = Document()
    ensure_styles(doc)
    style = doc.styles["AIG Title"]
    assert style.font.bold is True
    assert style.font.size.pt == 28
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/aig/test_styles.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.aig.styles'`

- [ ] **Step 3: Create `src/aig/styles.py`**

```python
"""Named paragraph styles for AIG documents."""

from docx import Document
from docx.shared import Pt, RGBColor

# (name, size_pt, bold, (r, g, b))
AIG_STYLES: list[tuple[str, int, bool, tuple[int, int, int]]] = [
    ("AIG Title",            28, True,  (44,  62,  80)),
    ("AIG Subtitle",         14, False, (127, 140, 141)),
    ("AIG Day Heading",      16, True,  (26,  82,  118)),
    ("AIG Section Heading",  14, True,  (26,  82,  118)),
    ("AIG Subsection",       12, True,  (46,  134, 193)),
    ("AIG Body",             11, False, (33,  33,  33)),
    ("AIG Restaurant Name",  11, True,  (26,  82,  118)),
    ("AIG Detail",           10, False, (85,  85,  85)),
    ("AIG Bullet",           11, False, (33,  33,  33)),
    ("AIG Overnight",        11, True,  (30,  132, 73)),
    ("AIG Note",             10, False, (230, 126, 34)),
]


def ensure_styles(doc: Document) -> None:
    """Add all AIG named styles to doc if not already present."""
    existing = {s.name for s in doc.styles}
    for name, pt, bold, (r, g, b) in AIG_STYLES:
        if name not in existing:
            style = doc.styles.add_style(name, 1)  # 1 = WD_STYLE_TYPE.PARAGRAPH
        else:
            style = doc.styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(pt)
        style.font.bold = bold
        style.font.color.rgb = RGBColor(r, g, b)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/aig/test_styles.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aig/styles.py tests/aig/test_styles.py
git commit -m "feat(aig): DOCX paragraph style definitions"
```

---

## Task 3: Day Builder — Load, Library Match, Travel Chain

**Files:**
- Create: `src/aig/day_builder.py`
- Create: `tests/aig/test_day_builder.py`

The day builder enriches one `TripDay` and writes `input/days/day_NN.json`. This task covers: loading activities in order, matching them to library attractions, and computing the travel chain in Python. AI enrichment is added in Task 4.

- [ ] **Step 1: Write the failing tests**

```python
# tests/aig/test_day_builder.py
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.aig.context import AIGContext, CityLibraryData
from src.aig.day_builder import (
    _match_attraction, _compute_chain, _is_cruise_day,
)
from src.common.models import TripFacts, TripDay, TripHotel


AMSTERDAM_LIBRARY = CityLibraryData(
    city="Amsterdam",
    attractions=[
        {"name": "Anne Frank House", "hours": "9:00 AM TO 10:00 PM",
         "entry_fee": "€16", "recommended_duration": "2 hours"},
        {"name": "Rijksmuseum", "hours": "9 AM – 6 PM",
         "entry_fee": "€22", "recommended_duration": "2-3 hours"},
    ],
    restaurants=[
        {"name": "Pancake Bakery", "nearby_landmarks": ["Anne Frank House"],
         "area": "Jordaan", "hours": "9am-8:30pm", "vegetarian_friendly": True,
         "must_try_dishes": ["Dutch pancake"], "cuisine_type": ["Dutch"]},
        {"name": "Broodje Bert", "nearby_landmarks": ["Rijksmuseum"],
         "area": "Museumplein", "hours": "11am-9pm", "vegetarian_friendly": False,
         "must_try_dishes": ["Broodje"], "cuisine_type": ["Dutch"]},
    ],
)

FACTS = TripFacts(
    client_names=["Ana"],
    destinations=["Amsterdam"],
    trip_start_date="2026-04-19",
    trip_end_date="2026-04-22",
    local_transport="Public Transport",
    hotels=[TripHotel(city="Amsterdam", hotel_name="Hotel V Nesplein")],
    days=[TripDay(
        day_number=1,
        date="2026-04-19",
        title="Amsterdam Highlights",
        overnight_city="Amsterdam",
        overnight_hotel="Hotel V Nesplein",
        activities=[
            "Visit Anne Frank House",
            "Walk to Rijksmuseum",
            "Return to hotel to freshen up",
            "Evening stroll at Vondelpark",
        ],
    )],
    dietary_restrictions=[],
    food_allergies=[],
)


class TestMatchAttraction:
    def test_exact_name_match(self):
        result = _match_attraction("Anne Frank House", AMSTERDAM_LIBRARY.attractions)
        assert result is not None
        assert result["hours"] == "9:00 AM TO 10:00 PM"

    def test_partial_name_match(self):
        result = _match_attraction("Visit Anne Frank House", AMSTERDAM_LIBRARY.attractions)
        assert result is not None
        assert result["name"] == "Anne Frank House"

    def test_no_match_returns_none(self):
        result = _match_attraction("Some Unknown Place", AMSTERDAM_LIBRARY.attractions)
        assert result is None


class TestComputeChain:
    def test_first_activity_departs_from_hotel(self):
        chain = _compute_chain(
            ["See Eiffel Tower", "Visit Louvre"],
            hotel_name="Hotel Ibis Paris",
        )
        assert chain[0] == "Hotel Ibis Paris"

    def test_second_activity_departs_from_previous(self):
        chain = _compute_chain(
            ["See Eiffel Tower", "Visit Louvre"],
            hotel_name="Hotel Ibis Paris",
        )
        assert chain[1] == "See Eiffel Tower"

    def test_reset_on_return_to_hotel(self):
        chain = _compute_chain(
            ["Anne Frank House", "Return to hotel to freshen up", "Vondelpark"],
            hotel_name="Hotel V",
        )
        # After "Return to hotel..." resets, next departs from hotel
        assert chain[2] == "Hotel V"

    def test_no_reset_on_regular_activity(self):
        chain = _compute_chain(
            ["Anne Frank House", "Rijksmuseum", "Vondelpark"],
            hotel_name="Hotel V",
        )
        assert chain[0] == "Hotel V"
        assert chain[1] == "Anne Frank House"
        assert chain[2] == "Rijksmuseum"


class TestIsCruiseDay:
    def test_overnight_city_none_is_cruise(self):
        day = TripDay(day_number=8, activities=["At Sea | Enjoy Cruise"], overnight_city=None)
        assert _is_cruise_day(day) is True

    def test_city_with_hotel_is_not_cruise(self):
        day = TripDay(day_number=1, activities=["Check in"], overnight_city="Amsterdam")
        assert _is_cruise_day(day) is False

    def test_at_sea_in_title_is_cruise(self):
        day = TripDay(day_number=9, activities=["At Sea | Relax"], overnight_city=None,
                      title="At Sea | Relax Day")
        assert _is_cruise_day(day) is True
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/aig/test_day_builder.py -v
```
Expected: `ImportError` — `_match_attraction`, `_compute_chain`, `_is_cruise_day` not yet defined.

- [ ] **Step 3: Create `src/aig/day_builder.py` with the three helper functions**

```python
"""Build enriched day content from TripFacts + library and save to JSON."""

import json
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from src.aig.context import AIGContext
from src.common.maps import maps_url
from src.common.models import TripDay


# ── Output models ────────────────────────────────────────────────────────────

class TravelLeg(BaseModel):
    from_location: str
    mode: str
    duration: str
    tip: Optional[str] = None


class EnrichedActivity(BaseModel):
    name: str
    vivid_description: str = ""
    hours: Optional[str] = None
    entry_fee: Optional[str] = None
    recommended_duration: Optional[str] = None
    source: str = "ai_estimated"          # "library" or "ai_estimated"
    maps_url: str = ""
    travel_leg: Optional[TravelLeg] = None


class RestaurantCard(BaseModel):
    name: str
    maps_url: str
    ambience: Optional[str] = None
    must_try_dishes: list[str] = Field(default_factory=list)
    hours: Optional[str] = None
    price_range: Optional[str] = None
    travel_note: Optional[str] = None     # "near Duomo" or "5 min from hotel"
    source: str = "library"               # "library" or "ai_curated"


class DayContent(BaseModel):
    day_number: int
    date: Optional[str] = None
    title: Optional[str] = None
    overnight_city: Optional[str] = None
    overnight_hotel: Optional[str] = None
    activities: list[EnrichedActivity] = Field(default_factory=list)
    lunch: list[RestaurantCard] = Field(default_factory=list)
    dinner: list[RestaurantCard] = Field(default_factory=list)
    is_cruise_day: bool = False
    transport_note: Optional[str] = None


# ── Helper functions ──────────────────────────────────────────────────────────

_RESET_KEYWORDS = [
    "return to hotel", "back to hotel", "rest", "freshen up", "nap",
    "hotel break", "check in", "check-in",
]


def _is_cruise_day(day: TripDay) -> bool:
    if day.overnight_city is None:
        return True
    combined = " ".join([day.title or ""] + day.activities).lower()
    return "at sea" in combined or "cruise" in combined


def _compute_chain(activities: list[str], hotel_name: str) -> list[str]:
    """Return from_location for each activity in order.

    Starts from hotel; resets to hotel after any activity that signals
    a return (rest, freshen up, etc.).
    """
    chain: list[str] = []
    current = hotel_name
    for activity in activities:
        chain.append(current)
        if any(kw in activity.lower() for kw in _RESET_KEYWORDS):
            current = hotel_name
        else:
            current = activity
    return chain


def _match_attraction(activity_name: str, attractions: list[dict]) -> Optional[dict]:
    """Fuzzy-match an activity string to a library attraction record."""
    name_lower = activity_name.lower()
    # Exact match first
    for attr in attractions:
        if attr.get("name", "").lower() == name_lower:
            return attr
    # Substring: attraction name appears in activity string or vice versa
    for attr in attractions:
        attr_name = attr.get("name", "").lower()
        if attr_name and (attr_name in name_lower or name_lower in attr_name):
            return attr
    return None
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/aig/test_day_builder.py -v
```
Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aig/day_builder.py tests/aig/test_day_builder.py
git commit -m "feat(aig): day builder helpers — chain computation, library match, cruise detection"
```

---

## Task 4: Day Builder — AI Enrichment

**Files:**
- Modify: `src/aig/day_builder.py`
- Modify: `tests/aig/test_day_builder.py`

Adds the AI call that fills in `vivid_description` and `travel_leg` for each activity.

- [ ] **Step 1: Write the failing tests**

Add to `tests/aig/test_day_builder.py`:

```python
import json as _json
from src.aig.day_builder import _enrich_activities_with_ai


AI_RESPONSE = _json.dumps([
    {
        "name": "Visit Anne Frank House",
        "vivid_description": "A house that stood still while time moved on around it.",
        "travel_leg": {
            "from_location": "Hotel V Nesplein",
            "mode": "walk",
            "duration": "~18 min",
            "tip": "Follow Prinsengracht canal north"
        }
    },
    {
        "name": "Walk to Rijksmuseum",
        "vivid_description": "Centuries of Dutch mastery hang in gilded frames.",
        "travel_leg": {
            "from_location": "Visit Anne Frank House",
            "mode": "walk",
            "duration": "~20 min",
            "tip": None
        }
    },
])


class TestEnrichActivitiesWithAI:
    def test_returns_enriched_list_in_order(self):
        mock_ai = MagicMock()
        mock_ai.complete.return_value = AI_RESPONSE
        activities = [
            {"name": "Visit Anne Frank House", "from_location": "Hotel V Nesplein",
             "hours": "9:00 AM TO 10:00 PM", "entry_fee": "€16"},
            {"name": "Walk to Rijksmuseum", "from_location": "Visit Anne Frank House",
             "hours": "9 AM – 6 PM", "entry_fee": "€22"},
        ]
        result = _enrich_activities_with_ai(activities, "Amsterdam", "Public Transport", mock_ai)
        assert len(result) == 2
        assert result[0]["name"] == "Visit Anne Frank House"
        assert result[0]["vivid_description"] != ""
        assert result[0]["travel_leg"]["mode"] == "walk"

    def test_order_preserved_even_if_ai_reorders(self):
        # AI returns items in wrong order — we re-sort by original index
        mock_ai = MagicMock()
        reversed_response = _json.dumps([
            {"name": "Walk to Rijksmuseum", "vivid_description": "Museums.", "travel_leg": None},
            {"name": "Visit Anne Frank House", "vivid_description": "House.", "travel_leg": None},
        ])
        mock_ai.complete.return_value = reversed_response
        activities = [
            {"name": "Visit Anne Frank House", "from_location": "Hotel V"},
            {"name": "Walk to Rijksmuseum", "from_location": "Visit Anne Frank House"},
        ]
        result = _enrich_activities_with_ai(activities, "Amsterdam", "Public Transport", mock_ai)
        assert result[0]["name"] == "Visit Anne Frank House"
        assert result[1]["name"] == "Walk to Rijksmuseum"

    def test_falls_back_gracefully_on_bad_ai_response(self):
        mock_ai = MagicMock()
        mock_ai.complete.return_value = "not json {{{"
        activities = [{"name": "Anne Frank House", "from_location": "Hotel V"}]
        result = _enrich_activities_with_ai(activities, "Amsterdam", "walk", mock_ai)
        assert len(result) == 1
        assert result[0]["name"] == "Anne Frank House"
        assert result[0].get("vivid_description", "") == ""
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/aig/test_day_builder.py::TestEnrichActivitiesWithAI -v
```
Expected: `ImportError` — `_enrich_activities_with_ai` not defined.

- [ ] **Step 3: Add `_enrich_activities_with_ai` and the prompt to `src/aig/day_builder.py`**

```python
import re as _re

_ENRICHMENT_PROMPT = """\
You are enriching a travel day for {client_names} in {city}.
Default transport mode: {local_transport}

For each activity below, provide:
- "vivid_description": 2–3 vivid, immersive, sensory sentences. Be specific, not generic.
- "travel_leg": how to travel TO this activity from the given from_location:
  - "mode": most practical transport. Use "walk" for distances under ~500m regardless of default.
  - "duration": estimated time e.g. "~20 min"
  - "tip": one practical tip (platform, app, route), or null

Activities (process in EXACTLY this order, never reorder):
{activities_json}

Return a JSON array of exactly {n} objects. Each object must include the original "name" unchanged.
No markdown fences. No explanation."""


def _enrich_activities_with_ai(
    activities: list[dict],
    city: str,
    local_transport: str,
    ai_client,
) -> list[dict]:
    """Call AI to add vivid_description and travel_leg to each activity dict."""
    client_names = "travellers"
    prompt = _ENRICHMENT_PROMPT.format(
        client_names=client_names,
        city=city,
        local_transport=local_transport,
        activities_json=json.dumps(activities, ensure_ascii=False, indent=2),
        n=len(activities),
    )
    raw = ai_client.complete(prompt, max_tokens=4096, temperature=0.3)
    enriched = _parse_json_list(raw)
    if not enriched or len(enriched) != len(activities):
        return activities  # fallback: return unenriched
    # Re-sort by original order using name matching
    name_to_enriched = {item.get("name", ""): item for item in enriched}
    result = []
    for original in activities:
        merged = dict(original)
        match = name_to_enriched.get(original["name"])
        if match:
            merged["vivid_description"] = match.get("vivid_description", "")
            merged["travel_leg"] = match.get("travel_leg")
        result.append(merged)
    return result


def _parse_json_list(text: str) -> list:
    text = text.strip()
    text = _re.sub(r"^```(?:json)?\s*", "", text)
    text = _re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    match = _re.search(r"\[.*\]", text, _re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return []
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/aig/test_day_builder.py -v
```
Expected: all 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aig/day_builder.py tests/aig/test_day_builder.py
git commit -m "feat(aig): day builder AI enrichment — vivid descriptions and travel chain"
```

---

## Task 5: Day Builder — Restaurant Selection + Full build_day()

**Files:**
- Modify: `src/aig/day_builder.py`
- Modify: `tests/aig/test_day_builder.py`

Adds restaurant selection (proximity match, dietary filter, rotation) and the top-level `build_day()` function that saves `day_NN.json`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/aig/test_day_builder.py`:

```python
from src.aig.day_builder import _select_restaurants, build_day


class TestSelectRestaurants:
    def _make_context(self, restaurants):
        ctx = MagicMock(spec=AIGContext)
        ctx.facts = FACTS
        lib = MagicMock()
        lib.restaurants = restaurants
        ctx.library = {"Amsterdam": lib}
        return ctx

    def test_lunch_matches_nearby_landmarks(self):
        ctx = self._make_context(AMSTERDAM_LIBRARY.restaurants)
        lunch, _ = _select_restaurants(
            city="Amsterdam",
            context=ctx,
            morning_activities=["Visit Anne Frank House"],
            day_number=1,
            used_restaurants={},
        )
        names = [r.name for r in lunch]
        assert "Pancake Bakery" in names

    def test_dietary_filter_excludes_non_vegetarian(self):
        facts = FACTS.model_copy(update={"dietary_restrictions": ["vegetarian"]})
        ctx = self._make_context(AMSTERDAM_LIBRARY.restaurants)
        ctx.facts = facts
        _, dinner = _select_restaurants(
            city="Amsterdam",
            context=ctx,
            morning_activities=[],
            day_number=1,
            used_restaurants={},
        )
        for card in dinner:
            assert card.source != "library" or "Broodje Bert" not in card.name

    def test_rotation_excludes_restaurant_used_twice_in_window(self):
        used = {"Pancake Bakery": [1, 2]}  # used on days 1 and 2
        ctx = self._make_context(AMSTERDAM_LIBRARY.restaurants)
        lunch, _ = _select_restaurants(
            city="Amsterdam",
            context=ctx,
            morning_activities=["Visit Anne Frank House"],
            day_number=3,
            used_restaurants=used,
        )
        assert all(r.name != "Pancake Bakery" for r in lunch)

    def test_restaurant_within_rotation_window_allowed_once(self):
        used = {"Pancake Bakery": [1]}   # used only once in window
        ctx = self._make_context(AMSTERDAM_LIBRARY.restaurants)
        lunch, _ = _select_restaurants(
            city="Amsterdam",
            context=ctx,
            morning_activities=["Visit Anne Frank House"],
            day_number=2,
            used_restaurants=used,
        )
        assert any(r.name == "Pancake Bakery" for r in lunch)


class TestBuildDay:
    def test_saves_day_json_to_input_days(self, tmp_path):
        mock_ai = MagicMock()
        mock_ai.complete.return_value = json.dumps([
            {"name": act, "vivid_description": "Lovely.", "travel_leg": None}
            for act in FACTS.days[0].activities
        ])
        ctx = AIGContext(
            facts=FACTS,
            library={"Amsterdam": AMSTERDAM_LIBRARY},
            db_path=tmp_path,
            ai_client=mock_ai,
        )
        build_day(ctx, day_number=1, input_dir=tmp_path)
        day_file = tmp_path / "days" / "day_01.json"
        assert day_file.exists()
        data = json.loads(day_file.read_text())
        assert data["day_number"] == 1

    def test_activity_order_preserved(self, tmp_path):
        mock_ai = MagicMock()
        mock_ai.complete.return_value = json.dumps([
            {"name": act, "vivid_description": "X.", "travel_leg": None}
            for act in FACTS.days[0].activities
        ])
        ctx = AIGContext(
            facts=FACTS,
            library={"Amsterdam": AMSTERDAM_LIBRARY},
            db_path=tmp_path,
            ai_client=mock_ai,
        )
        build_day(ctx, day_number=1, input_dir=tmp_path)
        data = json.loads((tmp_path / "days" / "day_01.json").read_text())
        names = [a["name"] for a in data["activities"]]
        assert names == FACTS.days[0].activities

    def test_cruise_day_skips_restaurant_lookup(self, tmp_path):
        cruise_facts = TripFacts(
            client_names=["Ana"],
            destinations=["Mediterranean"],
            trip_start_date="2026-04-26",
            trip_end_date="2026-04-27",
            hotels=[],
            days=[TripDay(
                day_number=8,
                title="At Sea | Relax",
                overnight_city=None,
                activities=["Relax on deck", "Spa treatment"],
            )],
        )
        mock_ai = MagicMock()
        mock_ai.complete.return_value = json.dumps([
            {"name": a, "vivid_description": "Sea.", "travel_leg": None}
            for a in cruise_facts.days[0].activities
        ])
        ctx = AIGContext(
            facts=cruise_facts, library={}, db_path=tmp_path, ai_client=mock_ai,
        )
        build_day(ctx, day_number=8, input_dir=tmp_path)
        data = json.loads((tmp_path / "days" / "day_08.json").read_text())
        assert data["is_cruise_day"] is True
        assert data["lunch"] == []
        assert data["dinner"] == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/aig/test_day_builder.py::TestSelectRestaurants tests/aig/test_day_builder.py::TestBuildDay -v
```
Expected: `ImportError`.

- [ ] **Step 3: Add `_select_restaurants` and `build_day` to `src/aig/day_builder.py`**

```python
from src.common.maps import maps_url as _maps_url


def _select_restaurants(
    city: str,
    context: AIGContext,
    morning_activities: list[str],
    day_number: int,
    used_restaurants: dict[str, list[int]],
) -> tuple[list[RestaurantCard], list[RestaurantCard]]:
    """Return (lunch_cards, dinner_cards) — max 3 each."""
    lib = context.library.get(city)
    all_rests = lib.restaurants if lib else []
    dietary = set(r.lower() for r in context.facts.dietary_restrictions)
    allergies = set(a.lower() for a in context.facts.food_allergies)

    def is_allowed(r: dict) -> bool:
        if dietary and not r.get("vegetarian_friendly", False):
            if "vegetarian" in dietary or "vegan" in dietary:
                return False
        return True

    def rotation_ok(name: str) -> bool:
        recent = [d for d in used_restaurants.get(name, []) if day_number - d <= 2]
        return len(recent) < 2

    def to_card(r: dict, note: str) -> RestaurantCard:
        return RestaurantCard(
            name=r["name"],
            maps_url=_maps_url(r["name"], city),
            must_try_dishes=r.get("must_try_dishes", []),
            hours=r.get("hours"),
            travel_note=note,
            source="library",
        )

    # Lunch: prefer restaurants near morning attractions
    morning_lower = {a.lower() for a in morning_activities}
    lunch_pool = [
        r for r in all_rests
        if is_allowed(r) and rotation_ok(r["name"])
        and any(lm.lower() in morning_lower or any(ml in lm.lower() for ml in morning_lower)
                for lm in r.get("nearby_landmarks", []))
    ]
    if len(lunch_pool) < 3:
        # widen: any allowed restaurant not already in pool
        extras = [r for r in all_rests if is_allowed(r) and rotation_ok(r["name"])
                  and r not in lunch_pool]
        lunch_pool += extras

    lunch_cards = [to_card(r, f"near {r.get('area', city)}") for r in lunch_pool[:3]]

    # Dinner: prefer restaurants near hotel (no specific landmark required)
    hotel_name = ""
    for h in context.facts.hotels:
        if h.city.lower() == city.lower():
            hotel_name = h.hotel_name
            break
    dinner_pool = [
        r for r in all_rests
        if is_allowed(r) and rotation_ok(r["name"])
        and r not in lunch_pool[:3]
    ]
    dinner_cards = [to_card(r, f"near {hotel_name or city}") for r in dinner_pool[:3]]

    return lunch_cards, dinner_cards


def _load_used_restaurants(input_dir: Path) -> dict[str, list[int]]:
    """Scan existing day JSONs to build a map of {restaurant_name: [day_numbers]}."""
    used: dict[str, list[int]] = {}
    days_dir = input_dir / "days"
    if not days_dir.exists():
        return used
    for f in sorted(days_dir.glob("day_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            day_num = data.get("day_number", 0)
            for meal in (data.get("lunch", []) + data.get("dinner", [])):
                name = meal.get("name", "")
                if name:
                    used.setdefault(name, []).append(day_num)
        except Exception:
            pass
    return used


def build_day(
    context: AIGContext,
    day_number: int,
    input_dir: Path,
    overrides: Optional[dict] = None,
) -> DayContent:
    """Enrich one TripDay and save to input_dir/days/day_NN.json."""
    overrides = overrides or {}
    day = context.facts.days[day_number - 1]
    city = day.overnight_city or ""
    hotel_name = next(
        (h.hotel_name for h in context.facts.hotels if h.city.lower() == city.lower()),
        context.facts.hotels[0].hotel_name if context.facts.hotels else "",
    )
    transport = overrides.get("transport") or day.transport_note or context.facts.local_transport or "taxi"
    cruise = _is_cruise_day(day)

    # Build activity list with from_location chain
    chain = _compute_chain(day.activities, hotel_name)
    lib = context.library.get(city)
    attraction_list = lib.attractions if lib else []

    activity_dicts = []
    for activity, from_loc in zip(day.activities, chain):
        attr = _match_attraction(activity, attraction_list)
        d: dict = {
            "name": activity,
            "from_location": from_loc,
            "hours": attr["hours"] if attr else None,
            "entry_fee": attr.get("entry_fee") if attr else None,
            "recommended_duration": attr.get("recommended_duration") if attr else None,
            "source": "library" if attr else "ai_estimated",
            "maps_url": _maps_url(activity, city),
        }
        activity_dicts.append(d)

    # AI enrichment
    if not cruise:
        enriched_dicts = _enrich_activities_with_ai(
            activity_dicts, city, transport, context.ai_client
        )
    else:
        enriched_dicts = activity_dicts

    activities = [
        EnrichedActivity(
            name=d["name"],
            vivid_description=d.get("vivid_description", ""),
            hours=d.get("hours"),
            entry_fee=d.get("entry_fee"),
            recommended_duration=d.get("recommended_duration"),
            source=d.get("source", "ai_estimated"),
            maps_url=d.get("maps_url", ""),
            travel_leg=TravelLeg(**d["travel_leg"]) if d.get("travel_leg") else None,
        )
        for d in enriched_dicts
    ]

    # Restaurants
    if cruise:
        lunch_cards, dinner_cards = [], []
    else:
        morning_acts = [a["name"] for a in activity_dicts[:len(activity_dicts) // 2 + 1]]
        used = _load_used_restaurants(input_dir)
        lunch_cards, dinner_cards = _select_restaurants(
            city, context, morning_acts, day_number, used
        )

    content = DayContent(
        day_number=day_number,
        date=day.date,
        title=day.title,
        overnight_city=city or None,
        overnight_hotel=day.overnight_hotel,
        activities=activities,
        lunch=lunch_cards,
        dinner=dinner_cards,
        is_cruise_day=cruise,
        transport_note=day.transport_note,
    )

    out_dir = input_dir / "days"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"day_{day_number:02d}.json").write_text(
        content.model_dump_json(indent=2), encoding="utf-8"
    )
    return content
```

- [ ] **Step 4: Run all day builder tests**

```bash
python -m pytest tests/aig/test_day_builder.py -v
```
Expected: all 20 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aig/day_builder.py tests/aig/test_day_builder.py
git commit -m "feat(aig): complete day builder — restaurant selection, rotation, build_day()"
```

---

## Task 6: Library-Backed Sections (must_try_dishes, souvenir_guide, getting_around)

**Files:**
- Create: `src/aig/sections/must_try_dishes.py`
- Create: `src/aig/sections/souvenir_guide.py`
- Create: `src/aig/sections/getting_around.py`
- Create: `tests/aig/sections/__init__.py`
- Create: `tests/aig/sections/test_sections.py`

These three sections pull directly from the library — no AI, no write-back.

- [ ] **Step 1: Write failing tests**

```python
# tests/aig/sections/__init__.py
# (empty)

# tests/aig/sections/test_sections.py
import pytest
from unittest.mock import MagicMock
from pathlib import Path

from src.aig.context import AIGContext, CityLibraryData
from src.common.models import TripFacts, TripHotel, TripDay
import src.aig.sections.must_try_dishes as must_try
import src.aig.sections.souvenir_guide as souvenirs
import src.aig.sections.getting_around as getting_around


def _make_context(library_overrides=None):
    lib = CityLibraryData(
        city="Amsterdam",
        local_dishes=[{"name": "Stroopwafel", "type": "Street Food", "description": "Caramel wafer"},
                      {"name": "Erwtensoep", "type": "Mains", "description": "Pea soup"}],
        souvenirs=[{"item": "Delft pottery", "where": "Delft shops", "tip": "Check for authenticity"}],
        transport_options=[{"mode": "metro", "tip": "Use OV-chipkaart", "where_to_buy": "Schiphol"}],
        **(library_overrides or {}),
    )
    facts = TripFacts(
        client_names=["Ana"],
        destinations=["Amsterdam"],
        trip_start_date="2026-04-19",
        trip_end_date="2026-04-22",
        hotels=[TripHotel(city="Amsterdam", hotel_name="Hotel V")],
        days=[TripDay(day_number=1, activities=[])],
    )
    ctx = MagicMock(spec=AIGContext)
    ctx.facts = facts
    ctx.library = {"Amsterdam": lib}
    return ctx


class TestMustTryDishes:
    def test_returns_dict_with_cities(self):
        result = must_try.build(_make_context())
        assert "cities" in result
        assert len(result["cities"]) == 1
        assert result["cities"][0]["city"] == "Amsterdam"

    def test_dishes_included(self):
        result = must_try.build(_make_context())
        names = [d["name"] for d in result["cities"][0]["dishes"]]
        assert "Stroopwafel" in names

    def test_empty_library_returns_empty_cities(self):
        ctx = _make_context({"local_dishes": []})
        result = must_try.build(ctx)
        assert result["cities"][0]["dishes"] == []


class TestSouvenirGuide:
    def test_returns_dict_with_cities(self):
        result = souvenirs.build(_make_context())
        assert "cities" in result

    def test_souvenir_items_included(self):
        result = souvenirs.build(_make_context())
        items = [s["item"] for s in result["cities"][0]["items"]]
        assert "Delft pottery" in items


class TestGettingAround:
    def test_returns_dict_with_cities(self):
        result = getting_around.build(_make_context())
        assert "cities" in result

    def test_transport_options_included(self):
        result = getting_around.build(_make_context())
        modes = [t["mode"] for t in result["cities"][0]["options"]]
        assert "metro" in modes
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/aig/sections/test_sections.py::TestMustTryDishes tests/aig/sections/test_sections.py::TestSouvenirGuide tests/aig/sections/test_sections.py::TestGettingAround -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create the three section files**

```python
# src/aig/sections/must_try_dishes.py
from src.aig.context import AIGContext

def build(context: AIGContext) -> dict:
    cities = []
    for city, lib in context.library.items():
        cities.append({"city": city, "dishes": list(lib.local_dishes)})
    return {"cities": cities}
```

```python
# src/aig/sections/souvenir_guide.py
from src.aig.context import AIGContext

def build(context: AIGContext) -> dict:
    cities = []
    for city, lib in context.library.items():
        cities.append({"city": city, "items": list(lib.souvenirs)})
    return {"cities": cities}
```

```python
# src/aig/sections/getting_around.py
from src.aig.context import AIGContext

def build(context: AIGContext) -> dict:
    cities = []
    for city, lib in context.library.items():
        cities.append({"city": city, "options": list(lib.transport_options)})
    return {"cities": cities}
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/aig/sections/test_sections.py::TestMustTryDishes tests/aig/sections/test_sections.py::TestSouvenirGuide tests/aig/sections/test_sections.py::TestGettingAround -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aig/sections/must_try_dishes.py src/aig/sections/souvenir_guide.py \
        src/aig/sections/getting_around.py tests/aig/sections/__init__.py \
        tests/aig/sections/test_sections.py
git commit -m "feat(aig): library-backed sections — must_try_dishes, souvenir_guide, getting_around"
```

---

## Task 7: Library + AI Fallback Sections

**Files:**
- Create: `src/aig/sections/cultural_etiquette.py`
- Create: `src/aig/sections/mobile_connectivity.py`
- Create: `src/aig/sections/safety_contacts.py`
- Create: `src/aig/sections/health_vaccination.py`
- Modify: `tests/aig/sections/test_sections.py`

Pattern: read library field → if empty, call AI → write result back to library DB.

- [ ] **Step 1: Write failing tests**

Add to `tests/aig/sections/test_sections.py`:

```python
import src.aig.sections.cultural_etiquette as cult_etiquette
import src.aig.sections.mobile_connectivity as connectivity
import src.aig.sections.safety_contacts as safety
import src.aig.sections.health_vaccination as health


def _make_context_with_ai(library_field, library_value, ai_response):
    """Helper: context where one library field is set (or empty) and AI returns ai_response."""
    ctx = _make_context({library_field: library_value})
    ctx.ai_client = MagicMock()
    ctx.ai_client.complete.return_value = ai_response
    ctx.db_path = Path("/fake/db")
    return ctx


class TestCulturalEtiquette:
    def test_uses_library_when_available(self):
        ctx = _make_context_with_ai("phrases", [{"phrase": "Dank je", "meaning": "Thank you"}], "ignored")
        result = cult_etiquette.build(ctx)
        assert result["cities"][0]["phrases"] == [{"phrase": "Dank je", "meaning": "Thank you"}]
        ctx.ai_client.complete.assert_not_called()

    def test_calls_ai_when_library_empty(self, tmp_path):
        ctx = _make_context_with_ai("phrases", [], '["Dank je — Thank you", "Alsjeblieft — Please"]')
        ctx.db_path = tmp_path
        (tmp_path / "Amsterdam.json").write_text('{"phrases": []}')
        result = cult_etiquette.build(ctx)
        assert result["cities"][0]["ai_generated"] is True
        ctx.ai_client.complete.assert_called_once()

    def test_writes_back_to_library_when_ai_generated(self, tmp_path):
        ctx = _make_context_with_ai("phrases", [], '["Dank je — Thank you"]')
        ctx.db_path = tmp_path
        (tmp_path / "Amsterdam.json").write_text('{"phrases": []}')
        cult_etiquette.build(ctx)
        data = __import__("json").loads((tmp_path / "Amsterdam.json").read_text())
        assert len(data.get("_audit", [])) == 1


class TestSafetyContacts:
    def test_uses_library_when_available(self):
        ctx = _make_context_with_ai(
            "safety_tips", ["Do not leave bags unattended"], "ignored"
        )
        result = safety.build(ctx)
        assert result["cities"][0]["tips"] == ["Do not leave bags unattended"]
        ctx.ai_client.complete.assert_not_called()

    def test_calls_ai_when_empty(self, tmp_path):
        ctx = _make_context_with_ai("safety_tips", [], '["Keep valuables hidden"]')
        ctx.db_path = tmp_path
        (tmp_path / "Amsterdam.json").write_text('{"safety_tips": []}')
        result = safety.build(ctx)
        assert result["cities"][0]["ai_generated"] is True
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/aig/sections/test_sections.py::TestCulturalEtiquette tests/aig/sections/test_sections.py::TestSafetyContacts -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create a shared `_library_or_ai` helper and the four section files**

```python
# src/aig/sections/_fallback.py
"""Shared helper: read library field, fall back to AI, write back."""

import json
from src.aig.context import AIGContext, write_back_to_library


def library_or_ai(
    context: AIGContext,
    city: str,
    library_field: str,
    ai_prompt: str,
) -> tuple[list, bool]:
    """Return (value, ai_generated). Writes back to library if AI was used."""
    lib = context.library.get(city)
    existing = getattr(lib, library_field, []) if lib else []
    if existing:
        return existing, False
    raw = context.ai_client.complete(ai_prompt, max_tokens=2048, temperature=0.3)
    # Parse: expect a JSON array of strings
    try:
        value = json.loads(raw)
        if not isinstance(value, list):
            value = [raw]
    except Exception:
        value = [raw]
    updated_by = (
        f"AI while building {', '.join(context.facts.client_names)} guide "
        f"{context.facts.trip_start_date or 'unknown date'}"
    )
    write_back_to_library(context.db_path, city, library_field, value, updated_by)
    return value, True
```

```python
# src/aig/sections/cultural_etiquette.py
from src.aig.context import AIGContext
from src.aig.sections._fallback import library_or_ai

_PROMPT = """\
List 5–8 essential cultural etiquette tips and useful local phrases for {city}.
Return a JSON array of strings, each item being either a phrase with translation
(e.g. "Dank je — Thank you") or a practical tip.
No markdown fences."""


def build(context: AIGContext) -> dict:
    cities = []
    for city, _lib in context.library.items():
        phrases, ai_generated = library_or_ai(
            context, city, "phrases", _PROMPT.format(city=city)
        )
        cities.append({"city": city, "phrases": phrases, "ai_generated": ai_generated})
    return {"cities": cities}
```

```python
# src/aig/sections/mobile_connectivity.py
from src.aig.context import AIGContext
from src.aig.sections._fallback import library_or_ai

_PROMPT = """\
Provide mobile connectivity tips for Indian travellers visiting {city}.
Cover: SIM and eSIM providers, where to buy, approximate cost, and coverage quality.
Return a JSON array of strings (one tip per item). No markdown fences."""


def build(context: AIGContext) -> dict:
    cities = []
    for city, _lib in context.library.items():
        tips, ai_generated = library_or_ai(
            context, city, "connectivity_tips", _PROMPT.format(city=city)
        )
        cities.append({"city": city, "tips": tips, "ai_generated": ai_generated})
    return {"cities": cities}
```

```python
# src/aig/sections/safety_contacts.py
from src.aig.context import AIGContext
from src.aig.sections._fallback import library_or_ai

_PROMPT = """\
Provide safety tips and emergency contacts for Indian travellers in {city}.
Include: Indian embassy details, police/ambulance numbers, common scams, practical safety advice.
Return a JSON array of strings. No markdown fences."""


def build(context: AIGContext) -> dict:
    cities = []
    for city, _lib in context.library.items():
        tips, ai_generated = library_or_ai(
            context, city, "safety_tips", _PROMPT.format(city=city)
        )
        cities.append({"city": city, "tips": tips, "ai_generated": ai_generated})
    return {"cities": cities}
```

```python
# src/aig/sections/health_vaccination.py
from src.aig.context import AIGContext
from src.aig.sections._fallback import library_or_ai

_PROMPT = """\
Provide health and vaccination guidance for Indian travellers visiting {city}.
Distinguish required vs recommended vaccines. Include food/water precautions and
any destination-specific health advice. Keep it practical, not alarmist.
Return a JSON array of strings. No markdown fences."""


def build(context: AIGContext) -> dict:
    cities = []
    for city, _lib in context.library.items():
        tips, ai_generated = library_or_ai(
            context, city, "health_tips", _PROMPT.format(city=city)
        )
        cities.append({"city": city, "tips": tips, "ai_generated": ai_generated})
    return {"cities": cities}
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/aig/sections/test_sections.py::TestCulturalEtiquette tests/aig/sections/test_sections.py::TestSafetyContacts -v
```
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aig/sections/_fallback.py src/aig/sections/cultural_etiquette.py \
        src/aig/sections/mobile_connectivity.py src/aig/sections/safety_contacts.py \
        src/aig/sections/health_vaccination.py tests/aig/sections/test_sections.py
git commit -m "feat(aig): library+AI fallback sections — etiquette, connectivity, safety, health"
```

---

## Task 8: AI-Only and Static Sections (cover, packing_list, thank_you)

**Files:**
- Create: `src/aig/sections/cover.py`
- Create: `src/aig/sections/packing_list.py`
- Create: `src/aig/sections/thank_you.py`
- Modify: `tests/aig/sections/test_sections.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/aig/sections/test_sections.py`:

```python
import src.aig.sections.cover as cover
import src.aig.sections.packing_list as packing
import src.aig.sections.thank_you as thank_you


class TestCover:
    def test_returns_title_and_subtitle(self):
        ctx = _make_context()
        ctx.ai_client = MagicMock()
        ctx.ai_client.complete.return_value = json.dumps({
            "title": "Windmills and Canals",
            "subtitle": "A 3-Night Amsterdam Adventure"
        })
        result = cover.build(ctx)
        assert "title" in result
        assert "subtitle" in result
        assert result["title"] != ""

    def test_falls_back_on_bad_ai_response(self):
        ctx = _make_context()
        ctx.ai_client = MagicMock()
        ctx.ai_client.complete.return_value = "not json"
        result = cover.build(ctx)
        assert "title" in result  # fallback title generated from destinations


class TestPackingList:
    def test_calls_ai_with_trip_context(self):
        ctx = _make_context()
        ctx.ai_client = MagicMock()
        ctx.ai_client.complete.return_value = json.dumps(["Comfortable walking shoes", "Rain jacket"])
        result = packing.build(ctx)
        assert "items" in result
        assert len(result["items"]) >= 1
        prompt_used = ctx.ai_client.complete.call_args[0][0]
        assert "Amsterdam" in prompt_used

    def test_trip_dates_in_prompt(self):
        ctx = _make_context()
        ctx.ai_client = MagicMock()
        ctx.ai_client.complete.return_value = "[]"
        packing.build(ctx)
        prompt = ctx.ai_client.complete.call_args[0][0]
        assert "2026-04-19" in prompt


class TestThankYou:
    def test_returns_static_text(self):
        ctx = _make_context()
        result = thank_you.build(ctx)
        assert "text" in result
        assert "Bon Voyage by Marina" in result["text"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/aig/sections/test_sections.py::TestCover tests/aig/sections/test_sections.py::TestPackingList tests/aig/sections/test_sections.py::TestThankYou -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create the three section files**

```python
# src/aig/sections/cover.py
import json
from src.aig.context import AIGContext

_PROMPT = """\
Generate a creative, premium travel guide title and subtitle for this trip.
Destinations: {destinations}
Dates: {start} to {end}
Client: {clients}

Return JSON: {{"title": "...", "subtitle": "..."}}
Title must be specific and evocative (e.g. "Windmills, Gelato & Ancient Ruins").
Never generic. No markdown fences."""


def build(context: AIGContext) -> dict:
    f = context.facts
    prompt = _PROMPT.format(
        destinations=", ".join(f.destinations),
        start=f.trip_start_date or "TBD",
        end=f.trip_end_date or "TBD",
        clients=", ".join(f.client_names),
    )
    raw = context.ai_client.complete(prompt, max_tokens=256, temperature=0.7)
    try:
        data = json.loads(raw)
        return {"title": data.get("title", ""), "subtitle": data.get("subtitle", "")}
    except Exception:
        fallback_title = " & ".join(f.destinations[:3]) + " — All Inclusive Guide"
        return {"title": fallback_title, "subtitle": f"{f.trip_start_date} – {f.trip_end_date}"}
```

```python
# src/aig/sections/packing_list.py
import json
from src.aig.context import AIGContext

_PROMPT = """\
Create a tailored packing list for this trip.
Destinations: {destinations}
Dates: {start} to {end} (infer the season and weather)
Activities mentioned: {activities}
Dietary/cultural notes: {dietary}

Return a JSON array of packing item strings. Group logically.
Be specific to this trip — not generic. No markdown fences."""


def build(context: AIGContext) -> dict:
    f = context.facts
    all_activities = []
    for day in f.days:
        all_activities.extend(day.activities[:2])
    prompt = _PROMPT.format(
        destinations=", ".join(f.destinations),
        start=f.trip_start_date or "",
        end=f.trip_end_date or "",
        activities=", ".join(all_activities[:10]),
        dietary=", ".join(f.dietary_restrictions) or "none",
    )
    raw = context.ai_client.complete(prompt, max_tokens=1024, temperature=0.3)
    try:
        items = json.loads(raw)
        if isinstance(items, list):
            return {"items": items}
    except Exception:
        pass
    return {"items": [raw]}
```

```python
# src/aig/sections/thank_you.py
from src.aig.context import AIGContext

_THANK_YOU_TEXT = (
    "Thank you for choosing Bon Voyage by Marina. "
    "We hope this guide makes your journey seamless, joyful, and truly unforgettable. "
    "Should you need anything during your trip, don't hesitate to reach out.\n\n"
    "Bon Voyage By Marina — Crafting unforgettable journeys.\n"
    "📞 +91-86000-15316  |  ✉ hello@bonvoyagebymarina.com"
)


def build(context: AIGContext) -> dict:
    return {"text": _THANK_YOU_TEXT}
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/aig/sections/test_sections.py::TestCover tests/aig/sections/test_sections.py::TestPackingList tests/aig/sections/test_sections.py::TestThankYou -v
```
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aig/sections/cover.py src/aig/sections/packing_list.py \
        src/aig/sections/thank_you.py tests/aig/sections/test_sections.py
git commit -m "feat(aig): cover, packing list, and thank you sections"
```

---

## Task 9: Client Information Page

**Files:**
- Create: `src/aig/sections/client_info.py`
- Modify: `tests/aig/sections/test_sections.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/aig/sections/test_sections.py`:

```python
import src.aig.sections.client_info as client_info
from src.common.models import TripFacts, TripHotel, TripDay


class TestClientInfo:
    def _make_multi_hotel_context(self):
        facts = TripFacts(
            client_names=["Ana", "Raj"],
            num_guests="2 adults",
            departure_city="Mumbai",
            destinations=["Amsterdam", "Florence"],
            trip_start_date="2026-04-19",
            trip_end_date="2026-04-25",
            local_transport="Public Transport",
            dietary_restrictions=["vegetarian"],
            hotels=[
                TripHotel(city="Amsterdam", hotel_name="Hotel V", check_in="2026-04-19", check_out="2026-04-22"),
                TripHotel(city="Florence", hotel_name="Hotel Alex", check_in="2026-04-22", check_out="2026-04-25"),
            ],
            days=[TripDay(day_number=1, activities=[])],
        )
        ctx = _make_context()
        ctx.facts = facts
        ctx.library = {}
        return ctx

    def test_client_names_in_result(self):
        result = client_info.build(self._make_multi_hotel_context())
        assert result["client_names"] == ["Ana", "Raj"]

    def test_one_row_per_hotel(self):
        result = client_info.build(self._make_multi_hotel_context())
        assert len(result["trip_summary"]) == 2

    def test_hotel_row_has_maps_link(self):
        result = client_info.build(self._make_multi_hotel_context())
        for row in result["trip_summary"]:
            assert row["hotel_maps_link"].startswith("https://www.google.com/maps")

    def test_transport_summary_from_local_transport(self):
        result = client_info.build(self._make_multi_hotel_context())
        for row in result["trip_summary"]:
            assert "Public Transport" in row["transport"]

    def test_dietary_preferences_included(self):
        result = client_info.build(self._make_multi_hotel_context())
        assert "vegetarian" in result["dietary_preferences"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/aig/sections/test_sections.py::TestClientInfo -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/aig/sections/client_info.py`**

```python
from src.aig.context import AIGContext
from src.common.maps import maps_url


def build(context: AIGContext) -> dict:
    f = context.facts
    rows = []
    for hotel in f.hotels:
        dates = ""
        if hotel.check_in and hotel.check_out:
            dates = f"{hotel.check_in} – {hotel.check_out}"
        rows.append({
            "city": hotel.city,
            "dates": dates,
            "hotel": hotel.hotel_name,
            "hotel_maps_link": maps_url(hotel.hotel_name, hotel.city),
            "transport": f.local_transport or "As per itinerary",
        })
    dietary_parts = list(f.dietary_restrictions)
    if f.food_allergies:
        dietary_parts.append(f"Allergies: {', '.join(f.food_allergies)}")
    return {
        "client_names": f.client_names,
        "num_guests": f.num_guests,
        "departure_city": f.departure_city,
        "dietary_preferences": ", ".join(dietary_parts) if dietary_parts else None,
        "trip_summary": rows,
    }
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/aig/sections/test_sections.py::TestClientInfo -v
```
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aig/sections/client_info.py tests/aig/sections/test_sections.py
git commit -m "feat(aig): client information page section"
```

---

## Task 10: DOCX Assembler

**Files:**
- Create: `src/aig/assembler.py`
- Create: `tests/aig/test_assembler.py`

Reads all stored JSONs from `input/days/` and `input/sections/`, applies styles, writes the final DOCX in mandatory section order.

- [ ] **Step 1: Write failing tests**

```python
# tests/aig/test_assembler.py
import json
import pytest
from pathlib import Path
from docx import Document

from src.aig.assembler import assemble


def _write_fixture_days(tmp_path: Path):
    days_dir = tmp_path / "days"
    days_dir.mkdir()
    (days_dir / "day_01.json").write_text(json.dumps({
        "day_number": 1, "date": "2026-04-19", "title": "Arrival in Amsterdam",
        "overnight_city": "Amsterdam", "overnight_hotel": "Hotel V",
        "is_cruise_day": False,
        "activities": [{"name": "Check in", "vivid_description": "Cozy hotel.", "hours": None,
                        "entry_fee": None, "recommended_duration": None,
                        "source": "ai_estimated", "maps_url": "https://maps.google.com",
                        "travel_leg": {"from_location": "Airport", "mode": "taxi",
                                       "duration": "~30 min", "tip": None}}],
        "lunch": [], "dinner": [], "transport_note": None,
    }))


def _write_fixture_sections(tmp_path: Path):
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    (sections_dir / "cover.json").write_text(json.dumps(
        {"title": "Golden Canals", "subtitle": "Amsterdam 2026"}
    ))
    (sections_dir / "client_info.json").write_text(json.dumps({
        "client_names": ["Ana"], "num_guests": "2 adults",
        "departure_city": "Mumbai", "dietary_preferences": None,
        "trip_summary": [{"city": "Amsterdam", "dates": "Apr 19–22",
                          "hotel": "Hotel V", "hotel_maps_link": "https://maps.google.com",
                          "transport": "Public Transport"}],
    }))
    for section in ["must_try_dishes", "souvenir_guide", "getting_around",
                    "cultural_etiquette", "mobile_connectivity", "safety_contacts",
                    "health_vaccination", "packing_list", "thank_you"]:
        (sections_dir / f"{section}.json").write_text(json.dumps({"cities": []}))
    (sections_dir / "thank_you.json").write_text(json.dumps(
        {"text": "Thank you for choosing Bon Voyage by Marina."}
    ))


class TestAssemble:
    def test_creates_docx_file(self, tmp_path):
        _write_fixture_days(tmp_path)
        _write_fixture_sections(tmp_path)
        output = tmp_path / "guide.docx"
        assemble(tmp_path, output)
        assert output.exists()
        assert output.stat().st_size > 0

    def test_output_is_valid_docx(self, tmp_path):
        _write_fixture_days(tmp_path)
        _write_fixture_sections(tmp_path)
        output = tmp_path / "guide.docx"
        assemble(tmp_path, output)
        doc = Document(str(output))
        assert len(doc.paragraphs) > 0

    def test_cover_title_in_document(self, tmp_path):
        _write_fixture_days(tmp_path)
        _write_fixture_sections(tmp_path)
        output = tmp_path / "guide.docx"
        assemble(tmp_path, output)
        doc = Document(str(output))
        text = "\n".join(p.text for p in doc.paragraphs)
        assert "Golden Canals" in text

    def test_day_heading_in_document(self, tmp_path):
        _write_fixture_days(tmp_path)
        _write_fixture_sections(tmp_path)
        output = tmp_path / "guide.docx"
        assemble(tmp_path, output)
        doc = Document(str(output))
        text = "\n".join(p.text for p in doc.paragraphs)
        assert "Arrival in Amsterdam" in text

    def test_thank_you_page_last(self, tmp_path):
        _write_fixture_days(tmp_path)
        _write_fixture_sections(tmp_path)
        output = tmp_path / "guide.docx"
        assemble(tmp_path, output)
        doc = Document(str(output))
        texts = [p.text for p in doc.paragraphs if p.text.strip()]
        assert "Bon Voyage by Marina" in texts[-1]

    def test_missing_section_file_does_not_crash(self, tmp_path):
        _write_fixture_days(tmp_path)
        sections_dir = tmp_path / "sections"
        sections_dir.mkdir()
        # Only cover and thank_you — everything else missing
        (sections_dir / "cover.json").write_text(json.dumps({"title": "T", "subtitle": "S"}))
        (sections_dir / "thank_you.json").write_text(json.dumps({"text": "Thanks!"}))
        output = tmp_path / "guide.docx"
        assemble(tmp_path, output)  # must not raise
        assert output.exists()
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/aig/test_assembler.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.aig.assembler'`.

- [ ] **Step 3: Create `src/aig/assembler.py`**

```python
"""Assemble all section and day JSONs into a single DOCX."""

import json
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

from src.aig.styles import ensure_styles
from src.common.maps import maps_url as _maps_url


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _add(doc: Document, text: str, style: str, bold: bool = False) -> None:
    p = doc.add_paragraph(text, style=style)
    if bold:
        for run in p.runs:
            run.bold = True


def _add_page_break(doc: Document) -> None:
    doc.add_page_break()


def _render_cover(doc: Document, data: dict) -> None:
    _add(doc, data.get("title", "All Inclusive Guide"), "AIG Title")
    _add(doc, data.get("subtitle", ""), "AIG Subtitle")
    _add_page_break(doc)


def _render_client_info(doc: Document, data: dict) -> None:
    _add(doc, "Client Information", "AIG Section Heading")
    names = ", ".join(data.get("client_names", []))
    if names:
        _add(doc, f"Prepared for: {names}", "AIG Body")
    if data.get("num_guests"):
        _add(doc, f"Guests: {data['num_guests']}", "AIG Body")
    if data.get("departure_city"):
        _add(doc, f"Departing from: {data['departure_city']}", "AIG Body")
    if data.get("dietary_preferences"):
        _add(doc, f"Dietary preferences: {data['dietary_preferences']}", "AIG Body")
    doc.add_paragraph()
    for row in data.get("trip_summary", []):
        _add(doc, f"{row['city']}", "AIG Subsection")
        _add(doc, f"Dates: {row['dates']}", "AIG Detail")
        p = doc.add_paragraph(style="AIG Detail")
        run = p.add_run(row["hotel"])
        run.add_break()
        hotel_url_run = p.add_run(row["hotel_maps_link"])
        _add(doc, f"Transport: {row['transport']}", "AIG Detail")
    _add_page_break(doc)


def _render_day(doc: Document, data: dict) -> None:
    day_num = data.get("day_number", "?")
    date_str = data.get("date", "")
    title = data.get("title", "")
    heading = f"Day {day_num}"
    if date_str:
        heading += f": {date_str}"
    if title:
        heading += f" — {title}"
    _add(doc, heading, "AIG Day Heading")

    if data.get("is_cruise_day"):
        _add(doc, "🚢 At Sea — Enjoy onboard dining and activities.", "AIG Body")
    else:
        for act in data.get("activities", []):
            leg = act.get("travel_leg")
            if leg:
                leg_text = (
                    f"🚗 {leg['duration']} by {leg['mode']} from {leg['from_location']}"
                )
                if leg.get("tip"):
                    leg_text += f" — {leg['tip']}"
                _add(doc, leg_text, "AIG Detail")
            _add(doc, f"📍 {act['name']}", "AIG Subsection")
            if act.get("vivid_description"):
                _add(doc, act["vivid_description"], "AIG Body")
            details = []
            if act.get("hours"):
                details.append(f"⏰ {act['hours']}")
            if act.get("entry_fee"):
                details.append(f"💰 {act['entry_fee']}")
            if act.get("recommended_duration"):
                details.append(f"⏱ {act['recommended_duration']}")
            if details:
                _add(doc, "  ".join(details), "AIG Detail")
            source = act.get("source", "library")
            if source == "ai_estimated":
                _add(doc, "⚠ Hours/fees are AI-estimated — please verify before sending.", "AIG Note")

        if data.get("lunch"):
            _add(doc, "🍽 Lunch Recommendations", "AIG Subsection")
            for r in data["lunch"]:
                _add(doc, r["name"], "AIG Restaurant Name")
                if r.get("must_try_dishes"):
                    _add(doc, f"🍴 Must try: {', '.join(r['must_try_dishes'])}", "AIG Detail")
                if r.get("hours"):
                    _add(doc, f"⏰ {r['hours']}", "AIG Detail")
                if r.get("travel_note"):
                    _add(doc, f"📍 {r['travel_note']}", "AIG Detail")

        if data.get("dinner"):
            _add(doc, "🍽 Dinner Recommendations", "AIG Subsection")
            for r in data["dinner"]:
                _add(doc, r["name"], "AIG Restaurant Name")
                if r.get("must_try_dishes"):
                    _add(doc, f"🍴 Must try: {', '.join(r['must_try_dishes'])}", "AIG Detail")
                if r.get("hours"):
                    _add(doc, f"⏰ {r['hours']}", "AIG Detail")

    overnight = data.get("overnight_city") or data.get("overnight_hotel")
    if overnight:
        _add(doc, f"✅ Overnight in {overnight}", "AIG Overnight")
    _add_page_break(doc)


def _render_list_section(doc: Document, heading: str, data: dict) -> None:
    if not data:
        return
    _add(doc, heading, "AIG Section Heading")
    for city_data in data.get("cities", []):
        _add(doc, city_data.get("city", ""), "AIG Subsection")
        items = (
            city_data.get("dishes")
            or city_data.get("items")
            or city_data.get("options")
            or city_data.get("phrases")
            or city_data.get("tips")
            or []
        )
        for item in items:
            text = item if isinstance(item, str) else str(item)
            _add(doc, f"• {text}", "AIG Bullet")
        if city_data.get("ai_generated"):
            _add(doc, "⚠ AI-generated — verify before sending.", "AIG Note")
    _add_page_break(doc)


def _render_packing_list(doc: Document, data: dict) -> None:
    if not data:
        return
    _add(doc, "🎒 Tailored Packing List", "AIG Section Heading")
    for item in data.get("items", []):
        _add(doc, f"• {item}", "AIG Bullet")
    _add_page_break(doc)


def _render_thank_you(doc: Document, data: dict) -> None:
    if not data:
        return
    _add(doc, "Thank You", "AIG Section Heading")
    _add(doc, data.get("text", ""), "AIG Body")


def assemble(input_dir: Path, output_path: Path) -> None:
    """Build DOCX from all stored JSONs in input_dir."""
    doc = Document()
    ensure_styles(doc)
    # Remove default empty paragraph
    for p in list(doc.paragraphs):
        p._element.getparent().remove(p._element)

    sec_dir = input_dir / "sections"
    days_dir = input_dir / "days"

    _render_cover(doc, _load(sec_dir / "cover.json"))
    _render_client_info(doc, _load(sec_dir / "client_info.json"))

    # Days in order
    if days_dir.exists():
        for day_file in sorted(days_dir.glob("day_*.json")):
            _render_day(doc, _load(day_file))

    _render_list_section(doc, "🏥 Important Places Around Your Stay",
                         _load(sec_dir / "important_places.json"))
    _render_list_section(doc, "🎁 Souvenir Shopping Guide",
                         _load(sec_dir / "souvenir_guide.json"))
    _render_list_section(doc, "🍽 Must-Try Local Dishes",
                         _load(sec_dir / "must_try_dishes.json"))
    _render_list_section(doc, "🚆 Getting Around",
                         _load(sec_dir / "getting_around.json"))
    _render_list_section(doc, "🌍 Cultural Etiquette & Local Phrases",
                         _load(sec_dir / "cultural_etiquette.json"))
    _render_packing_list(doc, _load(sec_dir / "packing_list.json"))
    _render_list_section(doc, "📱 Mobile Connectivity",
                         _load(sec_dir / "mobile_connectivity.json"))
    _render_list_section(doc, "🚨 Safety & Emergency Contacts",
                         _load(sec_dir / "safety_contacts.json"))
    _render_list_section(doc, "💉 Health & Vaccination Guidance",
                         _load(sec_dir / "health_vaccination.json"))
    _render_thank_you(doc, _load(sec_dir / "thank_you.json"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/aig/test_assembler.py -v
```
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aig/assembler.py tests/aig/test_assembler.py
git commit -m "feat(aig): DOCX assembler — renders all sections in mandatory order"
```

---

## Task 11: CLI Commands

**Files:**
- Modify: `src/aig/__main__.py`

Wires up the full pipeline into the CLI. No new tests — the CLI is the integration layer and is verified by running `python -m src.aig generate input/` manually.

- [ ] **Step 1: Replace the stub `generate` command and add remaining commands in `src/aig/__main__.py`**

Replace the existing `generate` command body (lines 338–340) and add the new commands:

```python
# Replace everything after the confirmed = typer.confirm line through end of generate():
    confirmed = typer.confirm("Proceed with generation?")
    if not confirmed:
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit(0)

    try:
        ai_client = get_ai_client(api_key=api_key)
    except ValueError:
        console.print("[red]AI API key required. Set AI_API_KEY in .env[/red]")
        raise typer.Exit(1)

    from .context import build_context
    from .day_builder import build_day
    from .assembler import assemble
    import src.aig.sections.client_info as _client_info
    import src.aig.sections.cover as _cover
    import src.aig.sections.must_try_dishes as _must_try
    import src.aig.sections.souvenir_guide as _souvenirs
    import src.aig.sections.getting_around as _getting_around
    import src.aig.sections.cultural_etiquette as _etiquette
    import src.aig.sections.mobile_connectivity as _connectivity
    import src.aig.sections.safety_contacts as _safety
    import src.aig.sections.health_vaccination as _health
    import src.aig.sections.packing_list as _packing
    import src.aig.sections.thank_you as _thank_you

    console.print(Rule("[dim]  BUILDING CONTEXT  [/dim]", style="dim"))
    ctx = build_context(facts, db_path, ai_client)
    console.print(f"  Library loaded for: {', '.join(ctx.library.keys()) or 'no cities matched'}")

    sections_dir = input_dir / "sections"
    sections_dir.mkdir(exist_ok=True)

    def save_section(name: str, data: dict) -> None:
        (sections_dir / f"{name}.json").write_text(
            __import__("json").dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    console.print(Rule("[dim]  GENERATING SECTIONS  [/dim]", style="dim"))
    save_section("cover", _cover.build(ctx)); console.print("  ✓ cover")
    save_section("client_info", _client_info.build(ctx)); console.print("  ✓ client_info")
    save_section("must_try_dishes", _must_try.build(ctx)); console.print("  ✓ must_try_dishes")
    save_section("souvenir_guide", _souvenirs.build(ctx)); console.print("  ✓ souvenir_guide")
    save_section("getting_around", _getting_around.build(ctx)); console.print("  ✓ getting_around")
    save_section("cultural_etiquette", _etiquette.build(ctx)); console.print("  ✓ cultural_etiquette")
    save_section("mobile_connectivity", _connectivity.build(ctx)); console.print("  ✓ mobile_connectivity")
    save_section("safety_contacts", _safety.build(ctx)); console.print("  ✓ safety_contacts")
    save_section("health_vaccination", _health.build(ctx)); console.print("  ✓ health_vaccination")
    save_section("packing_list", _packing.build(ctx)); console.print("  ✓ packing_list")
    save_section("thank_you", _thank_you.build(ctx)); console.print("  ✓ thank_you")

    console.print(Rule("[dim]  GENERATING DAYS  [/dim]", style="dim"))
    for day in facts.days:
        console.print(f"  Day {day.day_number}: {day.title or ''}")
        build_day(ctx, day.day_number, input_dir)
    console.print()

    if output is None:
        names = "_".join(facts.client_names[:1]) or "guide"
        output = input_dir / f"AIG_{names}.docx"

    console.print(Rule("[dim]  ASSEMBLING DOCX  [/dim]", style="dim"))
    assemble(input_dir, output)
    console.print(f"\n[green bold]✓ Guide saved →[/green bold] {output}")
```

Add these new commands after the `generate` function, before `def main()`:

```python
@app.command(name="redo-day")
def redo_day(
    input_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    day: int = typer.Option(..., "--day", "-d", help="Day number to regenerate"),
    note: Optional[str] = typer.Option(None, "--note", help="Override note e.g. 'use taxis today'"),
    db_path: Path = typer.Option(Path("library_db"), "--db"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    api_key: Optional[str] = typer.Option(None, "--api-key"),
):
    """Regenerate one day and reassemble the guide."""
    facts_path = input_dir / "trip_facts.json"
    if not facts_path.exists():
        console.print(f"[red]trip_facts.json not found in {input_dir}[/red]")
        raise typer.Exit(1)
    facts = TripFacts.model_validate_json(facts_path.read_text(encoding="utf-8"))
    try:
        ai_client = get_ai_client(api_key=api_key)
    except ValueError:
        console.print("[red]AI API key required.[/red]")
        raise typer.Exit(1)
    from .context import build_context
    from .day_builder import build_day
    from .assembler import assemble
    ctx = build_context(facts, db_path, ai_client)
    overrides = {"transport": note} if note else {}
    console.print(f"Regenerating Day {day}...")
    build_day(ctx, day, input_dir, overrides=overrides)
    if output is None:
        names = "_".join(facts.client_names[:1]) or "guide"
        output = input_dir / f"AIG_{names}.docx"
    assemble(input_dir, output)
    console.print(f"[green]✓ Day {day} regenerated → {output}[/green]")


@app.command(name="redo-section")
def redo_section(
    input_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    section: str = typer.Option(..., "--section", "-s",
                                help="Section name e.g. packing-list, cultural-etiquette"),
    db_path: Path = typer.Option(Path("library_db"), "--db"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    api_key: Optional[str] = typer.Option(None, "--api-key"),
):
    """Regenerate one supplementary section and reassemble."""
    _SECTION_MAP = {
        "cover": "cover", "client-info": "client_info",
        "must-try-dishes": "must_try_dishes", "souvenir-guide": "souvenir_guide",
        "getting-around": "getting_around", "cultural-etiquette": "cultural_etiquette",
        "mobile-connectivity": "mobile_connectivity", "safety-contacts": "safety_contacts",
        "health-vaccination": "health_vaccination", "packing-list": "packing_list",
        "thank-you": "thank_you",
    }
    if section not in _SECTION_MAP:
        console.print(f"[red]Unknown section '{section}'. Options: {', '.join(_SECTION_MAP)}[/red]")
        raise typer.Exit(1)
    facts = TripFacts.model_validate_json((input_dir / "trip_facts.json").read_text(encoding="utf-8"))
    try:
        ai_client = get_ai_client(api_key=api_key)
    except ValueError:
        console.print("[red]AI API key required.[/red]")
        raise typer.Exit(1)
    from .context import build_context
    from .assembler import assemble
    import importlib
    ctx = build_context(facts, db_path, ai_client)
    mod = importlib.import_module(f"src.aig.sections.{_SECTION_MAP[section]}")
    data = mod.build(ctx)
    sections_dir = input_dir / "sections"
    sections_dir.mkdir(exist_ok=True)
    import json as _json
    (sections_dir / f"{_SECTION_MAP[section]}.json").write_text(
        _json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if output is None:
        names = "_".join(facts.client_names[:1]) or "guide"
        output = input_dir / f"AIG_{names}.docx"
    assemble(input_dir, output)
    console.print(f"[green]✓ Section '{section}' regenerated → {output}[/green]")


@app.command()
def assemble_cmd(
    input_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
):
    """Re-render DOCX from existing day and section JSONs (no AI calls)."""
    from .assembler import assemble
    facts_path = input_dir / "trip_facts.json"
    facts = TripFacts.model_validate_json(facts_path.read_text(encoding="utf-8"))
    if output is None:
        names = "_".join(facts.client_names[:1]) or "guide"
        output = input_dir / f"AIG_{names}.docx"
    assemble(input_dir, output)
    console.print(f"[green]✓ Assembled → {output}[/green]")


@app.command(name="build-styles")
def build_styles_cmd(
    output: Path = typer.Option(
        Path("AIG_style_sample.docx"), "--output", "-o",
        help="Path for sample DOCX showing all AIG styles"
    ),
):
    """Generate a sample DOCX demonstrating all AIG paragraph styles."""
    from docx import Document
    from .styles import ensure_styles, AIG_STYLES
    doc = Document()
    ensure_styles(doc)
    for name, *_ in AIG_STYLES:
        doc.add_paragraph(f"Sample text in style: {name}", style=name)
    doc.save(str(output))
    console.print(f"[green]✓ Style sample saved → {output}[/green]")
```

Also add `import json as __import__` is incorrect — fix the save_section lambda to use `import json` at the top of the file. Add to the imports at the top of `__main__.py`:

```python
import json
```

And simplify `save_section`:

```python
    def save_section(name: str, data: dict) -> None:
        (sections_dir / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
```

- [ ] **Step 2: Run full test suite to verify nothing broke**

```bash
python -m pytest tests/aig/ -v
```
Expected: all tests PASS (39 existing + new ones from this plan).

- [ ] **Step 3: Smoke-test the CLI**

```bash
python -m src.aig --help
```
Expected: shows `parse`, `generate`, `redo-day`, `redo-section`, `assemble`, `build-styles` commands.

```bash
python -m src.aig build-styles
```
Expected: `✓ Style sample saved → AIG_style_sample.docx`

- [ ] **Step 4: Commit**

```bash
git add src/aig/__main__.py
git commit -m "feat(aig): full CLI — generate, redo-day, redo-section, assemble, build-styles"
```

---

## Self-Review Checklist

**Spec coverage check:**
- ✅ AIGContext with CityLibraryData — Task 1
- ✅ DOCX styles — Task 2
- ✅ Activity order preservation — Task 3 + 5 (test: `test_activity_order_preserved`)
- ✅ Travel chain from hotel, resets on return — Task 3 (`_compute_chain`)
- ✅ AI vivid descriptions + travel times — Task 4
- ✅ Restaurant selection: proximity, dietary filter, rotation — Task 5
- ✅ Cruise/At Sea day handling — Task 3 + 5
- ✅ Library-backed sections — Task 6
- ✅ Library + AI fallback + write-back — Task 7 (`write_back_to_library`)
- ✅ AI-only sections — Task 8
- ✅ Client info page — Task 9
- ✅ DOCX assembly in mandatory section order — Task 10
- ✅ Per-day regeneration with override — Task 11 (`redo-day --note`)
- ✅ Per-section regeneration — Task 11 (`redo-section`)
- ✅ AI-estimated marker for unverified facts — Task 10 (assembler renders `AIG Note` style)
- ✅ `write_back_to_library` audit entry format — Task 1

**Not covered in this plan (Plan 2):**
- Google Places Important Places section (pharmacy/grocery/hospital with radius expansion)
- Library verification with `--verify` flag
- Hotel geocoding for `hotel_coords`

The `important_places` section will render empty/placeholder from Plan 1 since `input/sections/important_places.json` won't exist. The assembler handles missing section files gracefully (tested in `test_missing_section_file_does_not_crash`).
