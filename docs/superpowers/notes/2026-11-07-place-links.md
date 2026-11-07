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
Restaurants are chosen at plan time (inside `build`), so they cannot be in the start-phase question list; the plan
checkpoint below covers them. Places that failed to match in attraction slots stay start-phase `place_link` questions.

## Plan checkpoint (optional pause between PLAN and WRITE)
Flow: `start` -> answer pre-flight questions -> `plan` (plans restaurants/schedule, saves `plan.json`, NO AI writing) ->
fix gaps -> `build` (writes, renders, QC). `build` still works alone in one go; the checkpoint is optional.

- CLI: `python -m src.aigv2 plan <run_id> --answers a.json` prints "Needs attention" items as `[meal_gap:<day>:<meal>]`.
  Add those ids to the same json with a Maps link (or `Skip`), run `plan` again to apply and re-list, then `build` with
  the same file. Several links for one slot may be separated by spaces.
- UI: "Plan restaurants first (optional)" next to Build guide -> `POST /api/aigv2/runs/{id}/plan {answers}` (background
  job; items are in `run.plan_items` and `job.questions`) -> paste links into the boxes -> press Plan again to apply,
  or just Build (build applies them too).
- Item `meal_gap` (kind `plan_gap`): a meal slot has fewer restaurants than wanted. Text: "Day N lunch near X: only k of 3
  restaurants found ... Library suggests: A, B, C" - the suggestions are the top 3 library restaurants (library rank)
  rejected only for "no confident Google match"; paste a link of one of those or any other place.
- Link format: Google Maps > open the restaurant > Share > Copy link (one place; same rules as place links).
- Applying: link -> `from_link` Place -> inserted as a pick (`lib.source = "user_link"`, no cuisine/price so PRICE UNKNOWN
  shows; hours from Google if found, else VERIFY), ADD RESTAURANT marker removed, travel time = straight-line estimate
  from the slot anchor (no Routes call), saved as an override (name|city). `plan.json` is rewritten, so
  `regenerate` uses it. Skip / blank / bad link leaves the marker; failures are listed in `plan_review.json`
  (`failed`) and printed as NOT USED. Applied answers are remembered in `plan_review.json` (`done`) so a later
  `build` with the same answers does not add a venue twice.
- Limitation: `regenerate --day N` re-plans that day from scratch, so links added to it must be re-applied.
- Not covered: unverified-diet confirmations (still VERIFY markers in the guide).
