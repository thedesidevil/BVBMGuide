# Place links and overrides

## What the team does
After `start`, the question list ends with `place_link:<key>` questions, one per place Google could not match
(or matched only doubtfully; those say 'Google suggested "X" ... answer Yes'). Answer each with one of:

- A Google Maps link of ONE place: open the place in Google Maps, **Share > Copy link**. Short `maps.app.goo.gl/...`
  links and full `google.com/maps/place/...` links both work. Search and directions links are rejected.
- The exact name as Google shows it (one normal Google lookup with that name).
- `Yes` (only when Google suggested a place) or `Skip` (the VERIFY marker stays).

Answers are applied at `build`. A bad link or a network failure never aborts the build; it is listed in
`qc_report.md` under "Place links applied this run" as NOT USED.

## How a link is used
The short link is followed (plain HTTP redirect, no API cost) to the full URL. Name = path segment after
`/place/`; coordinates = the `!3d..!4d..` pin; cid = `0x..:0x..` (not a Places place_id, never sent to Places).
One text search (150 m bias around the pin) borrows place_id, hours, status and phone from the nearest candidate
whose name overlaps >= 0.5 or that is within 40 m. If none, the Place is built from the link alone
(hours missing, so VERIFY markers show). The user's link is always the confirmation (`match_ok`).

## Overrides
Each confirmed link is saved in `<library folder>/_place_overrides.json` (key = folded name|folded city; fields:
name_asked, city, google_name, lat, lng, cid, maps_url, place_id, address, confirmed_by, added). The library
builder, ingester and qc commands skip `_` files. `PlacesClient.find` / `peek` check overrides FIRST, so every
future guide (hotels, attractions, activities, transfer endpoints, restaurants) uses them with zero HTTP calls.
A file that cannot be read is treated as empty and copied to `.bak` first.

To remove a wrong override, delete its entry from the json. `qc_report.md` lists "Places matched from saved
overrides" (name -> Google name, link) so mistakes are noticed.

## Not covered / follow-up
Restaurants chosen at plan time (inside `build`) are not in the start-phase question list. An override added later
IS used for them. Proposal: a `plan` checkpoint (plan, list unmatched, ask, then write).
