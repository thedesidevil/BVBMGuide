"""Plan checkpoint: after PLAN and before WRITE, list the gaps the plan could not fill (restaurants) and apply the
Google Maps links the team pastes for them. Items are optional: unanswered ones keep their markers."""
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Optional

from src.aigv2.google.maplink import default_fetch
from src.aigv2.google.places import _haversine_km
from src.aigv2.hours import format_for_day
from src.aigv2.library import norm_name
from src.aigv2.models import Answers, Question
from src.aigv2.planning.meals import ChosenRestaurant
from src.aigv2.planning.travel import APPROX_LABEL
from src.aigv2.place_links import _resolve, validate_place_link

GAP_PREFIX = "meal_gap:"
REVIEW_FILE = "plan_review.json"
SKIP = "Skip"
_URL = re.compile(r"https?://\S+", re.I)
_WALK_M_PER_MIN = 80
_SUGGEST = 3


@dataclass
class Gap:
    id: str
    pick_idx: int
    day_index: int
    meal: str
    texts: list[str]  # the ADD_RESTAURANT marker texts of this slot, in order (one per missing restaurant)
    text: str
    suggestions: list[str]


def _near(marker_text: str) -> str:
    return marker_text.split(", near ", 1)[-1]


def meal_gaps(state) -> list[Gap]:
    """One gap per meal slot that still carries ADD RESTAURANT markers."""
    counts = Counter((p.day_index, p.slot.meal) for p in state.picks)
    out: list[Gap] = []
    for i, p in enumerate(state.picks):
        texts = [m.text for m in p.markers if m.kind == "ADD_RESTAURANT"]
        if not texts:
            continue
        gid = f"{GAP_PREFIX}{p.day_index}:{p.slot.meal}"
        if counts[(p.day_index, p.slot.meal)] > 1:
            gid += f":{p.slot.start.strftime('%H:%M')}"
        found = len(p.restaurants)
        wanted = found + len(texts)
        near = ", ".join(dict.fromkeys(_near(t) for t in texts))
        chosen = {norm_name(c.lib.get("name", c.place.name)) for c in p.restaurants}
        sugg: list[str] = []
        for e in state.exclusions:
            if e.reason == "no_match" and any(e.detail.startswith(t + ":") for t in set(texts)):
                if norm_name(e.name) not in chosen and e.name not in sugg:
                    sugg.append(e.name)
        sugg = sugg[:_SUGGEST]
        text = (f"{p.slot.meal.capitalize()} near {near}: only {found} of {wanted} restaurants found. "
                "Add one by pasting a Google Maps link (open the restaurant in Google Maps > Share > Copy link of ONE "
                f"place), or answer {SKIP}.")
        if sugg:
            text += f" Library suggests: {', '.join(sugg)} - paste a link for one of them."
        out.append(Gap(gid, i, p.day_index, p.slot.meal, texts, text, sugg))
    return out


def plan_items(state) -> list[Question]:
    from src.aigv2.question_days import day_label
    day_date = {d.index: d.date for d in state.days}
    return [Question(id=g.id, kind="plan_gap", options=[SKIP], day=day_date.get(g.day_index),
                     text=day_label(state.trip, [day_date[g.day_index]] if g.day_index in day_date else []) + g.text)
            for g in meal_gaps(state)]


def _answers_of(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw or raw.casefold() == "skip":
        return []
    urls = _URL.findall(raw)
    return urls if urls else [raw]


def _travel(pick, place) -> tuple[str, int]:
    """Straight-line estimate from the slot's first anchor (no Routes call at the checkpoint)."""
    if pick.slot.anchors and pick.slot.anchors[0][1]:
        ax, ay = pick.slot.anchors[0][1]
        m = _haversine_km(ax, ay, place.lat, place.lng) * 1000
        if m / _WALK_M_PER_MIN <= 10:
            return "Walk", max(1, math.ceil(m / _WALK_M_PER_MIN))
        return APPROX_LABEL, math.ceil(m / 1000 * 3.0 + 5)
    return APPROX_LABEL, 15


def _insert_at(pick, marker_text: str) -> int:
    """Index in pick.restaurants where the new venue belongs: at the end of the anchor whose marker it replaces."""
    anchors = pick.slot.anchors
    if pick.slot.unanchored or not anchors:
        return len(pick.restaurants)
    total = 0
    markers = [m.text for m in pick.markers if m.kind == "ADD_RESTAURANT"]
    for i, (name, _, count) in enumerate(anchors):
        mine = markers.count(f"{pick.slot.meal.capitalize()}, Day {pick.day_index}, near {name}")
        take = len(pick.restaurants) - total if i == len(anchors) - 1 else max(count - mine, 0)
        total += take
        if marker_text.endswith(f"near {name}"):
            return total
    return len(pick.restaurants)


def apply_plan_answers(state, answers: Answers, client, fetch: Callable[[str], str] = default_fetch,
                       done: Optional[dict] = None) -> dict:
    """Add the pasted places to the plan (state.picks is modified in place). Returns
    {'applied': [...], 'failed': [...], 'done': {item id: answer}}; a bad link never raises."""
    done = dict(done or {})
    report = {"applied": [], "failed": [], "done": done}
    overrides = getattr(client, "overrides", None)
    cities = {d.index: d.city for d in state.days}
    dates = {d.index: d.date for d in state.days}
    for gap in meal_gaps(state):
        raw = (answers.get(gap.id) or "").strip()
        if not _answers_of(raw) or done.get(gap.id) == raw:
            continue
        pick = state.picks[gap.pick_idx]
        city = cities.get(gap.day_index, "")
        q = Question(id=gap.id, kind="plan_gap", text="", options=[SKIP])
        count_ok = 0
        for ans in _answers_of(raw):
            if not pick_has_gap(pick):
                report["failed"].append(f"Day {gap.day_index} {gap.meal}: slot is already full; {ans} not added")
                continue
            problem = validate_place_link(ans, q)
            if problem:
                report["failed"].append(f"Day {gap.day_index} {gap.meal}: {ans}: {problem}")
                continue
            try:
                place, how = _resolve(ans, ans, city, None, client, fetch)
            except Exception as e:  # never abort the build for a bad answer
                report["failed"].append(f"Day {gap.day_index} {gap.meal}: link could not be used: {e}")
                continue
            names = {norm_name(c.lib.get("name", c.place.name)) for p in state.picks if p.day_index == gap.day_index
                     for c in p.restaurants}
            if norm_name(place.name) in names:
                report["failed"].append(f"Day {gap.day_index} {gap.meal}: {place.name} is already in this day")
                continue
            label, minutes = _travel(pick, place)
            chosen = ChosenRestaurant(lib={"name": place.name, "source": "user_link"}, place=place,
                                      travel_min=minutes, travel_label=label,
                                      hours_text=format_for_day(place.hours, dates[gap.day_index]) if place.hours else "",
                                      hours_verify=False)
            marker = next(m for m in pick.markers if m.kind == "ADD_RESTAURANT")
            pick.restaurants.insert(_insert_at(pick, marker.text), chosen)
            pick.markers.remove(marker)
            if overrides is not None:
                overrides.put(place.name, city, place.name, place.lat, place.lng, place.maps_url,
                              cid=how.get("cid"), place_id=place.place_id, address=place.address)
            report["applied"].append(f"Day {gap.day_index} {gap.meal}: {place.name} {place.maps_url}")
            count_ok += 1
        done[gap.id] = raw
    return report


def pick_has_gap(pick) -> bool:
    return any(m.kind == "ADD_RESTAURANT" for m in pick.markers)
