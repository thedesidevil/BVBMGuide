# Dilna Bali: generated (run 20261105-gdocs-check6) vs hand-curated, content comparison

Scope: content only (layout and look are final and out of scope). Sources: `aigv2_data/runs/20261105-gdocs-check6/` (guide.json, days/*.json, plan.json picks + exclusions, qc_report.md) and the hand-curated `Dilna- Bali- All Inclusive Guide.docx`. Read-only analysis; no LLM, Google or build calls.

## 0. Caveats that colour the whole comparison

1. **Not an independent test.** `library_db_new` (Ubud, Tegallalang, Tampaksiring, Nusa Lembongan) contains records whose `_source_file` is the hand-curated Dilna guide itself (`Bali Indonesia/Dilna- Bali- All Inclusive Guide.docx`, 2026-10-20). Attraction text for Tegallalang, Tirta Empul, Devil's Tear and Dream Beach is therefore near-verbatim the hand-curated text. Where our guide matches the reference, part of that is leakage. Where it still misses, the miss is a real engine gap, not a data gap.
2. The hand-curated guide has its own defects (leftover names "Tanya"/"Tanya's guide", "Lempuyang", Day 8 label "Near D'NUSA" for the Sanur hotel, Jinny's Garden hours garbled, Rapuan Cili listed for a 7:30 PM dinner though it closes 8 PM). It is a target for content, not for typos.
3. The generated guide is still FAIL in QC (25 findings, 30 markers). Many "missing" items below are intentional VERIFY/ADD markers.

## 1. Day-by-day content comparison

Restaurant overlap, hand-curated picks that also appear in ours: **7 of 30** (D4 lunch 2/3, D5 lunch 2/3, D6 lunch 2/3, D7 dinner 1/3, everything else 0/3).

### Day 1, Thu 24 Sep, arrival
- Reference: meet-and-greet, "Approx. 90 mins from the airport", private AC vehicle, English-speaking driver, "settle into the room".
- Ours: flight card (SQ 948, lands 00:10), transfer card, sightseeing card with "Pick-up time 00:10", overnight card. **No transfer duration** (VERIFY marker), no vehicle/driver info, no "after a late arrival, rest" warmth.
- Wrong/unsupported: the pick-up time card says 00:10 while the voucher says 23:00 (QC error; marker left inline). Fine as a flag, but the guide shows it twice.

### Day 2, Fri 25 Sep, Tegallalang / Ubud Palace / Ubud Market
- Attractions: all 3 covered, same order as reference. Descriptions are essentially the library text.
- Reference extras missing in ours:
  - "Good to know" block for the terrace (wear comfortable footwear, sun protection, swings optional and not in the booked service, cafe food at own expense). The library has these as `tips` for Tegallalang Rice Terrace, but `days/day_02.json` shows `"tips": null` on every attraction.
  - Palace: dress code (shoulders and knees), "free admission to general grounds", and the toddler tip "30-45 minutes is plenty" (ours gives only "Duration 30-45 minutes").
  - Travel-time notes: reference 45-60 min hotel to terraces, 35 min to Palace, 1 min Palace to Market. Ours 33 min, 24 min, "Walk 4 min | By car 2 min". Ours are Google-derived and probably more accurate; the reference is rounded and arguably padded. Acceptable difference.
- Timings: ours invents 2:54 PM (Palace) and 4:26 PM (Market). That leaves a 90-minute gap after a 30-45 minute Palace stop, so the schedule looks padded and arbitrary. Reference gives no clock times for the stops, only the 1-6 PM window and a "~6:00 PM back" note.
- Lunch: reference gives 3 scenic cafes at Tegallalang (TIS Cafe, d'Alas, RUMA), because the tour starts at 1 PM and lunch is on the way. Ours gives a hotel-area lunch at 11:30 (Sendang, Lao Ba Cha, Wedja). Defensible (tour starts 13:00) but loses the scenic-view lunch. d'Alas and RUMA exist only in `Tegallalang.json`; TIS Cafe was excluded `too_far` ("straight-line 13.0 km") because the lunch slot is anchored on the hotel, not on the first attraction.
- Dinner: reference Jinny's Garden, Wedja, TanaRasa. Ours Galle Club (a vegetarian-leaning Sri Lankan place), Bebek Tebasari, Ramu Kitchen. Jinny's Garden was excluded `too_far` ("walk 71, car 22 min"); TanaRasa was never picked (excluded only at D4 lunch); Wedja was used at lunch (`repeat_limit`: "already used this day").
- Tone: reference "Morning, a slow start at Mayura... enjoy the pool". Ours has no hotel-leisure morning (just "Breakfast, included").

### Day 3, Sat 26 Sep, Bali Safari and Marine Park (Sea Dragon)
- Ours: one card, **"Marine Park (Sea Dragon Package) is the day's featured activity."** plus VERIFY "place not found on Google". The library has a full description for "Bali Safari & Marine Park" (Ubud.json: "Family-friendly park with underwater exhibits, interactive experiences, animal encounters...") that was not matched to "Marine Park". This is the weakest day. Reference has the long description, opening hours (9:00-5:30), toddler tips (stroller, hat, water, check show times), and "~30 min from the resort".
- Lunch: **ours has none**, only "Lunch falls within your full-day package; confirm with the operator whether it is included". Reference gives 3 near the park (Warung Bendega Lebih, Andrawina, Tsavo Lion). All three are in the library and were excluded as `too_far` from the hotel anchor (9-10 km) on the Day 2 lunch slot, so for Day 3 no lunch slot was created at all.
- Dinner: ours Sendang, Lao Ba Cha, Galle Club, i.e. the same restaurants as Day 2 (Sendang and Lao Ba Cha at Day 2 lunch, Galle Club at Day 2 dinner). Reference Bebek Tepi Sawah, Ramu, Basilico. Dinner variety is poor: the Day 3 intro even says "Choose from a range of dinner options" as its only sentence about the day's meals.
- Missing: "Return to Ubud" and a free pool afternoon (reference).

### Day 4, Sun 27 Sep, Kintamani / Tirta Empul / coffee
- Attractions: all 3 covered. Ours has Kintamani with VERIFY "place not found on Google" and a single line ("Pause at Kintamani Volcano View"). Reference adds "Mount Batur, Lake Batur", "90 min from the resort", "Open 24/7".
- **Tirta Empul: the key menstruation notice** ("Women on their menstruation cycle are not permitted to enter the temple"), which the library holds with `tips` and `dress_code`, is not on the Day 4 card in ours. It appears only inside the generic Etiquette page. Dress code and the "spare dry clothing if joining purification" note are also not on the day (the latter is in Packing).
- Coffee Plantation: ours "Visit Coffee Plantation in Peliatan for a stop among the plantation grounds." **"in Peliatan" is unsupported** (Peliatan is in Ubud, not on the Kintamani/Tampaksiring route; the Google match is an unrelated place, hence travel "By car 41 min"). Reference: coffee and herbal tea tasting, process explained. Ours loses the "Balinese coffee and herbal tea tasting" detail the library/voucher provides.
- Lunch: reference Bararasa Bali, The Nini Restaurant (marked "12+"), Nukad Tampaksiring. Ours Bararasa and Nukad only, plus an `ADD RESTAURANT` marker (the third was lost: The Nini = `no_match` on Google; all Ubud-town restaurants = `too_far` at 11-19 km from Tirta Empul). Note the reference's "12+" age restriction is a useful child-specific fact that we do not carry.
- Dinner: reference Rapuan Cili, Dmade, NOONIK. Ours Wedja, Ramu, Basilico. Rapuan was excluded correctly (`not_open_at_meal`, closes 8 PM). Dmade/NOONIK are in the library and weren't excluded; they just lost the ranking.

### Day 5, Mon 28 Sep, Ubud to Nusa Lembongan
- Logistics: ours is good and arguably better than reference: JourneyStrip (leave 7:00, check-in 8:15, departs 9:15), fast boat BookingCard, hotel check-in 2:00 PM. Reference has an explicit "Approx. 60 min from Mayura" and the 07:00 check-out.
- Weaknesses: "Mangrove Boat Experience... Take a boat experience at Nusa Lembongan Mangrove Forest." versus the reference's evocative paragraph (wooden boat, boatman explaining the ecosystem, "a nice contrast to the sightseeing-heavy Ubud days"). Library text is available (Nusa Lembongan.json). Seven VERIFY markers on the day (transfer time and cost, boat transfer timing, "location of Mangrove Boat Experience unknown", etc.).
- Lunch: ours The Sampan, Kayu Lembongan, Nisi; reference Kayu, Nisi, Warung Ten Poh (2/3). Dinner: ours Curry Traders, Little Prema, Ginger & Jamu; reference The Sampan, Warung Putu, Jala (0/3). Ginger & Jamu is a vegan/plant-based place, a poor fit for a family whose reference picks lean to "meat dishes". Curry Traders (opens 5 PM) is suitable but is repeated on Day 6.

### Day 6, Tue 29 Sep, Lembongan island tour
- Attractions: Yellow Bridge, Blue Lagoon, Devil's Tear, Dream Beach all covered. Descriptions OK for Yellow Bridge, Devil's Tear and Dream Beach, but Blue Lagoon is a single bare sentence ("Visit Blue Lagoon on Ceningan Island.") versus the reference's "dramatic limestone cliffs... exposed edges, so a look-and-photograph stop". That is a real safety tip for a toddler, and it is missing.
- Lunch: ours Sea Breeze, Bumbu Oma, Sandy Bay; reference Sea Breeze, Dhipa Warung, Bumbu Oma (2/3). Dhipa is in the library (Ubud.json record) but not Nusa Lembongan.json, so it wasn't a candidate here.
- Dinner: ours Curry Traders, Sampan, Nisi: **three of three repeat Day 5** (Curry Traders and Sampan from Day 5 dinner/lunch; Nisi from Day 5 lunch). Reference Sandy Bay, Indi Warung, Alponte. Our `exclusions` list marks Bumbu Oma/Sandy Bay as `repeat_limit` for Day 6 dinner only because they were already used at lunch, so the engine's repeat rule pushed in other repeats instead.
- Reference note on Sandy Bay "menu includes pork options, so choose non-pork dishes" has no equivalent in ours (see diet question below).

### Day 7, Wed 30 Sep, Lembongan to Sanur
- Logistics: ours has the JourneyStrip, fast boat card, Taksu Sanur check-in. Good.
- Shopping: ours has an OptionCards block (Icon Mall / Sindhu Market) with "Best visited later in the day: it opens at 5:00 PM", a useful catch. Reference has more descriptive text and the "What to look for" list (handicrafts, batik, spice blends, child-friendly souvenirs). Ours has minimal descriptions ("Choose Icon Mall as an optional afternoon stop in Sanur").
- Dinner: ours Sumak, Warung Blanjong, SEJA; reference Kayumanis (beachfront), Kaluma, Sumak (1/3). Kayumanis and Kaluma are in Sanur.json and were never excluded; just lost on ranking.

### Day 8, Thu 1 Oct, departure
- Ours: check-out checklist, leave-by 9:45 AM for the 13:15 flight, honest caveat text ("the road time is still to be confirmed"). Reference leaves 9:30 AM and gives a "hand luggage" checklist including "Child's essentials". Equivalent. Our explanatory sentence on the leave-by calculation is long and engineer-voiced, not client-voiced.

### Tone and voice
- Reference is warm second-person ("Enjoy a relaxed breakfast", "a nice contrast", "settle into the room") with a personal letter and recurring emoji section cues. Ours is competent but flat: openers are one-line summaries, attraction text is catalogue-like, and many cards read as system output ("Included in your package", "confirm with the operator", "Lunch during your package").
- The personal letter is an empty placeholder (`WRITE_LETTER` marker). The reference letter is specific (the team has done this trip, "exciting firsts for Ivaan", being "just a message away"). This is the biggest voice difference.
- No child-specific voice: the child (age 2) is only reflected in Packing ("For your little one") and the Health boat-crossing note. The reference weaves it into days ("with a young child 30-45 minutes is plenty", "a stroller can be useful").

### Facts in ours that are wrong or unsupported
- "Coffee Plantation in Peliatan" (Day 4).
- Day 2 clock times 2:54 PM and 4:26 PM (artefacts of the scheduler, not source data).
- Etiquette: duplicated bullets ("Greet locals with a smile and a light bow" twice; "Avoid touching anyone's head" twice), plus "Arrive at Ngurah Rai at least 3 hours before the flight" inside a Do list.
- Getting Around: "Airport to Ubud takes approx. 1.5 hrs by taxi from Denpasar International Airport (DPS)" (unusual airport name; DPS is Ngurah Rai); and meta/voucher text pasted as guidance ("Provider handles transport only, giving flexibility to switch things around in the itinerary", "Hotel bookings / Hotel-booked transport" duplicates).
- Money: repeated sentences ("Use only authorized money changers" three times) and "PT. Central Kuta" (Kuta, not on this route).
- Important Places: hours like "8-9 Mon-Sun", "7-10", "8-12am" without AM/PM; "Sampyan Mas" and "Buk Mang Mas Ubud" look like warungs, listed as shops; at Lembongan the 14-min "East Medical Care Center" is listed while the reference's 1-min "Nusa Medica Clinic" is not.
- Contact cards: Google Maps queries are suffixed with "Ubud" even for Denpasar/Jakarta entries (e.g. query `Consulate General of India – Denpasar Ubud`).

## 2. Reference sections

| Section | Reference has, ours lacks | Ours has, reference lacks |
|---|---|---|
| Important Places | Grouped by type (Pharmacies, Convenience store/Supermarket, Hospital/Medical clinic) with ~1-5 min distances. Nusa Medica Clinic (1 min) at Lembongan. | Address, phone, walk and drive minutes, VERIFY flags; 5 places per hotel. More complete, but includes dubious entries and ambiguous hours. Missing nearer clinic at Lembongan. |
| Must-Try Dishes | 12 dishes with a short "why" and 3-4 "Best places to try" *from the itinerary's own restaurants* (Bebek Tepi Sawah, Bararasa, Nukad, Sea Breeze, Jala...). Includes Ikan Bakar, Lawar Sayur, Sambal Matah. | 11 dishes. Restaurant lists are long and partly irrelevant to the trip (Scene Restaurant - The Samaya, Tandjung Sari, Dining Corner, Wajik) and Nasi Goreng alone has 8. Near-duplicates (Sate Lilit and "Balinese Chicken Satay (Sate Lilit)"; Nasi Goreng and Mie Goreng split). Babi Guling (pork) included without a note. Missing Ikan Bakar and Lawar. Several dishes have no restaurants (Babi Guling has one). |
| Souvenirs | Trip-specific narrative: Tegallalang craft shops, Kintamani coffee tied to Day 4, what to buy and where per category. | Categories overlap (Handicrafts, Home decor, "Handicrafts & Home Decor"); "Food" mixes coffee, chocolates, "Snacks and clothing"; recommends "Kopi Luwak" (animal-welfare concern, and not what the reference suggests); store names are mostly generic ("Markets", "Supermarkets", "Ubud"). No day linkage. |
| Packing | Seasonal sentence (September warm and humid), 8 groups with itinerary hooks. | Richer than reference: toddler panel, boat/mangrove items, Tirta Empul tops, adapter types. Ours is better. |
| Etiquette/Phrases | Short Do/Don't plus 5 phrases with warm one-liner. | 12-phrase table, Do/Dont, "Markets and tipping", Temple etiquette including menstruation note. More complete but duplicative. Missing "Nyak" as a table row (in a note instead). |
| Connectivity | Telkomsel, where to buy, 15-25 GB, tips, apps. | Same content, structured; one thin "Before you leave the airport" panel (a single check). |
| Safety | Tips + numbers + Indian consulate. | Adds Tourist Police, Jakarta embassy, scams, cliff/blowhole and sea-condition safety (good for Lembongan), though the VERIFY marker remains. |
| Health | Medications list. | Adds vaccines, food/water, toddler boat-sickness advice. Better than reference. |
| Getting Around | not in reference | Extra; mostly redundant and partly voucher text (see section 1). |
| Money | not in reference | Extra; useful (IDR rate, tipping) but repetitive. |

## 3. Prioritised gap list

Types: ENG = engine bug, LIB = library data gap, PROMPT = writing/ranking prompt, ACC = acceptable difference.

| # | Gap | Cause | Suggested fix | Effort | Type |
|---|---|---|---|---|---|
| 1 | Personal letter is a placeholder | Letter intentionally not generated (WRITE_LETTER marker) | Generate a draft letter from intake (names, child, occasion, prior-trip note, key moments) in the warm house voice; keep a review marker | M | PROMPT |
| 2 | Day 3 attraction is one bare line ("featured activity") and "Marine Park" not matched | Name "Marine Park (Sea Dragon Package)" does not match library "Bali Safari & Marine Park" and Google match fails | Add alias/fuzzy match step (token overlap + same-region), and fall back to library attraction description for unmatched names; carry the booked package name as a sub-line | M | ENG |
| 3 | Attraction "Good to know" tips, dress code, entry fee, best time never rendered (all null on Day 2-7 cards); Tirta Empul menstruation notice missing on Day 4 | Day-writing step leaves `tips`, `dress_code` etc. null even though library records carry them (Tegallalang, Tirta Empul) | Populate attraction fields from the matched library record before writing; render tips block under each attraction; always surface hard "Important" warnings on the day | M | ENG/PROMPT |
| 4 | Child-specific advice absent from days (stroller, 30-45 min cap, age limits like Nini "12+", cliff edges at Blue Lagoon) | Child age only reaches Packing and Health prompts | Pass kid ages into day writing; add 1-2 family tips per day (flagged as tips, no invented facts); store `min_age` in library records | M | PROMPT + LIB |
| 5 | Lunch missing on package days (Day 3) and too few restaurants on Day 4 (ADD RESTAURANT marker) | Meal slots anchored on hotel or attraction with a hard distance cap; restaurants near Safari/Tampaksiring not in range of the anchor, and "in package" lunch slot is skipped | When a full-day tour is booked and lunch is not stated as included, create a lunch slot anchored on the day's main attraction (Safari Park, Tirta Empul) and widen the radius for rural areas; cap fallback at 3 | M | ENG |
| 6 | Dinner repeats across days (Day 3 = Day 2 lunch/dinner list; Day 6 = Day 5 list) | Repeat rule applied only per-slot/day; library candidates with 3+ vs hotel anchor at Mas is small because Ubud-centre places are over the car-time cap (22-32 min) | Penalise repeats across the whole stay in the ranker; relax car-time cap for dinner (25-30 min) in Ubud or anchor dinner at the last stop of the day (e.g. Ubud Market for Day 2) | M | ENG |
| 7 | Dining fit: Galle Club (vegetarian-leaning), Ginger & Jamu (plant-based) offered to a family whose reference picks lean meat; no pork caution notes (reference: "menu includes pork, choose non-pork") | Diet "none" in intake; ranker has no preference signal; reference reflects planner knowledge | Ask the intake for "no pork / halal-friendly" explicitly, and add a pork flag on library restaurants (Sandy Bay, Kayumanis, Babi Guling); deprioritise cuisine types that are exclusively vegan when diet is "none" and notes say family | S-M | LIB + PROMPT |
| 8 | Dishes page: irrelevant/far restaurants, near-duplicate dishes, pork dish with no caution, no Ikan Bakar | Dish to restaurant mapping uses library-wide mentions instead of trip restaurants | Restrict "best places" to restaurants appearing in the guide (days) plus at most 1-2 generic fallbacks; dedupe by canonical dish; add pork flag/skip rule | M | ENG |
| 9 | Souvenirs page: overlapping categories, Kopi Luwak, generic store names, no trip linkage (Kintamani coffee on Day 4) | Merge of library souvenirs with no category normalisation | Normalise categories, drop Kopi Luwak by default, reference trip stops, move "Snacks and clothing" out of Food | M | ENG + LIB |
| 10 | Important Places: ambiguous hours, shops that are really warungs, missing nearer clinic at Lembongan | Hours formatting drops AM/PM; Google nearby search has no category filter beyond name | Format hours as "8:00 AM - 9:00 PM"; filter by place `types` (pharmacy, convenience_store, hospital/clinic); include clinics, not only the hospital, for islands | M | ENG |
| 11 | Day 1 transfer duration missing (VERIFY) and Day 5/7 transfer "time/cost" markers | Route lookup for airport to hotel and boat legs not computed | Use routes API for airport-hotel; use library `route_guides` for boat legs; keep marker only if still unknown | S-M | ENG |
| 12 | Day 2 invented clock times (2:54 PM, 4:26 PM) with large gaps | Scheduler spreads stops across the window | Fill from duration (30-45 min) and keep times compact, or show windows instead of exact times | S | ENG |
| 13 | "Coffee Plantation in Peliatan" unsupported | Google/geocode matched a generic name to a place in Peliatan | Treat generic names ("Coffee Plantation") as unmatched; ask for the real stop; do not add locality text | S | ENG |
| 14 | Boilerplate/duplicate text in Getting Around, Money, Etiquette (e.g. "Hotel bookings" twice, "authorized money changers" x3) and voucher meta text | Sections merge library facts + AI paragraphs without dedupe | Add a sentence-level dedupe/merge step in section builders; filter operator-meta sentences | S-M | ENG |
| 15 | Contact-card Maps queries carry the wrong city suffix | Query appends trip city | Build query from the contact's own city | S | ENG |
| 16 | Flat, catalogue tone; hotel-leisure mornings and "return to hotel" beats missing; verbose engineer-voice on Day 8 | Writing prompt asks for facts, not for planner voice | Add a voice guide with 2-3 sample sentences; add leisure and return beats from the plan | M | PROMPT |
| 17 | d'Alas, RUMA, Dhipa, Kaluma etc. not chosen | Library coverage exists but ranker prefers other options | Not a bug; small ranking variance | - | ACC |
| 18 | Our travel times differ from reference (33 vs 45-60 min) | Ours are Google-derived | Keep ours | - | ACC |
| 19 | Extra Money and Getting Around sections; richer Packing/Health/Safety | By design | Keep; clean duplicates (item 14) | - | ACC |
| 20 | Library contains the hand-curated Dilna guide as a source (leakage) | Library was rebuilt including this client's own AIG | For a fair test, evaluate on a trip whose AIG is excluded from the library, or tag and exclude it for this run | S | LIB |

## 4. Quality verdict

Not yet sendable with only light edits. The structure and reference pages are strong (packing, health, safety and logistics cards are often better than the reference), but a travel planner would still need to do real work on the days themselves.

Top 5 things she would edit:
1. **Write the personal letter** (empty) and warm up the day openers; the guide currently reads as a data sheet.
2. **Day 3 (Marine Park)**: replace the one-line "featured activity", add the park description, opening hours and toddler tips, and add three lunch options near the park.
3. **Day 4**: add the Tirta Empul warning and dress code on the day, fix "Coffee Plantation in Peliatan", and supply the third lunch (The Nini) she knows.
4. **Dinner picks**: replace repeated lists (Day 3 vs Day 2, Day 6 vs Day 5) and swap out the vegetarian/vegan options (Galle Club, Ginger & Jamu) and add the pork caution notes.
5. **Clean the reference pages**: de-duplicate Etiquette/Money/Getting Around text, tidy Dishes (restaurants she actually booked, Ikan Bakar) and Souvenirs (categories, Kopi Luwak), and resolve the 30 VERIFY markers (Day 1 pick-up time 23:00 vs 00:10, transfer durations, emergency contacts).

Also expect her to add a few kid-specific tips by hand, since none appear on the day pages.


## 5. Batch A fixes

Fixture-only work: no LLM, Google or pipeline calls. New tests: `tests/aigv2/test_batch_a.py` with trimmed library records in `tests/aigv2/fixtures/bali_batch_a/`.

| # | Result | What changed |
|---|---|---|
| 2 | NOT FIXED on purpose (user ruling) | No fuzzy / alias matching. "Marine Park (Sea Dragon Package)" stays unmatched: the card keeps the booking name as its title and the VERIFY "place not found on Google". Pinned by a test that the name does not link to "Bali Safari & Marine Park". Only exact (case/space-folded) names and a trailing parenthetical (e.g. "(Viewpoint & Scenic Cafe)") match the library. |
| 3 | Fixed | Day cards now read the matched library record (`planning/attraction_match.py: good_to_know`, `pipeline._library_attractions`, `guide/build._item`). Library `tips` are copied verbatim into the card's existing GOOD TO KNOW list: de-duplicated, no we/our/us lines, max 4, hard warnings (not permitted, prohibited, must, warning, cliff, strict) first and never cut. `entry_fee`, `dress_code`, `best_time` and library hours become facts (VERIFY-flagged when the record is legacy / needs verification). Verified on saved data: Tirta Empul shows the menstruation warning first and the dress code; Blue Lagoon shows the cliff-edge line; Tegallalang shows its three tips. |
| 5 | Fixed, with the user's limits | A lunch inside a long (6 h+) booking window, on a day where the stop at lunchtime is a MATCHED place, now anchors on that stop with a 20 min car cap (`MealSlot.max_min`), and the "in package" note stays when the voucher is silent about lunch. If the voucher states lunch is included, no options are offered. An unmatched stop (Marine Park) keeps the note only, no guess. Tirta Empul on Day 4 gets the wider radius. The planner cap per slot is `_limit()` in `planning/meals.py`. |
| 6 | Fixed | Planning was keyed per day: `uses_by_name` only stopped a third use. Now unused restaurants rank ahead of any already used in the stay, and a slot takes repeats only for the shortfall (fresh first, then ranked repeats). When fewer than 3 fresh candidates fit, the dinner car cap is relaxed by 5 minutes once before repeating. |
| 12 | Fixed | A short voucher window (under 6 h) packs untimed stops from each stop's library duration (45 min default) plus a 20 min drive allowance, so Day 2 no longer spreads 2:54 PM / 4:26 PM across the window. Post-lunch spacing uses the same durations. Displayed start times round to the nearest 15 minutes (`round15`, used by the day cards). Full-day windows keep the even spread. |
| 13 | Fixed | `is_generic_name` treats category-only phrases (coffee plantation, market, temple, beach, waterfall, viewpoint...) as unmatched unless the library holds exactly one such attraction. `resolve_places` no longer searches or reuses a cached Google hit for them; the card shows the generic name with VERIFY "location not specified in the voucher". The day writer is told matched=false stops have an unknown location, and a new validator rejects "in/at/near <Locality>" claims for unmatched stops. |
| diet | Fixed | `library.is_veg_only` (cuisine tags only veg/vegan/plant-based, or text such as "purely vegetarian", "vegan cafe") with `wants_veg(diet)`; veg-only venues are excluded in `_pool` unless the client asked for vegetarian/vegan. Checked on the Bali data: **Ginger & Jamu is plant-based only and is now skipped**; **Galle Club is not veg-only** (Sri Lankan and coastal Indian with veg dishes among its must-tries), so it is NOT excluded, as ruled. Also caught by the classifier: Mudra Cafe, Seeds Eatery, Zest Ubud, Plant Bistro, Alchemy Bali, Healthyubud, Soul Bites, Casa Curandera, Prasadam, and Udupi Bali (tagged Vegetarian). |

Not changed: the Day 2 reference-style scenic lunch on the way to the terraces (the tour starts at 13:00, lunch stays hotel-side) because the voucher window starts after lunch; Jinny's Garden remains `too_far`.

## 6. Batch B fixes

Tests: `tests/aigv2/test_batch_b.py`.

| # | Result | What changed |
|---|---|---|
| 1 letter, 4 kid tips, 7 pork flags | Skipped by the user | Team writes the letter; no child tips; only the veg-only rule (section 5) was taken from #7. |
| 3 | Done in batch A | Library lines copied onto the card as GOOD TO KNOW. |
| 8 Dishes | Fixed | `guide/reference._dishes`: WHERE TO TRY lists only restaurants picked in this guide's day meal blocks (otherwise the dish shows without the line); dishes are de-duplicated by canonical word set (Nasi Campur / Nasi Campur Bali, Sate Lilit / Balinese Chicken Satay (Sate Lilit)) and their where-to-try lists merged; cap 12; a dish whose name or description says pork/babi gets a plain "Contains pork." line. |
| 9 Souvenirs | Fixed | `merge_souvenirs`: categories sharing a synonym-folded title word merge transitively (Handicrafts + Home decor + Handicrafts & Home Decor), Kopi Luwak / civet lines dropped, a mixed fragment such as "Snacks and clothing" moves to the category it names, places unioned, cap 6. No trip linkage added (the library does not give it). On the saved run the 8 categories become 5. |
| 10 Important Places | Fixed | Hours are formatted with AM/PM ("8:00 AM – 9:00 PM Mon–Sun", "24 hours") in `hours.format_week` (the "8-9 Mon-Sun" came from the compact no-meridiem form). Groceries drop food venues (warung, cafe, restaurant... by name, because the cached `Place` carries no Google types). When no hospital is within 15 minutes, a nearer clinic from the nearby CACHE only (`PlacesClient.nearby_peek`, never a Google call) takes the hospital slot with a VERIFY note that it is a clinic. If the clinic search was never cached, nothing changes. |
| 11 Transfer durations | Partly fixed | Airport to hotel city: the library's own `transport_options` text is used (`airport_transfer_minutes`) only when every entry for the city agrees (Ubud: 90 min); shown as "Approx. 1 h 30 min by car" with a VERIFY "from the library guides". Sanur has no airport figure in the library, so its marker stays. Boat legs: the library `route_guides` hold drive-day stops, not harbour crossings, and no boat durations were in the cache, so the boat-leg markers stay (no new calls). |
| 14 Prose dedupe | Fixed | `dedupe_sentences` (sentence key-word subset test across a section) and operator/voucher meta filtering ("Provider handles transport only", "Hotel bookings", "Booking via the hotel", "without guide", "included in your package"...) in Money, Getting Around, Connectivity and Etiquette prose; duplicate headings merged; Dos and Don'ts de-duplicated (greet x2, touch head x2) and airport/check-in advice removed from the Do list. Wrong "Denpasar International Airport (DPS)" wording is library text and is left as is. |
| 15 Contact cards | Fixed | Maps query uses the city named in the contact itself (Denpasar, Jakarta); Tourist Police keep the trip city; others get the name alone. |
| 16 Voice | Fixed | Day-writing prompt asks for planner warmth with leisure beats ("Enjoy a slow breakfast at your hotel before heading out", "Return to your hotel to unwind before dinner"; no times or facts), validators unchanged. The builder adds a "Return to your hotel" card only when the last stop or booking ends at least two hours before dinner (Day 2 and the 8:00-18:00 tour days get none). Test checks the prompt contains the guidance. |
| 20 Leakage | Report only | The Dilna Bali guide is itself a source in `library_db_new`, so Tegallalang, Tirta Empul, Blue Lagoon, Devil's Tear and Dream Beach text matches the reference by construction. For a fair evaluation, run a trip whose AIG is not in the library, or ingest into a separate folder without that file. No code change. |
