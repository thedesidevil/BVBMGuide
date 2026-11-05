from datetime import date, datetime, time

from src.aigv2.config import Settings
from src.aigv2.models import DayPlan, HotelStay, PlannedItem, Place, Stop, TransportLeg
from src.aigv2.planning.slots import _slot_for, leave_by, parse_time, schedule_day

D = date(2026, 11, 3)
S = Settings(models={})


def place(name, lat=1.0, lng=2.0):
    return Place(query=name, place_id="p", name=name, address="", lat=lat, lng=lng, status="OPERATIONAL",
                 maps_url="u", fetched_at=datetime(2026, 1, 1), match_ok=True)


def stay(hotel="Hotel H", cin=date(2026, 11, 1), cout=date(2026, 11, 6), **kw):
    return HotelStay(city="X", hotel=hotel, check_in=cin, check_out=cout, source="voucher", **kw)


def item(name, **kw):
    return PlannedItem(name=name, kind=kw.pop("kind", "attraction"), city="X", **kw)


def day(items=(), rules=(), stops=(), title="Day", d=D):
    return DayPlan(date=d, title=title, city="X", items=list(items), meal_rules=list(rules), drive_stops=list(stops))


def places(*names):
    return {n: place(n, i + 1.0, i + 2.0) for i, n in enumerate(names)}


def run(dp, stays=None, arrival=None, departure=None, pl=None, **kw):
    return schedule_day(dp, stays or [stay()], arrival, departure, pl if pl is not None else places("Hotel H", "A", "B", "C", "Fado show", "Seine cruise"), S, **kw)


def meal(res, name):
    return next((m for m in res.meals if m.meal == name), None)


def leg(kind="flight", arrive=None, depart=None):
    return TransportLeg(kind=kind, from_place="a", to_place="b", arrive=arrive, depart=depart, source="t")


def test_untimed_items_fill_in_order():
    r = run(day([item("A"), item("B"), item("C")]))
    assert [(s.item.name, s.slot) for s in r.scheduled] == [("A", "morning"), ("B", "morning"), ("C", "afternoon")]
    assert r.scheduled[0].start == time(9, 0) and r.scheduled[1].start == time(10, 30)


def test_explicit_time_and_hint_win():
    r = run(day([item("A", time="15:00"), item("B", slot_hint="evening"), item("C", pickup_time="10:15 AM", time="14:00")]))
    got = {s.item.name: (s.slot, s.start) for s in r.scheduled}
    assert got["A"] == ("afternoon", time(15, 0))
    assert got["B"][0] == "evening"
    assert got["C"] == ("morning", time(10, 15))


def test_lunch_near_last_morning_attraction():
    r = run(day([item("A"), item("B"), item("C")]))
    assert meal(r, "lunch").anchors == [("B", (3.0, 4.0), 3)]


def test_lunch_uses_locality_when_set():
    pl = places("Hotel H", "Old Town")
    r = run(day([item("A", locality="Old Town")]), pl=pl | {"A": place("A")})
    assert meal(r, "lunch").anchors[0][0] == "Old Town"


def test_lunch_at_hotel_on_midday_checkin():
    s = stay(cin=D, cout=date(2026, 11, 6), check_in_time=time(12, 0))
    r = run(day([item("A")]), stays=[s])
    assert meal(r, "lunch").anchors == [("Hotel H", (1.0, 2.0), 3)]


def test_lunch_at_hotel_on_midday_arrival():
    s = stay(cin=D)
    r = run(day([item("A")]), stays=[s], arrival=leg(arrive=datetime(2026, 11, 3, 11, 0)))
    assert meal(r, "lunch").anchors[0][0] == "Hotel H"


def test_dinner_split_with_evening_attraction():
    r = run(day([item("A"), item("Fado show", slot_hint="evening")]))
    assert meal(r, "dinner").anchors == [("Fado show", (5.0, 6.0), 1), ("Hotel H", (1.0, 2.0), 2)]


def test_dinner_before_cruise_rule():
    r = run(day([item("Seine cruise", slot_hint="evening")], rules=["dinner before Seine cruise"]))
    assert meal(r, "dinner").anchors == [("Seine cruise", (6.0, 7.0), 3)]


def test_dinner_default_at_hotel():
    assert meal(run(day([item("A")])), "dinner").anchors == [("Hotel H", (1.0, 2.0), 3)]


def test_hotel_change_day_dinner_at_new_hotel():
    old = stay("Old", cout=D)
    new = stay("New", cin=D, check_in_time=time(14, 0))
    r = run(day([item("A")]), stays=[old, new], pl=places("Old", "New", "A"))
    assert meal(r, "dinner").anchors[0][0] == "New"


def test_breakfast_only_when_out():
    assert meal(run(day([item("A")])), "breakfast") is None
    r = run(day([item("A")], rules=["breakfast out at a cafe"]))
    assert meal(r, "breakfast").anchors == [("Hotel H", (1.0, 2.0), 3)]


def test_late_arrival_no_lunch():
    r = run(day([item("A")]), stays=[stay(cin=D)], arrival=leg(arrive=datetime(2026, 11, 3, 15, 30)))
    assert meal(r, "lunch") is None and meal(r, "dinner")


def test_arrival_before_cutoff_still_has_lunch_slot():
    r = run(day(), stays=[stay(cin=D)], arrival=leg(arrive=datetime(2026, 11, 3, 13, 30)))
    assert meal(r, "lunch")


def test_very_late_arrival_no_dinner():
    r = run(day(), stays=[stay(cin=D)], arrival=leg(arrive=datetime(2026, 11, 3, 21, 30)))
    assert meal(r, "dinner") is None


def test_early_arrival_no_meals():
    r = run(day([item("A")]), stays=[stay(cin=D)], arrival=leg(arrive=datetime(2026, 11, 3, 3, 0)))
    assert r.meals == [] and len(r.scheduled) == 1


def test_departure_suppresses_meals_and_packed_breakfast_tip():
    r = run(day(), departure=leg(depart=datetime(2026, 11, 3, 16, 0)))
    assert meal(r, "lunch") and meal(r, "dinner") is None
    r = run(day(), departure=leg(depart=datetime(2026, 11, 3, 16, 0)), domestic=True)
    assert meal(r, "dinner") is None
    r = run(day(), departure=leg(kind="train", depart=datetime(2026, 11, 3, 20, 0)))
    assert meal(r, "dinner") is None
    r = run(day(), departure=leg(depart=datetime(2026, 11, 3, 6, 0)))
    assert r.meals == [] and r.tips == ["Ask the hotel for a packed breakfast"]


def test_included_dinner_no_options():
    r = run(day([item("A")]), stays=[stay(meal_plan="half_board")])
    assert meal(r, "dinner").included and meal(r, "dinner").anchors == []
    assert meal(r, "breakfast").included
    assert not meal(r, "lunch").included
    r = run(day([item("Tour", includes_meal=["lunch"])]))
    assert meal(r, "lunch").included


def test_spain_dinner_window():
    r = run(day([item("A")]), country="Spain")
    assert meal(r, "dinner").start == time(20, 30) and meal(r, "lunch").start == time(13, 30)


def test_sea_day_no_meals_and_port_day_anchor():
    cr = stay("Ship", kind="cruise")
    assert run(day(title="Day at sea"), stays=[cr], pl=places("Ship")).meals == []
    r = run(day(), stays=[cr], pl=places("Ship", "X"))
    assert meal(r, "dinner").included and meal(r, "lunch").anchors[0][0] == "X"


def test_drive_day_lunch_at_waypoint():
    stops = [Stop(name="A", minutes_from_prev=60, suggested_stop_min=20, km_from_prev=50),
             Stop(name="B", minutes_from_prev=100, suggested_stop_min=30, km_from_prev=90),
             Stop(name="C", minutes_from_prev=120, suggested_stop_min=30, km_from_prev=90)]
    r = run(day([item("Drive", kind="transfer", time="09:00")], stops=stops))
    assert meal(r, "lunch").anchors[0][0] == "B"


def test_missing_place_moves_count_to_hotel():
    r = run(day([item("A"), item("Fado show", slot_hint="evening")]), pl=places("Hotel H", "A"))
    assert meal(r, "dinner").anchors == [("Hotel H", (1.0, 2.0), 3)]
    assert [m.text for m in r.markers] == ["location of Fado show unknown"]
    assert not meal(r, "dinner").unanchored


def test_all_places_missing_is_unanchored_not_included():
    r = run(day([item("A")]), pl={})
    m = meal(r, "dinner")
    assert m.anchors == [] and m.unanchored and not m.included
    assert not meal(r, "dinner").included


def test_parse_time():
    assert parse_time("9:00 pickup") == time(9, 0)
    assert parse_time("9:00 private tour") == time(9, 0)
    assert parse_time("9 pm") == time(21, 0)
    assert parse_time("9:30 a.m.") == time(9, 30)
    assert parse_time("2 hours") is None


def test_dinner_hotel_targets_ignore_evening_split():
    for rule in ("dinner at the hotel", "dinner near hotel", "dinner near my hotel", "Dinner near Hotel H"):
        r = run(day([item("Fado show", slot_hint="evening")], rules=[rule]))
        assert meal(r, "dinner").anchors == [("Hotel H", (1.0, 2.0), 3)], rule


def test_dinner_time_target_ignored():
    r = run(day([item("Fado show", slot_hint="evening")], rules=["dinner before 8pm"]))
    assert [a[0] for a in meal(r, "dinner").anchors] == ["Fado show", "Hotel H"]


def test_dinner_between_anchors_at_first():
    pl = places("Hotel H", "Eiffel Tower", "Seine cruise")
    r = run(day([item("Eiffel Tower"), item("Seine cruise", slot_hint="evening")],
                rules=["dinner between Eiffel Tower and Seine cruise"]), pl=pl)
    assert meal(r, "dinner").anchors == [("Eiffel Tower", (2.0, 3.0), 3)]


def test_no_breakfast_on_checkin_day_without_prior_stay():
    s = stay(cin=D, meal_plan="breakfast")
    r = run(day([item("A")], rules=["breakfast out"]), stays=[s])
    assert meal(r, "breakfast") is None


def test_return_to_hotel_only_before_lunch():
    r = run(day([item("A")], rules=["return to hotel before lunch"]))
    assert meal(r, "lunch").anchors[0][0] == "Hotel H"
    r = run(day([item("A")], rules=["lunch near A, then return to hotel"]))
    assert meal(r, "lunch").anchors[0][0] == "A"


def test_unmatched_place_is_not_an_anchor():
    pl = places("Hotel H", "A", "B")
    pl["A"] = pl["A"].model_copy(update={"match_ok": False})
    pl["B"] = pl["B"].model_copy(update={"match_ok": False})
    r = run(day([item("A"), item("B")]), pl=pl)
    assert meal(r, "lunch").anchors == [("Hotel H", (1.0, 2.0), 3)]
    assert any(m.text == "location of B unknown" for m in r.markers)


def test_late_night_arrival_next_day_no_meals_keeps_items():
    r = run(day([item("A")], d=date(2026, 11, 3)), stays=[stay(cin=D)], arrival=leg(arrive=datetime(2026, 11, 4, 0, 10)))
    assert r.meals == [] and len(r.scheduled) == 1


# ---------- change-over days and in-day boat legs ----------

def cstay(city, hotel, cin, cout):
    return HotelStay(city=city, hotel=hotel, check_in=cin, check_out=cout, source="voucher")


def cday(city, d, **kw):
    return DayPlan(date=d, title="Day", city=city, items=[], meal_rules=[], drive_stops=[], **kw)


CD = date(2026, 9, 28)
OLD = cstay("Ubud", "Old H", date(2026, 9, 24), CD)
NEW = cstay("Nusa Lembongan", "New H", CD, date(2026, 9, 30))


def test_stay_for_change_over_lunch_and_dinner_prefer_day_city():
    from src.aigv2.planning.slots import _stay_for
    st = [OLD, NEW]
    assert _stay_for(st, CD, "lunch", time(12, 30), "Nusa Lembongan") is NEW
    assert _stay_for(st, CD, "dinner", time(19, 30), "nusa-lembongan") is NEW
    assert _stay_for(st, CD, "lunch", time(12, 30), "Ubud") is OLD


def test_stay_for_breakfast_unchanged_and_fallback_without_city_match():
    from src.aigv2.planning.slots import _stay_for
    st = [OLD, NEW]
    assert _stay_for(st, CD, "breakfast", time(7, 30), "Nusa Lembongan") is OLD
    assert _stay_for(st, CD, "lunch", time(12, 30), "Elsewhere") is OLD
    assert _stay_for(st, CD, "lunch", time(12, 30)) is OLD


BD = date(2026, 9, 30)


def boat(h, m, arrive=None, d=BD):
    return TransportLeg(kind="boat", from_place="a", to_place="b", depart=datetime(d.year, d.month, d.day, h, m),
                        arrive=arrive, source="t")


def lunch_run(legs, **kw):
    dp = cday("X", BD)
    return schedule_day(dp, [stay(cin=date(2026, 9, 24), cout=date(2026, 10, 2))], None, None,
                        places("Hotel H"), S, legs=legs, **kw)


def test_boat_leg_shifts_lunch():
    r = lunch_run([boat(12, 0, arrive=datetime(2026, 9, 30, 12, 45))])
    assert meal(r, "lunch").start == time(13, 15)


def test_boat_leg_default_duration_drops_lunch_past_1330():
    assert meal(lunch_run([boat(12, 0)]), "lunch") is None


def test_boat_leg_ending_before_lunch_no_change():
    r = lunch_run([boat(8, 0)])
    assert meal(r, "lunch").start == time(12, 30)
    r = lunch_run([boat(8, 0, arrive=datetime(2026, 9, 30, 11, 0))])
    assert meal(r, "lunch").start == time(12, 30)


def test_boat_leg_other_day_ignored_and_arrival_departure_not_double_handled():
    assert meal(lunch_run([boat(12, 0, d=date(2026, 10, 1))]), "lunch").start == time(12, 30)
    dep = boat(12, 0)
    dp = cday("X", BD)
    r = schedule_day(dp, [stay(cin=date(2026, 9, 24), cout=date(2026, 10, 2))], None, dep,
                     places("Hotel H"), S, legs=[dep])
    r2 = schedule_day(dp, [stay(cin=date(2026, 9, 24), cout=date(2026, 10, 2))], None, dep, places("Hotel H"), S)
    assert r.meals == r2.meals


# ---- multi-city day titles ----

from src.aigv2.planning.slots import resolve_day_city, split_city


def test_split_city_separators():
    assert split_city("Ubud / Nusa Lembongan") == ["Ubud", "Nusa Lembongan"]
    assert split_city("Paris → Lyon") == ["Paris", "Lyon"]
    assert split_city("Paris -> Lyon") == ["Paris", "Lyon"]
    assert split_city("Rome to Florence") == ["Rome", "Florence"]
    assert split_city("Rome - Florence") == ["Rome", "Florence"]
    assert split_city("Rome, Florence & Pisa and Siena") == ["Rome", "Florence", "Pisa", "Siena"]
    assert split_city("") == []
    assert split_city("Sanur") == ["Sanur"]


def _stays():
    return [HotelStay(city="Ubud", hotel="A", check_in=date(2026, 9, 24), check_out=date(2026, 9, 28), source="voucher"),
            HotelStay(city="Nusa Lembongan", hotel="B", check_in=date(2026, 9, 28), check_out=date(2026, 9, 30),
                      source="voucher")]


def test_resolve_day_city_night_stay_and_fallbacks():
    assert resolve_day_city("Ubud / Nusa Lembongan", date(2026, 9, 28), _stays()) == "Nusa Lembongan"
    assert resolve_day_city("nusa lembongan / Ubud", date(2026, 9, 28), _stays()) == "nusa lembongan"
    assert resolve_day_city("Ubud / Somewhere", date(2026, 9, 27), _stays()) == "Ubud"
    assert resolve_day_city("Ubud / Elsewhere", date(2026, 12, 1), _stays()) == "Elsewhere"
    assert resolve_day_city("Sanur", date(2026, 9, 28), _stays()) == "Sanur"
    assert resolve_day_city("", date(2026, 9, 28), _stays()) == ""


# ---------- lunch anchor: nearest lunchtime, not last / vague ----------

def tour(*names, start="08:00"):
    return [item(n, time=start) for n in names]


def lunch_anchor(items, pl, ends=None):
    r = schedule_day(day(items), [stay()], None, None, pl, S, booking_ends=ends)
    return meal(r, "lunch").anchors[0][0]


def test_lunch_anchor_middle_of_three_same_time_stops():
    pl = places("Hotel H", "A", "B", "C")
    assert lunch_anchor(tour("A", "B", "C"), pl, {"A": time(16, 0)}) == "B"


def test_lunch_anchor_four_stops_nearest_lunchtime():
    pl = places("Hotel H", "A", "B", "C", "D")
    # 09:00-17:00: centres 10:00, 12:00, 14:00, 16:00 -> B is nearest 12:30
    assert lunch_anchor(tour("A", "B", "C", "D", start="09:00"), pl, {"A": time(17, 0)}) == "B"


def test_lunch_anchor_default_window_is_eight_hours():
    pl = places("Hotel H", "A", "B", "C")
    assert lunch_anchor(tour("A", "B", "C"), pl) == "B"


def test_lunch_anchor_skips_vague_name():
    pl = places("Hotel H", "Coffee Plantation", "Tirta Empul")
    assert lunch_anchor(tour("Tirta Empul", "Coffee Plantation"), pl) == "Tirta Empul"
    assert lunch_anchor(tour("Tirta Empul", "Local Market Visit"), pl | {"Local Market Visit": place("Local Market Visit")}) == "Tirta Empul"


def test_lunch_anchor_prefers_matched_place():
    pl = places("Hotel H", "A", "C")
    assert lunch_anchor(tour("A", "B", "C"), pl) in ("A", "C")


def test_lunch_anchor_all_vague_falls_back():
    pl = places("Hotel H", "Beach", "Temple", "Waterfall")
    assert lunch_anchor(tour("Beach", "Temple", "Waterfall"), pl) == "Temple"


def test_lunch_anchor_single_stop_and_distinct_times():
    pl = places("Hotel H", "A", "B")
    assert lunch_anchor([item("A")], pl) == "A"
    assert lunch_anchor([item("A", time="09:00"), item("B", time="12:00")], pl) == "B"


def test_tour_starting_after_lunch_start_lunches_at_hotel_first():
    pl = places("Hotel H", "A", "B")
    assert lunch_anchor(tour("A", "B", start="13:00"), pl) == "Hotel H"


# ---------- nothing before the boat lands ----------

def _boat_day(arrive=None):
    dp = cday("X", BD)
    dp.items = [item("Fast boat", kind="activity", time="12:00"), item("Shopping", kind="free_time"),
                item("Dinner out", kind="meal_out"), item("Transfer to hotel", kind="transfer")]
    st = [cstay("Y", "Old", date(2026, 9, 24), BD), cstay("X", "New", BD, date(2026, 10, 2))]
    return schedule_day(dp, st, None, None, places("New", "Old"), S, legs=[boat(12, 0, arrive=arrive)])


def test_nothing_before_boat_arrives_default_duration():
    r = _boat_day()
    got = [(s.item.name, s.start) for s in r.scheduled]
    assert got[0] == ("Fast boat", time(12, 0))
    assert [n for n, _ in got] == ["Fast boat", "Transfer to hotel", "Shopping", "Dinner out"]
    assert all(t >= time(13, 50) for n, t in got[1:])
    assert got[-1][1] >= time(17, 30)


def test_nothing_before_boat_arrives_known_arrival():
    r = _boat_day(arrive=datetime(2026, 9, 30, 12, 45))
    assert r.scheduled[1].item.name == "Transfer to hotel" and r.scheduled[1].start == time(12, 45)


def test_boat_floor_only_on_hotel_change_days():
    from src.aigv2.planning.slots import boat_floor
    b = boat(9, 0)
    assert boat_floor(BD, [b], [cstay("X", "New", BD, date(2026, 10, 2))]) == time(10, 50)
    assert boat_floor(BD, [b], [cstay("X", "Old", date(2026, 9, 24), date(2026, 10, 2))]) is None


def test_region_day_city_uses_the_town_the_group_sleeps_in():
    from datetime import date
    from src.aigv2.planning.slots import region_day_city
    stays = [HotelStay(city="Ubud", hotel="H", check_in=date(2027, 5, 1), check_out=date(2027, 5, 5), source="voucher"),
             HotelStay(city="Sanur", hotel="S", check_in=date(2027, 5, 5), check_out=date(2027, 5, 7), source="voucher")]
    size = {"Bali": 13, "Ubud": 86, "Sanur": 26}.get
    d = date(2027, 5, 2)
    assert region_day_city("Bali", d, stays, size) == "Ubud"
    assert region_day_city("Ubud", d, stays, size) == "Ubud"
    assert region_day_city("Pisa", d, stays, lambda c: {"Pisa": 30, "Ubud": 10}.get(c, 0)) == "Pisa"
    assert region_day_city("Bali", date(2027, 5, 9), stays, size) == "Bali"
    assert region_day_city("Bali", d, stays, lambda c: 0) == "Bali"


def _hours(start, end):
    from src.aigv2.models import WeeklyHours
    return WeeklyHours(periods={D.weekday(): [(start, end)]}, source="google")


def _with_hours(name, start, end):
    p = place(name, 5.0, 6.0)
    p.hours = _hours(start, end)
    return p


def test_optional_stop_that_opens_in_the_evening_moves_to_its_opening():
    pl = places("Hotel H", "Icon Mall")
    pl["Sindhu Market"] = _with_hours("Sindhu Market", time(17, 0), time(22, 0))
    r = run(day([item("Icon Mall", optional=True), item("Sindhu Market", optional=True, time=None)]), pl=pl)
    got = {s.item.name: (s.slot, s.start) for s in r.scheduled}
    assert got["Sindhu Market"] == (_slot_for(time(17, 0), S), time(17, 0))


def test_optional_stop_opening_after_nine_pm_keeps_its_slot():
    pl = places("Hotel H")
    pl["Night Bar"] = _with_hours("Night Bar", time(21, 30), time(23, 59))
    r = run(day([item("Night Bar", optional=True)]), pl=pl)
    assert r.scheduled[0].start == time(9, 0)


def test_required_stop_is_not_moved():
    pl = places("Hotel H")
    pl["Sindhu Market"] = _with_hours("Sindhu Market", time(17, 0), time(22, 0))
    r = run(day([item("Sindhu Market")]), pl=pl)
    assert r.scheduled[0].start == time(9, 0)


def test_leave_by_uses_buffer_and_road_time_rounded_down():
    dep = leg(depart=datetime(2026, 10, 1, 13, 15))
    assert leave_by(dep, False) == time(10, 15)
    assert leave_by(dep, False, 83) == time(8, 50)
    assert leave_by(dep, True, 40) == time(10, 35)
    assert leave_by(leg(kind="train", depart=datetime(2026, 10, 1, 9, 0)), False, 20) == time(8, 0)


def test_option_group_members_share_a_start_and_advance_the_clock_once():
    r = run(day([item("A", slot_hint="afternoon"),
                 item("B", optional=True, slot_hint="afternoon", option_group="choice-0"),
                 item("C", optional=True, slot_hint="afternoon", option_group="choice-0"),
                 item("Fado show", slot_hint="afternoon")]))
    got = {s.item.name: s.start for s in r.scheduled}
    assert got["B"] == got["C"] == time(15, 30)
    assert got["Fado show"] == time(17, 0)
    assert {s.item.name: s.option_group for s in r.scheduled}["B"] == "choice-0"


def test_ungrouped_optional_items_stay_sequential():
    r = run(day([item("B", optional=True, slot_hint="afternoon"), item("C", optional=True, slot_hint="afternoon")]))
    assert r.scheduled[0].start != r.scheduled[1].start


def test_grouped_late_opener_stays_with_its_group():
    pl = places("Hotel H", "Icon Mall")
    pl["Sindhu Market"] = _with_hours("Sindhu Market", time(17, 0), time(22, 0))
    r = run(day([item("Icon Mall", optional=True, slot_hint="afternoon", option_group="g"),
                 item("Sindhu Market", optional=True, slot_hint="afternoon", option_group="g")]), pl=pl)
    assert r.scheduled[0].start == r.scheduled[1].start


# ---------- a lone full-day package covers lunch ----------

def test_full_day_package_replaces_lunch_options():
    r = schedule_day(day([item("Marine Park", time="09:00")]), [stay()], None, None, places("Hotel H", "Marine Park"), S,
                     booking_ends={"Marine Park": time(16, 0)})
    m = meal(r, "lunch")
    assert m.in_package and not m.anchors and not m.included
    assert meal(r, "dinner").anchors


def test_short_or_shared_tour_keeps_lunch_options():
    pl = places("Hotel H", "A", "B")
    r = schedule_day(day([item("A", time="09:00")]), [stay()], None, None, pl, S, booking_ends={"A": time(13, 0)})
    assert not meal(r, "lunch").in_package
    r = schedule_day(day([item("A", time="09:00"), item("B", time="09:00")]), [stay()], None, None, pl, S,
                     booking_ends={"A": time(16, 0)})
    assert not meal(r, "lunch").in_package


def test_checkout_and_airport_drop_at_leave_by_time_not_default_9am():
    dep = leg(depart=datetime(2026, 11, 3, 13, 15))
    r = run(day([item("Hotel check-out and airport drop", kind="transfer")]), [stay(cout=D)], None, dep, domestic=False)
    s = r.scheduled[0]
    assert s.start == time(10, 15) and s.slot == "morning"


def test_breakfast_before_an_early_pickup():
    r = run(day([item("Transfer to harbour", kind="transfer", time="07:00")]), [stay(meal_plan="breakfast")])
    assert meal(r, "breakfast").start == time(6, 15)
