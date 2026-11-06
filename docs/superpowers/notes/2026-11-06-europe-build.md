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
