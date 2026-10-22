from datetime import date, datetime, time

from src.aigv2.config import Settings
from src.aigv2.models import DayPlan, HotelStay, PlannedItem, Place, Stop, TransportLeg
from src.aigv2.planning.slots import parse_time, schedule_day

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
    pl["B"] = pl["B"].model_copy(update={"match_ok": False})
    r = run(day([item("A"), item("B")]), pl=pl)
    assert meal(r, "lunch").anchors == [("Hotel H", (1.0, 2.0), 3)]
    assert any(m.text == "location of B unknown" for m in r.markers)
