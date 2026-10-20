# AIG v2 — Automated All Inclusive Guide Generation + QC

Date: 2026-10-19 · Branch: `aigv2` · Status: **draft for approval** (builder check done; answers folded in)
Source of every decision: `docs/aigv2/2026-10-19-discovery-notes.md` (§ references below point there). Items marked **[Claude's call]** were left to Claude and can be overridden.

---

## 1. Intent

Bon Voyage by Marina's team builds each All Inclusive Guide (AIG) by hand in one long ChatGPT chat, pastes it into Google Docs, reformats it, and QCs it manually — some teammates spend **up to 8 hours on QC alone** (§5c). Mistakes still slip through, and they are almost all mechanical:

- walk times wrong ("2 min walk" that is 25 min),
- restaurants recommended for lunch that open at 4 PM,
- restaurants that have closed (carried over from old guides),
- attractions closed on the planned day or during midday hours,
- fewer than 3 restaurant options, repeated restaurants,
- format drift on long trips (Maps links stop being hyperlinks, restaurant fields change shape),
- QC false alarms because the checker doesn't know the client (e.g. diet).

v2 is a web-UI tool that takes the team's intake doc plus trip attachments and produces a **finished, on-brand, editable Word AIG**, checked by an **independent QC agent**, with anything uncertain clearly marked for a human. The team then uploads it to Google Docs, resolves the markers, and can re-upload it for a final QC pass.

**Success** (§5i): zero errors found in QC; accuracy is paramount; **never guess** — mark it. v1 is a win if it **saves ~50% of the team's time**; later versions iterate on team feedback. v1 is not expected to produce a ship-as-is guide.

## 2. Goals

1. One run turns intake + attachments into a complete AIG .docx in the new format and brand.
2. Every factual claim is either (a) from the client's inputs, (b) from the BVM library, (c) checked against Google, or (d) carries a visible marker for a human.
3. Formatting is produced by code, so it is identical on day 1 and day 15.
4. A separate QC agent re-checks the built guide independently and highlights problems in the doc.
5. Ambiguities are asked once, all together, before generation.
6. The team can regenerate any chosen days/sections, and can re-run QC on their edited doc.
7. Cost ≤ **$1 per AIG all-in** (AI + Google) (§5f, §5i).

## 3. Non-goals (v1)

- **Photos** of attractions/restaurants — deferred until v1 is adopted (§5h).
- **Any writes to the BVM library** — none, not even locations or approved corrections. The library is updated only by ingesting shipped, QC'd AIGs with the existing library tool (§5k #19, §5l R3-2).
- Reading screenshots/images (OCR) — the team pastes text instead (§5d).
- Writing the personal letter — always hand-written (§5b).
- Recommending restaurants from outside the library (§5e).
- Adding attractions the itinerary doesn't name (§5n R4-8).
- Special walking rules for seniors/mobility (§5n R4-12).
- Instagrammable Cafés section, Client Info page, trip summary table, per-day "at a glance" tables (§5g, §5k).
- Live editing inside Google Docs (the tool produces .docx; the team uploads it).

## 4. Anti-goals (would be failure even if it "works")

- A plausible-looking fact the tool made up (hours, prices, distances, fees, addresses) without a marker.
- A restaurant recommended that is closed at that meal time on that weekday.
- A walking leg over 10 minutes presented as walking.
- Planner commentary from the notes ("I'd skip Edge if you're already doing Top of the Rock") leaking into the client's guide.
- Format that varies between days.
- A marker that reaches a client unnoticed (QC must fail while any marker remains).
- Asking the team one question at a time mid-run.

## 5. Users & workflow

Teammates, in the existing web UI (FastAPI + React, `src/library/ui/`, `ui-frontend/`), deployed on Lambda (§5c).

1. **Upload**: the filled intake template (.docx) + attachments (itinerary, hotel vouchers, BVM service vouchers, tickets — PDF/DOCX). Images are rejected with "please paste the text" (§5d, §5n R4-21). Image-only content inside a .docx (e.g. Annie's pasted itinerary screenshot) is detected and reported the same way.
2. **Pre-flight**: the tool reads everything and shows **all** its questions in one web-UI form: missing required fields, contradictions, open choices in planner drafts (Top of the Rock *or* Empire State), ambiguous hotel nights or checkout dates, missing travel mode (§5d, §5l R3-7, §5m R3-11). The run does not start until answered. The tool also warns up front if a destination has no library data (it still proceeds if the user confirms; restaurant slots become gap markers) (§5m R3-14).
3. **Generate** (background job; UI says "check back in ~15–30 minutes"; recent runs are listed) (§5i, §5n R4-4).
4. **Download**: the AIG .docx, a **QC report**, and a **verification sheet** (§5k, §5m R3-12/R3-17).
5. **Regenerate (optional, before editing)**: a table of every day and every section with checkboxes and one **Regenerate** button. The UI warns that regenerated output won't contain edits already made in Google Docs; every run's outputs are kept (§5m R3-13, §5n R4-6).
6. Team uploads the .docx to **Google Docs**, edits there only, resolves all markers.
7. **Re-QC**: a separate screen where they upload the edited doc (downloaded from Google Docs as .docx) and the QC agent runs again (§5k).

During the first few AIGs the team will still check everything by hand, using the verification sheet (§5f).

## 6. Inputs

### 6.1 Intake template (Word/Google Doc) — to be drafted by the builder and reviewed by the team
Fixed labelled fields (parsed deterministically, no AI), ending with free-text **Additional notes** (AI-read) (§5d, §5m R3-9, §5n R4-5).

**Required** (if absent from both the template and the attachments, asked in pre-flight):
- Client name(s)
- Number of travellers + kids' ages
- Diet (restrictions, allergies, likes)
- Travel mode(s) (taxi/Uber, public transport, self-drive, walking-where-short)
- Itinerary (pasted text, or "see attachments")

**Optional — may say "use information from the attached files"**:
dates; cities & nights; hotel per city; flights/trains; confirmed bookings (tours, shows, time slots); seniors/mobility notes; budget level; occasion; must-dos/avoids.

### 6.2 Source of truth (§5c)
Vouchers win for hotels, flight/train times, checkout dates. Otherwise notes, then itinerary. Conflicts between sources become pre-flight questions.

### 6.3 Planner drafts
The itinerary field may contain a planner's draft with commentary and either/or choices (Saumitra case). The tool must (a) turn open choices into pre-flight questions, (b) strip internal commentary — it never appears in the guide.

## 7. Output document

Editable **.docx**, **A4**, designed to survive **Google Docs import** cleanly: real hyperlinks; fonts available in Google Docs (Cormorant Garamond, Georgia); cards built as bordered tables; no floating shapes or text boxes. **American English** (§5n R4-22). File name: `All Inclusive Guide - <Client> - <Destinations>.docx` (§5n R4-19).

### 7.1 Section order (§5k #15–17)
1. **Cover** — same branded navy cover image for every client (logo, gold border, tagline, phone, website), rebuilt at A4 from brand assets; Claude produces it, user approves (§5h, §5n R4-15).
2. **Personal letter** — "Dear <first name>," pre-filled + **⚠ WRITE PERSONAL LETTER** marker, rest blank (§5b, R5-2).
3. **Title + TOC page** (mockup style) — logo, gold italic kicker "Your All-Inclusive Guide", **creative destination title** (e.g. *Sakura Adventures*), subtitle "All Inclusive Guide – <Destination>", then a grouped TOC with clickable section links and **no page numbers** (§5g, §5h, §5k #18):
   - **Day by Day** — one entry per day
   - **Before You Go** — Tailored Packing List · Mobile Connectivity & SIM Guide · Health & Vaccination
   - **While You're There** — Important Places Around Your Stays · Getting Around · Must-Try Local Dishes · Souvenir Shopping Guide · Cultural Etiquette & Local Phrases · Safety & Emergency Contacts
4. **Days**
5. **Before You Go** sections (order as above)
6. **While You're There** sections (order as above)
7. **Thank You** — Annie's text verbatim + phone + website (§5n R4-16/R4-18).

### 7.2 Day format (§5g, mockup)
- Header: `Day 1 – Thu, 29 Oct | Welcome to Istanbul` (3-letter weekday and month, no year, pipe, plain title).
- Short intro (1–2 sentences).
- Time-slot headings in the mockup's gold italic: **Morning**, **Lunch near <anchor>**, **Afternoon**, **Evening**, **Dinner near <anchor>** — interleaved, only those the day needs. Breakfast only when the itinerary says breakfast out, from the library (§5n R4-9).
- **Attraction card**: name (Maps hyperlink); description (2–3 vivid sentences); facts grid with small-caps labels — travel time from previous stop per allowed mode, opening hours (for that day), entry fee, suggested duration, best time, dress code/etiquette, your booking (if confirmed), tips.
- **Restaurant card**: name (Maps hyperlink); facts grid — must-try dishes, approx. cost (local currency + INR in brackets, e.g. "€25 (~₹2,400)"), opening hours for that day, travel time from anchor; ambience + "best for" as pill tags.
- Arrival day: airport → hotel by each allowed mode with time and approx. cost. Departure day: hotel → airport with a "leave by" time from the flight (verify marker) (§5n R4-10).
- Free time stays free; at most one light nearby idea if the itinerary hints at one (§5n R4-7).
- Ends with "Overnight in <city>".
- No emojis; classy typographic styling like the mockup **[Claude's call, §5g]**.

### 7.3 Brand & styling (§5 branding, mockup `BVBMWebsite/tmp/BVBM FAQ Section/aig-preview/aig-preview.html`)
Navy #0C1F3E (titles), royal #2F5FA8 (small-caps labels, group labels, pills text), gold #C68A32 (kicker, time-slot headings), slate #41536E (body/lede), powder #AEC7E7 (rules), frost #EEF4FB (pill background), card border #DCE6F2, card fill #FBFDFF. Headlines Cormorant Garamond; body Georgia; labels Georgia small caps. Header: small logo. Footer: "Your Vacation · Your Story · Your Way" left, page number right (§5n R4-16). Exact sizes from the mockup spec in the discovery notes §5; the builder adapts px to pt.

### 7.4 Markers (§5n R4-17)
Yellow-highlighted inline text; QC fails while any remain. Types:
- `⚠ ADD RESTAURANT – <Meal>, Day N, near <anchor>` (§5j R2-1)
- `⚠ VERIFY: <what>` — AI-sourced facts (entry fee + official-site link, dress code, tips, embassy/SIM/health when not in library, inter-city day logistics, departure "leave by")
- `⚠ PRICE UNKNOWN`
- `⚠ WRITE PERSONAL LETTER`
- QC-agent findings (see §10), e.g. `⚠ CHECK: <issue>`

## 8. Content rules

### 8.1 Restaurants (§5e, §5j, §5l)
- **Library only** (incl. cafés, bakeries, breakfast, "where to try" for dishes). Never from Google or AI.
- **3 options per meal.** Fewer valid → list what's valid + one `⚠ ADD RESTAURANT` marker per missing slot. No suggestions in the UI.
- **Diet: only places known to fit** (user decision, builder check). Clients with no restrictions → every library restaurant fits. Clients with restrictions (vegetarian, no pork, no beef, nothing raw, allergies…) → a restaurant is used only if its library data positively shows it fits (e.g. `vegetarian_friendly`, a vegetarian/vegan cuisine, or dishes/notes stating it); unknown = excluded → `⚠ ADD RESTAURANT` gap. No AI judgement of diet fit. QC applies the same rule and the same client profile — no false diet alarms. Expect more gap markers for restricted diets until library ingestion captures diet info (future enhancement).
- Must be **open at that meal time on that weekday** and **operational** per Google; otherwise dropped → gap marker; the discrepancy is listed in the verification sheet/QC report (§5j R2-2).
- **Repeats**: within a city, a restaurant appears **at most twice in total**, and **never twice on the same day** (§5j R2-4).
- **Lunch anchor**: near that day's attractions by default; near the hotel when the itinerary has them at the hotel at lunchtime (check-in ~11 AM–1 PM, "return to hotel" after a morning start) (§5e).
- **Dinner anchor**: near the hotel by default. If there's an evening attraction: 1 near the attraction + 2 near the hotel. If the itinerary says dinner before/between/near X: all 3 near X (§5j R2-7, §5l R3-1).
- **"Near"**: lunch ≤10 min walk or ≤15 min by the trip's transport; dinner ≤20 min (§5l R3-3).
- Price: library price → local currency + INR at the day's rate, rounded to ₹50; missing → `⚠ PRICE UNKNOWN` (§5j R2-5).

### 8.2 Attractions (§5l R3-4, §5n R4-8)
- Only places named in the itinerary/notes.
- Hours and closed days from Google, checked against the planned weekday and time slot (incl. midday closures). Conflict → QC flag, never silently moved.
- Entry fee: AI + `⚠ VERIFY` + official-site link. Dress code and tips: AI + `⚠ VERIFY`. Descriptions: AI prose, no marker, but must contain no factual claims (§5l R3-6).

### 8.3 Travel (§5l R3-3/R3-7/R3-8, §5n R4-11)
- Modes shown = modes allowed by the intake (asked in pre-flight if missing).
- **Walking only when ≤10 min**; longer legs switch to the trip's transport.
- Times from Google routes: from the previous stop (hotel for the first stop); restaurants from their anchor.
- Inter-city travel days: transfers at both ends + lunch near where they are at midday; the day carries a `⚠ VERIFY` marker. Specific rules **[Claude's call, to iterate]**.

### 8.4 End sections
| Section | Source |
|---|---|
| Important Places Around Your Stays | **Per city/stay**: 2 pharmacies, 2 groceries/convenience stores, **emergency hospital** — from Google, within 10-min walk of the hotel (hospital: nearest), with Maps link, distance, hours (§5g #21, §5j R2-6) |
| Getting Around | Library; else AI + `⚠ VERIFY` (§5n R4-13) |
| Must-Try Local Dishes | Library dishes; "where to try" = library restaurants only |
| Souvenir Shopping Guide | Library; else AI + `⚠ VERIFY` |
| Cultural Etiquette & Local Phrases | Library; else AI + `⚠ VERIFY`; phrases as plain lines (§5k #14) |
| Tailored Packing List | AI, from season/weather + booked activities; no marker (§5n R4-14) |
| Mobile Connectivity & SIM | Library; else AI + `⚠ VERIFY` |
| Safety & Emergency Contacts | Library; else AI + `⚠ VERIFY`; Indian embassy/consulate address + phone checked on Google (§5l R3-5) |
| Health & Vaccination | Library; else AI + `⚠ VERIFY` |

AI-written section content is **never saved back** to the library (§5i, §5k).

## 9. Builder pipeline — principle: code decides facts, AI writes words

**[Claude's call]** The builder is code-orchestrated, not one long AI conversation:

1. **Extract** (`gpt-6-luna`): template fields parsed deterministically; attachments + additional notes + itinerary → a structured trip plan (travellers, diet, modes, hotels per night, flights/trains, bookings, per-day planned items with times, open choices, commentary removed). Source-of-truth rules applied; conflicts → questions.
2. **Pre-flight** questions (web UI, all at once). Answers merge into the trip plan.
3. **Resolve places** (code + Google): every hotel, attraction and candidate library restaurant → Google place (ID, location, status, hours). Ambiguous matches (name/area differ from library) are not used — they become QC-report items.
4. **Plan meals** (code): compute anchors, filter library restaurants by diet, open-at-meal-time, operational, distance, repeat rules; produce 0–3 valid candidates per slot. AI (`gpt-6.1-sol`) may only **rank/choose among valid candidates** and write their prose — it cannot add restaurants.
5. **Travel times** (code + Google routes) for every leg, applying the 10-minute walking rule.
6. **Write** (`gpt-6.1-sol`, structured JSON output): day intros, descriptions, creative title, AI-sourced section content — given only verified facts; returns prose + any fact it supplies flagged as AI-sourced (→ marker). Days written in parallel.
7. **Render** (code, python-docx): deterministic templates from §7. The renderer, not the AI, decides layout, links and labels.

Facts never pass through AI unmarked: hours, distances, statuses and links come from code; AI-supplied facts always get a marker.

## 10. QC agent (independent) (§5f)

Runs after building, and again on any re-uploaded edited doc. It reads **the .docx itself** (not the builder's internal data) plus the trip plan and pre-flight answers, and uses **fresh Google lookups**. Same model, separate prompt (§5k #12).

1. **Rule checks (code)**: section presence and order; day header format and weekday↔date; every venue has a working Maps hyperlink; 3 restaurants per meal or a gap marker; repeat rules; diet vs profile; restaurant open at that meal/weekday; attraction open at planned day/time; walking legs ≤10 min; hotel/dates/flight times consistent with vouchers; no leftover placeholders; no `utm_source=chatgpt.com`; no planner commentary; markers counted.
2. **Fresh fact checks (Google)**: re-verify status, hours, travel times against what the doc says.
3. **Sense check (`gpt-6.1-sol`)**: a "does this make sense?" read-through like the team does with ChatGPT today — e.g. 1 AM flight on the 15th means leaving the hotel on the night of the 14th; checkout date plausibility; contradictions between days (§5f, §1 voice note).
4. Findings are **highlighted in the doc** as `⚠ CHECK:` markers (not shown in the web UI) (§5k #8) and summarised in the QC report. **Never auto-fix** (§5f).
5. **Pass** = no markers and no findings.

**Verification sheet** (separate .xlsx or .docx): one row per place — day, place, what the guide says (hours, travel time, link), what Google says, match ✓/✗, blank "checked by" column (§5m R3-17).

## 11. Platform & cost

- **Models**: per-step split in §11b (mostly `gpt-6-luna`; `gpt-6.1-sol` for the QC read-through and as automatic fallback), via the OpenAI-compatible proxy locally and OpenAI directly in production — same models both places (§R5-1). New env var `AI_MODEL_FAST` alongside `AI_MODEL`.
- **Google**: existing `GOOGLE_MAPS_API_KEY`; enable Places API (New) + Routes API on the billing project — Claude sends console steps (§5n R4-2).
- **Cache** (S3, library bucket, separate prefix, e.g. `aigv2-cache/places/`): place ID, location, status, hours, fetched-at; refreshed after 30 days; never mixed with `library_db/` (§5n R4-3). Locally mirrored to a folder.
- **Runs** (S3 per-run folder: inputs, answers, trip plan, outputs, QC report, verification sheet), kept 90 days, listed in the web UI (§5n R4-4).
- **Background execution**: runs exceed one Lambda invocation's 15-minute limit risk; the job must be resumable from S3 checkpoints per stage, with no single invocation near the limit **[Claude's call; mechanism left to builder — e.g. async self-invocation per stage]**.
- **Budget**: ≤ $1 all-in per AIG. Builder must produce a per-run cost log (AI tokens + Google calls) and confirm on the test trips. Rough AI estimate for a 10-day trip: $0.40–0.80 incl. QC; Google cost reduced by the cache and Google's free monthly usage caps — to be measured.
- **Code location**: new package `src/aigv2/` **[Claude's call]**, so the current `prep` keeps working; the Prep panel stays hidden-but-available for one month after v2 ships, then is removed (§5k #20). Existing helpers (`src/common/ai_provider.py`, library DB reader, `hotel_options` styling patterns, Verify-tab rules) are reused where sensible.
- No auto-deploy to Lambda; deploys only when the user asks (memory).

## 11b. Model split per step (user decision, 2026-10-20)

Each step's model is a **config setting**, not hard-coded, so any step can be switched after measuring cost and quality on the test trips. Where luna output fails a code validation (schema, dates vs vouchers, hotel coverage), that step **automatically retries on sol**.

| Step | Model |
|---|---|
| Extract intake + attachments → trip plan (also tags open choices, vague days, planner commentary) | `gpt-6-luna` |
| Pre-flight ambiguity detection | **Code checklist** (no LLM) — see below |
| Rank valid restaurant candidates | `gpt-6-luna` |
| Day writing (intros, descriptions) + creative title | `gpt-6-luna` — **switch to `gpt-6.1-sol` if luna's writing proves deficient** |
| List-style sections (packing, SIM, getting around, etc.) | `gpt-6-luna` |
| QC: "no facts in prose" check | `gpt-6-luna` |
| QC: "does this make sense?" read-through | `gpt-6.1-sol` |

**Always `gpt-6.1-sol`, never `gpt-6-sol` (6.0).**

**Pre-flight checklist (code):** required fields missing from intake *and* attachments; any night without a hotel, overlapping stays, or gaps between stays; departure flight between 00:00–05:00 (→ "which night is checkout?"); notes vs vouchers disagreeing on dates/hotels/flight times (vouchers win, but ask when they conflict with notes); itinerary day count vs date range; missing travel mode; image-only uploads; destinations with no library data. Language-dependent items (open choices like "X or Y", "if comfortable", vague days like "Choose your day trip", planner commentary) are **tagged by luna during extraction** and turned into questions by code. Backstop: the sol QC read-through.

Revised AI estimate: **~$0.15–0.25 per AIG** (10-day trip), leaving most of the $1 for Google.

## 12. Testing & acceptance

- Test trips: **Jumana (Lisbon), Annie (Istanbul), Saumitra (NYC)** + ideally one **10–15 night multi-city trip** — user is gathering vouchers, tickets, shipped AIGs and known-problem notes (§10, pending).
- v1 is judged on these before the team uses it: every factual item either verified or marked; QC agent catches deliberately planted errors (wrong weekday, closed restaurant, 25-min "walk", repeated restaurant, missing hyperlink); format identical across all days; output imports into Google Docs with links and styling intact; cost per run ≤ $1.
- Comparison with the shipped AIGs is for coverage and tone, not as ground truth (their accuracy is unknown — §5n R4-20).
- **Library coverage prerequisite**: today Lisbon has no library data and Istanbul has only 8 restaurants; New York (27) is the only test city that exercises the restaurant pipeline. The user will **ingest the latest AIGs into the library before testing**. Until then, NYC is the primary restaurant test; Lisbon/Istanbul test everything else (and the gap-marker path).

## 12b. Decisions from the builder check [Claude's calls — override if wrong]

- **Untimed itineraries** (e.g. Jumana's paragraphs): the builder assigns Morning/Afternoon/Evening from the itinerary's order and wording, then checks those slots against Google hours. It does **not** ask about every untimed item; it asks in pre-flight only when the assigned slot conflicts with a place's hours and no other order works.
- **QC and the cache**: QC reuses cached place IDs, locations and travel times, but re-fetches **status and hours** fresh (cheap, and these are what goes stale). The **$1 cap covers the first full run** (build + one QC). Re-QC and regenerations cost extra, are logged, and should stay well under $1 each.
- **Restaurants the team adds by hand** into gaps: QC accepts them (they need not be library entries) and checks only the Google facts — open/operational, hours at that meal, distance, and diet where it can tell. Not being in the library is never a finding.
- **QC parsing**: the builder embeds stable structure in the .docx (consistent styles/labels per card) so QC can read venues reliably after a Google Docs round-trip; QC falls back to loose parsing for hand-added content.
- **Walking vs modes**: walking is shown for any leg ≤10 min regardless of the listed modes; other modes (taxi, public transport, self-drive) are shown only if listed in the intake.
- **Sign-off**: building starts after this document is approved. The rebuilt cover, the intake template and the Google API setup are approval checkpoints inside the plan, not blockers before it.
- **Library city naming** (e.g. empty `New York City.json` alongside a populated New York file): the builder resolves city aliases at read time; it does not rename or edit library files.

## 13. Left to the builder

- Intake template layout and exact field labels (team reviews before use).
- Exact pt sizes/spacing translating the mockup into Word styles; cover rebuild (user approves).
- Prompt wording; JSON schemas; how places are matched to Google (thresholds for "shaky" matches).
- Inter-city day rules (reasonable defaults, verify-marked).
- Background-job mechanism on Lambda; S3 key layout.
- Verification sheet as .xlsx vs .docx.
- Exchange-rate source.
- How much of the existing `src/aig/` and Verify-tab code to reuse.
