"""Place links: ask the team for a Google Maps link for places Google could not match, and apply the answers."""
from datetime import date
from typing import Callable, Optional

from src.aigv2.google.maplink import MapLinkError, default_fetch, is_maps_host, is_short, looks_like_url, \
    parse_maps_url, resolve_maps_link
from src.aigv2.models import Answers, Place, Question, TripPlan, place_key
from src.aigv2.planning.attraction_match import is_generic_name

PREFIX = "place_link:"
_SKIP_NAMES = ("free time", "overnight", "hotel check", "check-in", "check in", "check-out", "check out",
               "leisure", "at leisure", "rest day")
NEAR_MISS_YES = "Yes"


def place_targets(trip: TripPlan) -> dict[str, tuple[str, str, Optional[date], str]]:
    """key -> (name, city, first day, kind) for every named place the plan will look up."""
    out: dict[str, tuple[str, str, Optional[date], str]] = {}
    for h in trip.hotels:
        out.setdefault(place_key(h.hotel, h.city), (h.hotel, h.city, h.check_in, "hotel"))
    for dp in sorted(trip.days, key=lambda d: d.date):
        for it in dp.items:
            if it.kind in ("free_time", "transfer", "meal_out"):
                continue
            low = it.name.casefold()
            if not it.name.strip() or any(w in low for w in _SKIP_NAMES) or is_generic_name(it.name):
                continue
            city = it.city or dp.city
            out.setdefault(place_key(it.name, city), (it.name, city, dp.date, it.kind))
    return out


def place_link_questions(trip: TripPlan, places: dict[str, Optional[Place]]) -> list[Question]:
    day_no = {dp.date: i for i, dp in enumerate(sorted(trip.days, key=lambda d: d.date), 1)}
    qs = []
    for k, (name, city, d, _kind) in place_targets(trip).items():
        if k not in places:
            continue
        p = places[k]
        if p is not None and p.match_ok:
            continue
        where = f"{city}, day {day_no[d]}" if d in day_no else city
        how = ("Paste its Google Maps link (open the place in Google Maps > Share > Copy link of ONE place), "
               "or type the exact name as Google shows it, or answer Skip.")
        if p is not None:
            text = f'Google suggested "{p.name}" for "{name}" ({where}) but was not sure. Answer Yes to accept it. {how}'
            opts = [NEAR_MISS_YES, "Skip"]
        else:
            text = f'Google could not find "{name}" ({where}). {how}'
            opts = ["Skip"]
        qs.append(Question(id=PREFIX + k, kind="place_link", text=text, options=opts, day=d))
    return qs


def validate_place_link(ans: str, q: Question) -> Optional[str]:
    low = ans.strip().casefold()
    if low == "skip":
        return None
    if low == "yes":
        return None if NEAR_MISS_YES in q.options else "there is no suggestion to accept; paste a link or type a name"
    if looks_like_url(ans):
        if not is_maps_host(ans):
            return "that is not a Google Maps link; paste the Share > Copy link of ONE place"
        if is_short(ans):
            return None
        try:
            parse_maps_url(ans)
        except MapLinkError as e:
            return str(e)
        return None
    if len(ans.strip()) < 3:
        return "paste a Google Maps link, type the exact place name (3+ letters), or answer Skip"
    return None


def apply_place_answers(trip: TripPlan, questions: list[Question], answers: Answers, raw_places: dict,
                        client, fetch: Callable[[str], str] = default_fetch) -> dict:
    """Update raw_places (key -> Place json or None) in place; persist overrides. Returns {'applied': [...], 'failed': [...]}."""
    targets = place_targets(trip)
    overrides = getattr(client, "overrides", None)
    report = {"applied": [], "failed": []}
    for q in questions:
        if q.kind != "place_link":
            continue
        ans = (answers.get(q.id) or "").strip()
        if not ans or ans.casefold() == "skip":
            continue
        k = q.id[len(PREFIX):]
        if k not in targets:
            continue
        name, city, _d, _kind = targets[k]
        try:
            place, how = _resolve(ans, name, city, raw_places.get(k), client, fetch)
        except Exception as e:  # never abort the build for a bad answer
            report["failed"].append(f"link for {name} ({city}) could not be used: {e}")
            continue
        raw_places[k] = place.model_dump(mode="json")
        if overrides is not None:
            overrides.put(name, city, place.name, place.lat, place.lng, place.maps_url,
                          cid=how.get("cid"), place_id=place.place_id, address=place.address)
        report["applied"].append(f"{name} ({city}) -> {place.name}: {place.maps_url}")
    return report


def _resolve(ans: str, name: str, city: str, current, client, fetch) -> tuple[Place, dict]:
    if ans.casefold() == "yes":
        if not current:
            raise ValueError("no suggestion to accept")
        return Place.model_validate(current).model_copy(update={"match_ok": True}), {}
    if looks_like_url(ans):
        link = resolve_maps_link(ans, fetch=fetch)
        return client.from_link(link), {"cid": link.cid}
    found = client.find(ans, city)
    if found is None or not found.match_ok:
        raise ValueError(f'Google still could not match "{ans}"')
    return found, {}


def override_report(trip: TripPlan, client) -> list[str]:
    """Markdown lines for places matched from saved overrides (this run)."""
    ov = getattr(client, "overrides", None)
    seen: dict[str, dict] = dict(getattr(client, "override_hits", {}) or {})
    if ov is not None:
        for name, city, _d, _k in place_targets(trip).values():
            e = ov.get(name, city)
            if e is not None:
                seen.setdefault(f"{name}|{city}", e)
    return [f'- {e["name_asked"]} ({e["city"]}) -> {e["google_name"]}: {e["maps_url"]} (added {e["added"]})'
            for e in seen.values()]
