# AIG Trip Facts Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse all documents in the `input/` folder using AI (one call per file, then one merge call), save consolidated facts to `trip_facts.json`, and update the `parse`/`generate` CLI commands to use it.

**Architecture:** New `FolderParser` class in `src/aig/folder_parser.py` handles file scanning, per-file AI extraction, and AI merge. New `TripFacts` + supporting Pydantic models in `src/common/models.py`. The `parse` command branches on dir vs. file — dirs use `FolderParser`, single files use the existing parser unchanged. The `generate` command reads `trip_facts.json` if present; aborts if not.

**Tech Stack:** Python 3.11+, pdfplumber (already in requirements), python-docx (already in requirements), Pydantic v2, pytest, unittest.mock

---

## File Structure

```
src/common/models.py         — (modify) Add TripFacts, TripDay, TripHotel, TransportLeg
src/aig/folder_parser.py     — (create) FolderParser class
src/aig/__main__.py          — (modify) Branch parse on dir/file; update generate
tests/aig/__init__.py        — (create) empty
tests/aig/test_trip_facts.py — (create) TripFacts model tests
tests/aig/test_folder_parser.py — (create) FolderParser unit tests
```

---

## Task 1: TripFacts models + test infrastructure

**Files:**
- Modify: `requirements.txt`
- Modify: `src/common/models.py`
- Create: `tests/aig/__init__.py`
- Create: `tests/aig/test_trip_facts.py`

- [ ] **Step 1: Add pytest to requirements.txt**

Append after the existing entries:
```
# Testing
pytest>=8.0.0
```

- [ ] **Step 2: Install pytest**

Run: `pip install pytest>=8.0.0`
Expected: Successfully installed (or already satisfied)

- [ ] **Step 3: Create tests/aig/__init__.py**

```python
```
(empty file)

- [ ] **Step 4: Write failing tests for TripFacts models**

Create `tests/aig/test_trip_facts.py`:
```python
import json
import pytest
from src.common.models import TripFacts, TripDay, TripHotel, TransportLeg


class TestTripFacts:
    def test_json_roundtrip_full(self):
        facts = TripFacts(
            client_names=["Divya", "Rahul"],
            num_guests="2 adults",
            departure_city="Mumbai",
            destinations=["Amsterdam", "Florence"],
            trip_start_date="2025-04-19",
            trip_end_date="2025-05-05",
            hotels=[TripHotel(city="Amsterdam", hotel_name="Marriott Amsterdam",
                              check_in="2025-04-19", check_out="2025-04-23")],
            transport_modes=[TransportLeg(from_city="Amsterdam", to_city="Florence",
                                          mode="flight", date="2025-04-23")],
            days=[TripDay(day_number=1, date="2025-04-19", title="Arrival",
                          overnight_city="Amsterdam", overnight_hotel="Marriott Amsterdam",
                          activities=["Check-in", "Canal walk"])],
            dietary_restrictions=["vegetarian"],
            food_allergies=[],
            cuisine_preferences=["local"],
        )
        data = json.loads(facts.model_dump_json())
        restored = TripFacts.model_validate(data)
        assert restored.client_names == ["Divya", "Rahul"]
        assert restored.hotels[0].hotel_name == "Marriott Amsterdam"
        assert restored.days[0].activities == ["Check-in", "Canal walk"]
        assert restored.transport_modes[0].from_city == "Amsterdam"

    def test_num_guests_is_string(self):
        facts = TripFacts(num_guests="2 adults, 2 kids (ages 10, 8)")
        assert isinstance(facts.num_guests, str)
        assert "kids" in facts.num_guests

    def test_num_guests_nullable(self):
        facts = TripFacts()
        assert facts.num_guests is None

    def test_missing_required_all_empty(self):
        missing = TripFacts().missing_required()
        assert "client_names" in missing
        assert "destinations" in missing
        assert "trip_start_date" in missing
        assert "trip_end_date" in missing
        assert "days" in missing
        assert "hotels" in missing

    def test_missing_required_all_present(self):
        facts = TripFacts(
            client_names=["Ana"],
            destinations=["Paris"],
            trip_start_date="2025-06-01",
            trip_end_date="2025-06-07",
            days=[TripDay(day_number=1, activities=[])],
            hotels=[TripHotel(city="Paris", hotel_name="Hotel de Ville")],
        )
        assert facts.missing_required() == []

    def test_missing_required_optional_fields_not_included(self):
        facts = TripFacts(
            client_names=["Ana"],
            destinations=["Paris"],
            trip_start_date="2025-06-01",
            trip_end_date="2025-06-07",
            days=[TripDay(day_number=1, activities=[])],
            hotels=[TripHotel(city="Paris", hotel_name="Hotel de Ville")],
        )
        missing = facts.missing_required()
        assert "num_guests" not in missing
        assert "departure_city" not in missing
        assert "dietary_restrictions" not in missing

    def test_is_ready_for_generation_false_when_empty(self):
        assert TripFacts().is_ready_for_generation() is False

    def test_is_ready_for_generation_true_when_complete(self):
        facts = TripFacts(
            client_names=["Ana"],
            destinations=["Paris"],
            trip_start_date="2025-06-01",
            trip_end_date="2025-06-07",
            days=[TripDay(day_number=1, activities=[])],
            hotels=[TripHotel(city="Paris", hotel_name="Hotel de Ville")],
        )
        assert facts.is_ready_for_generation() is True
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pytest tests/aig/test_trip_facts.py -v`
Expected: Multiple errors — `TripFacts`, `TripDay`, `TripHotel`, `TransportLeg` not found in models.py

- [ ] **Step 6: Add TripFacts models to src/common/models.py**

Append to the bottom of `src/common/models.py` (after the existing `AIGDocument` class):
```python

class TripDay(BaseModel):
    """One day in the trip, for human-editable trip_facts.json."""
    day_number: int
    date: Optional[str] = None           # ISO YYYY-MM-DD
    title: Optional[str] = None
    overnight_city: Optional[str] = None
    overnight_hotel: Optional[str] = None
    activities: list[str] = Field(default_factory=list)


class TripHotel(BaseModel):
    """A hotel stay, for human-editable trip_facts.json."""
    city: str
    hotel_name: str
    check_in: Optional[str] = None       # ISO YYYY-MM-DD
    check_out: Optional[str] = None      # ISO YYYY-MM-DD


class TransportLeg(BaseModel):
    """One transport leg between destinations."""
    from_city: str
    to_city: str
    mode: str                            # flight, train, cruise, bus, car
    date: Optional[str] = None          # ISO YYYY-MM-DD


class TripFacts(BaseModel):
    """All facts needed to generate an AIG. Saved as trip_facts.json for user review."""
    client_names: list[str] = Field(default_factory=list)
    num_guests: Optional[str] = None    # free text e.g. "2 adults, 2 kids (10, 8)"
    departure_city: Optional[str] = None
    destinations: list[str] = Field(default_factory=list)
    trip_start_date: Optional[str] = None   # ISO YYYY-MM-DD
    trip_end_date: Optional[str] = None     # ISO YYYY-MM-DD
    hotels: list[TripHotel] = Field(default_factory=list)
    transport_modes: list[TransportLeg] = Field(default_factory=list)
    days: list[TripDay] = Field(default_factory=list)
    dietary_restrictions: list[str] = Field(default_factory=list)
    food_allergies: list[str] = Field(default_factory=list)
    cuisine_preferences: list[str] = Field(default_factory=list)

    def missing_required(self) -> list[str]:
        """Return names of required fields that are empty or null."""
        missing = []
        if not self.client_names:
            missing.append("client_names")
        if not self.destinations:
            missing.append("destinations")
        if not self.trip_start_date:
            missing.append("trip_start_date")
        if not self.trip_end_date:
            missing.append("trip_end_date")
        if not self.days:
            missing.append("days")
        if not self.hotels:
            missing.append("hotels")
        return missing

    def is_ready_for_generation(self) -> bool:
        return len(self.missing_required()) == 0
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/aig/test_trip_facts.py -v`
Expected: All 8 tests PASS

- [ ] **Step 8: Commit**

```bash
git add requirements.txt src/common/models.py tests/aig/__init__.py tests/aig/test_trip_facts.py
git commit -m "feat(aig): add TripFacts pydantic models and tests"
```

---

## Task 2: FolderParser — file scanning and text extraction

**Files:**
- Create: `src/aig/folder_parser.py`
- Modify: `tests/aig/test_folder_parser.py` (create with first set of tests)

- [ ] **Step 1: Write failing tests for _find_files and _extract_text**

Create `tests/aig/test_folder_parser.py`:
```python
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from docx import Document

from src.aig.folder_parser import FolderParser
from src.common.models import TripFacts


MINIMAL_FACTS_DICT = {
    "client_names": ["Ana"],
    "num_guests": "2 adults",
    "departure_city": "Mumbai",
    "destinations": ["Paris"],
    "trip_start_date": "2025-06-01",
    "trip_end_date": "2025-06-07",
    "hotels": [{"city": "Paris", "hotel_name": "Hotel Paris",
                "check_in": "2025-06-01", "check_out": "2025-06-07"}],
    "transport_modes": [{"from_city": "Mumbai", "to_city": "Paris",
                         "mode": "flight", "date": "2025-06-01"}],
    "days": [{"day_number": 1, "date": "2025-06-01", "title": "Arrival",
              "overnight_city": "Paris", "overnight_hotel": "Hotel Paris",
              "activities": ["Check-in"]}],
    "dietary_restrictions": [],
    "food_allergies": [],
    "cuisine_preferences": [],
}


@pytest.fixture
def mock_ai():
    client = MagicMock()
    client.complete.return_value = json.dumps(MINIMAL_FACTS_DICT)
    return client


@pytest.fixture
def parser(mock_ai):
    return FolderParser(ai_client=mock_ai)


class TestFindFiles:
    def test_finds_pdf_and_docx(self, tmp_path, parser):
        (tmp_path / "itinerary.pdf").write_bytes(b"fake")
        (tmp_path / "hotel.docx").write_bytes(b"fake")
        (tmp_path / "notes.txt").write_text("ignore")
        names = {f.name for f in parser._find_files(tmp_path)}
        assert "itinerary.pdf" in names
        assert "hotel.docx" in names
        assert "notes.txt" not in names

    def test_returns_sorted_by_name(self, tmp_path, parser):
        (tmp_path / "z_last.pdf").write_bytes(b"fake")
        (tmp_path / "a_first.pdf").write_bytes(b"fake")
        files = parser._find_files(tmp_path)
        assert files[0].name == "a_first.pdf"
        assert files[1].name == "z_last.pdf"

    def test_empty_folder_returns_empty_list(self, tmp_path, parser):
        assert parser._find_files(tmp_path) == []


class TestExtractText:
    def test_extract_docx_text(self, tmp_path, parser):
        doc = Document()
        doc.add_paragraph("Hello Amsterdam")
        doc.add_paragraph("Day 1: Arrival")
        path = tmp_path / "trip.docx"
        doc.save(str(path))
        text = parser._extract_text(path)
        assert text is not None
        assert "Hello Amsterdam" in text
        assert "Day 1: Arrival" in text

    def test_returns_none_on_corrupt_pdf(self, tmp_path, parser):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"not a real pdf")
        assert parser._extract_text(bad) is None

    def test_returns_none_on_nonexistent_file(self, tmp_path, parser):
        assert parser._extract_text(tmp_path / "ghost.pdf") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/aig/test_folder_parser.py -v`
Expected: `ImportError` — `folder_parser` module does not exist yet

- [ ] **Step 3: Create src/aig/folder_parser.py with file scanning and text extraction only**

Note: AI extraction methods are added in Task 3 after tests are written first.

```python
"""Parse all documents in an input folder and extract trip facts via AI."""

from pathlib import Path
from typing import Optional

import pdfplumber
from docx import Document as DocxDocument

from src.common.ai_provider import get_ai_client


class FolderParser:
    """Parses all documents in a folder and returns consolidated TripFacts."""

    SUPPORTED_EXTENSIONS = {".pdf", ".docx"}

    def __init__(self, ai_client=None):
        self._ai = ai_client if ai_client is not None else get_ai_client()

    def _find_files(self, folder: Path) -> list[Path]:
        files: list[Path] = []
        for ext in self.SUPPORTED_EXTENSIONS:
            files.extend(folder.glob(f"*{ext}"))
        return sorted(files)

    def _extract_text(self, file: Path) -> Optional[str]:
        try:
            if file.suffix.lower() == ".pdf":
                return self._extract_pdf_text(file)
            if file.suffix.lower() == ".docx":
                return self._extract_docx_text(file)
        except Exception:
            pass
        return None

    def _extract_pdf_text(self, file: Path) -> str:
        with pdfplumber.open(file) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)

    def _extract_docx_text(self, file: Path) -> str:
        doc = DocxDocument(str(file))
        return "\n".join(p.text for p in doc.paragraphs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/aig/test_folder_parser.py::TestFindFiles tests/aig/test_folder_parser.py::TestExtractText -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/aig/folder_parser.py tests/aig/test_folder_parser.py
git commit -m "feat(aig): add FolderParser with file scanning and text extraction"
```

---

## Task 3: FolderParser — AI extraction, merge, and parse()

**Files:**
- Modify: `src/aig/folder_parser.py` (add AI methods)
- Modify: `tests/aig/test_folder_parser.py` (add new test classes)

- [ ] **Step 1: Add failing tests for AI extraction, merge, and parse()**

Append to `tests/aig/test_folder_parser.py`:
```python

class TestExtractFactsFromFile:
    def test_returns_parsed_dict(self, parser, mock_ai):
        result = parser._extract_facts_from_file("some travel text", "itinerary.pdf")
        assert result["client_names"] == ["Ana"]
        assert result["destinations"] == ["Paris"]
        mock_ai.complete.assert_called_once()

    def test_handles_json_with_code_fences(self, parser, mock_ai):
        mock_ai.complete.return_value = f"```json\n{json.dumps(MINIMAL_FACTS_DICT)}\n```"
        result = parser._extract_facts_from_file("text", "file.pdf")
        assert result["client_names"] == ["Ana"]

    def test_returns_empty_dict_on_bad_json(self, parser, mock_ai):
        mock_ai.complete.return_value = "not valid json at all {{{"
        result = parser._extract_facts_from_file("text", "file.pdf")
        assert result == {}

    def test_truncates_long_text_to_40000_chars(self, parser, mock_ai):
        long_text = "x" * 100_000
        parser._extract_facts_from_file(long_text, "big.pdf")
        prompt_used = mock_ai.complete.call_args[0][0]
        assert len(prompt_used) < 90_000  # text was truncated


class TestMergeFacts:
    def test_returns_trip_facts_instance(self, parser, mock_ai):
        partials = [
            ("itinerary.pdf", MINIMAL_FACTS_DICT),
            ("flight.pdf", {"client_names": [], "num_guests": None, "departure_city": "Mumbai",
                            "destinations": [], "trip_start_date": None, "trip_end_date": None,
                            "hotels": [], "transport_modes": [], "days": [],
                            "dietary_restrictions": [], "food_allergies": [], "cuisine_preferences": []}),
        ]
        result = parser._merge_facts(partials)
        assert isinstance(result, TripFacts)
        mock_ai.complete.assert_called_once()

    def test_merge_prompt_includes_all_filenames(self, parser, mock_ai):
        partials = [("a.pdf", MINIMAL_FACTS_DICT), ("b.pdf", MINIMAL_FACTS_DICT)]
        parser._merge_facts(partials)
        prompt = mock_ai.complete.call_args[0][0]
        assert "a.pdf" in prompt
        assert "b.pdf" in prompt


class TestParse:
    def test_empty_folder_returns_empty_facts(self, tmp_path, mock_ai):
        p = FolderParser(ai_client=mock_ai)
        facts, warnings = p.parse(tmp_path)
        assert isinstance(facts, TripFacts)
        assert facts.client_names == []
        assert warnings == []
        mock_ai.complete.assert_not_called()

    def test_single_file_extracts_without_merge(self, tmp_path, mock_ai):
        doc = Document()
        doc.add_paragraph("Trip content")
        doc.save(str(tmp_path / "itinerary.docx"))
        p = FolderParser(ai_client=mock_ai)
        facts, warnings = p.parse(tmp_path)
        assert isinstance(facts, TripFacts)
        assert warnings == []
        assert mock_ai.complete.call_count == 1  # extract only, no merge

    def test_multiple_files_calls_merge(self, tmp_path, mock_ai):
        for name in ("a.docx", "b.docx"):
            doc = Document()
            doc.add_paragraph("content")
            doc.save(str(tmp_path / name))
        p = FolderParser(ai_client=mock_ai)
        p.parse(tmp_path)
        assert mock_ai.complete.call_count == 3  # 2 extractions + 1 merge

    def test_unreadable_file_added_to_warnings(self, tmp_path, mock_ai):
        (tmp_path / "bad.pdf").write_bytes(b"not a pdf")
        doc = Document()
        doc.add_paragraph("Good content")
        doc.save(str(tmp_path / "good.docx"))
        p = FolderParser(ai_client=mock_ai)
        facts, warnings = p.parse(tmp_path)
        assert "bad.pdf" in warnings
        assert mock_ai.complete.call_count == 1  # only good.docx extracted

    def test_all_files_unreadable_returns_empty_facts(self, tmp_path, mock_ai):
        (tmp_path / "bad.pdf").write_bytes(b"not a pdf")
        p = FolderParser(ai_client=mock_ai)
        facts, warnings = p.parse(tmp_path)
        assert facts.client_names == []
        assert "bad.pdf" in warnings
        mock_ai.complete.assert_not_called()
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `pytest tests/aig/test_folder_parser.py::TestExtractFactsFromFile tests/aig/test_folder_parser.py::TestMergeFacts tests/aig/test_folder_parser.py::TestParse -v`
Expected: `AttributeError` — `_extract_facts_from_file`, `_merge_facts`, `parse` not yet defined on `FolderParser`

- [ ] **Step 3: Add AI methods and prompts to src/aig/folder_parser.py**

Add the following imports at the top of `src/aig/folder_parser.py` (after existing imports):
```python
import json
import re

from src.common.models import TripFacts, TripDay, TripHotel, TransportLeg
```

Add the two prompt constants after the imports (before the `FolderParser` class):
```python
_EXTRACTION_PROMPT = """\
You are extracting travel facts from a travel document.

Read the document and return ONLY a JSON object with these exact fields:
{{
  "client_names": [],
  "num_guests": null,
  "departure_city": null,
  "destinations": [],
  "trip_start_date": null,
  "trip_end_date": null,
  "hotels": [],
  "transport_modes": [],
  "days": [],
  "dietary_restrictions": [],
  "food_allergies": [],
  "cuisine_preferences": []
}}

Field notes:
- client_names: list of traveller names
- num_guests: free-text string e.g. "2 adults" or "2 adults, 2 kids (ages 10, 8)" — null if not mentioned
- departure_city: home city they are travelling FROM — null if not mentioned
- destinations: ordered list of destination cities visited
- trip_start_date / trip_end_date: ISO YYYY-MM-DD (infer year from context; default to 2025 or 2026)
- hotels: list of {{"city": str, "hotel_name": str, "check_in": "YYYY-MM-DD"|null, "check_out": "YYYY-MM-DD"|null}}
- transport_modes: list of {{"from_city": str, "to_city": str, "mode": "flight"|"train"|"cruise"|"bus"|"car", "date": "YYYY-MM-DD"|null}}
- days: list of {{"day_number": int, "date": "YYYY-MM-DD"|null, "title": str|null, "overnight_city": str|null, "overnight_hotel": str|null, "activities": [str]}}
- activities: plain strings e.g. "Visit Anne Frank House", "Check in to hotel"
- dietary_restrictions: e.g. "vegetarian", "halal", "Jain", "no pork"
- food_allergies: e.g. "nuts", "shellfish", "gluten", "dairy"
- cuisine_preferences: e.g. "local cuisine", "seafood", "Italian"

Rules:
- Return null for any field you cannot find in the document
- Return [] for empty lists
- Do NOT guess — only return facts explicitly stated in the document
- Return only valid JSON with no markdown fences and no explanation

Document ({filename}):
{text}"""


_MERGE_PROMPT = """\
You are merging travel facts extracted from {n} travel documents into one final fact sheet.

Documents:
{file_list}

Extracted facts from each document:
{facts_json}

Merge into a single JSON object using this schema:
{{
  "client_names": [],
  "num_guests": null,
  "departure_city": null,
  "destinations": [],
  "trip_start_date": null,
  "trip_end_date": null,
  "hotels": [],
  "transport_modes": [],
  "days": [],
  "dietary_restrictions": [],
  "food_allergies": [],
  "cuisine_preferences": []
}}

Merge rules:
- For scalar conflicts, prefer facts from the file with the most days (that is the main itinerary)
- Deduplicate hotels and transport legs by meaning (e.g. "Marriott Amsterdam" == "Amsterdam Marriott")
- Combine dietary_restrictions, food_allergies, cuisine_preferences from all files (union, no duplicates)
- days must come from the file with the most complete day-by-day itinerary
- Return only valid JSON with no markdown fences and no explanation"""
```

Add the following methods inside the `FolderParser` class (after `_extract_docx_text`):
```python
    def parse(self, folder: Path) -> tuple[TripFacts, list[str]]:
        """
        Parse all supported files in folder.
        Returns (TripFacts, warnings) where warnings is a list of filenames
        that could not be read.
        """
        files = self._find_files(folder)
        warnings: list[str] = []
        partials: list[tuple[str, dict]] = []

        for file in files:
            text = self._extract_text(file)
            if text is None:
                warnings.append(file.name)
                continue
            raw = self._extract_facts_from_file(text, file.name)
            partials.append((file.name, raw))

        if not partials:
            return TripFacts(), warnings

        if len(partials) == 1:
            facts = self._dict_to_trip_facts(partials[0][1])
        else:
            facts = self._merge_facts(partials)

        return facts, warnings

    def _extract_facts_from_file(self, text: str, filename: str) -> dict:
        prompt = _EXTRACTION_PROMPT.format(filename=filename, text=text[:40000])
        response = self._ai.complete(prompt, max_tokens=4096, temperature=0.1)
        return self._parse_json_response(response)

    def _merge_facts(self, partials: list[tuple[str, dict]]) -> TripFacts:
        file_list = "\n".join(f"- {name}" for name, _ in partials)
        facts_json = json.dumps(
            {name: data for name, data in partials},
            indent=2,
            ensure_ascii=False,
        )
        prompt = _MERGE_PROMPT.format(
            n=len(partials),
            file_list=file_list,
            facts_json=facts_json,
        )
        response = self._ai.complete(prompt, max_tokens=4096, temperature=0.1)
        merged = self._parse_json_response(response)
        return self._dict_to_trip_facts(merged)

    def _parse_json_response(self, response: str) -> dict:
        text = response.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    def _dict_to_trip_facts(self, data: dict) -> TripFacts:
        hotels = [
            TripHotel(
                city=h.get("city", ""),
                hotel_name=h.get("hotel_name", ""),
                check_in=h.get("check_in"),
                check_out=h.get("check_out"),
            )
            for h in (data.get("hotels") or [])
            if isinstance(h, dict) and h.get("city") and h.get("hotel_name")
        ]
        transport = [
            TransportLeg(
                from_city=t.get("from_city", ""),
                to_city=t.get("to_city", ""),
                mode=t.get("mode", "flight"),
                date=t.get("date"),
            )
            for t in (data.get("transport_modes") or [])
            if isinstance(t, dict) and t.get("from_city") and t.get("to_city")
        ]
        days = [
            TripDay(
                day_number=d.get("day_number", i + 1),
                date=d.get("date"),
                title=d.get("title"),
                overnight_city=d.get("overnight_city"),
                overnight_hotel=d.get("overnight_hotel"),
                activities=[str(a) for a in (d.get("activities") or [])],
            )
            for i, d in enumerate(data.get("days") or [])
            if isinstance(d, dict)
        ]
        return TripFacts(
            client_names=[str(n) for n in (data.get("client_names") or []) if n],
            num_guests=data.get("num_guests") or None,
            departure_city=data.get("departure_city") or None,
            destinations=[str(d) for d in (data.get("destinations") or []) if d],
            trip_start_date=data.get("trip_start_date") or None,
            trip_end_date=data.get("trip_end_date") or None,
            hotels=hotels,
            transport_modes=transport,
            days=days,
            dietary_restrictions=[str(r) for r in (data.get("dietary_restrictions") or []) if r],
            food_allergies=[str(a) for a in (data.get("food_allergies") or []) if a],
            cuisine_preferences=[str(p) for p in (data.get("cuisine_preferences") or []) if p],
        )
```

- [ ] **Step 4: Run all folder_parser tests to confirm full suite passes**

Run: `pytest tests/aig/test_folder_parser.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/aig/folder_parser.py tests/aig/test_folder_parser.py
git commit -m "feat(aig): add FolderParser AI extraction, merge, and parse()"
```

---

## Task 4: Update parse command

**Files:**
- Modify: `src/aig/__main__.py`

- [ ] **Step 1: Replace src/aig/__main__.py with the updated version**

Replace the entire file with:
```python
"""CLI for AIG generation: parse inputs and generate guides."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule

from src.common.ai_provider import get_ai_client
from src.common.models import TripFacts
from .parser import parse_itinerary

app = typer.Typer(
    name="aig",
    help="Generate All Inclusive Guides from client itineraries",
)
console = Console()


@app.command()
def parse(
    input_dir: Path = typer.Argument(
        ...,
        help="Path to the input directory (multi-file) or a single itinerary PDF",
        exists=True,
    ),
    days: bool = typer.Option(
        False,
        "--days", "-d",
        help="Also print the day-by-day activity preview",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="AI API key (uses AI_API_KEY from .env if not set)",
    ),
):
    """Parse input files and show a found/missing summary.

    When given a directory, all PDF and DOCX files are parsed and facts are
    saved to trip_facts.json inside that directory.
    When given a single file, the existing single-file parser runs (unchanged).
    """
    if input_dir.is_dir():
        _parse_folder(input_dir, show_days=days, api_key=api_key)
    else:
        _parse_single_file(input_dir, show_days=days, api_key=api_key)


def _parse_folder(folder: Path, show_days: bool, api_key: Optional[str]) -> None:
    from .folder_parser import FolderParser

    try:
        ai_client = get_ai_client(api_key=api_key)
    except ValueError:
        console.print("[red]AI API key required for multi-file parsing. Set AI_API_KEY in .env[/red]")
        raise typer.Exit(1)

    supported = sorted(folder.glob("*.pdf")) + sorted(folder.glob("*.docx"))
    if not supported:
        console.print(f"[red]No PDF or DOCX files found in {folder}[/red]")
        raise typer.Exit(1)

    console.print()
    console.print(f"Scanning {folder}/ — {len(supported)} file(s) found")
    for f in supported:
        console.print(f"  [dim]✓ {f.name}[/dim]")
    console.print()

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Extracting facts with AI...", total=None)
        parser = FolderParser(ai_client=ai_client)
        facts, warnings = parser.parse(folder)
        progress.update(task, completed=True)

    for w in warnings:
        console.print(f"  [yellow]⚠ Could not extract text from {w} — skipped[/yellow]")

    _print_trip_facts_summary(facts)

    if show_days and facts.days:
        console.print(Rule("[dim]  ACTIVITIES  [/dim]", style="dim"))
        console.print()
        for day in facts.days:
            console.print(f"  [bold cyan]Day {day.day_number}[/bold cyan] [{day.date or ''}]: {day.title or ''}")
            for act in day.activities[:4]:
                console.print(f"    [dim]·[/dim] {act}")
            if len(day.activities) > 4:
                console.print(f"    [dim]... and {len(day.activities) - 4} more[/dim]")
            console.print()

    out_path = folder / "trip_facts.json"
    out_path.write_text(facts.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"\n[green]Saved →[/green] {out_path}")


def _print_trip_facts_summary(facts: TripFacts) -> None:
    console.print(Rule("[green bold]  FOUND  [/green bold]", style="green"))
    console.print()
    if facts.client_names:
        console.print(f"  [bold]{'client_names':<22}[/bold] {', '.join(facts.client_names)}")
    if facts.num_guests:
        console.print(f"  [bold]{'num_guests':<22}[/bold] {facts.num_guests}")
    if facts.departure_city:
        console.print(f"  [bold]{'departure_city':<22}[/bold] {facts.departure_city}")
    if facts.destinations:
        console.print(f"  [bold]{'destinations':<22}[/bold] {' → '.join(facts.destinations)}")
    if facts.trip_start_date:
        console.print(f"  [bold]{'trip_start_date':<22}[/bold] {facts.trip_start_date}")
    if facts.trip_end_date:
        console.print(f"  [bold]{'trip_end_date':<22}[/bold] {facts.trip_end_date}")
    if facts.days:
        console.print(f"  [bold]{'days':<22}[/bold] {len(facts.days)} days extracted")
    if facts.hotels:
        console.print(f"  [bold]{'hotels':<22}[/bold] {len(facts.hotels)} properties")
    if facts.transport_modes:
        console.print(f"  [bold]{'transport_modes':<22}[/bold] {len(facts.transport_modes)} legs")
    if facts.dietary_restrictions:
        console.print(f"  [bold]{'dietary_restrictions':<22}[/bold] {', '.join(facts.dietary_restrictions)}")
    if facts.food_allergies:
        console.print(f"  [bold]{'food_allergies':<22}[/bold] {', '.join(facts.food_allergies)}")
    if facts.cuisine_preferences:
        console.print(f"  [bold]{'cuisine_preferences':<22}[/bold] {', '.join(facts.cuisine_preferences)}")

    all_fields = [
        "client_names", "num_guests", "departure_city", "destinations",
        "trip_start_date", "trip_end_date", "days", "hotels",
        "transport_modes", "dietary_restrictions", "food_allergies", "cuisine_preferences",
    ]
    required = facts.missing_required()
    optional_missing = [
        f for f in all_fields
        if not getattr(facts, f) and f not in required
    ]

    if required or optional_missing:
        console.print()
        console.print(Rule("[yellow bold]  MISSING  [/yellow bold]", style="yellow"))
        console.print()
        for field in required:
            console.print(f"  [red]✗[/red]  [bold]{field:<26}[/bold] [red](required for generation)[/red]")
        for field in optional_missing:
            console.print(f"  [yellow]·[/yellow]  [bold]{field:<26}[/bold] [dim](optional — saved as null/[])[/dim]")
    console.print()


def _parse_single_file(file: Path, show_days: bool, api_key: Optional[str]) -> None:
    try:
        ai_client = get_ai_client(api_key=api_key)
    except ValueError:
        ai_client = None
        console.print("[dim]No AI API key — using regex parser[/dim]")

    itinerary = parse_itinerary(file, ai_client=ai_client)

    console.print()
    console.print(Panel.fit("[bold]PARSED ITINERARY SUMMARY[/bold]", border_style="blue"))
    console.print()

    console.print(Rule("[green bold]  FOUND IN ITINERARY  [/green bold]", style="green"))
    console.print()

    if itinerary.destinations:
        console.print(f"  [bold]{'Destinations':<20}[/bold] {', '.join(itinerary.destinations)}")
    elif itinerary.destination and itinerary.destination != "Unknown":
        console.print(f"  [bold]{'Destinations':<20}[/bold] {itinerary.destination}")

    if itinerary.trip_start_date and itinerary.trip_end_date:
        console.print(
            f"  [bold]{'Trip Dates':<20}[/bold] "
            f"{itinerary.trip_start_date} – {itinerary.trip_end_date} "
            f"({itinerary.duration_days} days)"
        )
    elif itinerary.duration_days:
        console.print(f"  [bold]{'Duration':<20}[/bold] {itinerary.duration_days} days")

    if itinerary.hotel_stays:
        console.print(f"  [bold]{'Hotels':<20}[/bold]")
        for stay in itinerary.hotel_stays:
            dates = ""
            if stay.check_in_date and stay.check_out_date:
                dates = f" ({stay.check_in_date} – {stay.check_out_date})"
            console.print(f"  {'':20}  [cyan]{stay.city}[/cyan]: {stay.hotel_name}{dates}")
    elif itinerary.hotel_name:
        console.print(f"  [bold]{'Hotel':<20}[/bold] {itinerary.hotel_name}")

    if itinerary.client_name:
        console.print(f"  [bold]{'Client Name':<20}[/bold] {itinerary.client_name}")
    if itinerary.num_guests:
        console.print(f"  [bold]{'Guests':<20}[/bold] {itinerary.num_guests}")
    if itinerary.dietary_preferences:
        console.print(f"  [bold]{'Dietary Prefs':<20}[/bold] {', '.join(itinerary.dietary_preferences)}")
    if itinerary.food_allergies:
        console.print(f"  [bold]{'Food Allergies':<20}[/bold] {', '.join(itinerary.food_allergies)}")
    if itinerary.cuisine_preferences:
        console.print(f"  [bold]{'Cuisine Prefs':<20}[/bold] {', '.join(itinerary.cuisine_preferences)}")
    if itinerary.budget_level:
        console.print(f"  [bold]{'Budget':<20}[/bold] {itinerary.budget_level}")
    if itinerary.special_occasions:
        console.print(f"  [bold]{'Special Occasions':<20}[/bold] {', '.join(itinerary.special_occasions)}")
    if itinerary.transport_mode:
        console.print(f"  [bold]{'Transport':<20}[/bold] {itinerary.transport_mode}")
    if itinerary.days:
        console.print(f"  [bold]{'Days Extracted':<20}[/bold] {len(itinerary.days)}")

    console.print()

    missing: list[tuple[str, str]] = []
    if not itinerary.client_name:
        missing.append(("Client name", "not found in PDF"))
    if not itinerary.num_guests:
        missing.append(("Number of guests", "not specified"))
    if not itinerary.food_allergies:
        missing.append(("Food allergies", "not specified"))
    if not itinerary.cuisine_preferences:
        missing.append(("Cuisine preferences", "not specified"))
    if not itinerary.budget_level:
        missing.append(("Budget level", "not specified"))
    if not itinerary.special_occasions:
        missing.append(("Special occasions", "not specified"))

    if missing:
        console.print(
            Rule(
                "[yellow bold]  MISSING[/yellow bold]  [dim](needed for full AIG generation)[/dim]",
                style="yellow",
            )
        )
        console.print()
        for field, reason in missing:
            console.print(f"  [yellow]x[/yellow]  [bold]{field:<22}[/bold] — {reason}")
        console.print()

    if itinerary.days:
        from rich.table import Table

        console.print(Rule("[bold]  OVERNIGHT BREAKDOWN  [/bold]", style="blue"))
        console.print()

        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("Day", style="bold cyan", no_wrap=True)
        table.add_column("Date", no_wrap=True)
        table.add_column("City", no_wrap=True)
        table.add_column("Hotel")

        for day in itinerary.days:
            date_str = day.date or ""
            city = day.overnight_city or "[dim]—[/dim]"
            hotel = day.overnight_hotel or "[dim]—[/dim]"
            if day.overnight_city == "Departure day":
                city = "[dim]Departure[/dim]"
                hotel = "[dim]no overnight[/dim]"
            elif day.overnight_city == "On Cruise":
                city = "[blue]On Cruise[/blue]"
                hotel = "[dim]—[/dim]"
            table.add_row(f"Day {day.day_number}", date_str, city, hotel)

        console.print(table)
        console.print()

    if show_days and itinerary.days:
        console.print(Rule("[dim]  ACTIVITIES  [/dim]", style="dim"))
        console.print()
        for day in itinerary.days:
            console.print(f"  [bold cyan]Day {day.day_number}[/bold cyan] [{day.date or ''}]: {day.title}")
            for act in day.activities[:4]:
                marker = "o" if act.is_optional else "."
                cost = " [dim](extra cost)[/dim]" if act.extra_cost else ""
                console.print(f"    [dim]{marker}[/dim] {act.name}{cost}")
            if len(day.activities) > 4:
                console.print(f"    [dim]... and {len(day.activities) - 4} more[/dim]")
            console.print()


@app.command()
def generate(
    input_dir: Path = typer.Argument(
        ...,
        help="Path to the input directory containing trip_facts.json",
        exists=True,
    ),
    db_path: Path = typer.Option(
        Path("library_db"),
        "--db",
        help="Path to the library database directory",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output file path (default: auto-generated)",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="API key (uses AI_API_KEY from .env if not set)",
    ),
):
    """Generate an All Inclusive Guide from trip_facts.json.

    Run 'parse <input_dir>' first to extract and save trip facts.
    """
    console.print(Panel.fit(
        "[bold blue]AIG Generator[/bold blue]\n"
        "[dim]Bon Voyage by Marina[/dim]",
        border_style="blue",
    ))

    if input_dir.is_file():
        console.print("[red]generate requires a directory, not a file.[/red]")
        raise typer.Exit(1)

    facts_path = input_dir / "trip_facts.json"
    if not facts_path.exists():
        console.print(
            f"[red]trip_facts.json not found in {input_dir}[/red]\n"
            f"Run [bold]python -m src.aig parse {input_dir}[/bold] first."
        )
        raise typer.Exit(1)

    facts = TripFacts.model_validate_json(facts_path.read_text(encoding="utf-8"))

    _print_trip_facts_summary(facts)

    missing = facts.missing_required()
    if missing:
        console.print(
            f"[red]Cannot generate: required fields are missing:[/red] {', '.join(missing)}\n"
            f"Edit [bold]{facts_path}[/bold] and fill them in."
        )
        raise typer.Exit(1)

    confirmed = typer.confirm("Proceed with generation?")
    if not confirmed:
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit(0)

    console.print("\n[yellow]Section generation not yet implemented.[/yellow]")
    console.print("[dim]Sections will be built incrementally in future sessions.[/dim]")


def main():
    app()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the full test suite to catch any regressions**

Run: `pytest tests/ -v`
Expected: All previously passing tests still pass

- [ ] **Step 3: Smoke-test the parse command with a single file (existing behaviour)**

Run: `python -m src.aig parse input/` (or whichever PDF exists in input/)
Expected: Should print the scanning header, then call AI, then show the found/missing summary, then print `Saved → input/trip_facts.json`

Note: This makes real AI calls and may take 1–2 minutes. You need a valid `.env` with `AI_API_KEY`.

- [ ] **Step 4: Verify trip_facts.json was written**

Run: `python -c "import json; d=json.load(open('input/trip_facts.json')); print(list(d.keys()))"`
Expected: `['client_names', 'num_guests', 'departure_city', 'destinations', 'trip_start_date', 'trip_end_date', 'hotels', 'transport_modes', 'days', 'dietary_restrictions', 'food_allergies', 'cuisine_preferences']`

- [ ] **Step 5: Commit**

```bash
git add src/aig/__main__.py
git commit -m "feat(aig): update parse command to scan input folder and save trip_facts.json"
```

---

## Task 5: Verify generate command and end-to-end smoke test

**Files:**
- No new files — manual verification only

- [ ] **Step 1: Test generate with no trip_facts.json**

Run:
```bash
mkdir /tmp/empty_input
python -m src.aig generate /tmp/empty_input
```
Expected: Error message `trip_facts.json not found` with instruction to run `parse` first. Exit code 1.

- [ ] **Step 2: Test generate with missing required fields**

Run:
```bash
echo '{"client_names":[],"num_guests":null,"departure_city":null,"destinations":[],"trip_start_date":null,"trip_end_date":null,"hotels":[],"transport_modes":[],"days":[],"dietary_restrictions":[],"food_allergies":[],"cuisine_preferences":[]}' > /tmp/empty_input/trip_facts.json
python -m src.aig generate /tmp/empty_input
```
Expected: Shows MISSING section in red listing all required fields. Exits with error.

- [ ] **Step 3: Test generate with valid trip_facts.json from parse**

Run: `python -m src.aig generate input/`
Expected: Shows found/missing summary, prompts `Proceed with generation?`, on `y` prints "Section generation not yet implemented."

- [ ] **Step 4: Inspect trip_facts.json for quality**

Open `input/trip_facts.json` and verify:
- `client_names` has the travellers' names
- `destinations` lists the cities in order
- `days` has day-by-day activities as plain strings
- `hotels` has city, hotel_name, check_in, check_out
- `transport_modes` has flight/cruise legs with from_city, to_city, mode, date
- `departure_city` is populated from flight ticket(s) if present
- Any missing optional fields are `null` or `[]` (not wrong values)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(aig): milestone 1 complete — multi-file extraction and trip_facts.json"
```

---

## Verification

After all tasks complete:

1. `pytest tests/ -v` — all tests pass (no regressions)
2. `python -m src.aig parse input/` — scans all files, prints found/missing summary, saves `input/trip_facts.json`
3. `input/trip_facts.json` — valid JSON with the correct 12-field schema, human-readable and editable
4. `python -m src.aig generate input/` — loads facts, validates required fields, prompts go/abort
5. `python -m src.aig parse input/Final\ Itinerary\ for\ AIG.pdf` — old single-file behaviour still works unchanged
