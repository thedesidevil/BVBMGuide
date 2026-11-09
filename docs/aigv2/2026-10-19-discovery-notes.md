# AIG v2 — Discovery Notes (2026-10-19)

Branch: `aigv2`. Status: **brainstorming / discovery — no design approved, no code written.**

## Goal (from user)

- Generate AIGs through code, end to end. $0.50–$1 per AIG in API cost is acceptable.
- Automate both **creation and QC**, aiming for zero mistakes.
- OK for the program to ask a human to verify things or fill blanks — but the bulk of the work is done for them.
- Adopt the **new format** (Trip D (Istanbul): pages before the TOC).
- Apply the **new branding** (BVBMWebsite) and the visual style of the AI-generated mockup (`BVBMWebsite/tmp/BVBM FAQ Section/aig-preview/aig-preview.png`).

---

## 1. Teammate voice note (`input/for-aigv2/PTT-20261019-WA0002.opus`) — basis for the work

### Current workflow
1. Fills an "AIG notes" doc → uploads to the tool's `prep` → gets `_client_profile.md` + `_library_context.md` (she finds these useful).
2. Uploads those + itinerary, flight/train tickets, experience vouchers, sample AIG, instruction set to ChatGPT.
3. Asks "am I missing anything?", then generates the guide day by day, spot-checking each day.
4. Assembles the doc → manual verification → review with the tool's Verify tab + ChatGPT.

### Pain points
1. **No notes template** — doesn't know which fields the client profile needs; forgets info and only learns via ChatGPT asking.
2. **Per-day spot checks** — 3 restaurants per meal, no repeats within the same city, lunch timing not too early/late → regenerates days that fail.
3. **Format drift on long trips** — 15-day trip: consistent for ~6–7 days, then Maps links lose hyperlinks and restaurant field layout changes → "the girls" spend a long time reformatting.
4. **Manual verification** (they insist, for accuracy) — links work, place still operational, opening hours, travel time/distance.
5. **QC tool lacks client context** — e.g. warns "non-veg restaurant, client is vegetarian" when the client is non-veg. Wants everything in one place.
6. **ChatGPT review catches useful logic issues** — wrong distances; departure edge cases (1 AM flight on the 15th → leave hotel night of the 14th; checkout may be 14th or 15th depending on client → must be confirmed by a human).

### Interpretation (Claude's guess — not yet confirmed by user)
- Code renders the document → format cannot drift.
- Fixed intake form replaces free-form notes → nothing forgotten.
- Restaurant count / repeats / meal timing become automated checks before a human sees the output.
- Generation and QC share one client profile → no false diet warnings.
- Ambiguous facts become explicit "please confirm" prompts.
- Verification (open/closed, hours, travel time, links) is the biggest time saver and needs team trust.

Full transcript: see Appendix A.

---

## 2. Current codebase state

**Pipeline** (`src/aig/__main__.py`): `parse` (AI-first, `folder_parser.py` + `parser.py`) → `trip_facts.json` (`TripFacts` in `src/common/models.py`) → `generate` (go/abort gate → `build_context` in `src/aig/context.py` → each `sections/*.build(ctx)` → `day_builder.py` per day → `assembler.py` renders DOCX). Helpers: `redo-day`, `redo-section`, `assemble`, `preview-day`, `build-styles`.

**What the team actually uses:** `prep` (`src/aig/prep.py`, UI `api/aig_prep.py`) — bundles library + client profile for ChatGPT. Spec: `docs/superpowers/specs/2026-08-23-aig-prep-design.md`.

**Section maturity:** all `src/aig/sections/*` are 8–34 lines.
- cover: one AI call for title. getting_around / souvenirs / dishes: pass-through of library lists.
- etiquette / safety / connectivity / health: library-or-AI fallback; AI output is **written back into library_db unreviewed**.
- packing / client_info / thank_you: minimal.
- **Missing:** TOC, Important Places builder, lunch (never populated — only dinner), new pre-TOC pages.

**Rendering:** plain python-docx, `src/aig/styles.py` = 13 black-Arial styles; no colours/tables/cards/header/footer/page numbers; Maps links are raw URL text, not hyperlinks. `src/hotel_options/generator.py` (1,281 lines) already does themed colours, shading, tables, photos — in-house model for branded output.

**Restaurants:** up to 3 library restaurants for the overnight city; diet filter uses only `vegetarian_friendly` (set on 11/69 London entries); no proximity check; no hours-vs-weekday check; an AI call adds ambience/INR price/travel note (unverified). London coverage: hours 64/69, area 61, price 44, landmarks 35; **no coordinates/addresses**. Google Maps API key unused for AIG.

**QC:** library QC (`src/library/qc.py`); output QC = Verify tab (`src/library/ui/services/verify_service.py`, rules R1–R12 + optional AI pass) — post-hoc, UI-only, not wired into generate. ChatGPT QC prompt: `docs/chatgpt-aig-qc-prompt.md`. Tests in `tests/aig/`.

**Deploy:** FastAPI (`src/library/ui`) on port 8765 locally; Lambda via Mangum (`deploy/aws/sam-template.yaml`, 900s timeout). React frontend `ui-frontend/` (AIGTab: PrepPanel + VerifyPanel; library loaded from S3). No UI path for full generation.

**Risks for full automation:**
1. Unverified invented facts (prices, transfers, etiquette/health/safety), silently written back to library.
2. Restaurant rules unenforceable with current data (no coords, weak diet flag, no lunch, no hours check).
3. Incomplete structure (TOC, Important Places, pre-TOC pages, hyperlinks, header format).
4. Unbranded renderer.
5. No generate-time validation loop / human-fill flagging.
6. Lambda 900s limit vs ~30 sequential AI calls for a 10-day trip.
7. `prep` and `parse` use different extraction paths → drift.

---

## 3. Manual ChatGPT process (`input/for-aigv2/generating-aigs-manually.zip`, extracted to `/tmp/aig-manual-zip/`)

Files: step-by-step PDF, Instruction Set PDF, 44-page Sample Guide (Paris/Switzerland/Italy), Cover Page & Note Template DOCX, QC checklist (DOCX + XLSX, 7 sheets Y/N).

**Process:** one ChatGPT chat → attach instructions → attach library AIG PDFs for destinations → attach sample guide ("copy look & feel") → attach itinerary → "day by day, restaurants/cafés/bakeries from library only, never internet" → paste into Google Doc "All Inclusive Guide - <Client> - <Destinations>" → manual QC via checklist.

**Rules by section (Instruction Set):**
- Days: bold date+title header; Morning/Afternoon/Evening/Meals with storytelling transitions.
- Every venue: Maps link embedded in name (`https://www.google.com/maps/search/?api=1&query=NAME`, spaces→`+`), travel time from hotel, hours, INR price pp, parking.
- Defaults: taxi unless specified; only client's hotels; single hotel → never mention hotel change.
- Distance: attractions/restaurants ≤20 min drive from hotel; pharmacies/groceries ≤10 min walk; venues tagged by hotel zone.
- Restaurants: library only; 3 per lunch & dinner; if too few, list what exists and leave rest blank; same place ≤2× in 3 days unless different dish/meal; if area <3, may add 1–2 (≥4.3★, photogenic) as "curated additions"; each with ambience, 1–3 must-try dishes, "Best for".
- Style: 2–3 vivid sentences per attraction.
- End sections: Instagrammable cafés (3–4 per hotel area); local dishes grouped with where to try; Important Places (2 pharmacies + 2 groceries per hotel, with phone); souvenirs (what/where/haggling/fakes); 4–5 phrases + tipping/temple tips; packing with special items; safety (Indian embassy addr/phone, police, ambulance, hospital); SIM (incl. documents needed); health (routine + Hep A/Typhoid where relevant).

**Not in repo docs (`CUSTOMGPT_INSTRUCTIONS.md`, `AIG_QC_CHECK.md`):**
1. Repo instruction file is stale (says 2 restaurants/meal; zip says 3; zip adds taxi default, "leave blank", Instagrammable Cafés).
2. New front pages: warm trip-specific "Dear (guest)" letter signed "With love, Bon Voyage by Marina" → "All Inclusive Guide – (Place)" heading → TOC.
3. Process rules (day by day, no internet restaurants, file naming).
4. Implicit rules seen only in sample: flag emojis in title/day headers; arrival time + airport→hotel by public transport and car; sunset times; pre-booked tickets/time slots called out; split plans when group divides; "✅ Overnight in X" day closer; local currency (EUR) prices; transport passes with kids-free-by-age rules; per-country embassies; per-city scam lists.
5. Parking required everywhere but never checked by the QC checklist.

**Contradictions / ambiguities (need decisions):**
- Currency: INR (rules) vs EUR (sample) vs ₹ (mockup).
- Lunch near attractions (checklist) vs ≤20 min from hotel in hotel's zone (instructions) — clash on day trips.
- "Leave blank" vs "curate 1–2 extras".
- Day layout: Morning/Afternoon/Evening/Meals vs meals interleaved (sample, mockup).
- Day header: checklist `Day X: Weekday, Date – Title`; sample `Day 1: September 9 — Arrival in Paris`; Trip D `Day 1 – Thursday, 29 October 2026 | Welcome to Istanbul`.
- Emergency hospital under Important Places (checklist) vs Safety (instructions).
- "(Insta Worthy)" tag vs separate Instagrammable Cafés section.
- Sample guide has leftover placeholders ("mention timings"), wrong hours (dinner spot "12 PM–2 PM"), typos; phrase/SIM examples copied from Mauritius.

**Most error-prone steps:** opening hours vs meal time/weekday; weekday/date drift in headers; "internal" distance/zone rules nobody can check; hand-pasting into Google Doc (breaks formatting, links, TOC); manually-counted restaurant rules; pax/kids/diet guessed from itinerary text; embassy/emergency/SIM facts trusted blindly; leftover placeholders.

---

## 4. New format — Trip D (Istanbul) (see `input/for-aigv2/` (gitignored))

**Order:**
1. **Cover (new)** — full-bleed PNG, navy with thin gold border, logo, tagline "Your Vacation • Your Story • Your Way", "BON VOYAGE BY MARINA", phone, website. Entirely boilerplate (no client/destination/title).
2. **Personal letter (new)** — "Dear [Name]," + 6 warm paragraphs + "With love, Bon Voyage by Marina". Per-client: name, repeat-client framing, whether team has done the trip, destination (×2), child's name, family tone; 💙 emoji.
3. Plain bold title "All Inclusive Guide- Istanbul" + H1 "Table of Contents" (real Word TOC field).
4. Days 1–6.
5. Important Places Around Your Stays → Must-Try Dishes → Souvenirs → Tailored Packing List → Cultural Etiquette & Phrases → Mobile Connectivity → Safety & Emergency → Health & Vaccination → Thank You.

**Deviations from `docs/AIG_STRUCTURE.md`:** no Client Info + Trip Summary page (letter replaces it); no Getting Around section; different section order; header `Day 1 – Thursday, 29 October 2026 | Welcome to Istanbul`; generic title.

**Day structure:** H1 header → 1–2 sentence intro → optional "Important planning note" / confirmed activities → emoji time-of-day sub-headers ("🕌 Morning – …") → bold timed items ("9:00 AM | …").
- Attraction fields: 📍 linked name, description, your booking, suggested duration, travel time, entry fee, best time, what to look out for, etiquette/dress code, parking, important.
- Restaurant fields: linked name, ambience, 🍴 must-try, hours, approx cost (₹ pp), travel time, parking, best for.
- Days 2+ end with "🗓️ Day N – Suggested Itinerary at a Glance" table (Time | Plan). Day 1 has airport→hotel by car / public transport / taxi.

**Other sections:** Important Places per hotel (💊 pharmacy, 🛒 store, 🏥 hospital; linked name, distance, hours). Dishes: 10 numbered with emoji. Souvenirs: 15 numbered, no shops/links. Packing: 7 emoji groups, "Item: qty + reason", season/activity-tailored. Etiquette: bullets + 5 phrase tables (Turkish (pronunciation) | Meaning). SIM: provider, where to buy, links, plan, tips, apps. Safety: tips, emergency numbers, Indian consulate. Thank You: boilerplate.

**Formatting:** theme defaults, no custom fonts/colours; H1 17pt, sub 13pt; heavy emoji; Letter size; header logo; footer "Bon Voyage by Marina / +91-86000-15316 / www.bonvoyagebymarina.com"; empty Heading 2 paragraphs used as page breaks (pollute TOC).

**Links:** 66 total — 49 contain `&utm_source=chatgpt.com`; 11 `maps.app.goo.gl`; some items unlinked.

**Human errors found (what QC must catch):**
- Letter says **"Bali" twice** in an Istanbul guide (copy-paste); "Ivaan,,".
- File named for one client but the letter addressed to another.
- <3 restaurants per meal (Day 2 lunch 2, Day 4 lunch 1, most dinners 2, Day 6 none).
- Repeats across days incl. inconsistent names (Turgut Kebab Sirkeci / "TurguT Restaurant Sirkeci").
- Messy hours ("Confirm directly before visiting.Listed as daily 8 am–12 am"), inconsistent am/AM.
- Typos: "5 walk from the Hippodrome", "10-15 minutes by car drive and public transport".
- Day 2 at-a-glance table contradicts body (optional Basilica Cistern vs "relax at hotel").
- Walkable attraction described as car/transit trip.
- Diet fit never stated → unverifiable.

---

## 5. Branding (`/Users/mjain/work/projects/travel/BVBMWebsite`)

**Logo:** `01 BVBM Final Logo Assets/` — RGB PNG/JPG (horizontal, vertical lockups 1–6; icons 1–4), CMYK vector PDFs, `.ai` sources. SVG used in mockup: `tmp/BVBM FAQ Section/aig-preview/assets/logo-v1.svg`.

**Official palette** (`02 BVBM Final Color Palette/`):

| Name | Hex |
|---|---|
| Royal Blue | #3A6CB5 |
| Crimson Red | #D92027 |
| Midnight Navy | #0C1F3E |
| Powder Blue | #AEC7E7 |
| Frost White | #F4F6FA |
| Slate Grey | #4A525E |
| Warm Taupe | #C4B3A1 |
| Amber Gold | #DEA350 |

Website/mockup actually use: navy #0C1F3E, ink #12294B, royal #2F5FA8, sky #3C74B8, powder #AEC7E7, frost #EEF4FB, fog #F8FBFE, slate #41536E, gold #C68A32, gold-soft #DEA350, red #D92027.

**Fonts:** Cormorant Garamond (headlines, italic overlines; Google Fonts, OFL) + Georgia (body; bold small caps for labels). Le Jour Serif (licensed; lacks apostrophe and en dash → display only). Bacalisties ("By Marina" script; logo only).

**Taglines:** "Your Vacation · Your Story · Your Way"; "Crafting Unforgettable Vacations". Tone: warm, first-person "we", never salesy, British-ish spelling.

**Mockup spec** (`tmp/BVBM FAQ Section/aig-preview/aig-preview.html`): 6px navy→royal gradient top bar; centred logo 150px; gold italic kicker "Your All-Inclusive Guide"; Cormorant 46px navy city title; powder rule; royal uppercase letter-spaced group labels ("YOUR DAYS", "WHILE YOU'RE THERE"); Georgia TOC rows with dotted leaders. Day page: "DAY 2" eyebrow, Cormorant 34px title, slate lede, gold italic time-slot headings ("Morning", "Lunch near Camden Market"). Stop card: 1px #DCE6F2 border, radius 6, #FBFDFF bg, Cormorant 23px title, 2-col facts grid with small-caps royal labels (BY PUBLIC TRANSPORT / BY CAR / OPENING HOURS / ENTRY; MUST TRY / APPROX. COST / FROM THE MARKET), slate description, pill tags (royal on #EEF4FB). Footer: italic tagline left, page number right.

Other sample AIGs: `tmp/BVBM FAQ Section/` (Bhushan London v3, Akankshaa Japan, Evelyn Nagaland). Print pieces with CMYK softproofs: `tmp/BVBM Brochure/`.

---

## 5b. Real client notes + `prep` outputs (`input/for-aigv2/`)

Three real cases, each with the notes docx the teammate fed to `prep` and the two files `prep` produced.

**What the notes look like (free-form, inconsistent):**
- **Trip C** (client notes; see `input/for-aigv2/` (gitignored)): 2 adults, Lisbon, 14–18 Oct; 16 Oct morning work event; Ubers except bus to Óbidos; "apart from pork they eat everything. Love food". Hotel (Sofitel Lisbon Liberdade) buried inside Day 1 text. Day-by-day itinerary as paragraphs with "Overnight: Lisbon". 18 Oct titled "Choose Your Day Trip" but only Óbidos given; no departure info.
- **Trip D** (client notes; see `input/for-aigv2/` (gitignored)): "3 senior citizen women / Budget- mid range / Leisure trip / Diet- no restrictions". **The itinerary is a pasted screenshot (image)**, not text: 29 Oct–3 Nov Istanbul, arrive 6:30 PM, Whirling Dervish at Hodjapasha, hammam in Taksim, depart 3 Nov. No hotel, no year, no flight times in notes.
- **Trip E** (client notes; see `input/for-aigv2/` (gitignored)): solo, NYC, work Nov 1–5 morning (evenings free), sightseeing from Nov 5 afternoon; "mid Manhattan 6th Avenue 1st–5th", Royalton from Nov 6 (night of 5th ambiguous); taxis; no beef, nothing raw; leaves ~noon Nov 8. Itinerary is a **planner's draft with internal commentary** written to the team, not the client ("I'd skip it if you're already doing Top of the Rock", "Since they have already got the main sightseeing days…", "they" for a solo traveller), pasted address/phone blocks, duplicate lines, optional/either-or choices (Top of the Rock OR Empire State; Museum "if comfortable").

**What `prep` produced — essentially empty:**
- Trip D → destination "Client notes", dates/hotel/diet/style/group all `[fill in]`; library context "No BVM library data for Client notes".
- Trip C → destination blank, dates "18 Oct 2026 – 18 Oct 2026", hotel `[fill in]` (Sofitel missed), diet `[fill in]` (pork-free missed); library context empty.
- Trip E → name `[fill in]`, destination "Solo traveller"; library context empty.

**Root causes in `src/aig/prep.py`:**
- `_extract_from_docx` treats the first heading/line as the destination title → "Client notes", "Solo traveller".
- `generate_client_profile` hardcodes Travel Style / Occasion / Group Composition / Special Requirements as `[fill in]` (lines ~744–750) — never populated even when the notes state them.
- Image-only itineraries are invisible to it.
- Wrong destination → library lookup misses → **library context is empty, so ChatGPT falls back to general knowledge**, silently breaking the "restaurants from library only" rule.

**Implications (Claude's read):**
- This explains the voice-note pain "I don't know which fields the profile needs / I forget things": the tool shows blanks for things she *did* write.
- ~~Trip D letter mismatch~~ — **User clarified (2026-10-19):** Trip D's guide may have been a work in progress. **The personal letter page is always written by hand for a personal touch; the program must leave it empty** (placeholder page only). Not an AI-generation concern; at most QC can flag if it was left unfilled.
- Notes mix confirmed facts, planner suggestions, optional choices and internal commentary. A v2 intake needs to separate these (structured fields + itinerary), and the generator must never leak planner commentary into the guide.
- Facts that arrive from elsewhere (Trip D's hotel, flight times, year) mean intake must combine notes + itinerary + tickets/vouchers, and flag what's missing.
- Ambiguities a human must confirm: Trip E's night of Nov 5 hotel; Trip C's departure; Trip D's year/hotel.

---

## 5c. Answers — A. People & workflow (`input/for-aigv2/answers-to-A.mp3`, user, 2026-10-19)

1. **Notes & source of truth:** client notes are written by the team (teammates). Source of truth for hotels, flight times, checkout dates: **vouchers when present; otherwise the notes / itinerary.**
2. **Who runs it / where:** teammates, **in the web UI**. They need a way to **upload all the documents**. After generation they **edit the guide in Google Docs** (user can tell them not to use Word).
   - *Implication (Claude):* output must be a DOCX that survives Google Docs import cleanly — Google-Docs-safe styling (tables for cards, real hyperlinks, fonts available in Google Docs: Cormorant Garamond ✓, Georgia ✓), no floating shapes/text boxes. Likely also answers Q23 (DOCX primary).
3. **Volume / length / time:** 15–20+ AIGs in busy months, 4–5 in quiet months. Typical trip 4 to 10–12 nights; 15–20 nights rare. Time varies by employee — **some take up to 8 hours just for QC.**
4. **Mistakes:** no specific shipped-mistake case, but common ones seen:
   - Walk time wrong ("2 min walk from hotel" that's actually 25 min).
   - Restaurant opening at 4 PM recommended for lunch.
   - Restaurants temporarily/permanently closed but still recommended (carried over from old guides in the library).
   - Attractions closed on the planned day (weekday/weekend-only, closed Mondays, midday closures e.g. 2–5 PM).
   - *Implication (Claude):* every one of these is mechanically checkable with Google Places (business_status, opening_hours by weekday) + Distance Matrix (walk/drive time from the actual hotel) against the planned date and time slot.

---

## 5d. Answers — B. Inputs (`input/for-aigv2/answers-to-B.mp3`, user, 2026-10-19)

5. **Intake:** yes, replace free-form notes — but **not as a UI form**. Instead define a **Word/Google Doc template** with **mandatory fields**, ending with a free-text **"Additional notes"** field. Reason: Word/Google Docs are much easier for the team than entering things in a UI.
   - *Implication (Claude):* tool must parse the template reliably (fixed labels → deterministic parse, AI only for the free-text field) and report missing mandatory fields up front. Uploaded alongside: itinerary, tickets, vouchers.
6. **Planner drafts with open choices / ambiguities:** tool **stops and asks a person first** — but **not one question at a time**. It reads all inputs, collects every question, and **asks them all in one go**.
7. **Screenshots:** **not supported** (keep cost down). Team pastes the text in.
   - *Implication (Claude):* tool should detect image-only content in uploads and tell the user to paste text, rather than silently ignore it.

---

## 5e. Answers — C. Restaurants (`input/for-aigv2/answers-to-C.mp3`, user, 2026-10-19)

8. **Strictly library only.** If fewer than 3 for a meal, **say so in the output document** — a visible marker that a restaurant needs to be added by hand.
9. Same as 8 (no blanks hidden, no AI fill — mark the gap).
10. **Lunch rule is complementary, not contradictory:** lunch near that day's attractions by default; **near the hotel** when the itinerary puts them at the hotel around lunchtime — e.g. check-in ~11 AM–1 PM, or "return to the hotel after attractions" (early start, back by 10–11 AM, rest, sightseeing later).
    - *Implication (Claude):* lunch anchor is derived per day from where the client is at ~12–2 PM in the plan (attraction cluster vs hotel). Dinner presumably near the hotel (existing rule).
11. **Repeats:** same restaurant **at most twice in any three days**. Don't distinguish by dish — restaurant identity only.
12. **Prices:** **both** — local currency with approximate INR in brackets, e.g. "€25 (~₹2,400)".

## 5f. Answers — D. Checking facts (`input/for-aigv2/answers-to-D.mp3`, user, 2026-10-19)

13. **Trust:** for the **first few AIGs the team still checks everything by hand**; once the tool proves 100% correct, they'll trust it. Regardless, the tool must have a **separate QA process: a builder produces the AIG, then hands it to a separate QC agent that checks everything** — builder and checker are independent.
14. **Failed check → flag to a person. Never replace automatically.**
15. **APIs:** yes — Google Places / Distance Matrix fine, as long as the **entire AIG costs ≤ $1** (all-in). If a paid Google subscription/plan is needed, tell the user and they'll set it up.
    - **New requirement — keep the library up to date:** after building, show the user a **table of every library item used where Google's info differed from the library** (hours, closed status, etc.). User can **multi-select rows and approve** → tool updates the library with the new info.
16. **Human-confirmation flags:** in addition to rule checks, run a **generic AI "does this make sense?" read-through** of the whole AIG (like they do with ChatGPT today) and flag anything odd or worth a human double-check.

## 5g. Answers — E. Structure & content (`input/for-aigv2/answers-to-E.mp3`, user, 2026-10-19)

17. **Sections:**
    - **Client info: not in the AIG.**
    - **Table of contents: yes**, generated in the Google Doc if the program can; otherwise generated by us, as long as it's in our theme/colour palette.
    - **Getting Around: yes, important — keep.**
    - **Instagrammable cafés: dropped** ("we don't do that anymore").
    - **Per-day "at a glance" table: not part of the new format** — new AIGs are flowing Word text, no tables. (Trip D's guide had them; it may have been WIP.)
18. **Day header:** `Day 1 – Thu, 29 Oct | Welcome to Istanbul` — 3-letter weekday, 3-letter month, no year, then a pipe and a plain title.
19. **Day layout:** go with the mockup's new layout (Morning → Lunch near X → Afternoon → Dinner). Cheap to change later if it proves troublesome.
20. **Emojis:** not important — **it must look classy**. Claude's call: drop them or use clean, mockup-style styling.
    - *Claude's call:* no emojis; use typographic styling (small-caps labels, gold italic slot headings) like the mockup.
21. **Emergency hospital: under "Important Places Around Your Stays"**, one set **per city/stay** (e.g. Interlaken, Zurich, Geneva each get their own hospital).
22. **Creative title stays**, with subtitle "All Inclusive Guide – Istanbul" underneath (e.g. *Sakura Adventures* / All Inclusive Guide – Japan).

## 5h. Answers — F. Look & output (`input/for-aigv2/answers-to-F.mp3`, user, 2026-10-19)

23. **Always an editable Word doc**, uploaded to Google Docs and **edited only in Google Docs**.
24. **Cover: keep the same branded navy cover image for everyone** (as in Trip D). Then the **TOC page (page 3, after the hand-written letter) uses the mockup style**: logo, "Your All-Inclusive Guide" kicker, creative title (e.g. *Sakura Adventures*) + destination subtitle, then grouped TOC.
    - Group labels: **find a better word than "Your Days"**. **"While You're There" may not fit** — packing list (and mobile/SIM) are pre-trip, so the grouping needs rethinking.
25. **A4.**
26. **Photos: yes, but in a later version.** v1 focus = **team efficiency + lift in look and feel**. Other new features come after v1 is in use and delivering productivity + accuracy gains. (Saved to memory as a deferred feature.)

## 5i. Answers — G. Scope & rollout (`input/for-aigv2/answers-to-G.mp3`, user, 2026-10-19)

27. **The new tool just builds a finalized AIG** (replaces `prep` + the ChatGPT generation step). The team may still run it through ChatGPT for QC for the first few iterations — that's their manual step, not the tool's.
28. **AI-written etiquette/safety/health content: do NOT save it back to the library for now.** (Ideal = review queue → library, but skip in v1.) The library builder tool can later ingest generated AIGs to update the library.
29. **Background job is fine.** Tell the team a generic "check back in 15–30 minutes".
30. **Success = zero errors found in QC; accuracy is paramount.** **Do not guess anything** — wherever unsure, put a **marker in the AIG for a human to fill in**. But perfection is iterative: **v1 saving ~50% of the team's time is a big win**; iterate v2, v3, v4 on team feedback. Not expecting a ship-as-is AIG in one go.

## 5j. Round-2 answers — Restaurants (`input/for-aigv2/answers-to-restaurants.mp3`, user, 2026-10-19)

R2-1. **Gap marker in the doc only**, e.g. "ADD RESTAURANT – Lunch, Day 3, near Galata Tower". **No Google candidate suggestions in the web UI.**
R2-2. **Agreed default:** library restaurant closed (or closed at that meal/weekday) per Google → drop it, show gap marker, add to library-update table.
R2-3. **Save lat/long in the library, lazily:** whenever a library restaurant is picked and has no location, look it up via Google, save it back to the library, then compute distance to hotel/attraction.
R2-4. **Repeat rule (replaces "twice in 3 days"):** within the same city, **a restaurant appears at most twice in total**, and **never more than once on the same day** (no same place for lunch and dinner).
R2-5. **Agreed default:** INR at today's rate, rounded to nearest ₹50; "price unknown" marker if library has no price.
R2-6. **Agreed default:** library-only covers cafés, bakeries and dish "where to try"; pharmacies/groceries/hospitals come from Google.
R2-7. **Dinner:**
  - If there's an **evening attraction**, give **1 option near the attraction and 2 near the hotel**.
  - Example given: Eiffel Tower 7 PM → Seine cruise 9 PM, itinerary says "grab dinner before the cruise" → options near the Eiffel Tower / cruise / between them.
  - Otherwise near the hotel.

## 5k. Round-2 answers — rest (`input/for-aigv2/answers-to-rest-of-round2.mp3`, user, 2026-10-19)

R2-8 (round-2 list #8). **Flags: highlighted in the doc only — not in the web UI.** A **separate UI** lets a person, after fixing all markers, **re-upload the doc and run QC again**.
R2-9 (#9). Re-run QC on edited doc: **yes** (same as above).
R2-10 (#10). **Verification sheet: yes**, produce it.
#11. Library-update approvals (any teammate; add/remove allowed): default OK — *but see #19 below; library writes are now deferred.*
#12. QC checker = same provider, separate prompt, own fresh Google lookups: **default OK**; revisit if it doesn't work.
#13. Trip summary table dropped: **default OK.**
#14. Cards as bordered tables; phrase lists as plain lines: **default OK.**
#15. Section order: **default OK** — Cover → letter (blank) → title + TOC page → Days → Before You Go (Packing, SIM, Health) → While You're There (Important Places, Getting Around, Dishes, Souvenirs, Etiquette & Phrases, Safety) → Thank You.
#16. TOC groups "Day by Day" / "Before You Go" / "While You're There": **default OK.**
#17. Creative title on the TOC page; cover is the same branded image for all: **default OK.**
#18. Mockup-style TOC with clickable section links, **no page numbers**: **default OK.**
#19. **Write nothing to the library for now.** The library is updated only via the library importer/builder tool, fed with AIGs that have shipped to clients. Keeps "building the library" and "using the library" completely separate.
#20. Old Prep panel: **default OK** — hidden-but-available for one month, then removed.

## 5l. Round-3 answers 1–8 (`input/for-aigv2/round3-q-1-8.mp3`, user, 2026-10-19)

R3-1. **Default OK:** itinerary wording wins ("dinner before/between/near X" → all 3 near X); otherwise 1 near last evening activity + 2 near hotel.
R3-2. **Nothing is saved to the library during AIG generation — no locations, no approval/selection UI.** Library is updated only by ingesting complete, QC'd, shipped AIGs with the library ingestion tool. *(Supersedes D-15 approval table and R2-3 lat/long write-back.)*
R3-3. **Distances:**
  - **Walking never more than 10 min.** If a leg needs more than 10 min of walking, switch the directions to public transport / cab / driving (whatever that itinerary uses).
  - **Lunch:** within 10 min walk, or 15 min by public transport or car.
  - **Dinner:** within 20 min.
R3-4. **Default OK:** hours/closed days from Google checked against the planned weekday/time; entry fee from AI with "verify fee" marker + official-site link. **Change: dress code and tips from AI also get a verify marker.**
  - *Future (saved to memory):* enhance library ingestion so entry fees, dress code, tips etc. get captured into the library from shipped AIGs, so they needn't be regenerated each time.
R3-5. **Default OK:** embassy/emergency/SIM/vaccines from library first; else AI with verify marker; embassy address/phone checked on Google.
R3-6. **Default OK:** descriptive prose AI-written without marker; QC agent ensures it contains no factual claims (prices/times/distances).
R3-7. **Travel modes come from the intake.** If the intake doesn't state them, the tool **asks before it starts building**. Walking only within 10 min.
R3-8. **Default OK:** travel time from the previous stop (hotel for the first stop); restaurants from their anchor.

## 5m. Round-3 answers 9–17 (`input/for-aigv2/round3-q-9-17.mp3`, user, 2026-10-19)

R3-9. **Template fields OK, but don't force facts that live in attachments.** For dates, cities & nights, hotels per city, flights/trains, confirmed bookings, the user can simply write "use information from the attached files". Don't waste the team's time re-typing.
R3-10. **Default OK:** paste anything (planner drafts fine); tool asks all questions in one go.
R3-11. **Default OK:** pre-generation questions answered in the web UI, all at once.
R3-12. **Default OK:** hand-off = .docx + QC report (markers, flags, verification sheet). *(Library-update table dropped per R3-2.)*
R3-13. **Regeneration:** a table listing **every day and every other section** (Before You Go items etc.) with **checkboxes**; user ticks any, clicks one **"Regenerate"** button.
R3-14. **Default OK:** no library data → still generate, with gap markers; heavy lift is still done.
R3-15. **Default OK** — separate cache, library untouched. User asks: **where will the cache be stored — S3?** (→ round 4)
R3-16. **Default OK:** pre-generation questions in the web UI (block the run); post-generation findings highlighted in the doc.
R3-17. **Default OK:** verification sheet = separate downloadable file, one row per place (day, place, guide says, Google says, ✓/✗, "checked by").

## 5n. Round-4 answers (`input/for-aigv2/answers-round-4.mp3`, user, 2026-10-19)

R4-1. **Use OpenAI models** (that's what the user has API keys for). Locally, use the same OpenAI models through the proxy in `.env`; in production, OpenAI APIs directly — apples-to-apples between local testing and production.
R4-2. **Default OK** — enable Places + Routes on the Maps key's billing-enabled project; Claude sends console steps.
R4-3. **Proposal OK** — cache in S3 under its own prefix in the library bucket, 30-day refresh, never mixed with the library.
R4-4. **Default OK** — runs in S3 per-run folders, 90 days, listed in web UI.
R4-5. **Default OK** — required: client name(s), travellers + kids' ages, diet, travel mode, itinerary (or "see attachments"); anything missing everywhere → asked before generating.
R4-6. **Default OK** — regenerate is pre-editing; UI warns; all run outputs kept.
R4-7. **Default OK** — free time stays free; at most one light nearby idea if hinted.
R4-8. **Default OK** — only itinerary-named attractions.
R4-9. **Skip breakfast** (usually at the hotel). If the itinerary says breakfast out, **give breakfast options from the library**.
R4-10. **Default OK** — arrival/departure transfers per allowed mode; "leave by" with verify marker.
R4-11. **Inter-city travel days: Claude sets reasonable rules** (iterate later); put a **verify marker** in the AIG on such days.
R4-12. **Walking stays ≤10 min for everyone.** No special senior/mobility rules for now (seniors often use wheelchairs where walking is involved).
R4-13. **Default OK** — library first, else AI with verify marker (Getting Around, Dishes, Souvenirs, Etiquette & Phrases).
R4-14. **Default OK** — packing list AI-written, no marker.
R4-15. **Default OK** — Claude rebuilds the cover at A4 from brand assets for approval.
R4-16. **Default OK** — logo header; footer tagline left + page number right; phone/website on Thank You page.
R4-17. **Default OK** — yellow-highlight markers ("⚠ VERIFY:", "⚠ ADD RESTAURANT:", "⚠ PRICE UNKNOWN"); QC fails while any remain.
R4-18. **Default OK** — Thank You text from Trip D's guide verbatim.
R4-19. **Default OK** — "All Inclusive Guide - <Client> - <Destinations>.docx".
R4-20. **User will provide test data** after checking with the team how accurate Trip C's, Trip D's and Trip E's AIGs are. Claude to give a list of what's needed; user uploads to `input/for-aigv2/`. *(Saved to memory as pending.)*
R4-21. **Default OK** — PDF + DOCX uploads; images rejected with "paste text".
R4-22. **American English, not British.**

---

## 7. Round-2 questions (jotted while processing; ask after all sections are in)

From C:
- R2-1. The "needs a restaurant" marker: what should it look like in the Google Doc (e.g. highlighted "⚠ ADD RESTAURANT – lunch, Day 3, near Galata")? Should the tool also list a few un-vetted Google candidates *outside* the guide (in the run report) to speed up the human, or nothing at all?
- R2-2. Should a library restaurant that Google reports as permanently/temporarily closed, or closed at that meal time on that weekday, be dropped and counted as a gap (→ marker)? And should it be flagged for removal from the library?
- R2-3. To check "near the attractions/hotel", library restaurants need coordinates (none today). OK to geocode library entries via Google once and store the result in the library DB?
- R2-4. "Twice in three days" — a rolling window (any 3 consecutive days)? Does lunch + dinner at the same place on one day count as 2? Applies only within a city, or across the whole trip?
- R2-5. INR conversion: use the live rate at generation time, rounded (e.g. to nearest ₹50/₹100)? Library prices that are missing (~35% in London) — leave blank, or estimate?
- R2-6. Does "library only" also cover cafés, bakeries, Instagrammable cafés, and "where to try" for must-try dishes? What about Important Places (pharmacies/groceries) — those can't come from the library; OK to source from Google?
- R2-7. Dinner: always near the hotel, or near the evening activity when there is one (e.g. Fado show, Times Square)?

From D:
- R2-8. Where should flags appear for the team: a checklist/report page in the web UI, highlighted comments inside the generated doc, or both? (Flags inside the doc risk being shipped to the client if not removed.)
- R2-9. Since the team edits in Google Docs afterwards, should the QC agent also be runnable on the *edited* doc (download → re-upload) to catch mistakes introduced during editing? (Today's Verify tab does this.)
- R2-10. During the "check everything by hand" phase, would a verification sheet help — every place with its Maps link, claimed hours/travel time and what Google said, with a tick column?
- R2-11. Library-update table: who can approve updates — any teammate, or only you? Should it also offer *removing* permanently-closed places and *adding* the restaurants the team hand-fills into gaps?
- R2-12. Budget check needed: ~50–80 places per guide × Google Places + travel-time lookups. Google's free monthly tier (per-API caps) likely covers 20 guides/month, especially if place IDs are cached in the library; I'll confirm costs in the design. Is the $1 cap per guide meant to include Google costs (assumed yes)?
- R2-13. Should the QC agent use a different AI model from the builder (more independent), or the same model with a different job?

From E:
- R2-14. "Trip summary table" meant the old client-info table (city | dates | hotel + Maps link | transport). Confirm it's dropped along with client info? Is there any per-trip overview at all after the letter (e.g. a one-line list of cities and nights)?
- R2-15. "No tables": the mockup's restaurant/attraction cards are built as tables in Word (the only Google-Docs-safe way to get a bordered card with a 2-column facts grid). Is that OK as long as it *looks* like cards, not a spreadsheet? Same for phrase lists (Turkish | Meaning) — table, or plain lines?
- R2-16. Proposed final order (please confirm): Cover → Personal letter (blank, hand-written) → Creative title + "All Inclusive Guide – X" → Table of contents → Days → Important Places Around Your Stays → Getting Around → Must-Try Local Dishes → Souvenir Shopping Guide → Cultural Etiquette & Local Phrases → Tailored Packing List → Mobile Connectivity → Safety & Emergency Contacts → Health & Vaccination → Thank You.
- R2-17. Where should the creative title sit: on the cover itself, or on the page after the letter (Trip D's position, before the TOC)?

From F:
- R2-18. TOC trade-off: a native Word TOC converts into a Google Docs TOC that stays correct as the team edits, but it can't do the mockup's group labels and is styled by Google. A custom mockup-style TOC (grouped, dotted leaders, our fonts) looks right but its page numbers go stale once the team edits in Google Docs. Options: (a) native TOC styled as close as possible; (b) custom grouped TOC with links but no page numbers; (c) custom with page numbers the team refreshes by hand. Preference?
- R2-19. Grouping proposal (please react): **"Day by Day"** (or "Your Journey") → Days; **"Before You Go"** → Packing List, Mobile Connectivity & SIM, Health & Vaccination; **"While You're There"** → Important Places Around Your Stays, Getting Around, Must-Try Dishes, Souvenirs, Cultural Etiquette & Phrases, Safety & Emergency Contacts. Should the sections then appear in the body in this same order (Before You Go after the days, or before them)?

From G:
- R2-20. Q28 says don't write back to the library in v1, while §5f asks for an approve-to-update table for Google-vs-library differences. Assumed: the **approval table stays in v1** (human-approved, factual fixes like hours/closed status), and only **unreviewed AI-written content** is never saved. Correct?
- R2-21. Once v2 ships, should the old Prep panel in the UI be removed, or kept for a while as a fallback?

(R2-12 answered by G-30/D-15: $1 is all-in, including Google.)

---

## 6. Open questions (to resume)

1. **Verification trust (most design-shaping):** if the tool looked up every restaurant/attraction on Google (operational/closed, hours for that weekday, travel time from hotel, working link) and showed the results, would the team trust it or still check each by hand?
2. ~~Deferred: last AIG with a mistake~~ — answered in §5c.
3. Confirm/correct the interpretation in §1.
4. Resolve contradictions in §3 (currency, lunch distance rule, blank vs curated, day layout, header format, hospital placement, Insta cafés).
5. Output medium: DOCX the team can edit vs PDF/HTML matching the mockup (or both).
6. Cover: boilerplate image (Trip D) vs client/destination-specific cover (mockup).
7. Client Info + Trip Summary page and Getting Around section — dropped in new format, or keep?
8. ~~Who writes notes / source of truth~~ — answered in §5c.
9. Remaining question sets C–G (Q8–Q30 of the full list given in chat) — user is answering via voice notes `answers-to-<X>.mp3` in `input/for-aigv2/`.

---

## Appendix A — Voice note transcript (Whisper medium, local)

> So, I think that the client profile file and the library context file are useful. One thing that would help is if I know what are the fields that the client profile file needs to have because I don't have that template right now and then inevitably I forget to put some of that information in, which I get to know when I ask ChatGPT if I'm missing any information. So if I know those details, I can make sure to have them as a standard when I am filling out the notes for AIG doc that I put as an input file, that I upload as an input file into the tool to have these two documents generated.
>
> So once those are generated, I download those, I upload it to ChatGPT along with the client's itinerary, their flight and train tickets or any other tickets, booking vouchers for experiences, basically whatever I have with me for that trip. And then I also upload a sample AIG along with the set of instructions that were there. So I ask it then again if I'm missing anything before it starts and once it has everything in place, I ask it to generate the itinerary day by day.
>
> So while it's doing that, I check it, roughly scan through it to make sure that it is following the give three restaurant recommendations per meal. So are there repetitions of these restaurants across days if they're in the same city? And sometimes if I find that, then I ask it to regenerate it for that day. Or if I feel like the lunch options in terms of timing are given too early or too late depending on the day, then I would ask to sort of reschedule that day. So I do that initial bit when I am generating it and then I get the whole document ready.
>
> So the verification part of it, whether the links are working, whether the establishment or the restaurant is actually operational, the timings of those and then the distances or how long it would take the client to travel to that place. I think those we still have to manually check.
>
> But one thing that would definitely help is that we get the output in the same format across the different days. So I notice that sometimes like for a 15 day long itinerary, maybe it keeps to the same format as the sample guide for like the first six or seven days and then it suddenly changes it for some reason. So map links are no longer hyperlinked or the format of information that we give for a restaurant, that kind of changes a bit. So I find that then the girls take a longer time to reformat that thing. Yeah, so I guess if we find a way to make sure that it's all uniform and standard, then we save that much time doing that and making sure that everything looks the same across the different days. Yeah, the verification part, like I said, we still have to do manually because we want to make sure that everything is accurate.
>
> So that's on the generation and the verification. And then from a review perspective, I do use the tool again and then I use ChatGPT also to check if there are things that are missing. And sometimes I find that on the tool, it does not have a lot of context like, for example, dietary preference. So it kind of pulls up wrong warnings that, you know, this is a non-vegetarian restaurant, but the client is vegetarian, but the client is in fact, non-vegetarian, right, which should be part of the client notes. So like you said, maybe having everything in one place would sort of help.
>
> Yeah, and then in that way, I have found it easier to get those inputs from ChatGPT about, you know, maybe a distance that is incorrectly mentioned or yeah, like, you know, just also making sure that we have the right departure timing, et cetera, mentioned, like we have someone leaving on the 15th at like 1 a.m., that's their flight. And so the checkout is still on the 15th, but they have to go to the airport at 14th, like in the night. And then ChatGPT is like, are you sure that, you know, they're checking out on the 15th? So it's a good thing that it throws it up because for some clients, they do have, in fact, the checkout on the 15th, but for some, they actually are going to check out on the 14th. So it's just good for us to recheck it and to make sure that it's correct.

---

## Appendix B — Full question list (asked 2026-10-19; ★ = most design-shaping)

**A. People & workflow** — answered (§5c)
1. ★ Who writes notes; source of truth for hotels/flights/checkout.
2. ★ Who runs the tool, where; do they edit after (Google Docs/Word)?
3. Volume, typical trip length, time per AIG today.
4. Last AIG that went out with a mistake.

**B. Inputs** — answered (§5d)
5. ★ Fixed intake form vs free-form notes.
6. Planner drafts with open choices — pick, include both, or ask?
7. Screenshot itineraries — OCR or paste text?

**C. Restaurants**
8. ★ Library only, or Google-verified additions when library has <3?
9. Truly <3 good options — blank, fewer, or ask?
10. Lunch near attractions vs ≤20 min from hotel.
11. Repeats rule: none within same city, or ≤2× in 3 days unless different dish?
12. Prices: INR, local currency, or both?

**D. Verification**
13. ★ Would the team trust Google-verified status/hours/travel time/links?
14. Failed check — auto-replace or flag?
15. OK to use Google Places + Distance Matrix APIs (~$0.20–0.50/guide)?
16. What must always be confirmed by a human (late-night departures, hotel gaps, missing year/hotel, others)?

**E. Structure & content**
17. ★ Final section order; keep/drop Client Info table, Getting Around, Instagrammable Cafés, at-a-glance table?
18. Day header format (Trip D / checklist / mockup eyebrow).
19. Day layout: mockup (Morning → Lunch near X → Afternoon → Dinner) vs M/A/E + Meals block.
20. Emojis: heavy, clean, or small icons?
21. Emergency hospital: Important Places or Safety?
22. Creative title vs "All Inclusive Guide – Istanbul"?

**F. Look & output**
23. ★ Editable Word, PDF, or both? (largely answered by §5c: DOCX that survives Google Docs)
24. Cover: same branded image for all vs mockup-style with destination?
25. A4 or US Letter?
26. Photos of attractions/restaurants?

**G. Scope & rollout**
27. Replace `prep` + ChatGPT entirely, or run side by side?
28. AI-written library content: review queue or never written back?
29. Background job OK given Lambda 15-min limit?
30. Success measure: time per guide or zero QC errors?

---

## 8. Round-3 questions (asked 2026-10-19; defaults after →)

**Restaurants (follow-ups)**
- R3-1. Dinner with an evening attraction: when the itinerary says "dinner *before* the cruise" (meal sits between two evening activities), should all 3 be near the activities, or still 1 near + 2 near hotel? → *Default: itinerary wording wins — "dinner before/between/near X" → all 3 near X; otherwise 1 near the last evening activity + 2 near hotel.*
- R3-2. Saving locations back to the library: automatic (no approval), since it's just the map pin? → *Default: automatic, but if Google's match looks shaky (different name/area than library), don't save — flag it.*
- R3-3. "Near": what distance counts? → *Default: lunch ≤15 min walk or ≤15 min drive from the anchor; dinner near hotel ≤20 min drive (instructions say 20); outside that = not near → gap marker.*

**Facts the library doesn't have (the "don't guess" rule)**
- R3-4. Attraction details — hours and closed days, entry fee, dress code, best time. Hours/closed days can be checked on Google. Entry fees often can't. → *Default: hours from Google (checked against the planned weekday/time); entry fee from AI only with a "verify fee" marker + official-site link; dress code/tips are fine from AI.*
- R3-5. Embassy, emergency numbers, SIM providers and prices, vaccine guidance: library first; when the library lacks them, AI-written with a "verify" marker? → *Default: yes; embassy/consulate address and phone checked via Google Places.*
- R3-6. Descriptive writing (2–3 vivid sentences per attraction, day intros) — AI-written, no marker? → *Default: yes; it's prose, not facts, but the QC agent checks it doesn't contain claims (prices, times, distances).*

**Travel times**
- R3-7. Which travel modes to show per place? The mockup shows public transport + car; instructions default to taxi. → *Default: car/taxi always; public transport too only if the intake says they'll use it; walking when ≤15 min.*
- R3-8. Travel time from where? → *Default: from the previous stop in the day (and hotel for the first stop); restaurants from their anchor (attraction or hotel).*

**Intake template**
- R3-9. I'll draft the intake Word template (mandatory fields + "Additional notes"). Draft fields: client name(s); number of adults + kids with ages; seniors/mobility needs; trip dates; cities with nights; hotel per city (if no voucher); arrival/departure flights/trains (if no ticket); confirmed bookings (tours, shows, times); diet (restrictions, allergies, likes); transport preference; budget level; occasion; must-dos/avoids; day-by-day itinerary text. Anything to add or remove? → *Default: build from that list; the team reviews it before use.*
- R3-10. Itinerary text with open choices or planner commentary (Trip E): should the template require a "client-ready" itinerary, or is it fine to paste the planner draft and let the tool ask questions? → *Default: paste anything; the tool asks all questions in one go (per B-6).*

**Run experience**
- R3-11. Questions to the team before generating: answered in the web UI (a form showing all questions at once), not in the doc? → *Default: in the web UI.*
- R3-12. What's the final hand-off? → *Default: the team downloads the .docx + a QC report (all markers, flags, verification sheet, library-update table); they upload the docx to Google Docs.*
- R3-13. Re-running parts: if the team doesn't like Day 4, can they regenerate just that day (after QC, before editing)? → *Default: yes — "redo day N" button.*
- R3-14. Where do destinations with no library data at all fit? (e.g. a city the team has never done.) → *Default: every restaurant slot becomes a gap marker; the run report warns up front, before spending money, so the team can decide whether to proceed.*
- R3-15. **Conflict to resolve:** #19 says write nothing to the library, but earlier answers asked to (a) save looked-up lat/long back into the library (R2-3) and (b) offer a Google-vs-library approval table to update the library (D-15). → *Default: v1 writes nothing to the library. Looked-up locations and Google checks go into a separate cache (e.g. `geo_cache.json` keyed by library restaurant), so lookups aren't repeated or paid for twice; the library itself is untouched. The Google-vs-library differences still appear in the QC report / verification sheet as information, so the team knows what to fix via the library tool.*
- R3-16. Since flags live only in the doc: what about the **questions the tool asks before generating** (ambiguities, missing mandatory fields)? → *Default: those are still asked in the web UI before generation (they block the run); everything found after generation is highlighted in the doc.*
- R3-17. Verification sheet format → *Default: a second .docx (or .xlsx) downloaded alongside the guide, one row per place: day, place, what the guide says (hours, travel time, link), what Google says, match ✓/✗, and a blank "checked by" column.*

---

## 9. Round-4 questions (drafted 2026-10-19; defaults after →)

**Accounts & cost**
- R4-1. AI account: `.env` currently points at `claude-sonnet-4-6` via a proxy endpoint. For the team's production runs (Lambda), which account/model should v2 use? → *Default: an Anthropic API key in your name, Sonnet-class model for building, same for QC; ~$0.30–0.60 AI cost per guide.*
- R4-2. Google: is the existing `GOOGLE_MAPS_API_KEY` on a billing-enabled Google Cloud project, and may I enable Places API (New) + Routes API on it? → *Default: yes; I'll give you the exact console steps.*

**Days — content the rules don't cover yet**
- R4-3. Free time ("evening at leisure", "if energy permits"): suggest something, or leave it as free time? → *Default: leave as free time with one light, nearby suggestion only if the itinerary hints at one; never invent new attractions.*
- R4-4. Attractions: must every attraction come from the itinerary/notes (tool never adds its own)? → *Default: yes — the tool only enriches what the itinerary names.*
- R4-5. Breakfast: include it? → *Default: no, unless the itinerary mentions breakfast out (e.g. "breakfast → short walk" on Trip E's last day).*
- R4-6. Arrival day: airport → hotel by each allowed mode with time and approx cost; departure day: hotel → airport with a "leave by" time from the flight time (e.g. 3 h before international)? → *Default: yes; "leave by" gets a verify marker.*
- R4-7. Inter-city travel days (train/flight between cities): include station/airport transfer at both ends, plus lunch near wherever they are around midday? → *Default: yes.*
- R4-8. Group adjustments: seniors, kids or mobility needs — tighter limits (e.g. walking ≤5 min for seniors), kid-friendly restaurant preference? → *Default: walking ≤5 min when seniors/mobility needs are noted; otherwise same rules.*

**Sections the library may not cover**
- R4-9. Getting Around, Must-Try Dishes, Souvenirs, Etiquette & Phrases: library first; if missing, AI-written with a verify marker? → *Default: yes (same as R3-5).*
- R4-10. Packing list: AI-written from season, weather and booked activities (hammam, mosque visits, hiking) — no marker needed? → *Default: no marker; it's advice, not facts.*

**Look & assets**
- R4-11. Cover: Trip D's cover image is US Letter size. Do you have an A4 version, or should I rebuild it at A4 from the brand assets (logo PDF, navy, gold border, tagline)? → *Default: I rebuild it at A4 and you approve it.*
- R4-12. Header/footer: mockup has tagline left + page number right; Trip D has logo header + phone/website footer. → *Default: small logo in the header; footer "Your Vacation · Your Story · Your Way" left, page number right; phone + website on the Thank You page only.*
- R4-13. Markers: yellow highlight with a prefix, e.g. **"⚠ VERIFY:"** / **"⚠ ADD RESTAURANT:"** / **"⚠ PRICE UNKNOWN"**; QC fails while any remain. → *Default: yes.*
- R4-14. Thank You page: fixed text taken from Trip D's guide? → *Default: yes, word for word.*
- R4-15. File name: "All Inclusive Guide - <Client> - <Destinations>.docx" (from the manual process). → *Default: yes.*

**Testing**
- R4-16. Test set: can I use Trip C (Lisbon), Trip D (Istanbul) and Trip E (NYC) as the first three test trips, and can you share their vouchers/tickets and the final shipped guides to compare against? → *Default: yes; we judge v1 on these three before the team uses it.*
- R4-17. Uploads: what file types do vouchers and tickets usually come as (PDF, DOCX, email printouts, images)? → *Default: PDF and DOCX supported; images rejected with a "paste text" message (per B-7).*
- R4-18. Spelling: British English throughout (brand tone guide)? → *Default: yes.*

**Added after round-3 answers 9–17**
- R4-19. Cache location → *Proposal: S3, in the same bucket the library already loads from, under a separate prefix (e.g. `aigv2-cache/places/…`), because Lambda has no lasting disk. Each entry = Google place ID, lat/long, status, hours, fetched-at date; refreshed if older than 30 days (hours/closures change). Locally it mirrors to a folder. Never mixed with `library_db/`.*
- R4-20. Regenerate after editing: regeneration works on the tool's copy, not on the Google Doc. If the team has already started editing in Google Docs, a regenerated .docx won't include their edits. → *Default: regenerate is meant for before editing; the UI warns about this. Each run's outputs are kept, so nothing is lost.*
- R4-21. Truly required intake fields (everything else may say "see attachments"): → *Default: client name(s); number of travellers + kids' ages; diet; travel mode; itinerary (pasted text or "see attachments"). If something is neither in the form nor in the attachments, the tool asks before generating.*
- R4-22. Where do past runs live, and for how long? → *Default: S3, per run folder (inputs, answers, generated .docx, QC report, verification sheet), kept 90 days; the web UI lists recent runs so the team can come back after the 15–30 min wait.*

---

## 10. Test data needed (R4-20 — pending from user)

For each of Trip C (Lisbon), Trip D (Istanbul), Trip E (NYC):
1. Client notes (have) — ideally re-done in the new intake template once it exists.
2. Itinerary PDF/DOCX as sent to the client.
3. All vouchers: hotel confirmations, BVM service vouchers, tours/shows/experiences.
4. Flight and train tickets.
5. The final shipped AIG (after QC), as .docx exported from Google Docs.
6. A short note from the team on known problems in that shipped AIG (anything they'd fix now).
Plus, if possible: **one long multi-city trip (10–15 nights, 2–3 cities, with an inter-city train)** with the same items — the three above are all single-city, so they won't test hotel changes, transfer days or long-trip format drift.

## 11. Round-5 questions (final)
- R5-1. Which OpenAI model should v2 use (exact model name), and does the proxy in `.env` expose it? → *Default: whatever model you name; same model for builder and QC agent.*
- R5-2. Personal letter page: blank page with "Dear <first name>," pre-filled and a "⚠ WRITE PERSONAL LETTER" marker (so QC catches it if forgotten), or completely blank? → *Default: pre-filled greeting + marker.*

**Round-5 answers (user, 2026-10-19, in chat)**
- R5-1. User asked Claude to choose from the GPT-6 range. **Choice: `gpt-6.1-sol` for all writing and the QC agent** (newest GPT-6, $2/M input, $10/M output per the proxy's pricing), **plus `gpt-6-luna` ($0.10/$0.50) for mechanical jobs** — reading the intake/vouchers into structured fields, simple classification. `gpt-6-astra` ($10/$50) rejected: 5× the price and would break the $1 budget. Both models verified responding through the proxy. Rough AI cost for a 10-day trip ≈ $0.40–0.80 incl. QC, leaving room for Google lookups within $1 — to be confirmed in the design.
- R5-2. **Letter page: "Dear <first name>," pre-filled + "⚠ WRITE PERSONAL LETTER" marker.**
