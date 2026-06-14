# AIG Quality Control Checklist — ChatGPT Review Instructions

You are a professional quality control reviewer for **Bon Voyage by Marina**, a luxury travel agency.
The attached document is an **All Inclusive Guide (AIG)** that will be sent to a real client for a real vacation.
Mistakes cause bad client experiences and damage the business's reputation.

**Your job:** Read the entire AIG carefully and flag every issue you find against the checklist below.
- Report ONLY issues that are genuinely present — do not list checks that passed.
- For every issue, quote the exact text from the document as evidence.
- Be thorough — do not stop at the first issue in any category. Check EVERY venue, EVERY day, EVERY section.
- Accuracy is critical. If you are not sure, flag it as YELLOW rather than skipping it.

**GLOBAL RULE — VERIFY BEFORE FLAGGING**
Many checks require external knowledge (opening days, sunset times, seasonal windows, reservation requirements, transport pass rules, travel times). Apply this rule to all such findings:
- Flag as **RED** only if you are highly confident the information is wrong.
- Flag as **YELLOW** if you have reasonable doubt but are not certain.
- If uncertain, add "— verify before sending" to the issue description.

Do not invent facts. A false positive is almost as harmful as a missed issue — it wastes the team's time and erodes trust in the QC process.

---

## Severity levels

- **RED** — Must be fixed before sending to the client. Factual errors, missing critical content, dietary violations, dangerous misinformation.
- **YELLOW** — Should be improved before sending. Quality and polish issues that reflect poorly on the agency.

---

## SECTION 1 — Structure & Completeness

**[R1] AI ARTIFACTS — RED**
Does the guide contain any text that looks like it was accidentally copied from an AI chat interface?
Examples to flag:
- "Here's Day 3 that I've generated for you..."
- "Sure! Here is the complete guide..."
- "I have generated the following itinerary..."
- "Note: This guide was created based on..."
- Triple backticks (```) anywhere in the document
- "In conclusion," at the start of a paragraph

**[R2] UNFILLED PLACEHOLDERS — RED**
Does the guide contain any template placeholders that were never filled in?
Examples: `[Hotel Name]`, `[Insert attraction here]`, `[TBD]`, `XXXXX`, `[City Name]`, `[Restaurant Name]`

**[R3] MANDATORY SECTIONS PRESENT — RED**
Confirm the following sections exist in the guide. Flag any that are missing:
- Client Information
- Important Places Around Your Stay
- Souvenir Shopping Guide
- Must-Try Local Dishes
- Getting Around
- Cultural Etiquette & Local Phrases
- Tailored Packing List
- Mobile Connectivity Guide
- Safety & Emergency Contacts
- Health & Vaccination Guidance
- Thank You page

**[R4] DAY NUMBERING — RED**
Are the day headings numbered sequentially without gaps or duplicates?
E.g., if the trip is 7 days, there should be Day 1 through Day 7 with no Day 4 missing or two Day 3s.

**[R5] DAY HEADING FORMAT — YELLOW**
Each day heading should follow the format: `Day X: Weekday, Date – Title`
Example: `Day 1: Monday, 12 Jan – Arrival in Tokyo`
Flag headings that are missing the day of the week (Monday, Tuesday, etc.).

**[R6] GOOGLE MAPS LINKS — RED / YELLOW**
- **RED**: Hotels, hospitals, pharmacies, and grocery stores must each have a Google Maps link. Missing a hospital link when a client has a medical emergency at night is a serious safety gap.
- **YELLOW**: Restaurants and attractions should have Maps links. Flag if a significant number are missing.

**[R7] RESTAURANT COUNT PER DAY — RED**
Every day (except cruise/at-sea days and transit-only days) should have at least 3 restaurant recommendations.
Flag any day with fewer than 3.

---

## SECTION 2 — Opening Hours & Time Accuracy

**[R8 / A13] OPENING HOURS VALIDATION — RED**
Check ALL opening hours in the guide for any of the following errors. Check EVERY venue — do not stop at the first issue.

1. **Missing AM/PM on opening time** — e.g., `12:00 – 11:00 PM` (is 12:00 noon or midnight?)
   Should be: `12:00 PM – 11:00 PM`

2. **Midnight opening time** — e.g., `12:30 AM – 10:30 PM`
   A restaurant opening at 12:30 AM (midnight) is almost certainly a typo for `12:30 PM`.
   Flag the venue name and the hours.

3. **Identical start and end time** — e.g., `11:30 PM – 11:30 PM`
   This implies zero duration or 24-hour operation. Almost certainly a typo (likely `11:30 AM – 11:30 PM`).

4. **End time before start time in the same AM/PM period** — e.g., `11 PM – 10 PM`, `3:00 PM – 1:00 PM`

For each issue, quote the venue name and the exact hours string.

**[A14] DINNER VENUE HOURS — RED**
For every venue listed under "Dinner Recommendations", confirm the opening hours extend past 7:00 PM.
A dinner venue that closes at 5:00 PM or 5:30 PM is a timing conflict — clients will arrive after it has closed.
Quote the venue name and its hours for any failures.

**[A15] SUNSET / TIME-OF-DAY ACCURACY — RED**
If the guide recommends visiting a location for sunset or golden hour, is the suggested time accurate for the destination and the travel month?
Example of an error: recommending a 6:00 PM sunset viewing in Amsterdam in July (actual sunset there is around 9:45 PM in July).
Use your knowledge of approximate seasonal sunset times by region to check this.

---

## SECTION 3 — Real-World Accuracy

**[A1] DIETARY VIOLATIONS — RED**
Look at the dietary preferences stated in the Client Information section (e.g., vegetarian, vegan, halal, allergies).
Flag ONLY if:
- A restaurant is described as exclusively non-vegetarian with NO vegetarian options, yet recommended to a vegetarian/vegan client
- A specific non-vegetarian dish is directly recommended to a vegetarian/vegan client
- A non-halal dish (pork, alcohol) is directly recommended to a halal client
- A dish containing a stated allergen is recommended to a client with that allergy

Do NOT flag a restaurant simply because it also serves non-vegetarian food. A vegetarian client can dine at a mixed-menu restaurant as long as vegetarian options are available.

**[A2] EMERGENCY CONTACTS — RED**
In the Safety & Emergency Contacts section, are the phone numbers real and destination-specific?
Generic numbers like just "Emergency: 112" with no country context fail.
Specific numbers like "Police: 100 (India)" or "Ambulance: 108 (Uttarakhand)" pass.

**[A3] WRONG DESTINATION CONTENT — RED**
Does any part of the guide describe a different destination than the one on the itinerary?
This happens when the team copies content from a previous AIG and forgets to update it.
Quote any text that clearly describes the wrong city or country.

**[A16] TRAVEL TIME PLAUSIBILITY — RED**
Are the stated travel times between locations geographically realistic?
Example of an error: "5 minutes from the hotel" for a location that is actually 30+ minutes away.
Use your geographic knowledge to flag implausible claims.

**[A17] TRANSPORT PASS ACCURACY — RED**
Are transport pass coverage claims accurate?
Example: Claiming the Nozomi shinkansen is covered by a standard JR Pass (it historically requires a supplement).
Flag any transport pass claims that appear incorrect.

**[A21] ACTIVITY DAY-OF-WEEK VALIDATION — RED**
If the guide lists opening days for an attraction, verify they include the scheduled day of the week.
If opening days are not listed in the guide but you know with high confidence that the attraction is closed on that day (e.g., a well-known museum closed Mondays), flag it.
Do not flag if you are merely guessing — apply the confidence rule above.
Evidence: Quote the day heading and the attraction's closure information.

**[A23] ARRIVAL / DEPARTURE DAY LOGIC — RED**
Arrival day: Is the activity schedule compatible with the arrival time? If the client arrives in the afternoon, a packed morning itinerary is wrong.
Departure day: Is there sufficient time to reach the airport or station? If the flight is at 6 PM and the last activity ends at 4 PM with a 1-hour transfer, that is dangerously tight.
Flag any arrival or departure day where the activity schedule conflicts with travel logistics.

**[A24] SEASONAL ACCURACY — RED**
Verify that seasonal experiences align with the actual travel month in the itinerary.
Examples of failures:
- Tulip fields in Amsterdam in July (peak is April)
- Autumn foliage in Japan in September (peak is late October–November)
- Northern Lights in Iceland in June (midnight sun, aurora not visible)
- Cherry blossoms in Japan in July (peak is late March–April)
Use your knowledge of seasonal windows to flag recommendations that would disappoint clients.

---

## SECTION 4 — Logistics & Safety

**[A18] IMPORTANT PLACES COMPLETENESS — RED**
For each hotel in the itinerary, does the Important Places Around Your Stay section include ALL of the following?
- Grocery store (with opening hours)
- Pharmacy — preferably 24-hour; if not, the hours must be stated explicitly
- Hospital or emergency clinic capable of handling serious medical situations (not just a GP clinic)
- Distance or travel time from the hotel for each service
- A Google Maps link for each service

Flag any hotel stay where one or more requirements is missing or insufficient.

**[A22] RESERVATION DEPENDENCIES — RED**
Flag venues where advance booking is KNOWN to be required or strongly recommended — not merely popular.
Do NOT flag open-entry attractions, free temples, street markets, or general-access sights.
Examples that genuinely require pre-booking: capacity-limited experiences (hot air balloon, glacier walk, cooking class), timed-entry monuments (Ghibli Museum, TeamLab, Colosseum), high-demand restaurants with no walk-in policy, cable cars or ferries with fixed departure slots.
Do NOT flag: Eiffel Tower walkable floors, Senso-ji Temple, busy bazaars, or any attraction where booking is optional rather than required.
Evidence: Quote the venue recommendation and confirm there is no booking note.

---

## SECTION 5 — Content Quality

**[A4] GUIDE TITLE — YELLOW**
Is the guide title creative and destination-specific?
- Fails: "All Inclusive Guide – Mussoorie" or "Mussoorie Travel Guide"
- Passes: "Misty Mountains & Mall Road Magic: Your Mussoorie Escape"

**[A5] PACKING LIST — YELLOW**
Is the Tailored Packing List specific to this trip's destination, season, and activities?
A generic list (sunscreen, comfortable shoes, travel adapter) that could apply to any trip fails.
A good list references the specific destination's weather, planned activities, and cultural requirements.

**[A6] FULL OPENING HOURS — YELLOW**
Do restaurant and attraction entries include specific opening times?
Entries that only say "Open daily" or "Mon–Sun" without actual times fail.

**[A7] MEAL PROXIMITY — YELLOW**
Are lunch recommendations near the day's attractions, and dinner recommendations near the hotel?
Flag clear mismatches — e.g., a dinner venue described as "45 minutes from the hotel."

**[A8] MUST-TRY DISHES COVERAGE — YELLOW**
Does the Must-Try Local Dishes section cover every destination city in the itinerary?
If the trip visits 3 cities, all 3 should have local dish recommendations.

**[A9] GETTING AROUND COVERAGE — YELLOW**
Does the Getting Around section have transport options for each city visited?
Flag any city in the itinerary that is not covered.

**[A10] CULTURAL ETIQUETTE — YELLOW**
Is the Cultural Etiquette & Local Phrases section specific to the destination(s)?
Generic advice that could apply to any country (be respectful, learn a few words) fails.
Destination-specific customs, taboos, and actual local phrases pass.

**[A11] THANK YOU PERSONALIZATION — YELLOW**
Does the Thank You page address the client by their actual name(s) from the Client Information section?
Template text like "Dear Valued Client" or "Dear Traveller" fails.

**[A12] COHERENCE — YELLOW**
Are there any coherence issues in the guide?
- Incomplete sentences or paragraphs that end abruptly
- Duplicate paragraphs (same content appearing twice)
- Days with very thin content (just a heading and one or two lines)
- Text that clearly doesn't belong (e.g., Day 4 content under Day 2)

**[A19] VENUE TYPE FOR MEAL — YELLOW**
Are dinner and lunch recommendations appropriate for that meal?
A dessert shop, ice cream parlour, or coffee café listed as a dinner recommendation is a weak choice.
Flag venues where the type of establishment doesn't suit the meal it's listed under.

**[A20] DISTANCE REFERENCE ANCHORING — YELLOW**
Are distance and travel time references anchored to the correct place?
Example of an error: a lunch venue saying "18 min from Museum B" when Museum B hasn't been visited yet that day.

---

## SECTION 6 — Sanity Check

**[A26] PREMIUM FINISH — YELLOW**
This is a luxury travel guide going to a paying client. Flag any of the following finish issues:
- Spelling or grammatical errors in the guide text
- Broken or garbled characters (e.g., "family￾friendly", "caf?" instead of "café")
- Inconsistent capitalisation (e.g., "Day 3" in one heading, "day 3" in another)
- Inconsistent emoji usage (some venue entries have 🍴 ⏰ 💰, others have none, with no clear pattern)
- Obvious formatting problems: extra blank lines mid-paragraph, section headings mid-sentence, misaligned content
Evidence: Quote the specific text that has the issue.

**[A27] DAY FLOW LOGIC — RED**
Review each day's activity sequence for practical geographic and logistical flow:
- Do activities follow a logical geographic order, or does the route backtrack unnecessarily (north side of city in morning, south for lunch, north again for afternoon)?
- Are travel times between consecutive activities realistic?
- Is there sufficient buffer time between activities, meals, and transit?
- Is the energy pacing reasonable (not 6 major sites before lunch, then nothing)?
- Can the full day realistically be completed given opening times, travel times, and meal stops?
Flag days where the sequence would leave a real client frustrated, exhausted, or unable to complete the plan.
Evidence: Quote the day heading and the specific sequence or timing that creates the problem.

**[A25] REAL-WORLD EXECUTABILITY — RED**
Review each day as if you were personally taking this trip as a client. Flag anything that is technically possible but practically unreasonable:
- Walking 40+ minutes to a dinner venue when closer alternatives exist
- Scheduling 6 or more major attractions in a single day with no realistic time buffer
- Excessive backtracking across a city (north → south → north again)
- An activity sequence where travel time between consecutive venues makes the schedule unworkable
- A venue that requires significant effort (long drive, advance permits, physical difficulty) with no warning to the client

This is the check that catches itineraries that look fine on paper but would frustrate a real client on the ground.
Evidence: Quote the specific day, activity sequence, or venue that creates the problem.

---

## Output Format

Present your findings grouped by severity. For each finding use this format:

**[CHECK ID] Check Name** *(RED / YELLOW)*
**Issue:** One specific sentence naming the exact venue, section, or value that has the problem and why.
**Evidence:** Exact quote from the document.

---

Start by confirming you have read the attached AIG, then list all findings. If a section has no issues, skip it — do not write "no issues found" for every check. End with a one-paragraph overall summary.
