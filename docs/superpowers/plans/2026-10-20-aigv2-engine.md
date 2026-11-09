# AIG v2 Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local, command-line AIG v2 engine: intake template + attachments → pre-flight questions → verified, on-brand .docx AIG → independent QC (markers in doc, QC report, verification sheet), with regenerate and re-QC.

**Architecture:** New package `src/aigv2/`. Code decides every fact (library, Google Places/Routes, client inputs); LLMs only extract, rank pre-validated candidates, and write prose, and every AI-supplied fact carries a marker. A deterministic python-docx renderer guarantees identical format across days. A separate QC stage reads the rendered .docx (not builder internals), re-checks Google, and annotates findings. All run state lives in a `StorageBackend` (local now, S3 in Plan B).

**Scope split:** This is Plan A (engine + CLI). **Plan B** (separate, later) adds the web UI screens (upload, pre-flight form, runs list, regenerate checkboxes, re-QC upload), Lambda background execution with S3 checkpoints, and S3 storage wiring. Plan A must not depend on anything in Plan B.

**Tech Stack:** Python 3.14, pydantic v2, python-docx, openpyxl, requests, pymupdf, Pillow, typer, pytest. OpenAI-compatible API via existing `src/common/ai_provider.py`. Google Places API (New) + Routes API.

**Spec:** `docs/superpowers/specs/2026-10-19-aigv2-design.md` (decisions referenced as §N; §12c = past-AIG decisions). Background: `docs/aigv2/2026-10-19-discovery-notes.md`, `docs/aigv2/2026-10-20-past-aigs-findings.md`.

## Global Constraints

- **Accuracy of information is paramount.** One incorrect piece of information can ruin a client's day, cause financial distress for them and for our business, and hurt our reputation. When a fact cannot be verified, mark it for a human — never guess, never fill a gap with something plausible.
- **Cost visibility:** every run (start, build, regenerate, qc) prints its cost in the console, split into **AI** and **Google**, with a breakdown per AI step/model and per Google API (call counts × unit price), plus the total. The same breakdown is saved in the run's `cost.json`, and Plan B's UI must show it after every run.
- Models: `gpt-6-luna` for all steps except the QC sense check, which uses `gpt-6.1-sol`. **Never `gpt-6-sol` (6.0).** Per-step model is configuration (§11b). On luna output failing validation, retry once on `gpt-6.1-sol`.
- Env: `AI_MODEL=gpt-6.1-sol`, `AI_MODEL_FAST=gpt-6-luna`, existing `AI_API_KEY`, `AI_BASE_URL`, `GOOGLE_MAPS_API_KEY`.
- Budget: ≤ **$1** per first full run (build + one QC), AI + Google; every run writes a cost log (§11, §12b).
- **Never write to `library_db/`** or any library file (§3). Read-only.
- Restaurants **library only**; 3 per meal; fewer → one `⚠ ADD RESTAURANT – <Meal>, Day N, near <anchor>` marker per missing slot (§8.1).
- Diet: only restaurants **known to fit**; unknown = excluded. Vegetarian: `vegetarian_friendly`, vegetarian/vegan cuisine, **or any Indian cuisine** fits — unless the client asks for "pure veg", then only explicit pure-veg/vegetarian-only (§8.1).
- Indian restaurants: on international trips, at least one Indian restaurant per meal when an eligible one exists in the library (99% of clients are Indian) (§8.1).
- Domestic India trips: no embassy, SIM, currency or vaccines; emergency 112; prices INR only (§12c).
- Included meals → "Included in your package", no options, no gap markers (§12c).
- No theme-park strategy tips unless present in the inputs (§12c).
- Repeats: same restaurant ≤ **2 times per city**, never twice the same day (§8.1).
- Near: lunch ≤ **10 min walk** or ≤ **15 min** by trip transport; dinner ≤ **20 min** (§8.1). Walking legs only when ≤ **10 min** (§8.3).
- Prices: local currency + INR in brackets, INR rounded to nearest **₹50**, e.g. `€25 (~₹2,400)`; unknown → `⚠ PRICE UNKNOWN` (§8.1).
- Day header exactly `Day 1 – Thu, 29 Oct | Welcome to Istanbul` (§7.2).
- Markers: yellow highlight, prefixes `⚠ ADD RESTAURANT`, `⚠ VERIFY:`, `⚠ PRICE UNKNOWN`, `⚠ WRITE PERSONAL LETTER`, `⚠ CHECK:` (§7.4). QC fails while any remain.
- Output: A4 .docx, Google-Docs-safe (built-in Heading 1–3 for structure, real hyperlinks, tables for cards, no floating shapes/text boxes), American English, no emojis except the ⚠ marker glyph, file name `All Inclusive Guide - <Client> - <Destinations>.docx` (§7, §7.2).
- Maps links: `https://www.google.com/maps/search/?api=1&query=<name+city, spaces as +>&query_place_id=<id>` when a place ID is known; never any `utm_` parameter.
- Brand: navy `#0C1F3E`, royal `#2F5FA8`, gold `#C68A32`, slate `#41536E`, powder `#AEC7E7`, frost `#EEF4FB`, card border `#DCE6F2`, card fill `#FBFDFF`; headings Cormorant Garamond, body Georgia, labels Georgia small caps; footer "Your Vacation · Your Story · Your Way" left + page number right (§7.3, R4-16).
- Place cache refresh after **30 days**; cache never mixed with `library_db/` (§11).
- Images are not read; image-only uploads/content produce a "paste the text" question (§5).
- Planner commentary from notes never appears in the guide (§6.3).

## Review Focus

1. **A library restaurant name matching the wrong Google place** (chains, common names, other city) — must not be used; excluded and listed in the QC report. Test in Task 9.
2. **Late-night departures and date boundaries** (01:00 flight on the 15th) — pre-flight checkout question; weekday in every header computed from the date. Tests in Tasks 11 and 18.
3. **Doc after a Google Docs round-trip** (custom style names stripped, direct formatting kept) — re-QC still finds days, venues, links and markers. Test in Task 19.
4. **No Google hours and unparseable library hours** ("Confirm directly before visiting") — restaurant treated as hours-unknown: never shown as open; excluded from meal slots, not a crash. Test in Task 8.
5. **Itinerary days not matching the dates, or a night with no hotel** (Trip E's 5 Nov) — pre-flight question, never a crash or silent guess. Test in Task 11.

---

## File Structure

```
src/aigv2/
  __init__.py
  __main__.py            CLI (typer): template, preflight, generate, regenerate, qc
  config.py              Settings: step→model map, thresholds, slot windows, brand, paths
  models.py              Pydantic models shared by all stages
  llm.py                 StepLLM: per-step model, JSON+schema, sol fallback, cost log
  store.py               RunStore (per-run folder) + PlaceCache, on StorageBackend
  intake/
    template.py          Build + parse the intake .docx template
    attachments.py       Text from PDF/DOCX; image-only detection
    extract.py           luna extraction → TripPlan; validation
  library.py             Read-only library adapter: city aliases, country shards, diet filter
  google/
    places.py            Places API (New): text search, nearby search, match scoring
    routes.py            Routes API: route matrix → durations per mode
  hours.py               Opening-hours model, Google + library parsing, is_open_for()
  money.py               Price parsing, FX rate, local + INR formatting
  preflight.py           Code checklist → Questions; apply Answers
  planning/
    slots.py             Assign slots/times; lunch & dinner anchors
    travel.py            Legs + 10-minute walking rule
    meals.py             Candidate filtering, repeats, gaps, breakfast
    important_places.py  Pharmacies, groceries, hospital per stay
  writing/
    days.py              luna: day intro, descriptions, AI facts (marked)
    sections.py          Library-first section content, else AI + VERIFY
    title.py             Creative title
  render/
    theme.py             Styles, colors, fonts, page setup, header/footer
    blocks.py            Card tables, facts grid, pills, links, markers, slot headings
    document.py          Assemble cover → letter → title/TOC → days → sections → thank you
  assets/
    cover_a4.png         Rebuilt A4 cover (Task 17, user-approved)
    logo.png             From BVBMWebsite logo assets
    thank_you.txt        Trip D's Thank You text verbatim
  qc/
    reader.py            Parse any .docx (incl. Google Docs export) into DocModel
    rules.py             Code rule checks → Findings
    facts.py             Fresh Google re-checks → Findings
    llm_checks.py        luna prose-fact check; sol sense check
    annotate.py          Insert ⚠ CHECK markers into the .docx
    report.py            QC report (.md + .json), pass/fail
  verification.py        Verification sheet (.xlsx)
  pipeline.py            Stage orchestration, checkpoints, regenerate
tests/aigv2/             mirrors the package; fixtures/ holds a NYC trip
```

Run data root: `aigv2_data/` (gitignored): `runs/<run_id>/…`, `cache/places/<key>.json`, `cache/fx/<date>.json`.

---

### Task 1: Package scaffold, config and shared models

**Files:**
- Create: `src/aigv2/__init__.py`, `src/aigv2/config.py`, `src/aigv2/models.py`, `tests/aigv2/__init__.py`, `tests/aigv2/test_models.py`
- Modify: `.gitignore` (add `aigv2_data/`), `src/common/ai_provider.py:18-27` (add pricing rows), `requirements.txt` (add `Pillow>=10.0.0` if absent)

**Interfaces:**
- Produces (`config.py`): `Settings` (pydantic `BaseModel`) with `models: dict[str, str]` keyed by step names `extract, rank, write_days, write_sections, title, qc_prose, qc_sense`; `fallback_model: str = "gpt-6.1-sol"`; `walk_max_min=10`, `lunch_max_min=15`, `dinner_max_min=20`, `cache_days=30`, `inr_round=50`; `slot_windows: dict[str, tuple[str,str]]` = `morning 09:00–12:00`, `lunch 12:30–14:00`, `afternoon 14:00–17:30`, `evening 17:30–20:00`, `dinner 19:30–21:00`; `data_root: Path = Path("aigv2_data")`. `load_settings() -> Settings` reads `AI_MODEL_FAST` (default `gpt-6-luna`) for every step except `qc_sense` which reads `AI_MODEL` (default `gpt-6.1-sol`); env `AIGV2_MODEL_<STEP>` overrides one step.
- Produces (`models.py`), all pydantic v2:
  - `Traveller(adults:int, kids_ages:list[int], notes:str="")`
  - `Diet(restrictions:list[str], allergies:list[str], likes:list[str])` — empty restrictions+allergies = no restrictions
  - `HotelStay(city:str, hotel:str, check_in:date, check_out:date, source:Literal["voucher","notes","itinerary","answer"])`
  - `TransportLeg(kind:Literal["flight","train","bus","other"], from_place:str, to_place:str, depart:datetime|None, arrive:datetime|None, ref:str="", source:str)`
  - `Booking(name:str, day:date, time:str|None, source:str)`
  - `PlannedItem(name:str, kind:Literal["attraction","activity","meal_out","transfer","free_time"], city:str, time:str|None, slot_hint:Literal["morning","afternoon","evening","any"]="any", note:str="")`
  - `DayPlan(date:date, title:str, city:str, items:list[PlannedItem], meal_rules:list[str]=[])` — `meal_rules` holds itinerary phrases like `"dinner before Seine cruise"`, `"lunch at hotel"`, `"breakfast out"`
  - `OpenChoice(day:date|None, text:str, options:list[str])`
  - `TripPlan(client_names:list[str], travellers:Traveller, diet:Diet, travel_modes:list[Literal["taxi","public_transport","self_drive"]], hotels:list[HotelStay], transport:list[TransportLeg], bookings:list[Booking], days:list[DayPlan], open_choices:list[OpenChoice], vague_days:list[date], commentary_removed:list[str], budget:str="", occasion:str="", additional_notes:str="")`
  - `Question(id:str, kind:str, text:str, options:list[str]=[], day:date|None=None)` and `Answers = dict[str, str]`
  - `Place(query:str, place_id:str, name:str, address:str, lat:float, lng:float, status:Literal["OPERATIONAL","CLOSED_TEMPORARILY","CLOSED_PERMANENTLY","UNKNOWN"], hours:"WeeklyHours|None", website:str|None, phone:str|None, maps_url:str, fetched_at:datetime, match_ok:bool)`
  - `Marker(kind:Literal["ADD_RESTAURANT","VERIFY","PRICE_UNKNOWN","WRITE_LETTER","CHECK"], text:str)` with `render() -> str` producing `"⚠ ADD RESTAURANT – Lunch, Day 3, near Galata Tower"`, `"⚠ VERIFY: <text>"`, `"⚠ PRICE UNKNOWN"`, `"⚠ WRITE PERSONAL LETTER"`, `"⚠ CHECK: <text>"`
  - `Finding(rule:str, severity:Literal["error","warning"], message:str, anchor_text:str="", day:int|None=None)`

- **Real-trip amendments (Trip B/Trip C/Trip A review, 2026-10-20):** `travel_modes` also allows `"private_driver"` (rendered "By car"); `TransportLeg.kind` adds `"boat"`; `TransportLeg` adds `pax_label: str = ""` (e.g. `"3 Adults"`, `"2x Youth"`); `HotelStay` adds `check_in_time: time|None`, `check_out_time: time|None`; `Booking` adds `end_time: str|None`, `meeting_point: str = ""`, `duration: str = ""`, `instructions: list[str] = []` (e.g. "exchange voucher at ticket office", "bring headphones"), `timed: bool` (False = valid all day / open-dated), `pax_label: str = ""`, `included_in_package: bool = False`; `PlannedItem` adds `optional: bool = False`, `booking_ref: str|None`, `locality: str = ""` (e.g. `"Engelberg"` for a Titlis day trip from Lucerne); `Traveller` adds `child_counts: dict[str,int] = {}` (voucher CWB/CWOB/Infant).
- **Past-AIG amendments (2026-10-20):** `TripPlan.trip_scope: Literal["international","domestic"]` (domestic = every city in India); `HotelStay.kind: Literal["hotel","resort","cruise","sleeper_train","lodge"] = "hotel"` and `HotelStay.meal_plan: Literal["none","breakfast","half_board","full_board","all_inclusive"] = "none"`; `PlannedItem.includes_meal: list[Literal["breakfast","lunch","dinner"]] = []` (safari BBQ, package lunch); `PlannedItem.pickup_time: str|None`, `pickup_place: str = ""`; `Diet.pure_veg: bool = False`; `TransportLeg` adds `operator: str = ""`, `number: str = ""`, `seat: str = ""`, `platform: str = ""` (only from tickets); new `Stop(name, minutes_from_prev, suggested_stop_min, km_from_prev)` and `DayPlan.drive_stops: list[Stop] = []`; `Settings.country_meal_windows: dict[str, dict[str, tuple[str,str]]]` = `{"Spain": {"lunch": ("13:30","16:00"), "dinner": ("20:30","22:30")}, "Greece": {"dinner": ("20:00","22:30")}}`; train "reach station by" = departure − 40 min.
- [ ] **Step 1: Write failing tests** `tests/aigv2/test_models.py`:
  - `test_settings_defaults`: with env cleared, `load_settings().models["write_days"] == "gpt-6-luna"` and `.models["qc_sense"] == "gpt-6.1-sol"`, `.walk_max_min == 10`.
  - `test_settings_step_override`: `AIGV2_MODEL_WRITE_DAYS=gpt-6.1-sol` → `models["write_days"] == "gpt-6.1-sol"`.
  - `test_marker_render`: `Marker(kind="ADD_RESTAURANT", text="Lunch, Day 3, near Galata Tower").render() == "⚠ ADD RESTAURANT – Lunch, Day 3, near Galata Tower"`; `Marker(kind="PRICE_UNKNOWN", text="").render() == "⚠ PRICE UNKNOWN"`.
  - `test_pricing_known`: `_lookup_pricing("gpt-6.1-sol") == (2.0, 10.0)` and `_lookup_pricing("gpt-6-luna") == (0.10, 0.50)`.
- [ ] **Step 2: Run** `pytest tests/aigv2/test_models.py -v` → FAIL (module not found).
- [ ] **Step 3: Implement** config, models, pricing rows `("gpt-6.1-sol", 2.00, 10.00)`, `("gpt-6-luna", 0.10, 0.50)` placed **before** any shorter overlapping prefix; `.gitignore` entry; Pillow requirement.
- [ ] **Step 4: Run** `pytest tests/aigv2/test_models.py -v` → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): scaffold package, settings and shared models`.

---

### Task 2: StepLLM — per-step model, JSON validation, sol fallback, cost log

**Files:** Create `src/aigv2/llm.py`, `tests/aigv2/test_llm.py`

**Interfaces:**
- Consumes: `Settings` (Task 1), `AIClient` (`src/common/ai_provider.py`).
- Produces: `class StepLLM(settings: Settings, client_factory: Callable[[str], AIClient] = <AIClient(model=m)>)`, method `run_json(step: str, system: str, prompt: str, schema: type[BaseModel], validate: Callable[[BaseModel], list[str]] | None = None, max_tokens: int = 8000) -> BaseModel`; property `cost_log -> list[dict]` (one entry per call: `step, model, prompt_tokens, completion_tokens, usd, fallback:bool`); `total_usd() -> float`.
- Behavior: call the step's model via a JSON completion that sends `max_completion_tokens` (GPT-6 rejects `max_tokens` — add `AIClient.complete_json(..., token_param="max_completion_tokens")` support or call `_client` directly inside `llm.py`); parse with `schema.model_validate_json`; if parse fails **or** `validate(obj)` returns non-empty problems, retry once with `settings.fallback_model`, appending the problems to the prompt; second failure raises `LLMStepError(step, problems)`.

- [ ] **Step 1: Write failing tests** using a fake client factory returning canned strings:
  - `test_valid_luna_output_no_fallback`: luna returns valid JSON → returned object, one log entry, `fallback is False`, `model == "gpt-6-luna"`.
  - `test_invalid_json_falls_back_to_sol`: luna returns `"not json"`, sol returns valid → object returned; log has 2 entries, second `model == "gpt-6.1-sol"`, `fallback is True`.
  - `test_validator_problems_trigger_fallback`: valid JSON but `validate` returns `["day 9 outside trip dates"]` → sol prompt contains `"day 9 outside trip dates"`.
  - `test_double_failure_raises`: both invalid → `LLMStepError`.
  - `test_cost_uses_pricing`: 1,000,000 prompt tokens on luna → `usd == 0.10`.
- [ ] **Step 2: Run** `pytest tests/aigv2/test_llm.py -v` → FAIL.
- [ ] **Step 3: Implement** `StepLLM`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add StepLLM with sol fallback and cost log`.

---

### Task 3: RunStore and PlaceCache

**Files:** Create `src/aigv2/store.py`, `tests/aigv2/test_store.py`

**Interfaces:**
- Consumes: `StorageBackend`, `LocalStorageBackend` (`src/library/ui/storage.py`), `Place` (Task 1).
- Produces:
  - `RunStore(backend: StorageBackend, run_id: str)`; `RunStore.create(backend) -> RunStore` (run_id = `YYYYMMDD-HHMMSS-<6 hex>`); `save_json(name: str, data: dict|BaseModel)`, `load_json(name) -> dict|None`, `save_bytes(name, data: bytes)`, `load_bytes(name) -> bytes|None`, `has(name) -> bool`, `list_runs(backend) -> list[str]` (newest first). Keys: `runs/<run_id>/<name>`.
  - `PlaceCache(backend, max_age_days: int)`; `get(key: str) -> Place|None` (None if missing or older than `max_age_days`); `put(key: str, place: Place)`. Keys `cache/places/<sha1(key)>.json`.
  - `default_backend(settings) -> StorageBackend` = `LocalStorageBackend(settings.data_root)`.

- [ ] **Step 1: Write failing tests** with `tmp_path`:
  - `test_run_roundtrip`: save/load json and bytes under a created run; `list_runs` returns it.
  - `test_cache_fresh_and_stale`: put a `Place` with `fetched_at` = now−10 days → `get` returns it; with now−31 days → `None`.
  - `test_cache_never_touches_library`: after operations, no file under `tmp_path` matches `library_db`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add run store and place cache`.

---

### Task 4: Intake template — build and parse

**Files:** Create `src/aigv2/intake/__init__.py`, `src/aigv2/intake/template.py`, `tests/aigv2/test_intake_template.py`; generate `docs/aigv2/AIG Intake Template.docx`

**Interfaces:**
- Produces: `FIELDS: list[tuple[str, bool]]` (label, required) in this order — required: `Client name(s)`, `Number of travellers (adults)`, `Kids' ages`, `Diet (restrictions, allergies, likes)`, `Travel mode(s)`, `Itinerary`; optional: `Trip dates`, `Cities and nights`, `Hotel per city`, `Flights / trains`, `Confirmed bookings (tours, shows, times)`, `Seniors / mobility notes`, `Budget level`, `Occasion`, `Must-dos / avoid`, `Additional notes`.
- `build_template(path: Path) -> None` — a heading, one instruction line ("Write 'see attachments' for anything in the attached files"), and a 2-column table `Field | Your answer`, one row per field, required labels suffixed ` *`.
- `parse_template(path: Path) -> IntakeFields` where `IntakeFields(values: dict[str, str], see_attachments: set[str], missing_required: list[str], is_template: bool)`. Label match is case-insensitive, ignores ` *` and surrounding whitespace. A value equal (case-insensitive, trimmed) to `see attachments` / `see attached` / `use information from the attached files` goes to `see_attachments`. `is_template=False` when no field table is found (caller then treats the whole doc as free-form notes).

- [ ] **Step 1: Write failing tests:**
  - `test_build_then_parse_empty`: built template parses with `is_template True`, `missing_required` == the 6 required labels.
  - `test_parse_filled`: fill rows programmatically (`Client name(s)`=`Asha`, `Itinerary`=`see attachments`, `Diet…`=`no beef, nothing raw`) → `values["Client name(s)"] == "Asha"`, `"Itinerary" in see_attachments`, `"Itinerary" not in missing_required`.
  - `test_freeform_notes_not_template`: parse a synthetic free-form notes docx → `is_template False`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; run `python -c "from pathlib import Path; from src.aigv2.intake.template import build_template; build_template(Path('docs/aigv2/AIG Intake Template.docx'))"`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add intake template build and parse` (include the generated .docx; it is the team-review checkpoint).

---

### Task 5: Attachment text extraction and image-only detection

**Files:** Create `src/aigv2/intake/attachments.py`, `tests/aigv2/test_attachments.py`

**Interfaces:**
- Produces: `Attachment(name: str, kind: Literal["pdf","docx","image","other"], text: str, image_only: bool, has_images: bool)`; `read_attachment(path: Path) -> Attachment`.
- PDF via pymupdf `page.get_text()`; `image_only=True` when total stripped text < 40 chars and the PDF has ≥1 image. DOCX via python-docx paragraphs + table cells in document order; `has_images=True` when the body contains inline pictures; `image_only=True` when text < 40 chars and has images. Files with image extensions (`.png .jpg .jpeg .heic .webp`) → `kind="image"`, `image_only=True`, text empty.

- **Amendments:** `.zip` attachments are expanded in memory (skip entries with `..`/absolute paths, cap 50 files and 50 MB uncompressed) and each inner file read as its own `Attachment` named `<zip>/<inner>`. Identical files (same SHA-256) are kept once (`duplicate_of: str|None` on the rest). PDFs with text but whose dates/times sit in images: `has_images=True` and `text_dates: list[str]` (dates found by regex) — Task 11 uses this (a booking-like PDF with images and no date in its text → "paste the booking details" question).
- [ ] **Step 1: Write failing tests:** fixture DOCX with text → text contains its paragraphs and table cells; a synthetic notes docx with an embedded itinerary image → `has_images True` and its text paragraphs extracted, the image content not; a generated PDF with no text and one image → `image_only True`; `x.png` → `kind "image"`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add attachment reader with image-only detection`.

---

### Task 6: Extraction to TripPlan (luna) with validation

**Files:** Create `src/aigv2/intake/extract.py`, `tests/aigv2/test_extract.py`, `tests/aigv2/fixtures/nyc_trip/` (notes text, a hotel voucher text, a flight ticket text, and `expected_trip_plan.json` hand-written, synthetic, modelled on Trip E's notes)

**Interfaces:**
- Consumes: `StepLLM.run_json` (step `extract`), `IntakeFields`, `list[Attachment]`, `TripPlan`.
- Produces: `extract_trip(intake: IntakeFields | None, attachments: list[Attachment], llm: StepLLM) -> TripPlan`; `validate_trip(plan: TripPlan) -> list[str]` (passed to `run_json` as `validate`).
- Prompt rules to encode (system prompt): source of truth — vouchers > notes > itinerary for hotels, flight/train times, checkout dates (§6.2); record every either/or or conditional choice as `OpenChoice`; mark days like "Choose your day trip" in `vague_days`; move planner-to-team commentary into `commentary_removed`, never into items; only items named in the inputs; `meal_rules` capture explicit meal phrases verbatim.
- `validate_trip` returns problems for: zero days; any `DayPlan.date` outside `[min check_in, max check_out]` when hotels exist; duplicate day dates; `HotelStay.check_out <= check_in`.

- **Amendments:** de-duplicate per-passenger tickets — legs with the same `ref` + train/flight number + departure are one leg (the BVM voucher, Eurostar/TGV PDFs). Service vouchers: read pax table, flights (free text like "MIDNIGHT ARRIVAL AT 00:10 ON 25 SEPTEMBER (NIGHT OF 24 SEPTEMBER)"), hotel table (city, hotel, check-in/out, confirmation notes), day-wise blocks (type, time window, pickup/checkout times, notes) into `Booking`/`PlannedItem` with `included_in_package=True`; ignore stray document headings (e.g. a leftover "vietnam"). Items the notes call "optional" get `optional=True`. A `Booking` is created only from an attachment; "confirmed" in the notes without an attachment stays a `PlannedItem` (Task 11 flags it).
- **Past-AIG amendments:** extract meal plans from vouchers/notes ("Breakfast included", "half board", "all meals on board", "BBQ dinner included") into `HotelStay.meal_plan` / `PlannedItem.includes_meal`; cruise and sleeper-train nights become `HotelStay(kind="cruise"|"sleeper_train")`; "pure veg" wording sets `Diet.pure_veg`; drive-day stops become `drive_stops`.
- [ ] **Step 1: Write failing tests** with a fake LLM:
  - `test_extract_passes_inputs_to_llm`: prompt includes voucher text and template values.
  - `test_validate_trip_flags_out_of_range_day` and `test_validate_trip_flags_bad_stay`.
  - `test_invalid_extraction_triggers_fallback`: fake luna returns a plan failing `validate_trip`; fake sol returns `expected_trip_plan.json` → result equals expected.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): extract TripPlan from intake and attachments`.

---

### Task 7: Read-only library adapter and diet filter

**Files:** Create `src/aigv2/library.py`, `tests/aigv2/test_library.py`

**Interfaces:**
- Consumes: `LibraryDatabase` (`src/library/builder.py`), `Diet`.
- Produces: `Library(db_path: Path)`; `city(city: str) -> dict` merging all alias shards (`"New York"`, `"New York City"`, `"NYC"`; generic rule: also try the name with/without trailing `" City"`), de-duplicating restaurants by case-folded name; `country(country: str) -> dict` (from `_country/<Country>.json`); `restaurants(city) -> list[dict]`; `has_data(city) -> bool`; `diet_fits(restaurant: dict, diet: Diet) -> bool`.
- `diet_fits` rule (§8.1): no restrictions and no allergies → True. `vegetarian`/`vegan` restriction → True only if `vegetarian_friendly is True` or any `cuisine_type` contains `vegetarian`/`vegan` (case-insensitive). Any other restriction or allergy (e.g. `no pork`, `no beef`, `nothing raw`, `nut allergy`) → True only if the restaurant's `highlights`/`must_try_dishes`/`notes` text explicitly mentions that restriction being catered for (e.g. contains `"pork-free"`, `"halal"` for no pork, `"no beef"`); otherwise False.
- The adapter opens files read-only; it exposes no write method.

- **Amendments:** `city()` also merges the **region shard** that covers the city (via `_index.json` `_folder_coverage`, e.g. `Bali.json` for Ubud/Sanur) and resolves the country shard through the folder name (e.g. `_country/Bali Indonesia.json`). `restaurants_near(locality: str)` returns that locality's shard (Engelberg, Jungfraujoch, Grindelwald, Disneyland Paris) so day-trip meals use the place they are in, not the overnight city.
- **Past-AIG amendments:** `diet_fits` for vegetarian: also True when any `cuisine_type` is Indian or a regional Indian cuisine (`indian, gujarati, south indian, north indian, rajasthani, punjabi, kerala, udupi, chettinad, bengali, maharashtrian`); when `diet.pure_veg`, True only if `vegetarian_friendly` with highlights/cuisine/name stating pure veg / vegetarian-only. Japanese/Korean venues need explicit vegetarian proof (hidden fish stock). Add `is_indian(restaurant) -> bool`. Tests: `test_gujarati_fits_vegetarian`, `test_pure_veg_requires_explicit`, `test_japanese_needs_explicit_veg`.
- [ ] **Step 1: Write failing tests** (use `local_db` fixture style from `tests/conftest.py`, plus a two-shard alias fixture):
  - `test_city_aliases_merge`: shards `New York.json` (2 restaurants) + `New York City.json` (1 overlapping, 1 new) → `restaurants("New York")` has 3.
  - `test_diet_no_restrictions_all_fit`, `test_vegetarian_requires_flag_or_cuisine`, `test_no_beef_unknown_excluded` (Vatan-like entry without explicit mention → False), `test_halal_mention_fits_no_pork`.
  - `test_library_files_unchanged`: mtimes of fixture files identical after all calls.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add read-only library adapter with diet rule`.

---

### Task 8: Opening hours

**Files:** Create `src/aigv2/hours.py`, `tests/aigv2/test_hours.py`

**Interfaces:**
- Produces: `WeeklyHours(periods: dict[int, list[tuple[time, time]]], source: Literal["google","library"])` (weekday 0=Mon; a period ending past midnight is split across days); `WeeklyHours.from_google(regular_opening_hours: dict) -> WeeklyHours`; `parse_library_hours(text: str) -> WeeklyHours | None` (handles `"5 pm - 9:30 pm"`, `"11 AM – 10 PM (Mon–Thu)"`, `"Daily 8 am–12 am"`, `"12 PM - 2 PM, 7 PM - 11 PM"`; returns `None` for anything else, e.g. `"Confirm directly before visiting"`); `is_open_for(hours: WeeklyHours | None, day: date, start: time, minutes: int) -> bool | None` (`None` = unknown); `format_for_day(hours, day) -> str` (e.g. `"11:00 AM – 10:00 PM"`, `"Closed"`).
- Effective hours rule (used by later tasks): Google hours if present; else library hours (rendered with `⚠ VERIFY: hours`); else unknown. Unknown hours → restaurant **not eligible** for meal slots; attraction rendered with `⚠ VERIFY: opening hours`.

- **Past-AIG amendments:** `parse_library_hours` returns `None` for end-before-start (unless end ≤ 04:00), start == end, or a 00:00 opening ("12 AM – 10 PM"); accepts narrow no-break spaces and all dash variants. `format_week(hours) -> str` ("9–6 Mon–Fri · 9–1 Sat · Closed Sun") for Important Places. Tests: `test_inverted_ampm_rejected` ("11:30 PM – 8:30 PM"), `test_equal_start_end_rejected`, `test_nnbsp_parsed`.
- [ ] **Step 1: Write failing tests:**
  - `test_google_periods_parse_and_overnight_split`.
  - `test_lunch_at_4pm_opener_is_closed`: library `"4 pm - 11 pm"` → `is_open_for(..., time(12,30), 60) is False`.
  - `test_midday_closure`: `"9 AM - 2 PM, 5 PM - 9 PM"` → open at 15:00 False.
  - `test_unparseable_returns_none` (Review Focus 4): `"Confirm directly before visiting.Listed as daily 8 am–12 am"` → `parse_library_hours` returns `None`; `is_open_for(None, …) is None`.
  - `test_closed_on_monday`: Google periods without Monday → Monday `False`, `format_for_day == "Closed"`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add opening-hours parsing and checks`.

---

### Task 9: Google Places client with cache and match scoring

**Files:** Create `src/aigv2/google/__init__.py`, `src/aigv2/google/places.py`, `tests/aigv2/test_places.py`

**Interfaces:**
- Consumes: `PlaceCache`, `Place`, `WeeklyHours.from_google` (Task 8).
- Produces: `PlacesClient(api_key: str, cache: PlaceCache, session: requests.Session | None = None)`; `find(name: str, city: str, near: tuple[float,float] | None = None) -> Place | None`; `nearby(lat: float, lng: float, types: list[str], radius_m: int, max_results: int) -> list[Place]`; counter `calls: dict[str, int]` (`text_search`, `nearby`).
- Text search: `POST https://places.googleapis.com/v1/places:searchText`, headers `X-Goog-Api-Key`, `X-Goog-FieldMask: places.id,places.displayName,places.formattedAddress,places.location,places.businessStatus,places.regularOpeningHours,places.websiteUri,places.internationalPhoneNumber`, body `{"textQuery": f"{name}, {city}"}` (+ `locationBias.circle` 20 km when `near`). Nearby: `POST …/places:searchNearby` with `includedTypes`, `maxResultCount`, `locationRestriction.circle`.
- Match scoring (Review Focus 1): `match_ok = True` only if normalized names (casefold, strip punctuation, drop words `restaurant, cafe, the`) share ≥ 60% token overlap **and** the formatted address contains the city name (or `near` is given and the place is ≤ 25 km away). `find` returns the place with `match_ok=False` when the best candidate fails — callers must not use it. Cache key `f"{name}|{city}"`; cached places are returned without an HTTP call.
- `maps_url` built per Global Constraints.

- **Amendment:** `nearby()` for hospitals falls back to types `["doctor","medical_clinic"]` when no hospital is within 10 km (islands like Nusa Lembongan); the result is verify-marked "nearest clinic, not a hospital".
- **Past-AIG amendments:** add `places.primaryType,places.types` to the field mask. `nearby()` keeps only results whose `primaryType` is in the requested type set and whose name has none of: `dental, dentist, physio, cardio, sexual health, circumcision, sports, cosmetic, aesthetic, veterinary, equipment, b.v., ltd, gmbh, petroleum, fuel`. Hospitals must be emergency hospitals (prefer names/types with emergency; open 24 h when hours known); fallback clinic with VERIFY. For cities in South Korea or China every `Place` is verify-marked (weak coverage). Tests: `test_steroid_shop_not_pharmacy`, `test_equipment_firm_not_hospital`.
- [ ] **Step 1: Write failing tests** with a fake session returning canned JSON:
  - `test_find_parses_place`: fields mapped; `maps_url` contains `query_place_id=` and no `utm_`.
  - `test_find_uses_cache`: second `find` makes no HTTP call; `calls["text_search"] == 1`.
  - `test_wrong_city_match_rejected`: query `"Joe's Pizza", "New York"` returning a Chicago address → `match_ok False`.
  - `test_chain_name_mismatch_rejected`: query `"Seher Restaurant"` returning `"Seher Kuaför"` → `match_ok False`.
  - `test_nearby_request_body`: types and radius in the posted body.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add Google Places client with match scoring and cache`.

---

### Task 10: Routes client and travel legs (10-minute walking rule)

**Files:** Create `src/aigv2/google/routes.py`, `src/aigv2/planning/__init__.py`, `src/aigv2/planning/travel.py`, `tests/aigv2/test_travel.py`

**Interfaces:**
- Produces (`routes.py`): `RoutesClient(api_key, session=None)`; `durations(origins: list[tuple[float,float]], destinations: list[tuple[float,float]], mode: Literal["WALK","DRIVE","TRANSIT"]) -> dict[tuple[int,int], int | None]` (minutes, rounded up) via `POST https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix`, field mask `originIndex,destinationIndex,duration,condition`; `calls: int` (elements requested).
- Produces (`travel.py`): `Leg(from_name: str, to_name: str, walk_min: int|None, drive_min: int|None, transit_min: int|None)`; `leg_options(leg: Leg, modes: list[str], walk_max: int) -> list[tuple[str, int]]` returning ordered `(label, minutes)` with labels `"Walk"`, `"By car"`, `"By public transport"`: walk included iff `walk_min <= walk_max`; `"By car"` iff `taxi` or `self_drive` in modes; transit iff `public_transport` in modes; if walk excluded and no other mode allowed → `[("By car", drive_min)]` plus a `Marker(VERIFY, "travel mode for this leg")` returned by `leg_markers(leg, modes, walk_max) -> list[Marker]`.
- `compute_legs(points: list[tuple[str, tuple[float,float]]], routes: RoutesClient, modes: list[str]) -> list[Leg]` — consecutive pairs; WALK always requested; DRIVE when taxi/self_drive; TRANSIT when public_transport.

- **Amendments:** a `boat` leg (or any leg whose DRIVE/TRANSIT result is `ROUTE_NOT_FOUND` across water) uses the voucher's times and gets `⚠ VERIFY: boat transfer timing`. Inter-city rail legs **without a ticket** use Routes TRANSIT for a duration only, rendered as "about N h by train" + `⚠ VERIFY: no ticket provided — check timetable`; never invent frequency claims like "direct trains every hour".
- **Past-AIG amendments:** TRANSIT requests also return steps → `TransitStep(line: str, headsign: str, board: str, alight: str, stops: int)`; `Leg.transit_steps: list[TransitStep]`. Drive days with `drive_stops` produce one leg per stop with km and minutes, and a day total. Platform numbers never come from Routes.
- [ ] **Step 1: Write failing tests:**
  - `test_walk_shown_only_when_short`: walk 8, drive 5, modes `["taxi"]` → `[("Walk",8),("By car",5)]`; walk 25 → `[("By car",5)]` (Review: "2 min walk" that is 25).
  - `test_transit_only_if_listed`: modes `["taxi"]`, transit 12 → no transit option.
  - `test_matrix_parse`: canned response with one `ROUTE_NOT_FOUND` element → that pair is `None`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add routes client and travel legs with walking rule`.

---

### Task 11: Pre-flight checklist (code) and answers

**Files:** Create `src/aigv2/preflight.py`, `tests/aigv2/test_preflight.py`

**Interfaces:**
- Consumes: `TripPlan`, `IntakeFields`, `list[Attachment]`, `Library.has_data`, places resolved for itinerary items (`dict[str, Place|None]`), `WeeklyHours`.
- Produces: `run_checklist(plan, intake, attachments, library, places) -> list[Question]`; `apply_answers(plan: TripPlan, questions: list[Question], answers: Answers) -> TripPlan`; `unanswered(questions, answers) -> list[Question]`.
- Checks and question ids (§11b): `missing:<field>` (required field absent from intake values and not in `see_attachments`-resolved plan data — client names empty, adults 0, travel_modes empty, days empty; diet: ask only when intake diet value is empty and plan diet is empty); `image_only:<name>` ("<name> is an image — please paste its text"); `hotel_gap:<date>` (night with no `HotelStay`); `hotel_overlap:<date>`; `late_departure:<date>` (departing flight/train with `depart.hour < 5` → "Departure is at 01:00 on 15 Oct. Is checkout on 14 Oct or 15 Oct?", options both dates); `conflict:<topic>` (notes vs voucher differ — voucher used, asked to confirm); `days_mismatch` (number of distinct day dates ≠ nights+1 when hotels cover the trip); `open_choice:<n>`, `vague_day:<date>` from `TripPlan`; `no_library:<city>` (warning question with options `Proceed`, `Stop`); `hours_conflict:<day>:<item>` (attraction `is_open_for` False in its slot hint window and no other window that day works).
- `apply_answers`: `late_departure` sets the stay's `check_out`; `open_choice` keeps the chosen option's item, drops others; `vague_day` answer text becomes that day's items via a simple split on commas; `missing:travel_modes` sets modes; `no_library` `Stop` raises `PreflightStop`.

- **Amendments — extra checks:** `early_arrival:<date>` (arrival 00:00–05:00 → the day is the previous date, the hotel night starts that previous date; confirm); `no_departure` (no outbound leg found → ask the departure time and mode); `booking_conflict:<ref>` (a booking's date/time differs from where the notes place that item — e.g. night tour Day 1 in notes vs 2 May on the ticket; booking wins, asked to confirm); `headcount:<ref>` (ticket `pax_label` disagrees with travellers, e.g. "3 Adults" vs 2 adults + 1 child, "2x Youth" for 2 adults); `unvouchered_confirmed:<item>` (notes say confirmed/booked but no attachment); `image_details:<name>` (booking-like attachment whose date/time is only in images, or a photo attachment — "this may contain bookings; paste its text"); `kids_ages` asked only when children exist and ages are unknown. **Optional items are not asked** — they render as optional suggestions (see Task 18); only either/or choices are asked (user confirmed 2026-10-20).
- Tests to add: `test_early_arrival_previous_day` (00:10 on 25 Sep → question; answer keeps Day 1 = 24 Sep), `test_no_departure_question`, `test_booking_conflict_question`, `test_headcount_mismatch`, `test_optional_items_not_asked`.
- **Past-AIG amendments:** no `hotel_gap` for nights covered by a `cruise`/`sleeper_train` stay; `permit:<item>` question when a domestic item is in a known permit area (Nathula, Tsomgo, Gurudongmar, Pangong, Nubra, Arunachal, Nagaland ILP areas) and no permit is mentioned.
- [ ] **Step 1: Write failing tests:**
  - `test_late_departure_question` (Review Focus 2): flight departs `2026-10-15 01:00` → question `late_departure:2026-10-15` with options `["2026-10-14","2026-10-15"]`; answering `2026-10-14` sets that stay's `check_out`.
  - `test_hotel_gap` (Review Focus 5): stays 1–5 Nov and 6–8 Nov → `hotel_gap:2026-11-05`.
  - `test_days_mismatch` (Review Focus 5): 6 day plans for a 4-night stay → `days_mismatch`, and no exception.
  - `test_open_choice_applied`: choice `Top of the Rock` keeps it, removes `Empire State Building` item.
  - `test_image_only_question`, `test_missing_travel_mode`, `test_no_library_stop_raises`.
  - `test_all_questions_returned_at_once`: a plan with 4 problems → one call returns 4 questions.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add code pre-flight checklist and answer application`.

---

### Task 12: Slot assignment and meal anchors

**Files:** Create `src/aigv2/planning/slots.py`, `tests/aigv2/test_slots.py`

**Interfaces:**
- Consumes: `DayPlan`, `HotelStay`, `TransportLeg`, `Settings.slot_windows`, places map.
- Produces: `ScheduledItem(item: PlannedItem, slot: Literal["morning","afternoon","evening"], start: time)`; `MealSlot(meal: Literal["breakfast","lunch","dinner"], start: time, anchors: list[tuple[str, tuple[float,float], int]])` (anchor name, coords, number of options for that anchor; counts sum to 3); `schedule_day(day: DayPlan, hotel: HotelStay, arrival: TransportLeg|None, places: dict[str, Place|None], settings) -> tuple[list[ScheduledItem], list[MealSlot]]`.
- Rules (§8.1, §12b):
  - Explicit `time` wins; else `slot_hint`; else items fill morning → afternoon in order, items with `slot_hint="evening"` go to evening.
  - Lunch anchor = place of the last morning item; = hotel when the hotel check-in falls 11:00–13:00 that day, when an arrival leg lands so the client reaches the hotel 11:00–13:00, or when `meal_rules` contains "lunch at hotel"/"return to hotel" before lunch.
  - Dinner: if `meal_rules` names a place ("dinner before/between/near X") → 3 at X; elif an evening item exists → 1 at the last evening item + 2 at the hotel; else 3 at the hotel.
  - Breakfast slot only when `meal_rules` contains "breakfast out" (anchor: hotel).
  - Arrival after 14:00 → no lunch slot; arrival after 21:00 → no dinner slot; departure day: no meal slots after the "leave by" time (departure − 3 h international flights, − 1 h trains) **[plan's call; verify-marked]**.

- **Amendments:** voucher time windows and pickup times fix the slot and start time of included tours. Early-arrival day (00:00–05:00): only the transfer + check-in, no meals. **Hotel-change day:** stays are looked up per meal — dinner anchors at the *new* hotel when check-in is before dinner; lunch anchor uses the item's `locality` when set. Optional items are scheduled like others but marked optional.
- **Past-AIG amendments:** meal windows use `Settings.country_meal_windows` for the day's country; included meals (stay `meal_plan`, item `includes_meal`, cruise days) produce a `MealSlot(included=True)` with no anchors; sea days have no meal slots; port days anchor at the port. Drive days: lunch anchor = the `drive_stop` nearest 13:00. Late-arrival lunch cutoff = hotel arrival after **15:00**. Departure before 07:00 → "ask the hotel for a packed breakfast" tip. Tests: `test_included_dinner_no_options`, `test_spain_dinner_window`, `test_drive_day_lunch_at_waypoint`.
- [ ] **Step 1: Write failing tests:**
  - `test_untimed_items_fill_in_order`; `test_lunch_near_last_morning_attraction`; `test_lunch_at_hotel_on_midday_checkin` (check-in 12:00); `test_dinner_split_with_evening_attraction` (evening Fado show → anchors `[("Fado show",…,1),("hotel",…,2)]`); `test_dinner_before_cruise_rule` (meal_rules `"dinner before Seine cruise"` → 3 near the cruise); `test_breakfast_only_when_out`; `test_late_arrival_no_lunch`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add slot assignment and meal anchors`.

---

### Task 13: Meal planning — candidates, repeats, gaps

**Files:** Create `src/aigv2/planning/meals.py`, `tests/aigv2/test_meals.py`

**Interfaces:**
- Consumes: `Library.restaurants`, `Library.diet_fits`, `PlacesClient.find`, `RoutesClient.durations`, `is_open_for`, `MealSlot`, `StepLLM` (step `rank`).
- Produces: `MealPick(slot: MealSlot, day_index: int, restaurants: list[ChosenRestaurant], markers: list[Marker])`; `ChosenRestaurant(lib: dict, place: Place, travel_min: int, travel_label: str, hours_text: str, hours_verify: bool)`; `Exclusion(name: str, reason: Literal["diet","closed","not_open_at_meal","too_far","no_match","hours_unknown","repeat_limit"], detail: str)`; `plan_meals(days: list[tuple[int, date, str, list[MealSlot]]], library, places, routes, diet, modes, llm, settings) -> tuple[list[MealPick], list[Exclusion]]`.
- Algorithm per slot, per anchor (in day order across the trip so repeat counts are global per city):
  1. Candidates = library restaurants of that city where `diet_fits`.
  2. Resolve `find(name, city, near=anchor)`; drop `match_ok False` (`no_match`), status not `OPERATIONAL` (`closed`).
  3. Effective hours (Task 8 rule); `is_open_for(day, slot.start, 60)` must be `True` (`None` → `hours_unknown`, `False` → `not_open_at_meal`).
  4. Distance from anchor: lunch eligible if walk ≤ `walk_max_min` or (allowed mode) ≤ `lunch_max_min`; dinner ≤ `dinner_max_min` by allowed mode or walk ≤ `walk_max_min` (`too_far`).
  5. Repeats: drop if already used 2× in that city or already used that day (`repeat_limit`).
  6. If more valid than needed: luna `rank` picks the needed count from valid names only; the response is validated to be a subset of the valid names (fallback otherwise).
  7. Missing count → one `Marker(ADD_RESTAURANT, f"{Meal}, Day {n}, near {anchor}")` per missing option.
- Every exclusion is returned for the QC report and verification sheet.

- **Amendments:** candidates come from the **anchor's locality** shard when the item has a `locality`, else the day's city (not the overnight hotel city). "Per city" for the repeat rule = the library shard used. Test: `test_day_trip_lunch_uses_locality` (Titlis lunch picks from Engelberg).
- **Past-AIG amendments:** skip `MealSlot(included=True)`. On international trips, when ≥1 eligible candidate `is_indian`, at least one pick per meal slot is Indian (ranking chooses which). Test: `test_indian_option_guaranteed_when_available`.
- [ ] **Step 1: Write failing tests** (fakes for places/routes/llm):
  - `test_three_valid_no_markers`; `test_two_valid_one_marker` with exact marker text `"⚠ ADD RESTAURANT – Lunch, Day 3, near Galata Tower"`.
  - `test_closed_restaurant_excluded` (`CLOSED_PERMANENTLY` → `closed`); `test_opens_at_4pm_not_lunch` → `not_open_at_meal`.
  - `test_repeat_limits`: same restaurant cannot appear on day 1 lunch and day 1 dinner; never a third time in the city.
  - `test_rank_cannot_add_names`: fake luna returns an unknown name → fallback called; final picks ⊆ valid.
  - `test_no_library_city_all_markers`: zero restaurants → 3 markers per slot.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add library-only meal planning with gap markers`.

---

### Task 14: Money — price parsing, FX, INR formatting

**Files:** Create `src/aigv2/money.py`, `tests/aigv2/test_money.py`

**Interfaces:**
- Produces: `parse_price(text: str | None, default_currency: str) -> tuple[str, float, float] | None` (currency code, low, high; recognizes `€ $ £ ₺ ¥ ₹` and ISO codes; `"€20-30"` → `("EUR", 20, 30)`; tier strings like `"€€"` or `"moderate"` → `None`); `FxRates(backend: StorageBackend, session=None)` with `rate(code: str, on: date) -> float` from `https://api.frankfurter.app/<date>?from=<code>&to=INR`, cached at `cache/fx/<date>.json`; `format_price(currency: str, low: float, high: float, inr_rate: float, round_to: int = 50) -> str` → `"€20–30 (~₹1,850–2,800)"` (Indian digit grouping via `src/hotel_options/generator.py:format_indian_number`); `price_text(lib_restaurant: dict, city_currency: str, fx, day) -> str | Marker` returning `Marker(PRICE_UNKNOWN, "")` when unparseable.
- City currency: from the library country shard field `currency` if present, else a small built-in map by country (EUR for eurozone, TRY Turkey, USD USA, GBP UK, JPY Japan, CHF Switzerland, THB Thailand, AED UAE, IDR Indonesia, SGD Singapore); unknown → `PRICE UNKNOWN`.

- **Amendment:** currency resolved per day's city/country (EUR in Paris, CHF in Switzerland on the same trip).
- **Past-AIG amendments:** domestic trips print INR only. Rupee-currency countries render ISO codes (`MUR 500 (~₹950)`, `LKR`, `NPR`), never bare "Rs".
- [ ] **Step 1: Write failing tests:** `test_parse_range`, `test_tier_unknown`, `test_format_rounds_to_50` (`€25` at 93.4 → `"€25 (~₹2,350)"`), `test_fx_cached` (second call no HTTP), `test_missing_price_marker`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add price parsing and INR conversion`.

---

### Task 15: Important places around each stay

**Files:** Create `src/aigv2/planning/important_places.py`, `tests/aigv2/test_important_places.py`

**Interfaces:**
- Consumes: `PlacesClient.nearby`, `RoutesClient.durations`, `HotelStay` + hotel `Place`.
- Produces: `ImportantPlaces(city: str, hotel: str, pharmacies: list[NearbyPlace], groceries: list[NearbyPlace], hospital: NearbyPlace | None)`; `NearbyPlace(place: Place, walk_min: int|None, drive_min: int|None, hours_text: str)`; `important_places(stays: list[HotelStay], hotel_places: dict[str, Place], places, routes, modes) -> list[ImportantPlaces]` — one per distinct hotel; pharmacies: types `["pharmacy"]`, 2 results within 10-min walk (search radius 900 m); groceries: `["supermarket","convenience_store","grocery_store"]`, 2 within 10-min walk; hospital: `["hospital"]`, radius 10 km, nearest by drive. Fewer than 2 found → `Marker(VERIFY, "fewer than 2 <type> within a 10-minute walk")`.

- **Past-AIG amendments:** Important Places entries show `format_week` hours (closed days included) and phone.
- [ ] **Step 1: Write failing tests:** two hotels in two cities → two `ImportantPlaces`; pharmacy 14-min walk filtered out with VERIFY marker; hospital chosen by shortest drive.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add important places per stay`.

---

### Task 16: Writing — days, sections, creative title (luna)

**Files:** Create `src/aigv2/writing/__init__.py`, `writing/days.py`, `writing/sections.py`, `writing/title.py`, `tests/aigv2/test_writing.py`

**Interfaces:**
- Consumes: `StepLLM` (steps `write_days`, `write_sections`, `title`), scheduled items, `MealPick`s, legs, `Library.city/country`, `PlacesClient.find` (embassy check).
- Produces:
  - `AttractionText(name: str, description: str, entry_fee: str|None, dress_code: str|None, tips: str|None, best_time: str|None, duration: str|None)`; `RestaurantText(name: str, ambience: str, best_for: str)`; `DayText(title: str, intro: str, attractions: list[AttractionText], restaurants: list[RestaurantText], free_time_idea: str|None)`.
  - `write_day(day_facts: dict, llm) -> DayText` — `day_facts` contains only verified facts (names, times, hours text, travel options, library dishes/highlights) plus client profile (travellers, occasion). Validation: names in output must equal input names; descriptions must not contain digits followed by `min`, `AM/PM`, currency symbols, or `km` (problems → fallback).
  - Field → marker mapping applied by the renderer, not the LLM: `entry_fee`, `dress_code`, `tips`, `best_time`, `duration` (when not from library `recommended_duration`) are rendered with `⚠ VERIFY:`; entry fee additionally links `Place.website` when present.
  - `SectionContent(key: str, items: list[SectionItem], from_library: bool)`; `SectionItem(heading: str, body: str, verify: bool)`; `write_section(key: str, city_data: list[dict], country_data: dict, trip: TripPlan, llm) -> SectionContent` for keys `packing, connectivity, health, getting_around, dishes, souvenirs, etiquette, safety`. Library-first: when the relevant library lists are non-empty, luna only formats them (`from_library=True`, `verify=False`); otherwise luna writes them with `verify=True` — except `packing`, always AI, `verify=False` (§8.4). `dishes` "where to try" names must be library restaurants (validated). `safety`: each Indian embassy/consulate entry (library or AI) is checked with `PlacesClient.find(name, city)`; when `match_ok`, its address and phone come from Google and it is not verify-marked; otherwise it keeps `⚠ VERIFY:` (§8.4).
  - `write_title(trip: TripPlan, llm) -> str` — 2–5 words, destination-specific, not containing "All Inclusive Guide".
- Prompts: American English; warm, first-person "we", never salesy; no emojis.

- **Past-AIG amendments:** new section key `money` (Money & Payments: currency per country, cards/ATMs, cash-only notes, forex card; today's rate from `FxRates`, never AI). Sub-content folded in: recommended apps (incl. Naver/Kakao for Korea, Amap/Alipay/WeChat for China) → `connectivity`; tipping + dos & don'ts → `etiquette`; scams → `safety`; plug type, travel insurance, visa documents, weather/season line → `packing`; transit cards and rail passes (how to use, coverage) → `getting_around`. Any price or provider name in section content is verify-marked even when from the library. **Domestic trips:** omit `money`, `connectivity`, and `health` unless altitude ≥ 2,500 m / sea travel / remote area; `safety` adds altitude, mountain-road and low-network guidance and emergency 112; entry fees may show Indian vs foreigner prices (VERIFY). **Multi-country trips:** `emergency`, `embassy`, `dishes`, `souvenirs`, `etiquette` (phrases), `money`, `connectivity` are written per country (`SectionContent.by_country: dict[str, list[SectionItem]]`). Never write theme-park strategy tips unless the inputs contain them. Tests: `test_domestic_omits_money_sim`, `test_multicountry_sections_grouped`, `test_library_price_still_verified`.
- [ ] **Step 1: Write failing tests** with fake LLM: `test_day_names_must_match_inputs` (extra name → fallback), `test_description_with_time_rejected` (`"open 9 AM"` → fallback), `test_section_library_first_not_verified`, `test_section_ai_marked_verify`, `test_packing_never_verify`, `test_dishes_where_to_try_library_only`, `test_title_rejects_generic`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add luna writers for days, sections and title`.

---

### Task 17: Render theme, blocks and cover asset

**Files:** Create `src/aigv2/render/__init__.py`, `render/theme.py`, `render/blocks.py`, `src/aigv2/assets/` (`logo.png` copied from `../BVBMWebsite/01 BVBM Final Logo Assets/RGB File (For Digital)/PNG/Horizontal Lockup/` — pick the navy-on-white variant; `cover_a4.png`; `thank_you.txt` with Trip D's Thank You text verbatim from the Trip D shipped guide (see `input/for-aigv2/` (gitignored))), `scripts/aigv2_build_cover.py`, `tests/aigv2/test_render_blocks.py`

**Interfaces:**
- Produces (`theme.py`): `new_document() -> Document` — A4 (21.0 × 29.7 cm), margins 2.0 cm; `Normal` = Georgia 10.5 pt slate; `Heading 1` = Cormorant Garamond 24 pt navy (days, end sections); `Heading 2` = Cormorant Garamond italic 15 pt gold (time-slot headings); `Heading 3` = Cormorant Garamond 15 pt navy semibold (card titles); `Title` = Cormorant Garamond 34 pt navy; header with `logo.png` 3 cm wide; footer tab-stopped "Your Vacation · Your Story · Your Way" (Cormorant italic 10 pt slate) left and a PAGE field right. Built-in style names only (Review Focus 3).
- Produces (`blocks.py`): `add_link(paragraph, text: str, url: str)` (real `w:hyperlink`, royal, no underline); `add_marker(paragraph, marker: Marker)` (run text `marker.render()`, yellow highlight); `add_eyebrow(doc, text)` (Georgia 8.5 pt bold small caps royal, letter-spacing 1.5 pt); `add_slot_heading(doc, text)` (Heading 2); `add_card(doc, title: str, url: str|None, facts: list[tuple[str, str | Marker | list[str|Marker]]], body: str|None, pills: list[str])` — 1-cell table, border `#DCE6F2` 0.5 pt, fill `#FBFDFF`, padding ~0.3 cm; title as Heading 3 with link; nested 2-column facts table without borders, label (small caps royal 7.5 pt) above value (10 pt); body slate; pills as runs shaded `#EEF4FB` with royal 8.5 pt text separated by spaces; `add_rule(doc)` (powder bottom border).
- `scripts/aigv2_build_cover.py` builds `cover_a4.png` at 2480×3508 px with Pillow: navy `#0C1F3E` background, gold `#C68A32` 6 px inset border at 60 px, centered white-variant logo, tagline "Your Vacation • Your Story • Your Way" white, "BON VOYAGE BY MARINA" gold, phone `+91-86000-15316`, `www.bonvoyagebymarina.com`. Use `Fonts/Main Font - Le Jour Serif.otf` only for the tagline line (no apostrophes/en dashes in it).

- [ ] **Step 1: Write failing tests:** `test_new_document_is_a4` (section page width 21.0 cm ± 0.01); `test_heading_styles_builtin_and_branded` (`Heading 1` font name `Cormorant Garamond`, color `0C1F3E`); `test_link_is_real_hyperlink` (XML contains `w:hyperlink` with r:id to the URL); `test_marker_highlighted_yellow`; `test_card_structure` (one outer table, title paragraph style `Heading 3`, labels present); `test_footer_has_tagline_and_page_field`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; run `python scripts/aigv2_build_cover.py`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Checkpoint — user approval of `src/aigv2/assets/cover_a4.png`** (open it and ask; adjust and re-run until approved).
- [ ] **Step 6: Commit** `feat(aigv2): add branded render primitives and A4 cover`.

---

### Task 18: Assemble the document

**Files:** Create `src/aigv2/render/document.py`, `tests/aigv2/test_render_document.py`

**Interfaces:**
- Consumes: Tasks 8–17 outputs, bundled as `GuideData(trip: TripPlan, title: str, days: list[RenderDay], sections: dict[str, SectionContent], important: list[ImportantPlaces])` where `RenderDay(index: int, date: date, city: str, text: DayText, scheduled: list[ScheduledItem], meals: list[MealPick], legs: dict[str, Leg], places: dict[str, Place|None], markers: list[Marker])`.
- Produces: `day_header(index: int, d: date, title: str) -> str` → `f"Day {index} – {d:%a}, {d.day} {d:%b} | {title}"` (e.g. `"Day 1 – Thu, 29 Oct | Welcome to Istanbul"`); `render_guide(data: GuideData, settings) -> bytes`; `output_filename(trip) -> str` → `"All Inclusive Guide - <first client name> - <cities joined ', '>.docx"`.
- Order (§7.1): cover image full page (inline picture sized to page, margins zero for that section) → page break → letter: `"Dear <first name>,"` + marker `WRITE_LETTER` → page break → title page: logo, eyebrow-styled gold italic kicker "Your All-Inclusive Guide", `Title` = creative title, subtitle `"All Inclusive Guide – <destinations>"`, rule, TOC groups `DAY BY DAY` / `BEFORE YOU GO` / `WHILE YOU'RE THERE` as eyebrows with one internal-hyperlink line per entry (bookmark on each target Heading 1), **no page numbers** → each day (Heading 1 header, intro, slot headings + cards in time order, travel options line before each card, meal cards per anchor with heading `"Lunch near <anchor>"`, markers, closing line `"Overnight in <city>"`; departure day omits it) → Before You Go (Packing, Mobile Connectivity & SIM, Health & Vaccination) → While You're There (Important Places Around Your Stays, Getting Around, Must-Try Local Dishes, Souvenir Shopping Guide, Cultural Etiquette & Local Phrases, Safety & Emergency Contacts) → Thank You (`thank_you.txt`, phone, website). Each Heading 1 starts on a new page. Section items with `verify=True` get a `⚠ VERIFY:` marker after the body.
- Day specifics: arrival day starts with an "Airport → <hotel>" card using `leg_options` for each allowed mode and `⚠ VERIFY: transfer cost`; departure day ends with "Leave for the airport by HH:MM" (flight − 3 h, train − 1 h) followed by `⚠ VERIFY: departure time`; any day whose city differs from the previous day's adds station/airport transfer cards at both ends and one `⚠ VERIFY: inter-city travel day logistics` (§8.3). Attractions whose `Place` is missing or `match_ok False` render without hours, with a search-only Maps link and `⚠ VERIFY: place not found on Google`. Important Places entries show name (link), walk/drive minutes, hours for today's weekday and phone.

- **Amendments:** arrival/departure cards use the actual mode — "Gare du Nord → <hotel>" for train arrivals, "Harbour → <hotel>" for boats; leave-by = departure − 3 h (international flight), − 2 h (domestic flight), − 30 min (train), − 1 h (boat) **[plan's call]**, verify-marked. Attraction cards show booking facts when present: `YOUR BOOKING` (time or "valid all day" when `timed=False` — never "Confirmed entry" without a booking attachment), `MEETING POINT`, `DURATION`, and voucher `instructions` as bullet tips. Optional items render with an "Optional" pill. Package-included items show an "Included in your package" pill.
- Test to add: `test_untimed_booking_not_shown_as_confirmed_time`.
- **Past-AIG amendments:** TOC "Before You Go" = Tailored Packing List · Money & Payments · Mobile Connectivity & SIM Guide · Health & Vaccination (omitted ones dropped). Included meals render a single line "Lunch — Included in your package" (no card). Self-drive trips add a `PARKING` fact on every venue (library value or AI + VERIFY). Train cards show operator, number, class/seat, stations, times, duration, "Reach the station by HH:MM", platform only if ticketed, and a luggage-drop tip when arriving before check-in; transit legs list steps ("Line 4 → Line 2, alight Samseong, 6 stops"); drive days list stops with km/minutes and a day total; cruise port days show dock time and "Back on board by HH:MM". Sunset time (computed, no API) shown when an item mentions sunset. Multi-country end sections render per-country sub-headings.
- [ ] **Step 1: Write failing tests** with a hand-built `GuideData` fixture (2 days):
  - `test_day_header_format` (Review Focus 2): `day_header(1, date(2026,10,29), "Welcome to Istanbul") == "Day 1 – Thu, 29 Oct | Welcome to Istanbul"`; 15 Nov 2026 renders `Sun`.
  - `test_section_order`: Heading 1 texts in exactly the §7.1 order.
  - `test_toc_has_no_page_numbers_and_links_to_bookmarks`.
  - `test_letter_page_marker`: `"⚠ WRITE PERSONAL LETTER"` present and `"Dear <first name>,"`.
  - `test_every_venue_card_has_hyperlink`.
  - `test_no_utm_and_no_emoji`: document text has no `utm_` and no characters in emoji ranges other than `⚠`.
  - `test_output_filename`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): assemble branded AIG document`.

---

### Task 19: QC reader and rule checks

**Files:** Create `src/aigv2/qc/__init__.py`, `qc/reader.py`, `qc/rules.py`, `tests/aigv2/test_qc_rules.py`, `tests/aigv2/fixtures/google_roundtrip.docx` (produce once: render the Task 18 fixture, upload to Google Docs, download as .docx — **manual step for the user**; until provided, the test builds a stand-in by renaming every non-built-in style to `Normal` while keeping run formatting)

**Interfaces:**
- Produces (`reader.py`): `DocModel(headings: list[tuple[int, str]], days: list[DocDay], sections: dict[str, list[str]], markers: list[str], links: list[tuple[str, str]], text: str)`; `DocDay(header: str, slots: list[DocSlot])`; `DocSlot(heading: str, venues: list[DocVenue])`; `DocVenue(name: str, url: str|None, facts: dict[str, str], body: str)`; `read_docx(data: bytes) -> DocModel`. Structure comes from outline level (built-in Heading 1/2/3 or `w:outlineLvl`) and, when heading styles were lost, from formatting fallbacks: Heading 1 ≈ paragraph text matching `^Day \d+ – ` or a known section title; venue = first paragraph inside a 1-cell table; facts = label/value pairs in nested tables (label = uppercase line). Markers = text matching `⚠ (ADD RESTAURANT|VERIFY:|PRICE UNKNOWN|WRITE PERSONAL LETTER|CHECK:)`.
- Produces (`rules.py`): `check_rules(doc: DocModel, trip: TripPlan, library: Library) -> list[Finding]` with rule ids: `section_order`, `day_header_format`, `day_weekday` (header weekday ≠ date), `day_dates` (header dates vs trip days), `venue_link` (venue without Maps hyperlink), `meal_count` (meal slot with < 3 venues and no ADD RESTAURANT marker), `repeat_city`, `repeat_day`, `diet` (venue that is a library restaurant failing `diet_fits`; hand-added non-library venues are skipped — §12b), `walk_limit` (a "Walk" fact > 10 min), `placeholder` (regex `\[fill in|TBD|mention timings|lorem`), `utm` (`utm_` in any link), `commentary` (any `trip.commentary_removed` sentence found in text), `markers_remaining` (one finding listing the count).

- **Amendment:** add rule `assistant_chatter` — regex for leaked AI/planner text: `\b(Here are|Here's|in your preferred format|as an AI|I'd (keep|suggest|skip)|the client'?s?|Tripadvisor\))\b` (case-insensitive) → error. Test with Trip C's "I'd keep dinner easy…" and Trip A's "Here are clear, step-by-step directions…".
- **Past-AIG amendments:** new rules `title_destination` (title/subtitle must name ≥1 trip destination; catches "All Inclusive Guide- Bali" in a Kerala guide), `closing_phrase_misplaced` ("We hope this vacation…", "Hope this trip brought you…" outside Thank You), `third_person_client` ("her", "him", "the client's" in client-facing text), `meal_label_mismatch` (warning: "best for dinner" in a lunch slot or vice versa), `repeat_in_set`; `placeholder` adds `Not specified`, `Please see options below`, `choose one of`. `assistant_chatter` matches first-person adviser voice (`\bI would recommend\b`, `\bI'd (aim|keep|suggest|skip|treat|choose)\b`) and specific AI phrases (`Here are clear`, `in your preferred format`, `Let me know if`, `as an AI`) — **not** bare "Here are" (house text "Here are few numbers you may need" must pass). Tests for each.
- [ ] **Step 1: Write failing tests:** rendered fixture → `check_rules` returns only `markers_remaining`; planted errors each produce their rule id: wrong weekday (`"Day 1 – Fri, 29 Oct"`), a repeated restaurant on one day, a 25-min walk, a link with `utm_source=chatgpt.com`, a commentary sentence; `test_reader_survives_google_roundtrip` (Review Focus 3): the round-trip/stand-in doc yields the same days, venue names, links and marker count as the original.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add QC document reader and rule checks`.

---

### Task 20: QC fresh facts, LLM checks, annotation and report

**Files:** Create `qc/facts.py`, `qc/llm_checks.py`, `qc/annotate.py`, `qc/report.py`, `tests/aigv2/test_qc_agent.py`

**Interfaces:**
- Produces (`facts.py`): `check_facts(doc: DocModel, trip: TripPlan, places: PlacesClient, routes: RoutesClient, fresh: bool = True) -> tuple[list[Finding], list[FactRow]]` — for each venue: resolve via cache for ID/location, then **re-fetch status and hours fresh** (bypass cache for those fields; §12b) and recompute travel time to its anchor; findings `closed_now`, `not_open_at_slot`, `travel_time_mismatch` (doc minutes differ from Google by > 5 min or > 30%); `FactRow(day: int, venue: str, guide_hours: str, google_hours: str, guide_travel: str, google_travel: str, link: str, match: bool)`.
- Produces (`llm_checks.py`): `prose_fact_check(doc, llm) -> list[Finding]` (step `qc_prose`, luna; batch all descriptions in one call; findings `prose_fact` with the quoted sentence as `anchor_text`); `sense_check(doc, trip, llm) -> list[Finding]` (step `qc_sense`, **gpt-6.1-sol**; input: full doc text + trip plan JSON + pre-flight answers; asks for anything that doesn't make sense or a human should double-check, each with a verbatim `anchor_text`; findings `sense`). Anchors not found verbatim in the doc are attached to the day header instead.
- Produces (`annotate.py`): `annotate(docx_bytes: bytes, findings: list[Finding]) -> bytes` — inserts after the paragraph containing `anchor_text` (or the day header / document start) a new paragraph with `Marker(CHECK, finding.message)`, yellow highlight. Never edits existing content.
- Produces (`report.py`): `QCResult(passed: bool, findings: list[Finding], marker_count: int, fact_rows: list[FactRow])` where `passed = not findings and marker_count == 0`; `write_report(result, exclusions: list[Exclusion], cost: dict) -> tuple[str, dict]` (markdown + json). Markdown sections: Summary (PASS/FAIL, counts), Markers by type, Findings by day, Restaurants excluded (from Task 13, with reasons — library differences for the team to fix via the library tool), Cost.
- `run_qc(docx_bytes, trip, answers, library, places, routes, llm, exclusions) -> tuple[bytes, QCResult, str]` in `qc/__init__.py` (annotated docx, result, report markdown).

- [ ] **Step 1: Write failing tests** with fakes: `test_closed_venue_found_fresh` (cache says OPERATIONAL, fresh says CLOSED_PERMANENTLY → `closed_now`); `test_sense_check_uses_sol` (fake factory records model `gpt-6.1-sol`); `test_annotate_inserts_after_anchor` (marker paragraph directly follows the anchored paragraph; original paragraph text unchanged); `test_pass_requires_zero_markers`; `test_report_lists_exclusions`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add independent QC agent with annotation and report`.

---

### Task 21: Verification sheet

**Files:** Create `src/aigv2/verification.py`, `tests/aigv2/test_verification.py`

**Interfaces:**
- Consumes: `list[FactRow]`, `list[Exclusion]`.
- Produces: `build_sheet(rows: list[FactRow], exclusions: list[Exclusion]) -> bytes` (.xlsx via openpyxl). Sheet "Places": columns `Day | Place | Guide says: hours | Google says: hours | Guide says: travel | Google says: travel | Maps link | Match | Checked by`; Match `✓`/`✗`; links clickable; header row frozen. Sheet "Excluded restaurants": `Name | Reason | Detail`.

- [ ] **Step 1: Write failing tests:** two rows → sheet has header + 2 rows, `Match` values `✓`,`✗`, `Checked by` empty, hyperlink set on the link cell; exclusions sheet present.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add verification sheet`.

---

### Task 22: Pipeline, regenerate and CLI

**Files:** Create `src/aigv2/pipeline.py`, `src/aigv2/__main__.py`, `tests/aigv2/test_pipeline.py`

**Interfaces:**
- Consumes: everything above.
- Produces (`pipeline.py`):
  - `start_run(intake_path: Path | None, attachment_paths: list[Path], deps: Deps) -> tuple[RunStore, list[Question]]` — stores inputs, reads, extracts, resolves places for hotels + itinerary items, runs the checklist; saves `trip_plan.json`, `questions.json`.
  - `build_run(store: RunStore, answers: Answers, deps) -> BuildResult` — refuses if `unanswered` is non-empty; applies answers; schedules, meals, legs, important places, writing (days in parallel with a `ThreadPoolExecutor(max_workers=6)`), render, QC, verification sheet. Checkpoints: `plan.json`, `days/day_NN.json`, `sections/<key>.json`, `guide.docx` (annotated), `qc_report.md/json`, `verification.xlsx`, `cost.json` with shape `{"ai": {"total_usd": float, "by_step": {step: {"model": str, "prompt_tokens": int, "completion_tokens": int, "usd": float}}}, "google": {"total_usd": float, "by_api": {api: {"calls": int, "usd": float}}}, "total_usd": float}`. `cost_summary(cost: dict) -> str` renders the console block. A stage whose checkpoint exists is skipped.
  - `regenerate(store, days: list[int], sections: list[str], deps) -> BuildResult` — deletes those checkpoints (and meal picks for those days, recomputing repeats against the remaining days), rebuilds, re-renders, re-runs QC; keeps the previous outputs as `guide.v<N>.docx`.
  - `requalify(store_or_none, docx_path: Path, deps) -> tuple[bytes, QCResult, str]` — QC on an edited doc (re-QC).
  - `Deps(settings, llm: StepLLM, library: Library, places: PlacesClient, routes: RoutesClient, fx: FxRates, backend: StorageBackend)`; `default_deps() -> Deps`.
  - `BuildResult(docx_name: str, qc: QCResult, cost_usd: float)`.
  - Google unit prices live in `Settings.google_usd_per_call: dict[str, float]` (keys `text_search`, `nearby`, `route_element`); set from Google's current price list when implementing; tests assert arithmetic only.
- Produces (`__main__.py`, typer): `python -m src.aigv2 template OUT.docx`; `python -m src.aigv2 start --intake X.docx ATTACHMENTS...` (prints run id and numbered questions); `python -m src.aigv2 build RUN_ID --answers answers.json` (JSON `{question_id: answer}`); `python -m src.aigv2 regenerate RUN_ID [--day N]... [--section KEY]...`; `python -m src.aigv2 qc EDITED.docx [--run RUN_ID]`. Each prints output paths, PASS/FAIL, marker count, and `cost_summary` — e.g.

```
Cost this run: $0.42
  AI      $0.19  (extract $0.01 · rank $0.01 · write_days $0.06 · write_sections $0.02 · title $0.00 · qc_prose $0.01 · qc_sense $0.08)
  Google  $0.23  (text_search 41 calls $0.13 · nearby 9 calls $0.03 · route_element 140 $0.07)
```

- [ ] **Step 1: Write failing tests** with all-fake deps on the `tests/aigv2/fixtures/nyc_trip` fixture:
  - `test_end_to_end_fakes`: `start_run` returns questions; `build_run` with answers produces `guide.docx`, `qc_report.md`, `verification.xlsx`, `cost.json`; reading the docx shows N day headers in order.
  - `test_build_refuses_unanswered`.
  - `test_checkpoint_skips_stage`: second `build_run` makes zero LLM calls.
  - `test_regenerate_one_day`: only day 2's writer is called; `guide.v1.docx` kept.
  - `test_requalify_edited_doc`: edited doc with markers removed and one hand-added restaurant → no `diet`/library finding for it.
  - `test_cost_log_totals`: `cost.json` has `ai.total_usd + google.total_usd == total_usd`; per-step and per-API entries present.
  - `test_cli_prints_cost_split`: CLI `build` output contains `Cost this run:`, an `AI` line and a `Google` line.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `pytest tests/aigv2 -v` → all PASS.
- [ ] **Step 5: Commit** `feat(aigv2): add pipeline, regenerate, re-QC and CLI`.

---

### Task 23: Live setup and acceptance run (manual checkpoints)

**Files:** Create `docs/aigv2/google-cloud-setup.md`, `docs/aigv2/acceptance-log.md`

- [ ] **Step 1:** Write `google-cloud-setup.md`: console steps to enable **Places API (New)** and **Routes API** on the project holding `GOOGLE_MAPS_API_KEY`, confirm billing, restrict the key to those two APIs, and set a budget alert at $20/month. Send to the user.
- [ ] **Step 2: Remind the user** (memory `aigv2-pending-test-data`) to ingest the latest AIGs into the library (Lisbon and Nusa Lembongan have no restaurants). Test-trip inputs for Trips A, B and C are already in place (see `input/for-aigv2/` (gitignored)).
- [ ] **Step 3:** Primary acceptance trip = **Trip A (Europe)** — best library coverage (Paris 77, Interlaken 57, Lucerne 46, Zurich 46 restaurants), multi-city, trains, zips and a photo attachment; inputs: see `input/for-aigv2/` (gitignored). Then **Trip B (Bali)** (service voucher, boats, midnight arrival, Nusa Lembongan has 0 restaurants) and **Trip C (Lisbon)** (many timed experience bookings; Lisbon has 0 restaurants → gap-marker path). Fill the intake template for each; run `start` → answer questions → `build`. Record in `acceptance-log.md`: questions asked, marker counts by type, QC findings, total cost (must be ≤ $1), wall time.
- [ ] **Step 4:** Run `qc` on the three **shipped** guides (Trip A, Trip B, Trip C; see `input/for-aigv2/` (gitignored)) and record that it catches the known errors: Trip C — 3 restaurants closed on Sunday 18 Oct, Matiz Lisboa twice on Day 1, planner commentary, 8 `utm_source=chatgpt.com` links; Trip A — impossible hours ("11:30 PM – 8:30 PM"), a 13-min walk, "Here are clear, step-by-step directions…" chatter, Day 2 header not a heading; Trip B — Important Places block headed with the wrong hotel. Also plant errors in our own output (wrong weekday, 25-min walk, repeated restaurant, removed link).
- [ ] **Step 5: User checkpoint:** user uploads `guide.docx` to Google Docs and confirms fonts, cards, links, TOC links, footer and markers survive; then downloads it back as .docx → save as `tests/aigv2/fixtures/google_roundtrip.docx` and re-run `pytest tests/aigv2/test_qc_rules.py -v` → PASS.
- [ ] **Step 6:** Repeat Step 3 for Trip D (Istanbul) and Trip C (Lisbon) once their library data exists; note luna writing quality for the "switch day writing to sol?" decision (§11b).
- [ ] **Step 7: Commit** `docs(aigv2): add Google setup guide and acceptance log`.
