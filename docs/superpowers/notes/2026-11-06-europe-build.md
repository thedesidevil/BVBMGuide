# Europe build (Sneha trip) - findings and fixes, 2026-11-06

Saved run: aigv2_data/runs/20261106-034752-0992be (QC FAIL, 130 markers: 64 ADD RESTAURANT, 65 VERIFY).
Fixtures: tests/aigv2/fixtures/europe/ ; tests: tests/aigv2/test_europe.py (+ test_meals.py, test_guide_build.py).

## Root cause of the 64 empty meal slots (item 1)
Not the diet filter, the car cap or Google lookups. Every meal slot had `anchors=[]` (unanchored), so the meal
planner never looked at a restaurant. Anchors come from the hotel place; all four hotels had `match_ok=False`:
- Google spells the cities "Luzern" (Lucerne), "Wilderswil" (Interlaken hotel in a
  neighbouring village), "Clichy" (Paris hotel in a suburb), and the voucher typo "Airport Mess" vs "Messe".
  `PlacesClient._match_ok` required the city name in the address or a `near` point.
- Day cities with slashes ("Paris / Lucerne") also made lunch/dinner wait on the wrong stay on train days, and
  `_library_country` filed Paris/Zurich under "Switzerland" (first of six country folders listing them).
Fix: `_match_ok` accepts local city aliases (Luzern, Zuerich, Wien, ...) and a lodging place whose name overlaps the
voucher name >= 0.7 (suburb / village); the library-country picker uses the city's own currency source folder.
Replay (saved plan.json + places.json + library_db_new, fake Places/Routes with Google-free coordinates):
meal slots with restaurants 0 of 18 -> 18 of 18; markers 64 -> 0 (replay only; real Google distances may drop some).

## Per item
1. City resolution: preflight `no_library` now uses `resolve_day_city` (no more "Paris / Lucerne" questions; a
   resolved city without data is still asked). Pipeline already resolved the day city. Train day Paris -> Lucerne:
   lunch moves to the arrival (13:45) and dinner is in Lucerne; the 'departure' of a train that is also the arrival
   no longer closes the day's meals. FIXED.
2. Public transport: no car mode => walk cap 15 min, transit cap 25 min (lunch and dinner) in `_Planner`. FIXED.
3. Open choices: header is now "AFTERNOON · TWO OPTIONS - CHOOSE ONE". An open choice answered "Interlaken"
   for "Return to Interlaken / nearby stay" no longer adds an "Interlaken" activity card. FIXED.
4a. Arrival-day items start after arrival + 60 min (`_after_arrival`). image_details answers
    ("Thu, 30 Apr 2026 03:30 PM - Loure museum+Seine River; ...") become timed PlannedItems unless the day already
    has that activity (time match or shared word stem); Disney/Hop-On/Tootbus/Eiffel lines are not duplicated. FIXED.
4b. `is_full_day` (library/booking duration >= 5h, window >= 6h, or Disney/Titlis/Jungfraujoch/day-pass names):
    no "Return to your hotel" beat; lunch anchored on the excursion place when Google found it, otherwise a
    "Lunch, Day N, near <destination>" marker (no hotel-city restaurants). Not fixed: restaurants near
    Disneyland/Titlis/Jungfraujoch need library shards for those places (not checked/ingested). PARTIAL.
4c. Untimed fireworks / light shows are the day's last item at 9:30 PM. FIXED.
4d. Train ticket ending outside the hotel city (Paris Est -> Bale SBB, hotel in Lucerne): no fake
    "Bale SBB -> hotel" transfer; VERIFY "onward train Bale SBB -> Lucerne: ticket not provided" then hotel check-in. FIXED.
4e. Places Google reports as CLOSED_TEMPORARILY: VERIFY "temporarily closed per Google - check before the trip".
    They are still shown in the plan (removing optional items outright was not done). PARTIAL.
4f. Departure day: untimed "Flight"/"Departure"/"Train to X" itinerary lines are dropped, so only check-out,
    transfer (leave-by) and the 16:30 flight card remain; meals stop at leave-by. FIXED.
5. Hotel typo: voucher name that is a prefix/word-completion of Google's name (Mess -> Messe) is replaced by the
   Google display name (hotel stay + places key). Suburb hotels accepted via item 1 rule. FIXED.
6. Multi-country reference sections:
   - Safety: SectionContent.numbers_by_country / contacts_by_country; EmergencyStrip(country=) and
     ContactCards(country=) per country with a country label (France then Switzerland). FIXED.
   - Money: one fact row "EUR (France) · CHF (Switzerland)" with both indicative INR rates. FIXED.
   - Getting around: rail-pass facts (Eurail, Swiss Travel Pass, Half Fare) dropped unless the trip text mentions a
     pass; airport facts of cities the trip does not fly to/from dropped (Paris CDG/Orly for a train trip). FIXED.
   - Health: hepatitis A / typhoid facts dropped when every trip country is Western Europe. FIXED. (Facts are
     filtered per country because each city's shard is already country-tagged; they are not merged across shards.)
   - Not changed: etiquette/dishes/souvenirs/connectivity stay generic per-country prose when multi-country.

## Not verified (no real calls allowed)
No real build was run; replay used fake Places/Routes. Re-run the Sneha trip once to confirm QC counts.

## Build 2 (run aigv2_data/runs/20261106-europe-b2, QC FAIL, 83 findings, $5.57) - fixes, 2026-11-06 (no real calls)

### 1. Exclusions / empty meal slots
- 788 exclusions: 599 diet, 98 no_match (34 names, mostly lunch/dinner repeats), 46 too_far, 18 repeat_limit, 15 closed, 12 not_open.
- Diet cause: `diet_fits` for plain `vegetarian` needed `vegetarian_friendly is True`, a veg cuisine tag or Indian cuisine
  (Zurich 15 of 49, Paris 25 of 77, Lucerne 16 of 49, Interlaken 18 of 56 pass); 36-54 venues per city have the field unset.
- The 23 remaining markers: 15 are unanchored by design (Day 2 Disneyland, Day 5 Titlis, Day 7 Jungfraujoch lunch: 3 each = 9, plus
  Day 9 lunch 3 and Day 10 lunch 2 near the airport hotel = 5; 1 each for Day 1/2/3/4 where only 2 qualified; total 23).
  Day 9/10 Zurich: 102 diet exclusions, rest no_match/too_far (walk 90+ min, transit 28-33 min > 25 cap).
- Fix: `library.diet_tier` (0 known fit, 1 cuisine usually has vegetarian dishes: Italian/Mediterranean/Asian/Swiss/cafe..., 2 unknown;
  None for steakhouse/bbq/seafood/grill/sushi/burger/kebab names or cuisine, or `vegetarian_friendly: false`). Only for a plain
  vegetarian client (not pure veg, not vegan, no other restriction). Tier 2 venues fill a slot only when fewer than the wanted
  count qualify (max 3 total), carry `diet_verify` and a "VERIFY: confirm vegetarian options" marker. Known-fit venues rank first.
  Diet none (Bali) unchanged. Not fixed: unanchored excursion-day slots (need library shards for Disneyland/Titlis/Jungfraujoch).

### 2. Vegetarian fit in prose
`library.dish_fits_diet / veg_dishes` (meat/fish word list, "vegetarian/veggie/vegan" in the text keeps it). Applied to:
restaurant `must_try_dishes` (planner), library `local_dishes` entries (reference_filter), and the dishes/souvenirs writer prompt
(told the family is vegetarian). FIXED.

### 3. Walk limit / travel-time mismatch
`qc.rules.walk_limit_for(trip)`: 15 when public transport is the only motorised mode (planner constant `TRANSIT_WALK_MIN`,
now shared from planning/travel.py), else 10. QC fact check now asks Routes for TRANSIT with the planned meal departure time
(same call mode/time the planner used; before it used no departure so Google returned a different timetable: 24 vs 33 min). FIXED.

### 4. Day structure
a) "Arrival in Paris" untimed transfer line restating the booked arrival is dropped (it was the 9:00 AM slot). FIXED.
b) Full-day park with a fireworks item: dinner anchored at the park (or "near <park>" marker). FIXED.
c) Eiffel: the open-choice item is named "Eiffel Tower (2nd floor)" (text head + selected option); the image line
   "Sat 02 May 10:45 AM - Eiffel Tower" gives that untimed item its time instead of being dropped/duplicated. The earlier
   "2nd floor" bare item is gone. The "unclear stop" inside the bus window was the bare "2nd floor" item. FIXED.
d) Train to Basel + unticketed onward leg: arrival estimate +75 min, lunch moves after it (cutoff 16:00). FIXED.
e) `after_journey`: visits before journey end (start + leg minutes + 30) are pushed, lunch moves after them; "Return to your hotel"
   only when the day has no transfer / inter-city move, stops include optional ones, and the beat is not before 15:00; label is
   "Afternoon" before 17:00. FIXED (uses pipeline legs["arrival"] minutes; untimed "Scenic train to X" only).
f) Visit-first travel day (Lauterbrunnen then Zurich): lunch anchored at the visits; transfer card follows the journey line.
   PARTIAL: the untimed "Travel to Zurich" item (14:00) is ordered by its slot; the 160-minute card now follows it, but the
   hotel check-in card is only deferred, no new departure time estimated.
g) Departure day: lunch only when leave-by - lunch end >= 60 min and the restaurant is within 15 min; otherwise no lunch slot
   and a tip "Lunch: have a light meal at the airport". FIXED.

### 5. Section content
a) `transport_off_trip`: drops library transport options whose "to X" endpoint is not a trip place, Pilatus/Harder-style rides not
   mentioned in the trip, and "Train to X" headings whose text never names X; `extract_transport` no longer merges a generic mode
   ("Train") into a route-specific one ("Train to Zurich"). FIXED.
b) Switzerland dishes: `Library.city()` merged a "France" region shard (29 French dishes) into every Swiss city; the section
   inputs now take `local_dishes` from the city's own shard (`city(region=False)`). FIXED.
c) Emergency numbers: national short lines (17/15/18, 117/144/118) preferred by vote, 112 as "Emergency (all services)", long
   local numbers and "non emergency"/NHS skipped. FIXED.
d) Hospital candidates exclude radiology/imaging/diagnostic/institute/MRI/IRG names. FIXED.
e) Stale "(~INR 2,600)" brackets stripped from library text (sections and attraction entry fees) so nothing disagrees with the
   guide's own rate. FIXED (the guide shows the CHF price only).
f) Sentences naming Swiss Travel Pass / Eurail etc. are removed from library facts and entry fees unless the trip mentions a pass. FIXED.
g) Title validator: must contain a trip city or country (country list passed from the plan), retried with the existing fallback. FIXED.

### 6. Google cost: $5.24 (text_search 87 = $3.05, nearby 14, details 36 = $0.72, route_element 197 = $0.985)
- text_search by city (plan.stats): Paris 25, Lucerne 16, Interlaken 18, Zurich 15 = 74 restaurant lookups; 13 more are hotel /
  attraction / endpoint lookups. Each restaurant that Google does not match costs up to 4 calls (query plus three simplified
  retries); 34 unique restaurant names failed to match (98 no_match exclusions), so about 30-60 calls were spent on unmatched names.
- details 36 = QC `fresh_status` per fact row; 57 rows, 44 distinct venues. Implemented: one Details call per place per QC run (memo).
- routes 197 elements: implemented: venues within the walking cap are not sent to DRIVE / TRANSIT matrices; the planner is
  unchanged otherwise. Straight-line pre-filtering already existed for cached places.
- Not implemented (listed): limit restaurant retries to 1 simplified query; cache "no match" results (None) for 30 days so a repeat
  slot does not re-query; skip lookups for library restaurants that already carry fresh Google fields (needs the ingester to store
  place_id/hours, see project_google_ingest_deferred); drop Details calls for places whose cached hours are < 7 days old.

### Not verified
No real build run; every fix is covered by unit tests on saved fixtures / fakes. Re-run Europe once to confirm QC counts.
