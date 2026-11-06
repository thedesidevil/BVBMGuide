import json
import math
import re
from collections import Counter
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.aigv2.config import Settings
from src.aigv2.hours import format_for_day, is_open_for, parse_library_hours
from src.aigv2.library import diet_tier, is_indian, is_veg_only, norm_name, soft_veg_diet, wants_veg
from src.aigv2.google.places import _haversine_km
from src.aigv2.planning.travel import APPROX_LABEL, approx_car_minutes
from src.aigv2.llm import LLMStepError
from src.aigv2.models import Diet, Marker, Place, WeeklyHours
from src.aigv2.planning.slots import Anchor, MealSlot

_CAR_MODES = {"taxi", "self_drive", "private_driver"}
_MEAL_MINUTES = 60
_MAX_USES = 2
_BATCH = 6
_SPARE = 2
_DINNER_RELAX_MIN = 5
_ANCHOR_LOOKUPS = 9
_CITY_CEILING = 60
_TRANSIT_WALK_MIN = 15
_TRANSIT_MAX_MIN = 25
_KM_PER_MIN = 0.6
_LOC_KEYS = ("area", "nearby_landmarks", "location")
_STOP = {"the", "and", "near", "hotel", "restaurant", "cafe", "street", "road"}
_CAPPED = object()
_RANK_SYSTEM = (
    "You choose restaurants for a travel guide. Pick only from the candidate names given, copied exactly. "
    "Answer in JSON only."
)

Reason = Literal["diet", "closed", "not_open_at_meal", "too_far", "no_match", "hours_unknown", "repeat_limit"]


class ChosenRestaurant(BaseModel):
    lib: dict
    place: Place
    travel_min: int
    travel_label: str
    hours_text: str
    hours_verify: bool
    diet_verify: bool = False


class MealPick(BaseModel):
    slot: MealSlot
    day_index: int
    restaurants: list[ChosenRestaurant] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)


class Exclusion(BaseModel):
    name: str
    reason: Reason
    detail: str


class PlanStats(BaseModel):
    lookups_by_city: dict[str, int] = Field(default_factory=dict)
    capped_cities: list[str] = Field(default_factory=list)


class _Rank(BaseModel):
    picks: list[str]


def _effective_hours(lib: dict, place: Place) -> tuple[Optional[WeeklyHours], bool]:
    if place.hours is not None:
        return place.hours, False
    text = lib.get("hours")
    if isinstance(text, str):
        parsed = parse_library_hours(text)
        if parsed is not None:
            return parsed, True
    return None, False


def _limit(slot_or_meal, settings: Settings) -> int:
    """Car-time cap for a meal: the slot's own cap when it has one (rural lunch anchors, relaxed dinners)."""
    own = getattr(slot_or_meal, "max_min", None)
    if own:
        return own
    meal = getattr(slot_or_meal, "meal", slot_or_meal)
    return settings.dinner_max_min if meal == "dinner" else settings.lunch_max_min


def _travel(meal, walk: Optional[int], drive: Optional[int], transit: Optional[int],
            settings: Settings) -> Optional[tuple[str, int]]:
    if walk is not None and walk <= settings.walk_max_min:
        return "Walk", walk
    limit = _limit(meal, settings)
    opts = [(m, label) for label, m in (("By car", drive), ("By public transport", transit))
            if m is not None and m <= limit]
    if not opts:
        return None
    m, label = min(opts)
    return label, m


def _approx_car(meal, km: float, settings: Settings) -> Optional[tuple[str, int]]:
    """No road route from Google (islands): estimate from straight-line distance, same limits as a real drive."""
    mins = approx_car_minutes(km)
    if mins is None:
        return None
    limit = _limit(meal, settings)
    return (APPROX_LABEL, mins) if mins <= limit else None


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", norm_name(text)) if len(w) > 2 and w not in _STOP}


def _location_words(r: dict) -> set[str]:
    out: set[str] = set()
    for k in _LOC_KEYS:
        v = r.get(k)
        for s in ([v] if isinstance(v, str) else v if isinstance(v, list) else []):
            if isinstance(s, str):
                out |= _words(s)
    return out


class _Planner:
    def __init__(self, library, places, routes, diet: Diet, modes: list[str], llm, settings: Settings, trip_scope: str):
        self.library, self.places, self.routes, self.llm = library, places, routes, llm
        self.diet, self.settings = diet, settings
        self.car = bool(_CAR_MODES & set(modes))
        self.transit = "public_transport" in modes
        if self.transit and not self.car:
            # no car: a longer walk plus the metro / tram / train reaches the same restaurants a taxi would
            self.settings = settings.model_copy(update={
                "walk_max_min": max(settings.walk_max_min, _TRANSIT_WALK_MIN),
                "lunch_max_min": max(settings.lunch_max_min, _TRANSIT_MAX_MIN),
                "dinner_max_min": max(settings.dinner_max_min, _TRANSIT_MAX_MIN)})
        self.international = trip_scope == "international"
        self.uses_by_place: Counter = Counter()
        self.uses_by_name: Counter = Counter()
        self.places_by_day: dict[int, set[str]] = {}
        self.names_by_day: dict[int, set[tuple[str, str]]] = {}
        self.resolved: dict[tuple[str, str], Optional[Place]] = {}
        self.stats = PlanStats()
        self.exclusions: list[Exclusion] = []
        self._unknown_diet = False  # second pass: only venues whose diet fit is unknown (vegetarian clients)

    def _shard(self, anchor_name: str, city: str) -> tuple[str, list[dict]]:
        if norm_name(anchor_name) != norm_name(city):
            found = self.library.area_for(anchor_name, city)
            if found and found[1]:
                return found
        return city, self.library.restaurants(city)

    def seed(self, city: str, pick: MealPick) -> None:
        n = pick.day_index
        for c in pick.restaurants:
            name = norm_name(c.lib["name"])
            key = (norm_name(city), name)
            for a_name, _, _ in pick.slot.anchors:
                shard, cands = self._shard(a_name, city)
                hit = [(shard, cands)]
                if norm_name(shard) != norm_name(city):
                    hit.append((city, self.library.restaurants(city)))
                found = next((sh for sh, cs in hit
                              if any(isinstance(r.get("name"), str) and norm_name(r["name"]) == name for r in cs)),
                             None)
                if found is not None:
                    key = (norm_name(found), name)
                    break
            pid = _pid(c.place, key)
            self.places_by_day.setdefault(n, set()).add(pid)
            self.names_by_day.setdefault(n, set()).add(key)
            self.uses_by_place[pid] += 1
            self.uses_by_name[key] += 1

    def _exclude(self, name: str, reason: Reason, where: str, detail: str) -> None:
        self.exclusions.append(Exclusion(name=name, reason=reason, detail=f"{where}: {detail}"))

    def _peek(self, name: str, shard: str) -> Optional[Place]:
        peek = getattr(self.places, "peek", None)
        return peek(name, shard) if callable(peek) else None

    def _resolve(self, name: str, shard: str, near: tuple[float, float], budget: Optional[list[int]] = None):
        key = (norm_name(shard), norm_name(name))
        if key in self.resolved:
            return self.resolved[key]
        used = self.stats.lookups_by_city.get(shard, 0)
        cached = self._peek(name, shard)
        if cached is not None:
            self.resolved[key] = cached
            return cached
        if used >= _CITY_CEILING:
            if shard not in self.stats.capped_cities:
                self.stats.capped_cities.append(shard)
            return _CAPPED
        if budget is not None and budget[0] >= _ANCHOR_LOOKUPS:
            return _CAPPED
        calls = getattr(self.places, "calls", None)
        before = calls.get("text_search", 0) if isinstance(calls, dict) else None
        place = self.places.find(name, shard, near=near)
        new = 1 if before is None else calls.get("text_search", 0) - before
        self.stats.lookups_by_city[shard] = used + new
        if budget is not None:
            budget[0] += new
        self.resolved[key] = place
        return place

    def slot(self, n: int, day: date, city: str, slot: MealSlot) -> MealPick:
        pick = MealPick(slot=slot, day_index=n)
        meal = slot.meal.capitalize()
        if slot.unanchored or not slot.anchors:
            pick.markers = [Marker(kind="ADD_RESTAURANT", text=f"{meal}, Day {n}, near {slot.near_label or city}") for _ in range(3)]
            return pick
        need_indian = self.international
        for anchor in slot.anchors:
            name, _, count = anchor
            where = f"{meal}, Day {n}, near {name}"
            chosen = self._anchor(n, day, city, slot, anchor, where, need_indian)
            if any(is_indian(c.lib) for c in chosen):
                need_indian = False
            pick.restaurants.extend(chosen)
            pick.markers.extend(Marker(kind="ADD_RESTAURANT", text=where) for _ in range(count - len(chosen)))
        return pick

    def _max_km(self, slot: MealSlot) -> float:
        return max(self.settings.walk_max_min, _limit(slot, self.settings)) * _KM_PER_MIN

    def _pool(self, n: int, candidates: list[dict], shard_key: str, anchor_words: set[str], where: str,
              shard: str = "", a_xy: Optional[tuple[float, float]] = None,
              slot: Optional[MealSlot] = None) -> list[dict]:
        names_today = self.names_by_day.setdefault(n, set())
        pool, seen = [], set()
        for i, r in enumerate(candidates):
            rname = r.get("name") if isinstance(r.get("name"), str) else ""
            key = norm_name(rname)
            if not key or key in seen:
                continue
            seen.add(key)
            tier = diet_tier(r, self.diet)
            if tier is None:
                if not self._unknown_diet:
                    self._exclude(rname, "diet", where, "not known to fit the client's diet")
                continue
            if (tier == 2) != self._unknown_diet:
                continue  # unknown-fit venues are only tried in the second (verify) pass
            if is_veg_only(r) and not wants_veg(self.diet):
                self._exclude(rname, "diet", where, "vegetarian-only venue; the client did not ask for vegetarian")
                continue
            if (shard_key, key) in names_today:
                self._exclude(rname, "repeat_limit", where, "already used this day")
                continue
            if self.uses_by_name[(shard_key, key)] >= _MAX_USES:
                self._exclude(rname, "repeat_limit", where, f"already used {_MAX_USES} times")
                continue
            dist = None
            known = self._peek(rname, shard) if a_xy is not None and slot is not None else None
            if known is not None and known.match_ok:
                dist = _haversine_km(a_xy[0], a_xy[1], known.lat, known.lng)
                if dist > self._max_km(slot):
                    self._exclude(rname, "too_far", where, f"straight-line {dist:.1f} km")
                    continue
            pool.append((-len(anchor_words & _location_words(r)), self.uses_by_name[(shard_key, key)], i, r, dist))
        # a restaurant already used on another day goes behind every unused one (stay-wide variety)
        ordered = []
        for used in (False, True):
            tier = [t for t in pool if (t[1] > 0) is used]
            near = sorted((t for t in tier if t[4] is not None), key=lambda t: t[4])
            rest = sorted((t for t in tier if t[4] is None), key=lambda t: t[:3])
            ordered += [t[3] for t in near + rest]
        if soft_veg_diet(self.diet):  # known vegetarian fit before cuisine-based guesses
            ordered = ([r for r in ordered if diet_tier(r, self.diet) == 0]
                       + [r for r in ordered if diet_tier(r, self.diet) != 0])
        if slot is not None:  # venues whose own text is for another meal go last
            ordered = ([r for r in ordered if not wrong_meal(r.get("best_for"), slot.meal)]
                       + [r for r in ordered if wrong_meal(r.get("best_for"), slot.meal)])
        return ordered

    def _collect(self, n, day, city, slot, a_name, a_xy, where, need_indian, count):
        shard, candidates = self._shard(a_name, city)
        sources = [(shard, candidates)]
        if norm_name(shard) != norm_name(city):
            sources.append((city, self.library.restaurants(city)))
        places_today = self.places_by_day.setdefault(n, set())
        valid: list[ChosenRestaurant] = []
        shard_of: dict[int, str] = {}
        budget = [0]
        seen_ids: dict[str, str] = {}
        tried: set[str] = set()
        for shard, candidates in sources:
            if len(valid) >= count:
                break
            candidates = [r for r in candidates if norm_name(r.get("name") or "") not in tried]
            tried |= {norm_name(r["name"]) for r in candidates if isinstance(r.get("name"), str)}
            before = len(valid)
            self._fill(n, day, shard, candidates, a_name, a_xy, slot, where, need_indian, count, valid,
                       places_today, budget, seen_ids)
            for c in valid[before:]:
                shard_of[id(c)] = shard
        return valid, shard_of

    def _fresh(self, c: ChosenRestaurant, shard_of: dict) -> bool:
        return self.uses_by_name[(norm_name(shard_of[id(c)]), norm_name(c.lib["name"]))] == 0

    def _anchor(self, n: int, day: date, city: str, slot: MealSlot, anchor: Anchor, where: str,
                need_indian: bool) -> list[ChosenRestaurant]:
        a_name, a_xy, count = anchor
        places_today = self.places_by_day.setdefault(n, set())
        mark = len(self.exclusions)
        valid, shard_of = self._collect(n, day, city, slot, a_name, a_xy, where, need_indian, count)
        fresh = [c for c in valid if self._fresh(c, shard_of)]
        if len(fresh) < count and slot.meal == "dinner" and not slot.max_min:
            # too few new restaurants within the dinner cap: allow five more minutes in the car before repeating
            wider = slot.model_copy(update={"max_min": self.settings.dinner_max_min + _DINNER_RELAX_MIN})
            mark2 = len(self.exclusions)
            v2, s2 = self._collect(n, day, city, wider, a_name, a_xy, where, need_indian, count)
            f2 = [c for c in v2 if self._fresh(c, s2)]
            if len(f2) > len(fresh):
                valid, shard_of, fresh = v2, s2, f2
                del self.exclusions[mark:mark2]
            else:
                del self.exclusions[mark2:]
        repeats = [c for c in valid if c not in fresh]
        if len(fresh) >= count:
            valid = fresh
            chosen = valid if len(valid) <= count else self._rank(
                valid, count, need_indian and any(is_indian(c.lib) for c in valid), slot, a_name, day)
        else:
            need = count - len(fresh)
            extra = repeats if len(repeats) <= need else self._rank(
                repeats, need, need_indian and not any(is_indian(c.lib) for c in fresh)
                and any(is_indian(c.lib) for c in repeats), slot, a_name, day)
            chosen = fresh + extra
        if len(chosen) < count and soft_veg_diet(self.diet):
            # nothing else qualifies: best-ranked venues with unknown vegetarian options, flagged to verify (max 3)
            self._unknown_diet = True
            try:
                v3, s3 = self._collect(n, day, city, slot, a_name, a_xy, where, need_indian, count - len(chosen))
            finally:
                self._unknown_diet = False
            for c in v3[: count - len(chosen)]:
                shard_of[id(c)] = s3[id(c)]
                chosen.append(c)
        for c in chosen:
            key = (norm_name(shard_of[id(c)]), norm_name(c.lib["name"]))
            pid = _pid(c.place, key)
            places_today.add(pid)
            self.uses_by_place[pid] += 1
            self.names_by_day[n].add(key)
            self.uses_by_name[key] += 1
        return chosen

    def _fill(self, n, day, shard, candidates, a_name, a_xy, slot, where, need_indian, count, valid,
              places_today, budget, seen_ids) -> None:
        shard_key = norm_name(shard)
        pool = self._pool(n, candidates, shard_key, _words(a_name), where, shard, a_xy, slot)
        while pool:
            first = None
            if need_indian and not any(is_indian(c.lib) for c in valid):
                first = next((i for i, r in enumerate(pool) if is_indian(r)), None)
            if len(valid) >= count + _SPARE and first is None:
                break
            if first:
                pool.insert(0, pool.pop(first))
            batch, taken = [], 0
            while pool and taken < _BATCH:
                r = pool.pop(0)
                taken += 1
                place = self._resolve(r["name"], shard, a_xy, budget)
                if place is _CAPPED:
                    continue
                checked = self._check(r, place, shard_key, day, slot, where, places_today, seen_ids)
                if checked:
                    batch.append(checked)
            valid.extend(self._measure(batch, a_xy, day, slot, where))

    def _check(self, r: dict, place: Optional[Place], shard_key: str, day: date, slot: MealSlot, where: str,
               places_today: set[str], seen_ids: dict[str, str]):
        rname = r["name"]
        if place is None or not place.match_ok:
            self._exclude(rname, "no_match", where, "no confident Google match")
            return None
        if place.status != "OPERATIONAL":
            self._exclude(rname, "closed", where, f"Google status {place.status}")
            return None
        pid = _pid(place, (shard_key, norm_name(rname)))
        if pid in places_today:
            self._exclude(rname, "repeat_limit", where, "same place already used this day")
            return None
        if self.uses_by_place[pid] >= _MAX_USES:
            self._exclude(rname, "repeat_limit", where, f"same place already used {_MAX_USES} times")
            return None
        if pid in seen_ids:
            self._exclude(rname, "repeat_limit", where, f"same place as {seen_ids[pid]}")
            return None
        seen_ids[pid] = rname
        hours, verify = _effective_hours(r, place)
        open_ = is_open_for(hours, day, slot.start, _MEAL_MINUTES)
        if open_ is None:
            self._exclude(rname, "hours_unknown", where, "no opening hours from Google or the library")
            return None
        if not open_:
            self._exclude(rname, "not_open_at_meal", where,
                          f"not open {slot.start.strftime('%H:%M')} on {day.strftime('%a')} "
                          f"({format_for_day(hours, day)})")
            return None
        return r, place, hours, verify

    def _measure(self, batch: list, a_xy: tuple[float, float], day: date, slot: MealSlot,
                 where: str) -> list[ChosenRestaurant]:
        if not batch:
            return []
        dests = [(p.lat, p.lng) for _, p, _, _ in batch]

        def mins(mode: str) -> list[Optional[int]]:
            when = datetime.combine(day, slot.start) if mode == "TRANSIT" else None
            got = self.routes.durations([a_xy], dests, mode, when=when)
            return [got.get((0, j)) for j in range(len(dests))]

        walk = mins("WALK")
        drive = mins("DRIVE") if self.car else [None] * len(batch)
        transit = mins("TRANSIT") if self.transit else [None] * len(batch)
        out = []
        for (r, place, hours, verify), w, d, t in zip(batch, walk, drive, transit):
            travel = _travel(slot, w, d, t, self.settings)
            if travel is None and d is None and t is None and w is not None and w > self.settings.walk_max_min:
                km = _haversine_km(a_xy[0], a_xy[1], place.lat, place.lng)
                travel = _approx_car(slot, km, self.settings)
            if travel is None:
                detail = "distance unknown" if w is None and d is None and t is None else \
                    f"walk {w}, car {d}, public transport {t} min"
                self._exclude(r["name"], "too_far", where, detail)
                continue
            out.append(ChosenRestaurant(lib=r, place=place, travel_min=travel[1], travel_label=travel[0],
                                        hours_text=format_for_day(hours, day), hours_verify=verify,
                                        diet_verify=self._unknown_diet))
        return out

    def _rank(self, valid: list[ChosenRestaurant], count: int, require_indian: bool, slot: MealSlot,
              anchor: str, day: date) -> list[ChosenRestaurant]:
        by_name = {c.lib["name"]: c for c in valid}

        def validate(obj: _Rank) -> list[str]:
            problems = []
            unknown = [p for p in obj.picks if p not in by_name]
            if unknown:
                problems.append(f"names not in the candidate list: {unknown}")
            if len(obj.picks) != count or len(set(obj.picks)) != len(obj.picks):
                problems.append(f"return exactly {count} distinct names")
            if require_indian and not unknown and not any(is_indian(by_name[p].lib) for p in obj.picks):
                problems.append("include at least one Indian restaurant")
            return problems

        cands = [{
            "name": c.lib["name"],
            "cuisine": c.lib.get("cuisine_type"),
            "price": c.lib.get("price_range"),
            "highlights": c.lib.get("highlights"),
            "best_for": c.lib.get("best_for"),
            "travel": f"{c.travel_label} {c.travel_min} min",
            "indian": is_indian(c.lib),
        } for c in valid]
        prompt = (
            f"Choose exactly {count} restaurants for {slot.meal} on {day.strftime('%A')} near {anchor}.\n"
            f"Client diet: {self.diet.model_dump_json()}\n"
            + ("At least one pick must be an Indian restaurant (\"indian\": true).\n" if require_indian else "")
            + "Prefer variety of cuisine, fit with the client's likes, and shorter travel.\n"
            f"Candidates (JSON): {json.dumps(cands, ensure_ascii=False)}\n"
            'Return JSON: {"picks": ["<exact candidate name>", ...]}'
        )
        try:
            out = self.llm.run_json(step="rank", system=_RANK_SYSTEM, prompt=prompt, schema=_Rank, validate=validate)
        except LLMStepError:
            return _fallback(valid, count, require_indian)
        if validate(out):
            return _fallback(valid, count, require_indian)
        return [by_name[p] for p in out.picks]


_MEAL_WORDS = ("breakfast", "lunch", "dinner")


def meals_named(text) -> set[str]:
    return {m for m in _MEAL_WORDS if isinstance(text, str) and re.search(rf"\b{m}\b", text, re.I)}


def wrong_meal(best_for, meal: str) -> bool:
    """True when the venue's own text names meals and the slot's meal is not one of them."""
    said = meals_named(best_for)
    return bool(said) and meal not in said


def _pid(place: Place, name_key: tuple[str, str]) -> str:
    return place.place_id or f"name:{name_key[0]}:{name_key[1]}"


def _fallback(valid: list[ChosenRestaurant], count: int, require_indian: bool) -> list[ChosenRestaurant]:
    ordered = sorted(valid, key=lambda c: c.travel_min)
    if require_indian:
        first = next(c for c in ordered if is_indian(c.lib))
        ordered = [first] + [c for c in ordered if c is not first]
    return ordered[:count]


def plan_meals(
    days: list[tuple[int, date, str, list[MealSlot]]],
    library,
    places,
    routes,
    diet: Diet,
    modes: list[str],
    llm,
    settings: Settings,
    *,
    trip_scope: str,
    prior: list[tuple[str, MealPick]] = (),
) -> tuple[list[MealPick], list[Exclusion], PlanStats]:
    planner = _Planner(library, places, routes, diet, modes, llm, settings, trip_scope)
    for city, pick in prior:
        planner.seed(city, pick)
    picks = []
    for n, day, city, slots in sorted(days, key=lambda d: (d[1], d[0])):
        for slot in slots:
            if not slot.included and (not slot.in_package or slot.anchors):
                picks.append(planner.slot(n, day, city, slot))
    return picks, planner.exclusions, planner.stats
