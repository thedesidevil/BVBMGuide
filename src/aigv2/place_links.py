"""Place links: ask the team for a Google Maps link for places Google could not match, and apply the answers."""
import re
from datetime import date
from typing import Callable, Optional

from src.aigv2.google.maplink import MapLinkError, default_fetch, is_maps_host, is_short, looks_like_url, \
    parse_maps_url, resolve_maps_link
from src.aigv2.models import Answers, Place, Question, TripPlan, place_key
from src.aigv2.planning.attraction_match import is_generic_name
from src.aigv2.textnorm import fold

PREFIX = "place_link:"
_SKIP_NAMES = ("free time", "overnight", "hotel check", "check-in", "check in", "check-out", "check out",
               "leisure", "at leisure", "rest day")
NEAR_MISS_YES = "Yes (accept suggestion)"
CONFIRM_YES = "Yes (correct)"
HOTEL_CONFIRM_OVERLAP = 0.95
_CITY_ALIASES = {"lucerne": ("luzern",), "luzern": ("lucerne",), "zurich": ("zuerich",), "geneva": ("geneve", "genf"),
                 "cologne": ("koln",), "munich": ("munchen",), "vienna": ("wien",), "florence": ("firenze",),
                 "rome": ("roma",), "venice": ("venezia",), "milan": ("milano",), "prague": ("praha",)}
_EVENT_RE = re.compile(r"\b(fireworks?|parade|shows?|light show|concert|ceremony|illuminations?|spectacular|"
                       r"performance|live music)\b", re.I)
_MOVE_RE = re.compile(r"^\s*(arrival in|arrive in|arrival at|departure from|depart from|departure|transfer to|transfer from|"
                      r"return to|travel to|train to|bus to|flight|fly to|check[- ]?in|check[- ]?out|evening at leisure|"
                      r"explore|stroll|walk around|day trip to)\b", re.I)


def _toks(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", fold(text)) if len(t) > 2}


def _booked(trip: TripPlan, it) -> bool:
    if it.booking_ref:
        return True
    names = [fold(b.name) for b in trip.bookings]
    n = fold(it.name)
    return bool(n) and any(n == b or n in b or b in n for b in names)


def _not_worth_asking(trip: TripPlan, it) -> bool:
    """Items whose name is not a single place Google can pin down, or that a ticket already confirms."""
    if _booked(trip, it) or _EVENT_RE.search(it.name):
        return True
    m = _MOVE_RE.match(it.name)
    return bool(m)


def _weak_hotel_match(name: str, city: str, p: Place) -> bool:
    """Not an exact match: names differ (token overlap < 0.95), or neither the city nor its local alias is in the address."""
    a, f = _toks(name), _toks(p.name)
    overlap = len(a & f) / max(len(a), len(f), 1)
    addr = fold(p.address or "")
    names = [fold(city), *_CITY_ALIASES.get(fold(city), ())] if city else []
    in_addr = (not names) or any(n in addr for n in names)
    return overlap < HOTEL_CONFIRM_OVERLAP or not in_addr


def _useless_suggestion(asked: str, found: str, kind: str) -> bool:
    """A near-miss that is only the city, or shares nothing with the asked name."""
    a, f = _toks(asked), _toks(found)
    if not f:
        return True
    if fold(found) in fold(asked) and len(f) <= 1 and kind not in ("hotel", "attraction", "activity"):
        return True
    if fold(found) in fold(asked) or fold(asked) in fold(found):
        return False
    return len(a & f) / max(len(a), len(f), 1) < 0.34


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
            if _not_worth_asking(trip, it):
                continue
            city = it.city or dp.city
            out.setdefault(place_key(it.name, city), (it.name, city, dp.date, it.kind))
    return out


def place_link_questions(trip: TripPlan, places: dict[str, Optional[Place]], overrides=None) -> list[Question]:
    qs = []
    for k, (name, city, d, _kind) in place_targets(trip).items():
        if k not in places:
            continue
        p = places[k]
        if p is not None and p.match_ok:
            if _kind == "hotel" and not (overrides is not None and overrides.get(name, city) is not None) \
                    and _weak_hotel_match(name, city, p):
                qs.append(Question(
                    id=PREFIX + k, kind="place_link", options=[CONFIRM_YES, "Skip"], day=d,
                    text=f'Hotel "{name}" ({city}): we matched it to Google\'s "{p.name}" at '
                         f'{p.address or "an unknown address"} ({p.maps_url}). Answer Yes if this is the right hotel, or '
                         "paste the correct Google Maps link (open the hotel in Google Maps > Share > Copy link of ONE "
                         "place), or Skip."))
            continue
        where = city
        how = ("Paste its Google Maps link (open the place in Google Maps > Share > Copy link of ONE place), "
               "or type the exact name as Google shows it, or answer Skip.")
        if p is not None and _useless_suggestion(name, p.name, _kind):
            if _kind not in ("hotel", "attraction", "activity"):
                continue
            p = None
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
    if low in ("yes", NEAR_MISS_YES.casefold(), CONFIRM_YES.casefold()):
        return None if (NEAR_MISS_YES in q.options or CONFIRM_YES in q.options) else "there is no suggestion to accept; paste a link or type a name"
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
    if ans.casefold() in ("yes", NEAR_MISS_YES.casefold(), CONFIRM_YES.casefold()):
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
