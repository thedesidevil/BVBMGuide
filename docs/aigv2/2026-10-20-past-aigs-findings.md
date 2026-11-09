# AIG v2 — Findings from 167 past AIGs (2026-10-20)

Source: `input/for-aigv2/all-aigs/` (287 .docx → 208 unique texts → 167 after dropping older versions). Read by region: India domestic (39), East Asia (21), SE Asia (39), Europe/UK/Turkey (26), Middle East/islands/Americas/Oceania (28), plus the team's instruction docs. Focus: data and rules, not design.

## A. Plan changes — Claude's calls (no user decision needed)

**Hours & facts**
- Library hours are unreliable (AM/PM inversions in 16+ Europe guides alone: "11:30 PM – 8:30 PM", "11:00 PM – 11:00 PM", "12 AM – 10 PM"). `parse_library_hours` rejects end-before-start (unless end ≤ 04:00), start == end, and 12 AM openings → hours unknown. Handle narrow no-break spaces and dash variants.
- Friday/holiday exceptions come from Google hours automatically; Ramadan dates (static table) → `⚠ VERIFY: Ramadan hours`.
- Last-entry times: from Google/library when present, verify-marked.
- Library facts containing prices or provider names (NOL card price, "Tata AIG Rs. 8370", "I would recommend Dialog") → always `⚠ VERIFY` even when library-sourced (recycled across years).
- Prices for rupee countries use unambiguous codes (MUR, LKR, NPR), never bare "Rs".
- Sunset time computed (astronomical formula, no API) when an item mentions sunset.

**Important Places**
- Filter by Google `primaryType` (hospital / pharmacy, drugstore / supermarket, grocery, convenience) and exclude non-care keywords (dental, physio, cardio, sexual health, circumcision, sports, cosmetic, veterinary, company offices "B.V.", "Ltd", petrol companies). Seen: steroid shop as pharmacy, medical-equipment firm and circumcision centre as hospital, ward health post closed weekends as hospital.
- Hospital = emergency hospital open 24/7; fallback "medical center/clinic" with `⚠ VERIFY` (islands).
- Show weekly hours with closed days, not just today.

**Transport**
- Rail/flight legs carry operator, train/flight number, stations, times, duration, seat/class; "reach station by" = departure − 40 min for trains (replaces −30). Luggage-drop tip when arriving before check-in.
- In-city transit legs carry Routes TRANSIT steps (line, direction, board/alight stop, stop count). Platform numbers only from tickets.
- Drive days: sequence of en-route stops with leg minutes, suggested stop duration, total km/time; lunch anchor = the stop at midday.
- Korea/China (weak Google coverage): place/route data `⚠ VERIFY`; Getting Around recommends Naver/Kakao (Korea), Amap (China).
- Early departures before 07:00: "ask the hotel for a packed breakfast" tip.
- Late-arrival lunch cutoff moves from 14:00 to 15:00 hotel arrival.
- Pickup time/place on bookings ("Pickup 2:00 PM from your hotel").

**Meals**
- Meal windows per country (Spain lunch 13:30–16:00, dinner 20:30–22:30; Greece dinner 20:00+); default elsewhere.
- Vegetarian rule also guards against hidden fish stock (Japan dashi): Japanese venues need explicit vegetarian proof.
- QC: a "best for dinner" restaurant in a lunch slot (or vice versa) → warning; repeats within one meal set → error.

**QC rules (new)**
- `title_destination`: title/subtitle must name the trip's destinations ("All Inclusive Guide- Bali" leaked into Kerala, Leh, Istanbul, Cappadocia, Japan, Lisbon guides).
- No thank-you/closing phrases outside the Thank You section.
- `placeholder` adds "Not specified", "Please see options below", "choose one of".
- `assistant_chatter`: first-person adviser voice ("I would recommend", "I'd aim/keep/suggest/skip/treat") and specific AI phrases ("Here are clear…", "in your preferred format", "Let me know if") — **not** bare "Here are" (house text uses "Here are few numbers you may need").
- Planner voice referring to the client in third person ("her", "him", "the client's") → error.
- Day headers must be real headings (format drift seen in Leh, Trip A).

**Multi-country trips**
- End sections that differ per country are grouped per country: emergency numbers, embassy/consulate (with email + after-hours number), dishes, souvenirs, phrases, currency, SIM (with multi-country eSIM option).

## B. Decisions needed from the user — see chat (2026-10-20)
1. Domestic India trips (39 of 167): what changes.
2. Included meals (resort all-inclusive / half-board, cruises, safaris, package meals).
3. Indian restaurants for Indian clients (25/39 SE Asia, 17/26 Europe guides include them).
4. Does Indian/Gujarati cuisine count as "known to fit" for vegetarian clients?
5. Parking line on venues.
6. Recurring house content: currency/forex, recommended apps, tipping, dos & don'ts, scams, insurance, plugs, transit cards/passes — where they go.
7. Cruises and overnight trains in v1.
8. Theme-park "how to do the park" blocks.

## C. Recurring content counts (for reference)
Currency/forex 37/39 SE Asia, 10/28 rest, Europe "Regarding Foreign Currency"; recommended apps 38/39 SE Asia, 12/21 East Asia, 9/28 rest; transit cards 20/21 East Asia, passes 17/26 Europe; tipping 19/26 Europe; dos & don'ts 24/39 SE Asia; scams 23/39 SE Asia; plugs 22/26 Europe, 32/39 SE Asia; insurance 33/39 SE Asia, 18/26 Europe; weather/season 16/28 rest, 33/39 India, 21/21 East Asia; parking 13/26 Europe (self-drive), many India guides.
