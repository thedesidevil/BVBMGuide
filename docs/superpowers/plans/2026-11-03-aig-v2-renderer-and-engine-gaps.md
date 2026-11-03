# AIG v2 New Look: Engine Gaps + Renderer Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AIG v2 engine produce the structured data the locked "Direction 7 v5 Harbour" design needs, and replace the current docx renderer with one that builds that design, so the three test guides (Dilna Bali, Jumana Lisbon, Sneha Europe) come out in the new look.

**Architecture:** Add a renderer-agnostic *guide model* (pydantic, JSON-serialisable: pages made of components such as `SightseeingCard`, `MealBlock`, `FactRow`) between the engine and the docx writer. A new `src/aigv2/render2/` package turns the model into a docx using helpers copied from the design prototype (`.superpowers/lookfeel/`). The old `src/aigv2/render/` stays working until the new one passes QC on all three trips, then is removed. A future HTML/tabbed-app renderer reads the same guide model.

**Tech Stack:** Python 3.14, python-docx, pydantic v2, pytest, Pillow (assets), LibreOffice (`soffice`) for preview PNGs only.

**Spec:** Design = `.superpowers/lookfeel/PATTERNS.md` + `.superpowers/lookfeel/LOCKED_d7_v5/` + `.superpowers/lookfeel/sample_all.py`/`content2.py`/`sample_all.docx` (27-page reference). Engine design = `docs/superpowers/specs/2026-10-19-aigv2-design.md`. Decisions = memory note `project_aig_look_and_feel.md`.

## Global Constraints

- **Models:** every Agent dispatch passes `model: "sonnet"` (Sonnet 5.5) or `"haiku"`; never Opus/Fable. No Google or LLM calls in tests (fakes only). Never run `python3 -m src.aigv2 start/build/regenerate` inside a task (real spend); only the milestone "live run" steps do, and only when the user says so.
- **Palette (official, with the derived dark gold for small text):** Royal `3A6CB5`, Crimson `D92027` (one title word only), Navy `0C1F3E`, Ink `12294B` (body), Powder `AEC7E7`, Frost `F4F6FA`, Slate `4A525E`, Taupe `C4B3A1`, Amber `DEA350` (bars/diamonds/underlines, never text), Gold ink `8F5A16` (small gold text), Harbour fill `EDF3FB`, Harbour edge `BCD0EA`, card edge `D3DFEF`, taupe tint `F3EFEA`. All text pairs >= 4.5:1.
- **Fonts:** headings Cormorant Garamond (altName Garamond in the font table), body Georgia 10 pt at 1.45 leading. No emoji anywhere.
- **Voice:** third-person descriptive about places, "you/your" for the client, imperative tips; never we/our/us (letter and Thank You are exempt only where signed by the agency). Hours, prices, minutes copied verbatim from data.
- **Logo rule:** vertical lockup is default; horizontal only in running header/footer strips; icon for tiny marks. Logo files live in `/Users/mjain/work/projects/travel/BVBMWebsite/01 BVBM Final Logo Assets/RGB File (For Digital)/PNG/` (crop to alpha bbox, downscale to ~1600 px before embedding; commit the cropped copies under `src/aigv2/render2/assets/`).
- **Output:** DOCX only, A4. Page background: VML gradient white -> `F4F6FA`@18% -> `EEF3FA` plus `displayBackgroundShape`. Every page type starts a new section; `w:pgNumType` start set ONLY on the first section (strip it from sections added later).
- **Opening letter:** NOT generated. Render a clearly marked placeholder page for the team (marker `WRITE_LETTER`). **Thank You** page text IS generated in the hand-curated voice.
- **Google spend:** none at ingestion. Tests never touch the network.
- **QC must keep working:** `src/aigv2/qc/reader.py` reads the finished docx by heading levels/style names and text patterns (`DAY_RE = ^Day\s*(\d+)\s*[–—:\-|,]`, `MEAL_SLOT_RE`, `Getting there:`, slot words). The new renderer must emit the same semantic anchors (see Task 6).
- **Process:** TDD, one commit per task, full suite green before each commit (`python3 -m pytest tests -q --ignore=tests/hotel_options/test_decoder.py`, baseline 1240 passed). `git add` only the task's files. Never touch `library_db`, `library_db_new`, `aig-library`, `aigv2_data`, `~/library_backups`, or the untracked `ingest_plan_extra/`. No pushing/merging/deploying inside tasks.
- **Fixtures:** replay data (read-only) = `/Users/mjain/library_backups/aigv2_bali_2026-11-02/run_rebuild8/`; copy small sanitised slices into `tests/aigv2/fixtures/` (dummy client names).

## Review Focus

1. **A day with no restaurants / all `ADD_RESTAURANT` markers** (library has none): the MealBlock must render the PlaceholderMeal footprint, never crash or leave an empty card.
2. **Very long names/descriptions** (a 90-character restaurant name, a 600-character blurb) must wrap inside cards without overflowing the right stack or splitting a card across pages.
3. **Single-day trips, domestic trips, cruise days** (no hotel, no flights): opener/cards degrade gracefully; no `None` text, no missing section crash.
4. **Missing optional data** (no hours, no price, no maps link, no place match): the card shows the review marker instead of blank labels like "Open  –".
5. **QC round-trip:** a rendered docx must be fully parseable by `qc/reader.py` (days, slots, venues, markers) so QC findings still land on the right paragraph.

---

## Milestone map (each ends in something that works; stop after any of them)

| M | Delivers | Tasks | Live spend |
|---|---|---|---|
| **M1** | Guide model + structured data contracts (no visual change; old renderer unchanged) | 1-4 | none |
| **M2** | Engine fills the content gaps (Day 1/5/7/8 facts, structured reference sections, Thank You writer) | 5-10 | small AI only if the user runs a build |
| **M3** | New renderer foundation (assets, fonts, theme, sections, header/footer, TOC) | 11-14 | none |
| **M4** | New renderer: day pages (all cards, meal blocks, placeholders, markers) | 15-19 | none |
| **M5** | New renderer: reference sections + letter/thank-you; old/new switch; QC compatible | 20-24 | none |
| **M6** | Live test guides + comparison + fixes (Dilna, Jumana, Sneha) | 25-27 | ~$2 per guide, user approves each |

M1-M2 improve data without changing the output. M3-M5 can be tested on saved runs without any spend.

---

## M1 - Guide model

### Task 1: Guide-model schema

**Files:**
- Create: `src/aigv2/guide/__init__.py`, `src/aigv2/guide/model.py`
- Test: `tests/aigv2/test_guide_model.py`

**Interfaces:**
- Produces (all pydantic v2, `model_config = ConfigDict(extra="forbid")`):
  - `Link(text: str, url: Optional[str] = None)`
  - `Fact(label: str, value: str, link: Optional[Link] = None)`
  - `MarkerRef(kind: Literal["ADD_RESTAURANT","VERIFY","PRICE_UNKNOWN","WRITE_LETTER","CHECK"], text: str)`
  - Components, each with `type: Literal[...]` as discriminator: `Opener`, `YourDay`, `JourneyStrip`, `SightseeingCard`, `BookingCard`, `ChecklistCard`, `OptionCards`, `MealBlock`, `PlaceholderMeal`, `ReviewMarkerBlock`, `ReferenceOpener`, `FactRowBlock`, `TitledParas`, `ChecklistGroups`, `TipPanel`, `NotePanel`, `AppGrid`, `PlaceGroups`, `DishGrid`, `SouvenirGrid`, `DosDonts`, `PhraseTable`, `EmergencyStrip`, `ContactCards`, `Letter`, `ThankYou`
  - `Page(kind: Literal["letter","toc","day","reference","thank_you"], title: str, bookmark: str, components: list[Component])`
  - `Guide(client: str, destination: str, title: str, subtitle: str, pages: list[Page])`
- Field lists per component follow `PATTERNS.md` "Data fields" column exactly (e.g. `MealBlock(meal: Literal["breakfast","lunch","dinner"], eyebrow: str, heading: str, restaurants: list[Restaurant])`; `Restaurant(name, maps_url, cuisines: list[str], veg: bool, text: str, must_try: str, hours: str, price: str | MarkerRef, travel: str)`).

- [ ] **Step 1: Write the failing test.** `test_guide_round_trip`: build a `Guide` with one page of each kind and 3 components, `Guide.model_validate_json(g.model_dump_json()) == g`. `test_unknown_field_rejected`: a `SightseeingCard` with `colour="red"` raises `ValidationError`. `test_component_discriminator`: parsing `{"type":"MealBlock",...}` yields a `MealBlock`.
- [ ] **Step 2: Run to verify failure** `python3 -m pytest tests/aigv2/test_guide_model.py -q` -> FAIL (import).
- [ ] **Step 3: Implement** the models above in `src/aigv2/guide/model.py` (one tagged union `Component = Annotated[Union[...], Field(discriminator="type")]`).
- [ ] **Step 4: Run** -> PASS. **Step 5: Commit** `feat(guide): renderer-agnostic guide model`.

### Task 2: Build the guide model from a finished run (days, no new data yet)

**Files:**
- Create: `src/aigv2/guide/build.py`
- Test: `tests/aigv2/test_guide_build.py`, fixture `tests/aigv2/fixtures/bali_guide/` (copy of `GuideData` JSON slices)

**Interfaces:**
- Consumes: `GuideData`, `RenderDay` from `src/aigv2/render/document.py`.
- Produces: `build_guide(data: GuideData, settings) -> Guide` and per-day helper `build_day_page(rd: RenderDay, data: GuideData, settings) -> Page`.

- [ ] **Step 1: Failing tests** on the Bali Day 2 fixture: `test_day2_components_order` (Opener, YourDay, SightseeingCard(breakfast-as-simple), SightseeingCard, SightseeingCard, MealBlock(lunch), SightseeingCard, BookingCard(return), MealBlock(dinner)); `test_meal_block_has_three_restaurants_with_links`; `test_no_restaurants_gives_placeholder_meal` (Review Focus 1); `test_missing_hours_gives_marker_not_blank` (Review Focus 4).
- [ ] **Step 2-4:** run (FAIL) -> implement `build_guide`/`build_day_page` mapping existing `DayRenderer` logic (arrival/departure/check-in, timeline slots, drive stops, meals via `rd.meals`, prices via `rd.price_by_restaurant`) into components -> PASS.
- [ ] **Step 5: Commit** `feat(guide): build day pages from a finished run`.

### Task 3: Reference-section pages from existing prose sections

**Files:** Modify `src/aigv2/guide/build.py`; Test `tests/aigv2/test_guide_build_sections.py`.

**Interfaces:**
- Produces: `build_reference_page(key: str, content: SectionContent, data: GuideData) -> Page` for keys in `BEFORE_YOU_GO + WHILE_THERE` (import from `render.document`), using `ReferenceOpener` + `TitledParas` for every key as a temporary generic mapping (structured components arrive in M2).
- `build_important_page(entries: list[ImportantPlaces]) -> Page` using `PlaceGroups` (one group per hotel; Pharmacies/Groceries/Hospital columns; walk/car minutes; hours text).

- [ ] **Step 1: Failing tests** `test_every_present_section_has_a_page`, `test_important_places_groups_per_hotel`, `test_markers_carried_as_markerrefs`.
- [ ] **Steps 2-5:** implement, PASS, commit `feat(guide): reference and important-places pages`.

### Task 4: Persist the guide model in the run and expose it

**Files:** Modify `src/aigv2/pipeline.py` (`_render_qc`: after `GuideData` is built, `store.save_json("guide.json", build_guide(...))`); Modify `src/aigv2/__main__.py` (add `python3 -m src.aigv2 guide-json <run_id>` that prints the path); Test `tests/aigv2/test_pipeline.py::test_guide_json_saved`.

- [ ] **Step 1:** failing test using the existing fake-deps pipeline test harness: after `build_run`, `store.has("guide.json")` and it validates as `Guide`.
- [ ] **Steps 2-5:** implement, PASS, full suite, commit `feat(aigv2): save guide.json next to guide.docx`.

---

## M2 - Engine content gaps

### Task 5: Late-arrival flag and driver time

**Files:** Modify `src/aigv2/render/document.py` (`RenderDay`: add `lands_next_day: bool = False`, `driver_from: Optional[time] = None`), `src/aigv2/pipeline.py` (`_render_days` fills them using `planning/late_night.py`), `src/aigv2/guide/build.py` (Day 1 cards use them); Test `tests/aigv2/test_guide_build.py::test_day1_late_arrival_cards`.

**Interfaces:** `planning/late_night.py` already exposes `AIRPORT_PICKUP`; add `driver_time(booking: Booking) -> Optional[time]` parsing "driver will come ... at 11:00 PM" from `Booking.instructions` (use `slots.parse_time`).

- [ ] **Step 1:** tests: flight card text `Lands 00:10 on Fri 25 Sep`; transfer card `driver booked from 11:00 PM and waits for your arrival at 00:10`; no meal blocks on Day 1.
- [ ] **Steps 2-5:** implement/PASS/commit `feat(aigv2): late-night arrival facts for the Day 1 cards`.

### Task 6: Transfer, boat and crossing facts

**Files:** Modify `src/aigv2/models.py` (`TransportLeg`: add `duration_min: Optional[int] = None`, `check_in: Optional[datetime] = None`), `src/aigv2/intake/extract.py` (prompt asks for boat check-in and crossing duration only if stated in the voucher; never invented), `src/aigv2/pipeline.py` (`_boat_legs` keeps parsed `departs`/`check in` times; drive time hotel->harbour from `compute_legs`), `src/aigv2/guide/build.py` (JourneyStrip + BoatCard); Test `tests/aigv2/test_pipeline.py::test_boat_leg_facts`, `tests/aigv2/test_guide_build.py::test_journey_strip_day5`.

**Interfaces:** `JourneyStrip(stops: list[Link], legs: list[str], times: list[str])` (legs like `Approx. 60 min by car`).

- [ ] **Step 1:** tests on the saved Bali Day 5: strip = Mayura Ubud Retreat -> Sanur Harbour -> D'Nusa Beach Club and Resort; times `Leave 7:00 AM`, `Check-in 8:15 AM · Departs 9:15 AM`; leg 1 `Approx. 60 min`; crossing text absent (not invented) unless the voucher states it.
- [ ] **Steps 2-5:** implement/PASS/commit `feat(aigv2): boat and transfer facts for journey strips`.

### Task 7: Open choices as options; Sanur Harbour leg on Day 7

**Files:** Modify `src/aigv2/planning/slots.py` (`ScheduledItem` gets `option_group: Optional[str] = None`; open-choice items with `answer == "both"` share a group and are NOT scheduled sequentially), `src/aigv2/pipeline.py`, `src/aigv2/guide/build.py` (OptionCards with `own_expense: bool`, `best_later_note`), `tests/aigv2/test_slots.py`, `tests/aigv2/test_guide_build.py::test_day7_option_cards`.

- [ ] **Step 1:** tests: Day 7 has a BoatCard (12:00 boat), a transfer-to-hotel card, one OptionCards block with two options, Icon Mall hours `10:00 AM – 10:00 PM`, Sindhu `5:00 PM – 10:00 PM` + note `Best visited later in the day`; dinner block after.
- [ ] **Steps 2-5:** implement/PASS/commit `feat(aigv2): open choices render as options`.

### Task 8: Departure-day facts (leave-by, checklist, airport place)

**Files:** Modify `src/aigv2/guide/build.py`; Modify `src/aigv2/pipeline.py` (airport place via `_endpoint`, already "X airport"); new `src/aigv2/guide/departure.py` with `departure_checklist(travellers: Traveller, international: bool) -> list[str]`; Test `tests/aigv2/test_guide_departure.py`.

**Interfaces:** checklist = `Passports and travel documents`, `Flight tickets and boarding passes`, `Phones and chargers`, `Any medication`, plus `Your child's essentials` only when a traveller is under 12, `Small snacks and water for the airport`, `Valuables and souvenirs` (fixed list; no AI).

- [ ] **Step 1:** tests: child present adds the child line; domestic trip omits passports; transfer card shows `Leave Taksu Sanur at approximately 9:30 AM, giving about 3½ hours before the 13:15 departure` using `slots.leave_by`.
- [ ] **Steps 2-5:** implement/PASS/commit `feat(aigv2): departure day card facts`.

### Task 9: Structured reference sections

**Files:** Modify `src/aigv2/writing/sections.py` (add `SectionContent.groups: list[SectionGroup]` where `SectionGroup(title: str, items: list[SectionItem])`; prompts ask for grouped output for `packing`, `connectivity` (apps), `etiquette` (do/dont/phrases), `safety` (numbers, consulate), `dishes` (+`places: list[str]`), `souvenirs` (+`what`, `places`)); Modify `src/aigv2/guide/build.py` to map each key to its components (`ChecklistGroups`, `AppGrid`, `DosDonts`, `PhraseTable`, `EmergencyStrip`, `ContactCards`, `DishGrid`, `SouvenirGrid`, `FactRowBlock`, `NotePanel`, `TipPanel`); Test `tests/aigv2/test_writing.py` (fake LLM returns grouped JSON; validator rejects invented numbers/names as today), `tests/aigv2/test_guide_build_sections.py`.

**Interfaces:** library lists from `Library.country(...)` (`plugs`, `tipping`, `dos_donts`, `scams`, `apps`, `phrases`, `emergency_contacts`, `embassies`, `money`) are used directly where already structured; the LLM only groups/rewrites in the guide voice and may not add facts (existing `_validator` rules stay). Dish "where to try" names must come from the day plan's chosen restaurants (links from `places`).

- [ ] **Step 1:** tests per key: packing has the eight group titles in order; child group appears iff a child < 12; safety numbers come only from library `emergency_contacts`; consulate shown only for Indian missions; motion-sickness rule present iff child < 12 (existing `_child_rule`).
- [ ] **Steps 2-5:** implement/PASS/commit `feat(aigv2): structured reference sections`.

### Task 10: Thank You writer and Important Places gaps

**Files:** Create `src/aigv2/writing/thanks.py` (`write_thank_you(trip, llm) -> ThankYouText(paragraphs: list[str], sign_off: str)`, voice rule from `writing/voice.py`, validator: no we/our/us, <= 2 paragraphs, mentions destination); Modify `src/aigv2/pipeline.py` (`_write` job `sections/thanks.json`); Modify `src/aigv2/planning/important_places.py` (when a hotel has no pharmacy within 10 min walk, also search by car radius 3 km once; mark groceries without hours with the existing VERIFY); Test `tests/aigv2/test_writing.py::test_thank_you`, `tests/aigv2/test_important_places.py`.

- [ ] **Step 1:** tests: fake LLM output containing "we" is retried then rejected; fallback text is the agency's fixed closing (copy from the hand-curated guide) when the LLM fails twice; Mayura-like hotel gets a car-radius pharmacy.
- [ ] **Steps 2-5:** implement/PASS/commit `feat(aigv2): Thank You writer and important-places pharmacy fallback`.

**Checkpoint M2:** full suite green; replaying the saved Bali run through `build_guide` yields all component kinds with real data. Stop here if needed: the engine data is richer and the old renderer is untouched.

---

## M3 - Renderer foundation

### Task 11: Assets, fonts and theme

**Files:**
- Create: `src/aigv2/render2/__init__.py`, `src/aigv2/render2/theme.py`, `src/aigv2/render2/assets/` (cropped logos: vertical colour `logo_v1.png`, vertical white `logo_v2.png`, horizontal colour `logo_h1.png`, icon colour `icon1.png`, `diamond_gold.png`, `ornament.png`), `src/aigv2/render2/fonts.py`
- Test: `tests/aigv2/test_render2_theme.py`

**Interfaces:** `theme.py` exports the palette constants (names as in Global Constraints), `HEAD="Cormorant Garamond"`, `HEAD_FALLBACK="Garamond"`, `BODYF="Georgia"`, `GRAD` (VML string), `contrast(fg, bg) -> float`, `PAIRS` (list of (fg,bg) used). `fonts.py`: `embed_fonts(docx_bytes: bytes, ttf_paths: list[Path]) -> bytes` (adds obfuscated `.odttf` parts, `w:embedRegular/Bold/Italic/BoldItalic` in the font table, `w:embedTrueTypeFonts`/`w:saveSubsetFonts` in settings; skips any font whose OS/2 `fsType` forbids embedding) and `find_cormorant() -> list[Path]` (looks in `~/Library/Fonts`, then `src/aigv2/render2/assets/fonts/`).

- [ ] **Step 1: Failing tests:** `test_all_text_pairs_pass_contrast` (every pair in `PAIRS` >= 4.5); `test_logo_assets_are_cropped` (each PNG width <= 1700 px, has alpha); `test_embed_fonts_adds_parts` (docx with 1 TTF: `word/fonts/font1.odttf` exists, fontTable references it); `test_embed_skips_restricted_font`.
- [ ] **Steps 2-5:** implement (crop script `scripts/make_render2_assets.py` run once, outputs committed), PASS, commit `feat(render2): theme, assets and font embedding`.

### Task 12: Low-level docx kit

**Files:** Create `src/aigv2/render2/kit.py` (copy and adapt from `.superpowers/lookfeel/kit.py` + `r2.py`: `new_doc`, `np`, `R`, `link`, `tbl`, `cell_shade`, `cell_borders`, `row_keep`, `bookmark`, `tabs`, `hairline`, `chips`, `ornament`, `diamond_eyebrow`, `review_marker`), `src/aigv2/render2/styles.py` (paragraph styles incl. `Review Marker (internal)` and table style `Placeholder Card (internal)`; Heading 1/2/3 styles map to page title / part heading / card title so `qc/reader.py` levels still resolve); Test `tests/aigv2/test_render2_kit.py`.

- [ ] **Step 1: Failing tests:** `test_link_is_real_hyperlink`; `test_card_row_cant_split` (`w:cantSplit` present); `test_review_marker_style_exists_and_removable` (deleting all paragraphs with that style leaves no ⚠ text); `test_page_number_restart_only_first_section`.
- [ ] **Steps 2-5:** implement/PASS/commit `feat(render2): docx kit and styles`.

### Task 13: Page frame (sections, header, footer, background)

**Files:** Create `src/aigv2/render2/frame.py`: `new_guide_doc(client: str, destination: str) -> Document`, `add_section(doc, kind: Literal["toc","day","reference","letter","thank_you"]) -> tuple[Section, float]` (margins per PATTERNS: TOC 2.0/1.4/1.7/1.4, others 2.2/1.9/2.0/1.9; returns text width cm; strips `pgNumType`), `header_footer(section, label: str)` (label `YOUR ALL-INCLUSIVE GUIDE · {CLIENT} · {DESTINATION}` in caps; horizontal logo; footer contact + PAGE field; `titlepg` True for opener sections); Test `tests/aigv2/test_render2_frame.py`.

- [ ] **Step 1:** tests: header text uses the client first name and destination; first page of a day section has no header; footer carries `+91 86000 15316 · @bonvoyagebymarina · www.bonvoyagebymarina.com`; background XML present once.
- [ ] **Steps 2-5:** implement/PASS/commit `feat(render2): page frame`.

### Task 14: Table-of-contents page

**Files:** Create `src/aigv2/render2/toc.py`: `render_toc(doc, guide: Guide)`; page numbers come from a first pass render (`page_map(docx_bytes) -> dict[str,int]` via LibreOffice text search is NOT used: use Word TOC-free static numbers computed by rendering twice and reading page breaks from `soffice --convert-to pdf` + `pdftotext`; when `soffice` is missing, fall back to PAGEREF fields so Word fills them). Test `tests/aigv2/test_render2_toc.py`.

- [ ] **Step 1:** tests: rows = days + present sections; Day rows are internal hyperlinks (`w:anchor`) to day bookmarks; every number sits on the same right tab; Thank You included; no "Your all-inclusive guide" eyebrow and no "What your guide includes" heading (user removed them).
- [ ] **Steps 2-5:** implement (day cards amber bar; two-column Before/While; gap before second block 14 pt), PASS, commit `feat(render2): contents page`.

**Checkpoint M3:** an empty guide renders to a docx with TOC, header/footer, background; opens in LibreOffice.

---

## M4 - Day pages

### Task 15: Opener, YourDay, JourneyStrip

**Files:** Create `src/aigv2/render2/day_components.py` (first three functions: `render_opener`, `render_your_day`, `render_journey_strip`); Test `tests/aigv2/test_render2_day.py`.

- [ ] **Step 1:** tests: opener text order = `DAY 2 · FRIDAY, 25 SEPTEMBER`, title, intro (no subtitle/prepared-for/pills/glance table); title paragraph is Heading 1 style and its text matches `^Day\s*2\s*[–—:\-|,]` somewhere in the page title OR the eyebrow paragraph so `qc.reader.DAY_RE` finds it (see Task 21); "YOUR DAY" is 12 pt; strip has N stops and N-1 legs.
- [ ] **Steps 2-5:** implement per PATTERNS "Opener/YourDay/JourneyStrip", PASS, commit `feat(render2): day opener and journey strip`.

### Task 16: SightseeingCard, SimpleCard, ChecklistCard

**Files:** Modify `day_components.py`; Tests extend `test_render2_day.py`.

- [ ] **Step 1:** tests: card is a single-row table with `cantSplit`; amber left bar 27/8 pt; title is a hyperlink; a `Getting there` fact paragraph exists as `Getting there:` text for QC; "Good to know" is a diamond list; checklist card is 2 columns; markers inside a card use the `Review Marker (internal)` style.
- [ ] **Steps 2-5:** implement/PASS/commit `feat(render2): sightseeing, simple and checklist cards`.

### Task 17: BookingCard family (flight, transfer, boat, hotel)

**Files:** Modify `day_components.py`; Tests extend.

- [ ] **Step 1:** tests: facts use tiny-caps labels (`FLIGHT`, `FROM`, `TO`, `LANDS`; `MEETING POINT`, `DRIVER`, `VEHICLE`; `CHECK IN`, `DEPARTS`, `CROSSING`, `TYPE`; `ROOM`, `MEALS`, `STAY`, `CHECK-OUT`); reference strip shows `BOOKING REFERENCE <ref>` left and `Included in your package` right only when the data has them; QC `_TRANSPORT_FACTS` words (`DEPARTS`, `ARRIVES`, `SERVICE`, `OPERATOR`) still appear for flights.
- [ ] **Steps 2-5:** implement/PASS/commit `feat(render2): booking cards`.

### Task 18: MealBlock (Harbour) and PlaceholderMeal

**Files:** Create `src/aigv2/render2/meals.py`: `render_meal_block(doc, W, block: MealBlock)`, `render_placeholder_meal(doc, W, block: PlaceholderMeal)`; Test `tests/aigv2/test_render2_meals.py`.

- [ ] **Step 1:** tests: heading is the meal heading (`Lunch near Ubud Palace`) as Heading 2 so `MEAL_SLOT_RE` matches; no italic sub-line under it; Harbour fill `EDF3FB`, royal bar, edge `BCD0EA`; three rows each with name link, chips, text, `Must try`, right stack `PER PERSON / OPEN / FROM HERE`; price `Approx. ` prefix moves to the label; a 90-character name wraps (Review Focus 2); `PlaceholderMeal` has the same footprint with three `ADD RESTAURANT n` rows and uses the placeholder table style; `price` that is a `MarkerRef` renders the marker (Review Focus 4).
- [ ] **Steps 2-5:** implement/PASS/commit `feat(render2): meal blocks`.

### Task 19: OptionCards, ReviewMarkerBlock and the day assembler

**Files:** Modify `day_components.py` (`render_option_cards`, `render_marker_block`); Create `src/aigv2/render2/render.py` with `render_day_page(doc, page: Page)`; Test `tests/aigv2/test_render2_day.py`.

- [ ] **Step 1:** tests: two option cards side by side with an `or` cell; pill `At your own expense` when `own_expense`; whole Bali Day 2/Day 5/Day 7/Day 8 pages (from the guide fixtures) render without exceptions and contain the expected texts in order; Review Focus 3: a cruise day and a one-day domestic trip render.
- [ ] **Steps 2-5:** implement/PASS/commit `feat(render2): option cards and day assembler`.

**Checkpoint M4:** `render_day_page` output for the saved Bali run matches `sample_all.docx` pages 5-17 visually (preview via `soffice` + `pdftoppm`, eyeball; no automated pixel test).

---

## M5 - Reference sections, letter, thank you, switch

### Task 20: Reference components

**Files:** Create `src/aigv2/render2/reference_components.py` (`render_reference_opener`, `fact_row`, `titled_paras`, `checklist_groups`, `tip_panel`, `note_panel`, `app_grid`, `place_groups`, `dish_grid`, `souvenir_grid`, `dos_donts`, `phrase_table`, `emergency_strip`, `contact_cards`); Test `tests/aigv2/test_render2_reference.py`.

- [ ] **Step 1:** one test per component: structure counts (groups, columns), colours (TipPanel Harbour family without outer edge vs NotePanel taupe tint), Do/Don't markers (◆ amber / × crimson), phrase table 2 side-by-side columns, emergency strip 4 cells, `PlaceGroups` card per hotel with `cantSplit`.
- [ ] **Steps 2-5:** implement/PASS/commit `feat(render2): reference components`.

### Task 21: Letter placeholder, Thank You page, full-document assembler

**Files:** Modify `src/aigv2/render2/render.py`: `render_guide2(guide: Guide) -> bytes` (letter placeholder page with `WRITE_LETTER` marker and the first name; TOC; day pages; reference pages; Thank You page with `Thank *You*` crimson italic, contacts as `tel:`/Instagram/web links, tagline, vertical logo; then `embed_fonts`); Test `tests/aigv2/test_render2_document.py`.

- [ ] **Step 1:** tests: page order; the letter page contains the marker and no generated prose; the Thank You text comes from the `Guide`; docx opens with python-docx; fonts embedded when Cormorant files are found; `qc.reader` parses the output: `DocModel.days` has all days, each with slots and venues (Review Focus 5) - assert on the saved Bali guide fixture that `len(model.days) == 8` and every meal slot has >= 1 venue or a marker.
- [ ] **Steps 2-5:** implement/PASS; if the reader misses days, adjust heading styles (Day title paragraph uses Heading 1 with text `Day N – Weekday, D Mon | Title` hidden in the bookmark paragraph only if needed: prefer making the visible eyebrow paragraph Heading 1) and re-test; commit `feat(render2): full document assembler`.

### Task 22: Switch and CLI

**Files:** Modify `src/aigv2/pipeline.py` (`_render_qc` uses `render_guide2(build_guide(...))` when `AIGV2_RENDERER=new` (default `old` until Task 27), else the old path), `src/aigv2/config.py` (setting `renderer: Literal["old","new"]`); Modify `src/aigv2/__main__.py` (`--renderer` flag on `build`/`regenerate`); Test `tests/aigv2/test_pipeline.py::test_new_renderer_flag`.

- [ ] **Steps 1-5:** failing test (fake deps, flag on -> guide.docx has the new header text), implement, PASS, full suite, commit `feat(aigv2): new renderer behind a flag`.

### Task 23: QC compatibility sweep

**Files:** Modify `src/aigv2/qc/reader.py`, `qc/annotate.py`, `qc/rules.py` ONLY where Task 21's sweep shows the new docx loses information (e.g. venues inside nested tables, `Getting there:` in glance cells); Test `tests/aigv2/test_qc_new_renderer.py` (run QC on the saved Bali guide docx from `render_guide2`: rules `booking_missing`, `markers_remaining`, `not_open_at_slot`, voice check still fire on seeded problems; annotated output keeps the layout).

- [ ] **Steps 1-5:** failing test, fix reader/annotate for the table layout, PASS, commit `fix(qc): read the new card layout`.

### Task 24: Preview tooling

**Files:** Create `scripts/preview_guide.py` (`python3 scripts/preview_guide.py <run_id>` renders `guide.docx` to PDF/PNG with LibreOffice and a throwaway font profile, writes `preview/` in the run folder); Test: smoke test skipped when `soffice` is missing.

- [ ] **Steps 1-5:** write the skip-aware test, implement, commit `chore: guide preview script`.

**Checkpoint M5:** `python3 -m src.aigv2 regenerate <saved run> --renderer new` (replays saved plan; $0 Google; small AI cost for rewritten sections if any) produces the full new-look Bali docx. Stop here for the user to review it in Word.

---

## M6 - Live test guides (user approves each spend)

### Task 25: Dilna Bali on the new renderer
- [ ] **Step 1:** user confirms spend (est. $0.2 AI + $0-1.5 Google list price; places/routes cached). **Step 2:** run `build` with the saved intake/answers (`~/library_backups/aigv2_bali_2026-11-02/dilna_*`), `--renderer new`. **Step 3:** compare against the hand-curated guide for content gaps; list issues in `docs/superpowers/notes/2026-11-xx-bali-new-look.md`. **Step 4:** fix issues as small commits (each with a test). **Step 5:** QC report must have no `error` from layout rules.

### Task 26: Jumana Lisbon and Sneha Europe
- [ ] Same procedure per trip (inputs in `input/for-aigv2/AIG Inputs and outputs/Jumana- Lisbon (...)` and `Sneha- Europe (...)`); user approves spend and answers the pre-flight questions; expect new bugs in train/experience-ticket handling; fix with tests.

### Task 27: Make the new renderer the default and retire the old one
- [ ] User approves. Default `renderer="new"`; delete `src/aigv2/render/` files no longer imported (keep `qc` imports of `BEFORE_YOU_GO`/`WHILE_THERE` by moving them to `src/aigv2/guide/constants.py`); full suite; commit `refactor(aigv2): remove the old renderer`. Merge/S3/Lambda remain separate user-approved steps (rollout plan step 7).

---

## Self-review notes

- **Spec coverage:** every PATTERNS.md component maps to a task (Opener/YourDay/JourneyStrip T15; Sightseeing/Simple/Checklist T16; Booking family T17; Meal/Placeholder T18; Option cards/markers T19; reference components T20; Letter/ThankYou T21). Engine gaps from the design agent's report map to T5-T10. Letter-by-hand and Thank-You-generated decisions are in T10 and T21. Fonts embedding in T11/T21. App/HTML future in T1 (guide model).
- **Known risks:** (1) QC reader coupling (T21/T23 exist for it). (2) Word vs LibreOffice rendering differences: LibreOffice previews only; the user spot-checks in Word after M3/M5. (3) Structured sections (T9) change LLM prompts and may need prompt tuning during M6.
- **Not in this plan (deferred by the user):** photos, HTML/app renderer, ingestion changes, Google place links in the library, feedback loop, dining budget/style facts.
