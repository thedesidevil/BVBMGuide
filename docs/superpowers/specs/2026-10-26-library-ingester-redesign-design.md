# Library Ingester Redesign — Design

Date: 2026-10-26. Status: draft for review. Branch: `aigv2`.

## 1. Intent

AIG v2 (the engine under `src/aigv2/`) now writes most of a guide from the library. The library, built years before v2 existed, holds only part of what v2 consumes, and its ingester has behaviours that fight how the team works. We are rebuilding the library from the 287 past AIGs in `input/for-aigv2/all-aigs/` with a redesigned ingester, so that:

- every content type v2 reads exists in the library, in the shape v2 expects;
- newer AIGs reliably overwrite older ones;
- there is one ingest path, used by both the CLI (`python -m src.library`) and the web UI;
- future AIGs (including ones v2 itself produced) can be ingested without polluting the library.

The user's team does the extraction on a local machine. Lambda deployment of ingestion is not in scope.

## 2. Goals, non-goals, anti-goals

**Goals**
1. Add the missing content types (section 5).
2. Newer-wins conflict rule with reliable ordering (section 6).
3. One code path for CLI and UI ingest, same dedup and provenance.
4. Country-level content extracted directly, not aggregated from city shards.
5. Protect the team's manual library edits with a small review workflow and a manual-protection flag (section 8).
6. Pilot the extraction on ~10 files with two models before the full run, and report cost (section 9).

**Non-goals**
- Google Places data at ingest. Deferred by the user as too expensive (about $200 estimated for ~6,000 entries; the $0.035/search price in `src/aigv2/config.py` is unconfirmed). Memory item `google-data-at-ingest-deferred` records a reminder to revisit it. The schema must keep optional room for it (section 5.1).
- Photos and other new AIG v2 features.
- Lambda deployment of ingestion, or changing which model AIG v2 itself uses.
- Changing how the AIG v2 engine reads the library, except where a new field makes something it already does easier. The reader (`src/aigv2/library.py`) and the section writers must keep working unchanged against the new shards.

**Anti-goals** (failure even if it technically works)
- Client-specific text (names, dates, bookings, "your hotel") ending up in the library as if it were reusable fact.
- `⚠`-marker or VERIFY text from v2-generated guides being ingested as library facts.
- Silent loss of the team's manual edits or of items they deliberately deleted.
- Two ingest paths drifting apart again.

## 3. Constraints

- Keep existing shard file names and field names that v2 reads: per-city `restaurants, attractions, hotels, local_dishes, souvenirs, phrases, safety_tips, emergency_contacts, connectivity_tips, transport_options, health_tips`, optional `currency`; `_index.json` with `_folder_coverage`; `_country/<name>.json`.
- Existing shards are sharded JSON in `library_db/` (482 files; 33 country shards). The UI (`ui-frontend`, Library & QC tabs) reads the same files and must keep working.
- Extraction model: **`claude-sonnet-5-5`** (set in `.env` as `AI_MODEL` by the user), compared in the pilot against **`claude-haiku-5-5`**. The AI client wraps an OpenAI-compatible endpoint (`src/common/ai_provider.py`); its pricing table only knows `claude-sonnet-4` and `claude-haiku-4`, so `claude-sonnet-5` ($2/$10 per M tokens) and `claude-haiku-5` ($0.10/$0.50 up to 100K-token prompts, $0.50/$2.50 beyond) must be added or cost will show as $0. Whether these models answer through the user's endpoint and accept the current request shape must be confirmed in the pilot.
- No Google calls during ingest. No interactive prompts in the flow.
- Never suggest `--force` rebuild shortcuts casually (user rule); this redesign is an explicit, approved full rebuild.

## 4. Current state (what exists)

- `LibraryBuilder.process_single_file` (`src/library/builder.py`): CLI path. One AI extraction per file with `LIBRARY_EXTRACTION_PROMPT` (`src/common/doc_extractor.py`), chunked for long documents, stamps `_source_file` and `_source_mtime` on every item, appends to shards.
- `IngestService.persist` (`src/library/ui/services/ingest_service.py`): UI path. Same extraction, but **skips** a new item when an item with the same name exists (older wins), appends tip-type items with no dedup, and does not stamp `_source_mtime`.
- `country_extractor.py`: builds `_country/*.json` by aggregating city shards. Result is thin (e.g. one country shard holds two transport items and nothing else).
- Library today: 3,287 restaurants, 550 hotels, 2,152 attractions, no `currency` anywhere, no per-restaurant meal slot, no `notes`, no structured SIM/country content. About 1,635 attractions and 2,427 restaurants carry no source marker.
- Audit log `library_db/_audit.json` has 9 entries, all test data from one user on one day. Normal UI edits are not logged.

## 5. What changes in the data

### 5.1 Shared item rules
Every item in every list gets provenance: `_source_file`, `_source_date` (the ordering date, section 6), `_source_format` (`new`|`old`). Items may also carry optional, initially empty place fields for the later Google work: `place_id, lat, lng, status, hours_structured, maps_url, website, phone, fetched_at`. Nothing in this project fills them.

### 5.2 New or extended content
The recurring-content counts in `docs/aigv2/2026-10-20-past-aigs-findings.md` section C show these appear in most past guides. All of it is extracted once into the library; v2 then formats it instead of writing it.

| Content | Where | Shape (minimum) |
|---|---|---|
| Currency | city shard `currency` (ISO code) and country shard | `"EUR"`; v2's `city_currency` already reads it |
| Plugs / voltage | country shard `plugs` | `{type, voltage}` |
| Tipping | country shard `tipping` | text items, per country |
| Dos and don'ts | country shard `dos_donts` | text items |
| Common scams | country shard `scams` | text items |
| Travel insurance advice | country shard `insurance` | text items |
| Recommended apps | country shard `apps` | `{name, purpose}` |
| Forex / cards / ATMs | country shard `money` | text items; never exchange rates |
| Transit cards and rail passes | country or city `transport_options` | extend with `how_to_use`, `covers` |
| Embassy / consulate | country shard `embassies` | `{name, address, phone, email, after_hours, city}` |
| SIM / eSIM | `connectivity_tips` extended | `{provider, kind, price_text, coverage_countries, notes}`; multi-country eSIM supported |
| Attraction fees, dress code, visit tips | attraction item | `entry_fee` (existing), plus `dress_code`, `tips` |
| Getting around how-to | `transport_options` item | `how_to_use` text |
| Which meal a restaurant was used for | restaurant item `meal_slots` | list of `breakfast|lunch|dinner`; v2 QC warns on a dinner place in a lunch slot |
| Restaurant `notes` | restaurant item | free text; v2 diet matching already reads it |
| Weather / season | city or country shard `season_notes` | text items |
| Drive-day stop sequences | `route_guides` (new list) | `{from, to, stops: [{name, minutes, suggested_stop}], total_km, total_time}` |

Facts containing prices or provider names are stored as written; v2 already marks those VERIFY at write time, so ingest does not drop them. Library hours stay as written text; v2 already rejects implausible hours.

### 5.3 Dropped on purpose
- Client-specific text: names, travel dates, booking references, "your hotel", itinerary-day wording. The prompt must say so and the post-processor must reject items matching client-name/booking patterns.
- Any text containing `⚠`, "VERIFY", "ADD RESTAURANT", "PRICE UNKNOWN", "WRITE PERSONAL LETTER", "CHECK:" (v2 marker strings from `Marker.render`) is dropped before dedup. Detection is by text patterns, plus an exact check: a file carrying the invisible v2 run id (custom document property `bvbm_run_id`) is recognised as v2-generated. The ingester reads that property; stamping it is the generation feedback-loop project (section 13).
- Assistant chatter ("I would recommend", "Here are clear…") is dropped (same patterns as v2's `assistant_chatter` QC rule).

## 6. Ordering and the conflict rule

**Process oldest to newest; the newer AIG's version of an item overwrites the older one.** An item's identity is its normalised name within its city (and for tip-type lists, normalised text). When an item is overwritten, the older record is not kept, but the replaced `_source_file` is noted in `_replaced_from` for traceability.

**Ordering date, per file**, in this order of preference:
1. If the file's modified date is not shared with a large group of other files, use it. (117 of the 287 files share the same modified date, 2026-03-01 — a bulk copy — so that date is treated as untrustworthy when more than a handful of files share it.)
2. Otherwise use the **travel dates inside the AIG** (the latest day date in the document).
3. If that is missing or ambiguous, **format wins**: a new-format AIG (day-per-paragraph / heading style) is treated as newer than an old-format AIG (one table row per day). Old format is detected by a day table; this detection is part of the build.
4. Remaining ties: file name order, and the choice is recorded in the run log.

Items from the old format never overwrite items from the new format for the same identity, whatever the dates say (user instruction: newer-format data is more accurate).

Exact duplicate files (208 unique texts across 287 files) are processed once.

**Dating details (my call).** Ordering is resolved before any paid extraction: a free pre-pass reads each file's text (no AI) to find the day dates and detect the format, so the processing order is fixed up front and can be shown to the user. A modified date shared by more than 5 files is treated as a bulk-copy date. Day dates without a year take the year of the file's modified date; if that is itself a bulk-copy date, the file is flagged in the run log for the user to date by hand.

**Measured limit of the pre-pass (2026-10-26).** Inferring the year from weekday-plus-date day headers resolves only 24 of the 117 bulk-dated files (and 39 of 170 others); the rest have no weekday dates. So for roughly 90 bulk-dated files the order comes from format (new beats old) and then file name. The run log lists every file ordered by that last fallback so the user can correct the order before the paid run.

## 7. One ingest path

A single module, `src/library/ingest_core.py`, owns: file → text → extraction → clean (section 5.3) → ordered merge into shards → provenance → index/coverage → country shards. `LibraryBuilder.process_single_file`, `LibraryIngester`, and `IngestService.persist` become thin callers. The UI keeps its upload/classify/review steps and then calls the shared merge. Result: identical dedup, provenance and conflict behaviour from both paths.

Country content is extracted in its own call per country folder (not aggregated from city shards): the same document pass emits country-level lists into `_country/<name>.json` directly, and city shards keep only city-level content. The folder→country mapping uses the existing `_folder_coverage`.

**Item identity (my call).** A normalised name (casefolded, accents stripped, leading "the" dropped, punctuation and whitespace collapsed), scoped to the city shard the item lands in. Text items (tips, tipping, scams, etc.) use exact normalised text only: no fuzzy or semantic matching in this version, so a paraphrase can leave a near-duplicate. To limit that, the prompt asks for short canonical wording.

**Multi-country folders (my call).** Each country-level item carries the country or countries it applies to and is written to every country shard it applies to. A multi-country eSIM is stored in each applicable country shard, with `coverage_countries` listing all of them. Folders such as "Dubai and Abu Dhabi - UAE" and "Singapore and Malaysia" therefore feed more than one country shard.

**Replaced items (my call).** The ingest result reports added, replaced and skipped counts per city and writes the replaced list to the run log. The UI ingest summary shows the counts; there is no per-item conflict screen. The UI and v2 readers must ignore unknown fields (v2's reader already does).

## 8. Protecting manual edits

The team's hand edits to the library are precious and must not be lost. Decided with the user: **a hand-edited item stays** when a later AIG disagrees (it is marked manual and protected from overwrite, and the disagreement is listed for review). The user does not remember what was edited or when, and the evidence points to little: the audit log has 9 test entries, the only commit labelled as hand edits (`d4147e1`, May 2026) touched three cities (Bukhara, Cairns, Samarkand), and the August 2026 full rebuild (`7620acf`) rewrote the library after it. Nothing has changed in `library_db` since. So this section is a small review workflow, not a replay tool.

1. **Back up first**: tag the current git state and copy `library_db/` and `aig-library/` outside the repo. No nuking before this exists. The rebuild then starts from an **empty** library (user: "nuke and start over").
2. **Find candidate edits**, cheaply and honestly:
   - the changes in `d4147e1` (Bukhara, Cairns, Samarkand) and the 9 audit entries;
   - items in the current library that carry no provenance marker (about 1,635 attractions and 2,427 restaurants lack one). These are candidates only; most are probably old extraction output, not edits;
   - review statuses: 6 cities pending, 5 in progress, none reviewed.
3. **After the new build**, produce `edit_candidates.md`: for each candidate city, the old items missing from or different in the new library. The team skims it in the UI and re-applies anything worth keeping. Anything re-applied or re-added through the UI is stamped manual and protected from overwrite from then on.
4. **Deletions**: items removed in `d4147e1` and by the audit log become a blocklist applying to the main build and to later ingests (my call).
5. Review statuses are carried over by city name where the city still exists.
6. The clean-rebuild diff idea is dropped: with a non-deterministic AI step it would be mostly noise.

**Manual protection in the data model**: an item edited or added through the library UI gets `_manual: true` and `_manual_by`/`_manual_at`. The ordered merge in section 6 never overwrites a `_manual` item; if the newer AIG's version differs, it is written to the city's `_conflicts` list for review. The UI edit and add paths must set the flag.

## 9. Pilot, then full run

- **Pilot**: ~10 files chosen to cover old format, new format, a very long guide (multi-chunk), a multi-country trip, and one from each of two regions. Run the same files through `claude-sonnet-5-5` and `claude-haiku-5-5`. Report per file: tokens, cost, items per content type, and a side-by-side diff of extracted items. The report is shown to the user, who picks the model. The user judges quality from the side-by-side diff; there is no automatic threshold. If either model does not answer through the endpoint, the pilot reports that and stops rather than substituting another model (my call).
- **Full run**: runs only after the user approves the pilot's model and cost projection (208 unique documents). Checkpoints every 10 files (the builder already does this) so an interruption does not lose work. Run locally. The projected total cost is shown first, and the user approves it or sets a ceiling before the run starts.
- The pilot also confirms the two models answer through the user's endpoint and that prompt size stays within limits with the larger extraction prompt.

## 10. Verification

- Unit tests for: ordering-date selection (including the 117-file case and old-vs-new format), newer-overwrites-older, old-format-never-overwrites-new, marker/client-text rejection, tip dedup on re-ingest (ingesting the same file twice changes nothing), both entry points producing identical shards from the same extraction.
- A small golden set: 3 hand-checked AIGs whose expected extracted items are asserted. I pick the three candidates (one old-format, one new-format, one multi-country) and the user spot-checks the expected items (my call).
- After the full run: `python -m src.library verify` and `qc` pass, UI loads, and an AIG v2 test trip builds against the new library with the section writers finding currency, SIM, plugs, tipping and embassy content for its country.

## 11. Left to the builder

- Prompt wording and JSON schema details for the new fields, within section 5.2.
- Exact normalisation rules for item identity (names with accents, "The", punctuation).
- How old-format detection is implemented, as long as section 6's behaviour holds.
- Chunking strategy for the larger prompt.
- Whether `route_guides` and `season_notes` need UI editing support now or later.

## 12. Open items for the user

None. The user's answers on 2026-10-26: a hand edit stays when a later AIG disagrees; the user does not remember the earlier edits, so section 8 is a small review workflow.

Calls made after the builder check are marked "my call" in sections 5.3, 6, 7, 8, 9 and 10. Decisions to confirm by reading: the model comparison (Sonnet 5.5 vs Haiku 5.5), the edit-review approach in section 8, and dropping client-specific text at ingest.

## 13. Follow-on, not in this project: generation feedback loop

User idea (2026-10-26): keep each generated guide in S3 with an invisible id embedded in the .docx, compare the team's corrected copies against what the program produced, and update the logic or the library from the differences; also write information learned during generation into the library to reduce Google spend. This is a separate project with its own design, after this one. Two points touch this design: (1) the ingester already reads the `bvbm_run_id` property to recognise v2-generated files (section 5.3); (2) writing learned data into the library reverses the earlier decision that nothing is saved to the library during generation, so that is confirmed with the user before that project starts. Recorded in memory as `generation-feedback-loop`.
