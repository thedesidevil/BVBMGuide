# Library Ingester Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two divergent library ingest paths with one ordered, newer-wins ingest core that captures everything AIG v2 consumes, then rebuild the library from the 287 past AIGs into a new folder.

**Architecture:** New package `src/library/ingest_core/` (text reading, item identity, cleaning, file ordering, extraction, ordered merge, runner). `LibraryBuilder`, `IngestService.persist` and the CLI become thin callers. All rebuild output goes to `library_db_new/`; `library_db/` is never written by the rebuild.

**Tech Stack:** Python 3.14, pytest, python-docx, PyMuPDF (`fitz`), typer/rich CLI (`src/library/__main__.py`), FastAPI UI backend (`src/library/ui/`), OpenAI-compatible client `src/common/ai_provider.py`.

**Spec:** `docs/superpowers/specs/2026-10-26-library-ingester-redesign-design.md`

## Global Constraints

- Extraction model: `claude-sonnet-5-5` (user's `.env` `AI_MODEL`); pilot compares it with `claude-haiku-5-5`.
- No Google calls anywhere in ingest. Optional place fields (`place_id, lat, lng, status, hours_structured, maps_url, website, phone, fetched_at`) are allowed on items but never filled here.
- Keep shard names and list names v2 reads: per city `restaurants, attractions, hotels, local_dishes, souvenirs, phrases, safety_tips, emergency_contacts, connectivity_tips, transport_options, health_tips`, optional `currency`; `_index.json` with `_folder_coverage`; `_country/<Country>.json`. New lists: country `plugs, tipping, dos_donts, scams, insurance, apps, money, embassies`; city or country `season_notes`; city `route_guides`.
- Provenance on every item: `_source_file`, `_source_date`, `_source_format` (`new`|`old`); overwritten items get `_replaced_from`; UI-edited items get `_manual: true`, `_manual_by`, `_manual_at`; protected-item disagreements go to the shard's `_conflicts` list.
- Ordering: modified date shared by more than 5 files is a bulk-copy date; then travel dates inside the AIG; then format (new beats old); then file name. Old-format items never overwrite new-format items. Exact duplicate texts are processed once (208 unique of 287).
- Item identity: normalised name (casefold, accents stripped, leading "the" dropped, punctuation and whitespace collapsed) scoped to the city shard; text items match on exact normalised text only.
- Drop before merge: any item containing `⚠`, "VERIFY", "ADD RESTAURANT", "PRICE UNKNOWN", "WRITE PERSONAL LETTER", "CHECK:"; assistant chatter; client-specific text; items with no identity.
- Checkpoint every 10 files. Pilot is about 10 files. Full run needs an explicit `--max-usd`. Never suggest `--force`.
- Tests live in `tests/library/` (create with `__init__.py`); no test calls a real model or Google.

## Review Focus

1. A file whose extraction is empty, garbled or has no cities is logged as failed and writes nothing; the run continues. (Task 7)
2. An item with a blank or punctuation-only name never creates a `""` entry. (Task 3)
3. Accent/case variants of one city ("São Paulo" / "Sao Paulo" / "sao paulo ") land in one shard. (Task 6)
4. DOCX tables carry real content (old-format day tables, tabular souvenir lists) and must be read in document order. The old builder read paragraphs only. (Task 2)
5. A run interrupted mid-way and restarted adds no duplicates and skips finished files; ingesting a file twice changes nothing. (Tasks 6 and 7)

---

### Task 1: Price the Anthropic 5.x models

**Files:**
- Modify: `src/common/ai_provider.py:18-29` (`_MODEL_PRICING`)
- Test: `tests/library/test_ai_pricing.py`

**Interfaces:**
- Produces: `_lookup_pricing("claude-sonnet-5-5") == (2.00, 10.00)`, `_lookup_pricing("claude-haiku-5-5") == (0.10, 0.50)`.

- [ ] **Step 1: Write the failing test** — assert the two values above, and that `claude-sonnet-4-6` still returns `(3.00, 15.00)` and `claude-haiku-4-5` still `(1.00, 5.00)` (prefix order must not shadow).
- [ ] **Step 2: Run** `pytest tests/library/test_ai_pricing.py -v`; expect FAIL (returns `None`).
- [ ] **Step 3: Add `("claude-sonnet-5", 2.00, 10.00)` and `("claude-haiku-5", 0.10, 0.50)`** to `_MODEL_PRICING`. Comment that Haiku 5.5 prompts above 100K tokens cost $0.50/$2.50; `cost_usd` stays flat and the pilot report flags any such prompt.
- [ ] **Step 4: Run test; expect PASS.**
- [ ] **Step 5: Commit** `feat(library): price claude 5.x models`.

---

### Task 2: Text reading and item identity

**Files:**
- Create: `src/library/ingest_core/__init__.py` (empty for now), `src/library/ingest_core/text.py`, `src/library/ingest_core/identity.py`
- Test: `tests/library/test_text.py`, `tests/library/test_identity.py`, `tests/library/__init__.py`

**Interfaces:**
- Produces:
  - `class UnreadableFile(Exception)`
  - `read_text(path: Path) -> str` — `.docx`: paragraphs and table rows in body order, a table row as its cell texts joined by `" | "`, one row per line; `.pdf`: PyMuPDF page text; raises `UnreadableFile` on any failure or unsupported suffix.
  - `text_hash(text: str) -> str` — sha1 of the whitespace-collapsed text.
  - `norm_key(s: str) -> str`
  - `IDENTITY_FIELDS: dict[str, list[tuple[str, ...]]]` — per list name, alternatives tried in order: `restaurants/attractions/hotels/local_dishes: [("name",)]`; `souvenirs: [("item",)]`; `phrases: [("english",)]`; `connectivity_tips: [("provider","kind"),("tip",)]`; `emergency_contacts: [("service","number"),("number",)]`; `transport_options: [("mode",)]`; `safety_tips/health_tips/tipping/dos_donts/scams/insurance/money/season_notes: [("tip",),("text",)]`; `apps: [("name",)]`; `plugs: [("type",)]`; `embassies: [("name","city")]`; `route_guides: [("from","to")]`.
  - `item_key(list_name: str, item: dict) -> str` — first alternative whose fields are all non-blank, each value passed through `norm_key`, joined with `"|"`; `""` if none usable.
  - `city_shard_name(raw: str) -> str` — strip, collapse spaces, `.title()`.

- [ ] **Step 1: Write failing tests.**
  - `test_read_text_includes_table_rows_in_body_order`: build a docx with paragraph, a 2-row table (`["Day 1","Arrive"]`, `["Day 2","Museum"]`), paragraph; assert the text lines are `[para1, "Day 1 | Arrive", "Day 2 | Museum", para2]`.
  - `test_read_text_unreadable_raises`: a text file renamed `.docx` raises `UnreadableFile`.
  - `test_text_hash_ignores_whitespace`.
  - `test_norm_key`: `norm_key("The  Café-Royal!") == "cafe royal"`; `norm_key("São Paulo") == norm_key("sao paulo")`.
  - `test_item_key_alternatives`: SIM item `{"provider":"Airalo","kind":"eSIM"}` → `"airalo|esim"`; legacy `{"tip":"Buy a SIM"}` → `"buy a sim"`; `{"name":"  "}` for restaurants → `""`.
- [ ] **Step 2: Run; expect FAIL (modules missing).**
- [ ] **Step 3: Implement.** Iterate `doc.element.body` children to keep paragraph/table order (python-docx `Paragraph`/`Table` wrappers). Accent stripping via `unicodedata.normalize("NFKD")`.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat(library): ingest_core text reading and item identity`.

---

### Task 3: Cleaning extraction output

**Files:**
- Create: `src/library/ingest_core/clean.py`
- Test: `tests/library/test_clean.py`

**Interfaces:**
- Consumes: `item_key`, `IDENTITY_FIELDS` (Task 2).
- Produces:
  - `MARKER_RE`, `CHATTER_RE`, `CLIENT_RE` (compiled, case-insensitive). Markers: the six strings in Global Constraints. Chatter: "I would recommend", "I'd (aim|keep|suggest|skip|treat)", "Here are clear", "in your preferred format", "Let me know if" (mirror the `assistant_chatter` rule in `src/aigv2/qc/rules.py`; copy the patterns, do not import across packages). Client text: `your (hotel|booking|flight|reservation|stay|itinerary)`, `(booking|confirmation|reservation) (ref(erence)?|number|no\.?|id)`, `Day \d+` at the start of a description.
  - `is_v2_generated(path: Path) -> bool` — True when `docProps/custom.xml` inside the docx zip has a property named `bvbm_run_id`; False on any read error.
  - `clean_extraction(data: dict) -> tuple[dict, list[dict]]` — returns a cleaned deep copy and the dropped items as `{"list", "reason", "text"}`, reason in `marker|chatter|client_specific|no_identity`. Applies to every list in `data` whose name is in `IDENTITY_FIELDS` and to the same lists inside each entry of `data["country_content"]`. Text checked is all string values of the item (lists joined).

- [ ] **Step 1: Write failing tests:** marker item dropped (`"⚠ VERIFY: price"` in a tip); chatter dropped; `"Ask your hotel for a map"` dropped as client_specific; blank-name restaurant dropped as `no_identity`; a clean restaurant kept untouched; country_content lists cleaned too; the input dict is not mutated; `is_v2_generated` True for a zip containing a custom.xml with `name="bvbm_run_id"`, False for a plain docx and for a non-zip file.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** Dropped items are returned, never silently lost; the runner (Task 7) writes them to the run log so over-dropping is visible.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat(library): clean extraction output before merge`.

---

### Task 4: File scanning and ordering

**Files:**
- Create: `src/library/ingest_core/ordering.py`
- Test: `tests/library/test_ordering.py`

**Interfaces:**
- Consumes: `read_text`, `text_hash` (Task 2).
- Produces:
  - `@dataclass(frozen=True) FileScan(path: Path, mtime: date, text_hash: str, fmt: Literal["new","old"], last_day: date | None, looks_like_aig: bool)`
  - `@dataclass OrderedFile(scan: FileScan, order_date: date | None, basis: Literal["mtime","travel","format","name"], duplicate_of: Path | None, skipped_reason: str | None)`
  - `scan_file(path: Path) -> FileScan` — `fmt="old"` when a docx table has at least 3 rows whose first cell matches `^\s*day\s*\d+`; `looks_like_aig` is True with at least 2 such "Day N" lines or rows; `last_day` is the latest date found in weekday-plus-date day headers (`Mon, 12 Jan` or `Monday 12th January`, both word orders), with the year chosen from 2023–2027 as the one whose weekday matches at least 60% of at least 2 headers; `None` otherwise.
  - `order_files(scans: list[FileScan], bulk_threshold: int = 5) -> list[OrderedFile]` — sorted by `(format rank old=0/new=1, order_date or date.min, path.name)`. `order_date` is `mtime` unless that date is shared by more than `bulk_threshold` scans, then `last_day`, else `None`. Duplicate `text_hash`: the first by path name stays, the rest get `duplicate_of` and are excluded from the sorted result's processing flag (`skipped_reason="duplicate"`). Files with `looks_like_aig=False` get `skipped_reason="not_an_aig"`.
  - `write_order_report(ordered: list[OrderedFile], out: Path) -> None` — markdown table: position, file, order_date, basis, format, skipped reason; a closing list of every file whose basis is `format` or `name` (the user checks these before the paid run).

- [ ] **Step 1: Write failing tests** with small generated docx files and `os.utime`: (a) 7 files sharing one mtime are bulk; 2 files with unique mtimes keep `basis="mtime"`; (b) a doc with headers `Mon, 12 Jan`, `Tue, 13 Jan`, `Wed, 14 Jan` resolves `last_day == date(2026,1,14)`; (c) a doc with a 3-row `Day N` table is `old`; (d) an old-format 2026 file sorts before a new-format 2024 file; (e) two files with identical text: second gets `duplicate_of`; (f) a doc without Day lines is `not_an_aig`; (g) order is deterministic across two calls.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** The year-inference regexes handle both header orders; dates that don't exist in a candidate year (29 Feb) are skipped for that year.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat(library): scan and order past AIGs before extraction`.

---

### Task 5: Extraction prompt and extractor

**Files:**
- Create: `src/library/ingest_core/prompt.py`, `src/library/ingest_core/extract.py`
- Test: `tests/library/test_extract.py`

**Interfaces:**
- Consumes: `read_text`, `item_key` (Task 2); `sanitize_text`, `split_into_chunks`, `call_and_parse`, `SINGLE_PASS_LIMIT` from `src/common/doc_extractor.py`.
- Produces:
  - `prompt.py`: `CITY_LISTS: tuple[str, ...]` (the eleven existing lists plus `route_guides`, `season_notes`), `COUNTRY_LISTS: tuple[str, ...]` (`plugs, tipping, dos_donts, scams, insurance, apps, money, embassies, season_notes, phrases, safety_tips, emergency_contacts, connectivity_tips, health_tips, transport_options`), `EXTRACTION_PROMPT` (a `str.format` template with `{text}`).
  - Output JSON of the prompt: `covered_cities: [str]`, `city_countries: {city: country}`, one array per `CITY_LISTS` name with each item carrying `city`, `country_content: [{country, currency, <each COUNTRY_LISTS name>: [...]}]`. Restaurant items add `meal_slots` (from the Breakfast/Lunch/Dinner heading they appear under) and `notes`; attractions add `entry_fee, dress_code, tips`; transport items add `how_to_use, covers`; connectivity items are `{provider, kind, price_text, coverage_countries, notes}`; a multi-country item is repeated in each country's entry.
  - The prompt must instruct: reusable facts only (no client names, dates, bookings or "your hotel"); no ⚠/VERIFY text; short canonical wording for tips; read table rows as content; `meal_slots` only when a heading states it.
  - `@dataclass Extraction(data: dict, chunks: int, prompt_tokens: int, completion_tokens: int, usd: float | None)`
  - `extract_file(client: AIClient, path: Path) -> Extraction | None` — `None` when the text is under 200 characters, unreadable, or every chunk fails; single pass up to `SINGLE_PASS_LIMIT`, otherwise `split_into_chunks` and `merge_chunks`. Token and cost figures are the delta of `client.usage` / `client.cost_usd` across the call.
  - `merge_chunks(results: list[dict]) -> dict` — first occurrence wins per `item_key`, `covered_cities` unioned, `city_countries` unioned, `country_content` merged by country name.

- [ ] **Step 1: Write failing tests** with a stub client exposing what `call_and_parse` uses (read `src/common/doc_extractor.py:80`), `usage`, `cost_usd`: (a) every name in `CITY_LISTS` and `COUNTRY_LISTS` and each new field name appears in `EXTRACTION_PROMPT`; (b) single pass returns the stub's data with token deltas; (c) a text longer than `SINGLE_PASS_LIMIT` makes multiple calls and `merge_chunks` removes an item repeated across chunks; (d) all-chunks-fail returns `None`; (e) text under 200 characters returns `None` without calling the client.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** Do not modify the old `LIBRARY_EXTRACTION_PROMPT` or `merge_extraction_results` (the old paths are retired in Task 8, not edited here).
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat(library): new extraction prompt and extractor`.

---

### Task 6: Ordered merge into shards

**Files:**
- Create: `src/library/ingest_core/merge.py`
- Modify: `src/library/ui/services/db_service.py` (add helpers below)
- Test: `tests/library/test_merge.py`

**Interfaces:**
- Consumes: `item_key`, `city_shard_name`, `norm_key` (Task 2); `LibraryDBService.get_city_data/save_city_data/get_country_data/save_country_data` (`src/library/ui/services/db_service.py`).
- Produces:
  - `db_service.py` additions: `list_city_shards(self) -> list[str]` (names of non-underscore shard keys), `get_blocklist(self) -> list[dict]` and `set_blocklist(self, entries: list[dict]) -> None` (stored under `_blocklist` in the index; entry `{city, list, key}`), `record_processed_file(self, rel_key: str, info: dict) -> None`, `add_folder_coverage(self, folder: str, cities: list[str]) -> None`, `save_index(self) -> None`.
  - `@dataclass FileMeta(source_file: str, order_date: date | None, fmt: Literal["new","old"], folder: str)`
  - `@dataclass MergeStats(added: int = 0, replaced: int = 0, unchanged: int = 0, skipped_older: int = 0, protected: int = 0, blocked: int = 0)` with `__iadd__`.
  - `resolve_city_shard(db: LibraryDBService, raw: str) -> str` — an existing shard whose `norm_key` equals `norm_key(raw)` wins; otherwise `city_shard_name(raw)`.
  - `merge_extraction(db: LibraryDBService, data: dict, meta: FileMeta) -> MergeStats` — `data` is already cleaned. City lists go to the shard from each item's `city` (tip-type items with a `cities` list go to each), country entries to `_country/<Country>.json` via `get_country_data/save_country_data`; `country_content[].currency` is stored on the country shard and on every city shard whose `city_countries` entry matches. Every written item gets provenance (`_source_file`, `_source_date` = `order_date` ISO or `None`, `_source_format`).

  Rules per incoming item with identity key K against the existing item with the same K in the same list:
  1. K blocked by `db.get_blocklist()` → `blocked`.
  2. No existing → append, `added`.
  3. Existing has `_manual` → leave it; if content differs append `{list, key, incoming, source_file}` to the shard's `_conflicts`, `protected`.
  4. Existing `_source_file` equals this file → replace in place without `_replaced_from`; identical content → `unchanged`, no write.
  5. Rank = `(fmt rank old=0/new=1, order_date or date.min)`; incoming rank lower than existing (unprovenanced existing counts as lowest) → `skipped_older`.
  6. Otherwise replace the whole item, setting `_replaced_from` to the old `_source_file`, `replaced`.

- [ ] **Step 1: Write failing tests** using `LibraryDBService` over an in-memory `StorageBackend` (copy the dict-backed fake from `tests/test_db_service.py`): (a) add then newer replace sets `_replaced_from`; (b) an old-format file after a new-format one → `skipped_older`; (c) a `_manual` item is untouched and a conflict is recorded; (d) merging the same file twice yields identical shards and `unchanged` counts; (e) `"São Paulo"`, `"Sao Paulo"`, `"sao paulo "` produce one shard; (f) a blocklisted item is not added; (g) a multi-country eSIM in two `country_content` entries lands in both country shards; (h) `currency` reaches the country shard and the matching city shard; (i) tip items with identical normalised text dedupe.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** Read each shard once per call and write once per shard at the end of the file, so an exception leaves no half-written file.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat(library): ordered newer-wins merge with manual protection`.

---

### Task 7: Runner with checkpoints, cost ceiling and run log

**Files:**
- Create: `src/library/ingest_core/runner.py`; export `run_ingest`, `PlanEntry`, `IngestReport` from `src/library/ingest_core/__init__.py`
- Test: `tests/library/test_runner.py`

**Interfaces:**
- Consumes: `extract_file` (Task 5), `clean_extraction`, `is_v2_generated` (Task 3), `merge_extraction`, `FileMeta`, `MergeStats` (Task 6), `OrderedFile` (Task 4).
- Produces:
  - `@dataclass PlanEntry(path: Path, folder: str, order_date: date | None, fmt: str, text_hash: str)`
  - `@dataclass IngestReport(processed: list[str], failed: list[tuple[str, str]], skipped: list[tuple[str, str]], stats: MergeStats, dropped: list[dict], cost_usd: float | None, stopped_on_ceiling: bool)`
  - `run_ingest(plan: list[PlanEntry], db: LibraryDBService, client: AIClient, *, log_dir: Path, workers: int = 5, max_usd: float | None = None, checkpoint_every: int = 10) -> IngestReport`

  Behaviour: extraction runs on up to `workers` threads, but results are merged strictly in plan order. A file is skipped when `db` index `_processed_files[rel_key].text_hash` equals its hash (resume) or when `is_v2_generated(path)`. A file whose extraction is `None` or has neither `covered_cities` nor any items goes to `failed` and writes nothing. After each merged file: `record_processed_file` (hash, order date, format, folder, covered cities, timestamp) and `add_folder_coverage`; `save_index()` every `checkpoint_every` files and in a `finally`. Appends one JSON line per file to `log_dir/ingest_log.jsonl` (stats, dropped items, tokens, usd). With `max_usd`, no new extraction is submitted once `client.cost_usd >= max_usd`; `stopped_on_ceiling=True`. If `max_usd` is set and `client.cost_usd is None` (unpriced model), raise `ValueError` before starting.

- [ ] **Step 1: Write failing tests** with a stub client and a patched `extract_file`: (a) three files merge in plan order even when the second finishes first; (b) an empty extraction goes to `failed`, writes no shard, and the next file still runs; (c) re-running the same plan processes nothing and changes no shard; (d) an exception inside the second file's merge leaves the index recording only the first file; (e) ceiling stops after the file that crosses it; (f) a v2-generated file is skipped with reason `v2_generated`; (g) unpriced model with `max_usd` raises.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** Use `concurrent.futures.ThreadPoolExecutor` with a dict of futures keyed by plan index, consumed in index order.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat(library): ingest runner with resume, checkpoints and cost ceiling`.

---

### Task 8: Point the old entry points at the core

**Files:**
- Modify: `src/library/builder.py` (`LibraryBuilder.build_database`, `process_single_file`, `_process_file`, `_deduplicate_by_name`), `src/library/ui/services/ingest_service.py` (`extract_all`, `persist`, `_CITY_FIELDS`, `_MULTI_CITY_FIELDS`, `_is_duplicate`, `_empty_city_shard`), `src/library/ui/services/country_extractor.py`
- Test: `tests/library/test_entrypoints_parity.py`

**Interfaces:**
- Consumes: `run_ingest`, `PlanEntry`, `scan_file`, `order_files`, `extract_file`, `merge_extraction`, `FileMeta`.
- Produces: `LibraryBuilder.build_database(...)` keeps its signature and return type but scans `library_path` subfolders, builds a plan (`folder` = subfolder name) with `scan_file`/`order_files`, and calls `run_ingest` against a `LibraryDBService` on `output_path`; `--force` keeps working by clearing the processed index first. `IngestService.extract_all` calls `extract_file` and stores `Extraction.data`; `IngestService.persist` calls `clean_extraction` then `merge_extraction` per extracted file (order date and format from `scan_file` of the uploaded file) and returns the same dict shape as today (`persisted_files`, `affected_cities`).

- [ ] **Step 1: Write the parity test:** feed one stored `Extraction.data` through `persist` (UI path, in-memory backend) and through `run_ingest` (CLI path) and assert identical shard contents and index coverage; assert the UI path now replaces an older same-name item (old behaviour skipped it).
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Rewire** as described. Remove the in-line dedup and the `_MULTI_CITY_FIELDS` splitting from `persist`. Stop `ensure_country_shards` aggregating city shards in ingest paths: find its callers with grep, keep the function only if something else needs it, otherwise delete it with its test.
- [ ] **Step 4: Run the parity test and `pytest tests -q --ignore=tests/hotel_options/test_decoder.py`; expect all PASS** (that file already fails to collect, independent of this work).
- [ ] **Step 5: Commit** `refactor(library): CLI and UI ingest share the ingest core`.

---

### Task 9: Manual-edit protection in the library UI

**Files:**
- Modify: `src/library/ui/api/city.py:76-90` (`save_city`), `src/library/ui/api/sweep.py:55` (`save_sweep`), and the add-item path if it is separate (grep `@router.post` in `src/library/ui/api/`)
- Test: `tests/library/test_manual_protection.py`

**Interfaces:**
- Consumes: the diff helper `_diff_city` in `city.py` (it already finds added and edited items).
- Produces: after a UI save, every added or edited item carries `_manual: True`, `_manual_by` (the request's `changed_by`), `_manual_at` (UTC ISO). Unknown keys (`_conflicts`, new lists, `_source_*`) round-trip through `GET /city/{name}` then `PUT /city/{name}` unchanged.

- [ ] **Step 1: Write failing tests** with FastAPI `TestClient` over `create_app(storage_backend=<in-memory backend>)`: editing a restaurant's hours sets the three flags on that item only; adding an item flags it; an untouched item stays unflagged; a PUT after a GET preserves a shard's `_conflicts` and `route_guides`; a manual item then survives `merge_extraction` of a disagreeing newer file (end-to-end of Task 6 rule 3).
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** the stamping in `save_city` after `_diff_city` and the same in the sweep save.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat(library-ui): flag hand-edited items so ingest never overwrites them`.

---

### Task 10: CLI commands `plan`, `pilot`, `rebuild`; docs

**Files:**
- Create: `src/library/ingest_core/plan.py`, `src/library/ingest_core/pilot.py`
- Modify: `src/library/__main__.py`, `CLAUDE.md` (Commands section), `docs/LIBRARY_BUILD_PIPELINE.md`
- Test: `tests/library/test_plan_pilot.py`

**Interfaces:**
- Consumes: `scan_file`, `order_files`, `write_order_report` (Task 4); `extract_file` (Task 5); `run_ingest`, `PlanEntry` (Task 7); `LibraryIngester._classify_file` (`src/library/ingester.py:89`).
- Produces:
  - `plan.py`: `build_plan(input_dir: Path, library_dir: Path, client: AIClient, out_dir: Path) -> list[PlanEntry]` — scans every `.docx`/`.pdf` in `input_dir`, orders them, assigns each unique file a destination folder (the folder of a same-named file in `library_dir` if one exists, otherwise the AI classification against the existing `library_dir` folder names), writes `out_dir/plan.json` (entries with folder, order date, basis, format, skipped reason) and `out_dir/order_report.md`.
  - `pilot.py`: `select_pilot_files(plan: list[PlanEntry], count: int = 10) -> list[PlanEntry]` — covers old and new format, the largest file (multi-chunk), a folder name containing " and " / "&" / "+" (multi-country), and at least two different folders; `run_pilot(entries, models: list[str], out_dir: Path) -> None` — for each model, a one-call connectivity probe first (stop with a clear message if it fails), then `extract_file` per entry into scratch (no library writes); writes `pilot_report.md` (per file and model: tokens, usd, item counts per list, flag if prompt over 100K tokens) plus a side-by-side listing of restaurant and attraction names per file and model, and `pilot_report.json` with average usd per file per model.
  - CLI: `python -m src.library plan --input DIR --library aig-library --out ingest_plan`; `python -m src.library pilot --plan ingest_plan --models claude-sonnet-5-5,claude-haiku-5-5 --count 10 --out pilot_out`; `python -m src.library rebuild --plan ingest_plan --db library_db_new --max-usd N [--estimate-from pilot_out/pilot_report.json --model NAME --dry-run]`. `rebuild` refuses to run without `--max-usd` unless `--dry-run`, refuses `--db library_db`, and with `--dry-run` prints the projected total (average usd per file for `--model` times the count of non-skipped plan entries).

- [ ] **Step 1: Write failing tests** with stub clients: `select_pilot_files` covers old and new format, multi-country and 2+ folders on a synthetic plan of 30 entries; `build_plan` prefers the same-named library folder over classification (stub classifier asserts it is not called); `rebuild --db library_db` exits non-zero; `rebuild` without `--max-usd` exits non-zero; `--dry-run` prints the projection from a sample `pilot_report.json`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** the modules and typer commands (follow the existing command style in `__main__.py`).
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Update docs:** add the three commands to the Commands block of `CLAUDE.md` and describe the new flow in `docs/LIBRARY_BUILD_PIPELINE.md`.
- [ ] **Step 6: Commit** `feat(library): plan, pilot and rebuild commands`.

---

### Task 11: Backup and edit-candidate tools

**Files:**
- Create: `src/library/ingest_core/edits.py`
- Modify: `src/library/__main__.py`
- Test: `tests/library/test_edits.py`

**Interfaces:**
- Produces:
  - `backup_library(db_dir: Path, library_dir: Path, dest: Path, tag: str) -> None` — copies both folders under `dest` (refuses if `dest` exists) and creates the local git tag `tag` (no push).
  - `build_blocklist(audit_path: Path, git_commit: str | None, repo: Path) -> list[dict]` — entries `{city, list, key}` from audit `delete` actions plus items present in `git_commit^` and absent in `git_commit` for each changed `library_db/<City>.json`.
  - `write_edit_candidates(old_db: Path, new_db: Path, git_commit: str | None, repo: Path, out: Path) -> None` — markdown per candidate city (cities changed in `git_commit` plus audit cities) listing old items missing from or different in `new_db`, then a section of old items that lacked `_source_file`, grouped by city, as lower-confidence candidates.
  - CLI: `python -m src.library backup --dest PATH --tag NAME`; `python -m src.library edit-candidates --old PATH --new library_db_new --git-commit d4147e1 --out edit_candidates.md`; `rebuild` loads `build_blocklist(...)` into the new DB through `set_blocklist` when `--blocklist-from-git COMMIT` is given.

- [ ] **Step 1: Write failing tests** with a throwaway git repo built in `tmp_path` (init, commit a shard, commit a version with one item removed): `build_blocklist` returns the removed item; an audit `delete` entry is included; `write_edit_candidates` lists a city whose old item is absent in the new DB; `backup_library` refuses an existing `dest` and creates the tag.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** with `subprocess` calls to `git` (`git show <commit>^:<path>` / `git show <commit>:<path>`); handle files absent on one side.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat(library): backup, blocklist and edit-candidate tools`.

---

### Task 12: Golden set, v2 readiness check and the gated rebuild runbook

**Files:**
- Create: `tests/library/test_golden.py`, `tests/library/golden/` (fixtures), `scripts/check_library_for_v2.py`
- Modify: `docs/superpowers/specs/2026-10-26-library-ingester-redesign-design.md` section 10 (record the chosen golden files)

**Interfaces:**
- Produces: `scripts/check_library_for_v2.py --db PATH` prints, per country shard found via `Library(PATH)`, which of `dishes, souvenirs, etiquette, safety, connectivity, getting_around, health, money` have library content, using `src.aigv2.writing.sections._library_items`. Exit code 1 if a country covered by any past AIG has none of the country-level lists.

- [ ] **Step 1: After the pilot, pick three golden AIGs** (one old format, one new format, one multi-country) and record them in the spec. The user spot-checks the expected items.
- [ ] **Step 2: Write `test_golden.py`:** for each golden file load a recorded extraction (`golden/<name>.extraction.json`, saved from the pilot's chosen model) and the hand-checked `golden/<name>.expected.json` (list name → item identity keys that must be present, and keys that must be absent, such as a client name); assert via `clean_extraction` + `merge_extraction` into an in-memory DB. No model calls.
- [ ] **Step 3: Write `scripts/check_library_for_v2.py`** and a smoke test that runs it on a tiny synthetic DB.
- [ ] **Step 4: Run `pytest tests/library -v`; expect all PASS.**
- [ ] **Step 5: Commit** `test(library): golden set and v2 readiness check`.
- [ ] **Step 6: Gated runbook (user approves each gate; nothing below runs ahead of its gate).**
  1. `plan` over `input/for-aigv2/all-aigs` → user reads `order_report.md` (the files ordered by format or name fallback) and the folder assignments in `plan.json`; user corrects any.
  2. `pilot` with both models → user reads `pilot_report.md`, picks the model. Set it as `AI_MODEL`.
  3. `rebuild --dry-run --estimate-from ... --model <chosen>` → user approves a `--max-usd` ceiling.
  4. `backup --dest ~/library_backups/<date> --tag library-pre-rebuild-2026-10-26`.
  5. `rebuild --db library_db_new --max-usd <ceiling> --blocklist-from-git d4147e1`; local machine, resumable by re-running the same command.
  6. `python -m src.library verify --db library_db_new` and `qc --db library_db_new`; `scripts/check_library_for_v2.py --db library_db_new`.
  7. `edit-candidates --old <backup>/library_db --new library_db_new --git-commit d4147e1 --out edit_candidates.md`; the team skims it in the UI and re-applies what matters.
  8. User approves swapping: move `library_db` aside and `library_db_new` into place; carry over `_review_status` by city name; restart the UI server.
