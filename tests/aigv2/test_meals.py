import itertools
import json
import re
from datetime import date, datetime, time
from types import SimpleNamespace

from src.aigv2.config import Settings
from src.aigv2.llm import StepLLM
from src.aigv2.library import Library
from src.aigv2.models import Diet, Place, WeeklyHours
from src.aigv2.planning.meals import plan_meals
from src.aigv2.planning.slots import MealSlot

TUE = date(2026, 11, 3)
S = Settings(models={"rank": "gpt-6-luna"})
GALATA = ("Galata Tower", (41.0, 29.0), 3)


def rest(name, cuisine=("Turkish",), veg=True, **kw):
    return {"name": name, "cuisine_type": list(cuisine), "vegetarian_friendly": veg, **kw}


def make_lib(tmp_path, shards):
    for city, rs in shards.items():
        (tmp_path / f"{city}.json").write_text(json.dumps({"restaurants": rs}), encoding="utf-8")
    return Library(tmp_path)


def hours(open_t=time(11), close_t=time(23)):
    return WeeklyHours(periods={d: [(open_t, close_t)] for d in range(7)}, source="google")


def place(name, idx, status="OPERATIONAL", hrs="default", match_ok=True):
    return Place(query=name, place_id=f"id{idx}", name=name, address="", lat=float(idx), lng=0.0, status=status,
                 hours=hours() if hrs == "default" else hrs, maps_url="u", fetched_at=datetime(2026, 1, 1),
                 match_ok=match_ok)


class FakePlaces:
    def __init__(self, places):
        self.places = places
        self.calls = []

    def find(self, name, city, near=None, fresh=False):
        self.calls.append((name, city, near))
        return self.places.get(name)


class FakeRoutes:
    def __init__(self, places, minutes):
        self.by_coord = {(p.lat, p.lng): n for n, p in places.items() if p}
        self.minutes = minutes
        self.by_origin = {}
        self.calls = []

    def durations(self, origins, destinations, mode, when=None):
        self.calls.append((tuple(origins), tuple(destinations), mode))
        table = self.by_origin.get(origins[0], {})
        out = {}
        for j, d in enumerate(destinations):
            n = self.by_coord[d]
            out[(0, j)] = (table.get(n) or self.minutes.get(n, {})).get(mode)
        return out


class FirstN:
    def __init__(self):
        self.prompts = []

    def run_json(self, step, system, prompt, schema, validate=None, **kw):
        self.prompts.append(prompt)
        n = int(re.search(r"Choose exactly (\d+)", prompt).group(1))
        cands = json.loads(re.search(r"Candidates \(JSON\): (.*)\n", prompt).group(1))
        for combo in itertools.combinations([c["name"] for c in cands], n):
            obj = schema(picks=list(combo))
            if not validate(obj):
                return obj
        raise AssertionError("no valid combination")


class FakeLLM:
    def __init__(self, picks):
        self.picks = picks
        self.calls = []

    def run_json(self, step, system, prompt, schema, validate=None, **kw):
        self.calls.append((step, system, prompt))
        obj = schema(picks=self.picks)
        assert not (validate(obj) if validate else [])
        return obj


def world(tmp_path, restaurants, city="Istanbul", minutes=None, overrides=None, extra=None):
    lib = make_lib(tmp_path, {city: restaurants, **(extra or {})})
    names = [r["name"] for r in restaurants] + [r["name"] for rs in (extra or {}).values() for r in rs]
    pl = {n: place(n, i + 1) for i, n in enumerate(names)}
    pl.update(overrides or {})
    mins = {n: {"WALK": 5, "DRIVE": 4} for n in names}
    mins.update(minutes or {})
    return lib, FakePlaces(pl), FakeRoutes(pl, mins)


def run_plan(days, lib, places, routes, diet=None, modes=("taxi",), llm=None, scope="international"):
    return plan_meals(days, lib, places, routes, diet or Diet(), list(modes), llm or FakeLLM([]), S, trip_scope=scope)


def plan(*a, **kw):
    return run_plan(*a, **kw)[:2]


def lunch(anchors=(GALATA,), start=time(12, 30), **kw):
    return MealSlot(meal="lunch", start=start, anchors=list(anchors), **kw)


def dinner(anchors=(GALATA,), **kw):
    return MealSlot(meal="dinner", start=time(19, 30), anchors=list(anchors), **kw)


def names(pick):
    return [c.lib["name"] for c in pick.restaurants]


def reasons(excl):
    return {(e.name, e.reason) for e in excl}


def test_three_valid_no_markers(tmp_path):
    lib, pl, rt = world(tmp_path, [rest("A"), rest("B"), rest("C")])
    llm = FakeLLM([])
    picks, excl = plan([(3, TUE, "Istanbul", [lunch()])], lib, pl, rt, llm=llm)
    assert len(picks) == 1 and picks[0].day_index == 3
    assert names(picks[0]) == ["A", "B", "C"]
    assert picks[0].markers == [] and excl == [] and llm.calls == []
    c = picks[0].restaurants[0]
    assert c.travel_label == "Walk" and c.travel_min == 5
    assert c.hours_text == "11:00 AM – 11:00 PM" and c.hours_verify is False
    assert c.place.name == "A"


def test_two_valid_one_marker(tmp_path):
    lib, pl, rt = world(tmp_path, [rest("A"), rest("B"), rest("Grill", veg=False)])
    picks, excl = plan([(3, TUE, "Istanbul", [lunch()])], lib, pl, rt, diet=Diet(restrictions=["vegetarian"]))
    assert names(picks[0]) == ["A", "B"]
    assert [m.render() for m in picks[0].markers] == ["⚠ ADD RESTAURANT – Lunch, Day 3, near Galata Tower"]
    assert reasons(excl) == {("Grill", "diet")}


def test_closed_restaurant_excluded(tmp_path):
    lib, pl, rt = world(tmp_path, [rest("A"), rest("B"), rest("C")],
                        overrides={"C": place("C", 3, status="CLOSED_PERMANENTLY")})
    picks, excl = plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt)
    assert names(picks[0]) == ["A", "B"]
    assert reasons(excl) == {("C", "closed")}


def test_opens_at_4pm_not_lunch(tmp_path):
    lib, pl, rt = world(tmp_path, [rest("A"), rest("B"), rest("Late")],
                        overrides={"Late": place("Late", 3, hrs=hours(time(16), time(23)))})
    picks, excl = plan([(1, TUE, "Istanbul", [lunch(), dinner()])], lib, pl, rt)
    assert "Late" not in names(picks[0])
    assert names(picks[1]) == ["Late"]
    assert {(n, r) for n, r in reasons(excl) if n == "Late"} == {("Late", "not_open_at_meal")}


def test_no_match_and_unknown_hours(tmp_path):
    lib, pl, rt = world(tmp_path, [rest("A"), rest("Ghost"), rest("Wrong"), rest("NoHrs")],
                        overrides={"Ghost": None, "Wrong": place("Wrong", 3, match_ok=False),
                                   "NoHrs": place("NoHrs", 4, hrs=None)})
    picks, excl = plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt)
    assert names(picks[0]) == ["A"]
    assert reasons(excl) == {("Ghost", "no_match"), ("Wrong", "no_match"), ("NoHrs", "hours_unknown")}
    assert len(picks[0].markers) == 2


def test_library_hours_fallback_marks_verify(tmp_path):
    lib, pl, rt = world(tmp_path, [rest("Lib", hours="11:30 AM – 3:30 PM | 6:30 PM – 11:00 PM")],
                        overrides={"Lib": place("Lib", 1, hrs=None)})
    picks, excl = plan([(1, TUE, "Istanbul", [lunch(), dinner()])], lib, pl, rt)
    c = picks[0].restaurants[0]
    assert c.hours_verify is True and c.hours_text == "11:30 AM – 3:30 PM, 6:30 PM – 11:00 PM"
    assert names(picks[1]) == []
    assert ("Lib", "repeat_limit") in reasons(excl)


def test_distance_rules(tmp_path):
    rs = [rest("Walk8"), rest("Car12"), rest("Car18"), rest("Far")]
    mins = {"Walk8": {"WALK": 8, "DRIVE": 3}, "Car12": {"WALK": 30, "DRIVE": 12},
            "Car18": {"WALK": 40, "DRIVE": 18}, "Far": {"WALK": 60, "DRIVE": 25}}
    lib, pl, rt = world(tmp_path, rs, minutes=mins)
    picks, excl = plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt)
    assert names(picks[0]) == ["Walk8", "Car12"]
    assert [(c.travel_label, c.travel_min) for c in picks[0].restaurants] == [("Walk", 8), ("By car", 12)]
    assert reasons(excl) == {("Car18", "too_far"), ("Far", "too_far")}
    picks, excl = plan([(2, TUE, "Istanbul", [dinner()])], lib, pl, rt)
    assert names(picks[0]) == ["Walk8", "Car12", "Car18"]
    assert reasons(excl) == {("Far", "too_far")}


def test_walk_only_without_car_modes(tmp_path):
    mins = {"Near": {"WALK": 9, "DRIVE": 2}, "Ride": {"WALK": 14, "DRIVE": 3, "TRANSIT": 12}}
    lib, pl, rt = world(tmp_path, [rest("Near"), rest("Ride")], minutes=mins)
    picks, excl = plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt, modes=())
    assert names(picks[0]) == ["Near"] and reasons(excl) == {("Ride", "too_far")}
    assert {c[2] for c in rt.calls} == {"WALK"}
    rt.calls.clear()
    picks, _ = plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt, modes=("public_transport",))
    assert [(c.lib["name"], c.travel_label) for c in picks[0].restaurants] == [("Near", "Walk"), ("Ride", "By public transport")]
    assert {c[2] for c in rt.calls} == {"WALK", "TRANSIT"}


def test_routes_batched_per_anchor_and_mode(tmp_path):
    lib, pl, rt = world(tmp_path, [rest("A"), rest("B"), rest("C"), rest("D")])
    plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt, llm=FakeLLM(["A", "B", "C"]))
    assert len(rt.calls) == 2
    assert all(len(c[1]) == 4 and c[0] == ((41.0, 29.0),) for c in rt.calls)
    assert all(c[2] == (41.0, 29.0) and c[1] == "Istanbul" for c in pl.calls)


def test_repeat_limits(tmp_path):
    lib, pl, rt = world(tmp_path, [rest("A"), rest("B"), rest("C")])
    days = [(1, TUE, "Istanbul", [lunch(), dinner()]),
            (2, date(2026, 11, 4), "Istanbul", [lunch()]),
            (3, date(2026, 11, 5), "Istanbul", [lunch()])]
    picks, excl = plan(days, lib, pl, rt)
    assert names(picks[0]) == ["A", "B", "C"]
    assert names(picks[1]) == [] and len(picks[1].markers) == 3
    assert names(picks[2]) == ["A", "B", "C"]
    assert names(picks[3]) == [] and len(picks[3].markers) == 3
    assert {e.reason for e in excl} == {"repeat_limit"}
    assert len(excl) == 6


def test_rank_cannot_add_names(tmp_path):
    lib, pl, rt = world(tmp_path, [rest("A"), rest("B"), rest("C"), rest("D")])
    calls = []
    replies = {"gpt-6-luna": '{"picks": ["A", "B", "Zed"]}', "gpt-6.1-sol": '{"picks": ["D", "B", "A"]}'}

    def factory(model):
        def create(**kw):
            calls.append((model, kw))
            msg = SimpleNamespace(content=replies[model])
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                                   usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))
        return SimpleNamespace(_client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))

    llm = StepLLM(S, client_factory=factory)
    picks, _ = plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt, llm=llm)
    assert [m for m, _ in calls] == ["gpt-6-luna", "gpt-6.1-sol"]
    assert "json" in calls[0][1]["messages"][-1]["content"].lower()
    assert names(picks[0]) == ["D", "B", "A"]

    replies["gpt-6.1-sol"] = '{"picks": ["Zed", "Yak", "A"]}'
    calls.clear()
    picks, _ = plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt, llm=llm)
    assert len(calls) == 2
    assert len(names(picks[0])) == 3 and set(names(picks[0])) <= {"A", "B", "C", "D"}


def test_no_library_city_all_markers(tmp_path):
    lib, pl, rt = world(tmp_path, [rest("A")], city="Elsewhere")
    picks, excl = plan([(2, TUE, "Nowhere", [lunch(), dinner()])], lib, pl, rt)
    assert [len(p.markers) for p in picks] == [3, 3]
    assert picks[1].markers[0].render() == "⚠ ADD RESTAURANT – Dinner, Day 2, near Galata Tower"
    assert pl.calls == [] and rt.calls == [] and excl == []


def test_included_skipped_unanchored_all_markers(tmp_path):
    lib, pl, rt = world(tmp_path, [rest("A")])
    slots = [MealSlot(meal="breakfast", start=time(7, 30), included=True),
             MealSlot(meal="lunch", start=time(12, 30), unanchored=True)]
    picks, _ = plan([(4, TUE, "Istanbul", slots)], lib, pl, rt)
    assert len(picks) == 1 and picks[0].slot.meal == "lunch"
    assert [m.render() for m in picks[0].markers] == ["⚠ ADD RESTAURANT – Lunch, Day 4, near Istanbul"] * 3


def test_multiple_anchors_split_counts(tmp_path):
    hotel = ("Hotel H", (40.0, 28.0), 2)
    show = ("Fado show", (41.0, 29.0), 1)
    lib, pl, rt = world(tmp_path, [rest("A"), rest("B"), rest("C")])
    picks, _ = plan([(1, TUE, "Istanbul", [dinner(anchors=(show, hotel))])], lib, pl, rt,
                    llm=FakeLLM(["A"]))
    assert names(picks[0]) == ["A", "B", "C"] and picks[0].markers == []


def test_day_trip_lunch_uses_locality(tmp_path):
    titlis = ("Engelberg", (46.8, 8.4), 3)
    lib, pl, rt = world(tmp_path, [rest("Lucerne One"), rest("Lucerne Two"), rest("Lucerne Three")],
                        city="Lucerne", extra={"Engelberg": [rest("Alpine A"), rest("Alpine B")]})
    days = [(2, TUE, "Lucerne", [lunch(anchors=(titlis,))])]
    for i in range(3):
        days.append((3 + i, date(2026, 11, 4 + i), "Lucerne", [lunch(anchors=(titlis,))]))
    picks, excl = plan(days, lib, pl, rt)
    assert names(picks[0]) == ["Alpine A", "Alpine B"]
    assert picks[0].markers[0].render() == "⚠ ADD RESTAURANT – Lunch, Day 2, near Engelberg"
    assert {c[1] for c in pl.calls} == {"Engelberg"}
    assert names(picks[1]) == ["Alpine A", "Alpine B"] and names(picks[2]) == []
    assert ("Alpine A", "repeat_limit") in reasons(excl)


def test_indian_option_guaranteed_when_available(tmp_path):
    rs = [rest("A"), rest("B"), rest("C"), rest("Tandoor", cuisine=("North Indian",))]
    lib, pl, rt = world(tmp_path, rs, minutes={"Tandoor": {"WALK": 9, "DRIVE": 9}})

    class Picky:
        def __init__(self):
            self.seen = []

        def run_json(self, step, system, prompt, schema, validate=None, **kw):
            first = schema(picks=["A", "B", "C"])
            self.seen.append(validate(first))
            return schema(picks=["A", "Tandoor", "B"])

    llm = Picky()
    picks, _ = plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt, llm=llm)
    assert "Tandoor" in names(picks[0])
    assert llm.seen[0]

    class Broken:
        def run_json(self, *a, **kw):
            from src.aigv2.llm import LLMStepError
            raise LLMStepError("rank", ["bad"])

    picks, _ = plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt, llm=Broken())
    assert "Tandoor" in names(picks[0]) and len(names(picks[0])) == 3

    domestic = FakeLLM(["A", "B", "C"])
    picks, _ = plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt, llm=domestic, scope="domestic")
    assert names(picks[0]) == ["A", "B", "C"]


def test_lazy_resolution_stops_after_enough_valid(tmp_path):
    lib, pl, rt = world(tmp_path, [rest(f"R{i}") for i in range(40)])
    picks, _, stats = run_plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt, llm=FirstN())
    assert len(pl.calls) <= 6 and stats.lookups_by_city == {"Istanbul": len(pl.calls)}
    assert stats.capped_cities == [] and len(names(picks[0])) == 3
    assert all(len(c[1]) <= 6 for c in rt.calls)


def test_lookup_cap_per_city(tmp_path):
    rs = [rest(f"R{i}") for i in range(30)]
    lib, pl, rt = world(tmp_path, rs, overrides={f"R{i}": place(f"R{i}", i + 1, status="CLOSED_PERMANENTLY") for i in range(30)})
    picks, _, stats = run_plan([(1, TUE, "Istanbul", [lunch(), dinner()])], lib, pl, rt)
    assert len(pl.calls) == 25 and stats.lookups_by_city == {"Istanbul": 25}
    assert stats.capped_cities == ["Istanbul"]
    assert [len(p.markers) for p in picks] == [3, 3]


def test_location_overlap_resolved_first(tmp_path):
    rs = [rest(f"R{i}") for i in range(10)] + [rest("Tower Grill", area="Galata Tower, Beyoglu")]
    lib, pl, rt = world(tmp_path, rs)
    run_plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt, llm=FirstN())
    assert pl.calls[0][0] == "Tower Grill"


def test_repeats_keyed_by_place_id(tmp_path):
    rs = [rest("Hamdi"), rest("Hamdi Restaurant"), rest("B"), rest("C"), rest("D")]
    same = place("Hamdi", 1)
    lib, pl, rt = world(tmp_path, rs, overrides={"Hamdi": same, "Hamdi Restaurant": same})
    days = [(1, TUE, "Istanbul", [lunch(), dinner()]),
            (2, date(2026, 11, 4), "Istanbul", [lunch(), dinner()]),
            (3, date(2026, 11, 5), "Istanbul", [lunch(), dinner()])]
    picks, excl = plan(days, lib, pl, rt, llm=FirstN())
    by_day = {}
    for p in picks:
        by_day.setdefault(p.day_index, []).extend(c.place.place_id for c in p.restaurants)
    assert all(ids.count("id1") <= 1 for ids in by_day.values())
    assert sum(ids.count("id1") for ids in by_day.values()) <= 2
    assert sum(ids.count("id1") for ids in by_day.values()) >= 1


def test_missing_route_is_distance_unknown(tmp_path):
    lib, pl, rt = world(tmp_path, [rest("A"), rest("NoRoute")], minutes={"NoRoute": {}})
    _, excl = plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt)
    assert [(e.name, e.reason) for e in excl] == [("NoRoute", "too_far")]
    assert excl[0].detail.endswith("distance unknown")


def test_no_eligible_indian_no_requirement_line(tmp_path):
    lib, pl, rt = world(tmp_path, [rest("A"), rest("B"), rest("C"), rest("D")])
    llm = FirstN()
    plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt, llm=llm)
    assert "Indian" not in llm.prompts[0]


def test_indian_guarantee_across_anchors(tmp_path):
    show = ("Fado show", (41.0, 29.0), 1)
    hotel = ("Hotel H", (40.0, 28.0), 2)
    rs = [rest("A"), rest("B"), rest("C"), rest("D"), rest("Tandoor", cuisine=("Punjabi",))]
    lib, pl, rt = world(tmp_path, rs)
    rt.by_origin[(41.0, 29.0)] = {"Tandoor": {"WALK": 50, "DRIVE": 40}}
    llm = FirstN()
    picks, _ = plan([(1, TUE, "Istanbul", [dinner(anchors=(show, hotel))])], lib, pl, rt, llm=llm)
    assert "Indian" not in llm.prompts[0] and "Indian restaurant" in llm.prompts[1]
    assert "Tandoor" in names(picks[0]) and len(names(picks[0])) == 3

    rt.by_origin.clear()
    llm = FirstN()
    picks, _ = plan([(1, TUE, "Istanbul", [dinner(anchors=(show, hotel))])], lib, pl, rt, llm=llm)
    assert names(picks[0])[0] == "Tandoor"
    assert all("Indian restaurant" not in p for p in llm.prompts[1:])


def test_indian_search_continues_past_spare(tmp_path):
    rs = [rest(f"N{i}") for i in range(5)] + [rest("Closed Curry", cuisine=("Indian",)), rest("Masala", cuisine=("Indian",))]
    lib, pl, rt = world(tmp_path, rs, overrides={"Closed Curry": place("Closed Curry", 6, status="CLOSED_PERMANENTLY")})
    picks, excl = plan([(1, TUE, "Istanbul", [lunch()])], lib, pl, rt, llm=FirstN())
    assert ("Closed Curry", "closed") in reasons(excl)
    assert "Masala" in names(picks[0])


def test_transit_lookup_carries_meal_time():
    from datetime import datetime as _dt
    seen = []

    class R:
        calls = {}

        def durations(self, origins, destinations, mode, when=None):
            seen.append((mode, when))
            return {(0, j): 5 for j in range(len(destinations))}

    from src.aigv2.planning.meals import _Planner
    planner = _Planner(None, None, R(), Diet(), ["public_transport"], None, Settings(models={}), "international")
    slot = MealSlot(meal="lunch", start=time(12, 30), anchors=[])
    p = place("X", 0)
    planner._measure([({"name": "X"}, p, p.hours, False)], (1.0, 2.0), date(2027, 3, 15), slot, "w")
    assert ("TRANSIT", _dt(2027, 3, 15, 12, 30)) in seen and ("WALK", None) in seen
