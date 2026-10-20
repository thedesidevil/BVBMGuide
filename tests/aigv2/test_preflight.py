from datetime import date, datetime, time

import pytest

from src.aigv2.intake.attachments import Attachment
from src.aigv2.intake.template import IntakeFields
from src.aigv2.models import (
    Booking, DayPlan, Diet, HotelStay, OpenChoice, Place, PlannedItem, TransportLeg, Traveller, TripPlan, WeeklyHours,
)
from src.aigv2.preflight import PreflightStop, apply_answers, run_checklist, unanswered, validate_answers


class FakeLib:
    def __init__(self, missing=()):
        self.missing = set(missing)

    def has_data(self, city):
        return city not in self.missing


def hotel(a, b, city="Paris", source="voucher", name="Hotel X", kind="hotel"):
    return HotelStay(city=city, hotel=name, check_in=a, check_out=b, source=source, kind=kind)


def make(**kw):
    base = dict(
        client_names=["A B"], travellers=Traveller(adults=2), diet=Diet(likes=["pasta"]),
        travel_modes=["taxi"], hotels=[hotel(date(2026, 10, 10), date(2026, 10, 12))],
        transport=[TransportLeg(kind="flight", from_place="Paris", to_place="Rome", source="t",
                                depart=datetime(2026, 10, 12, 10, 0))],
        bookings=[],
        days=[DayPlan(date=date(2026, 10, d), title="t", city="Paris") for d in (10, 11, 12)],
        open_choices=[], vague_days=[], commentary_removed=[], trip_scope="international",
    )
    base.update(kw)
    return TripPlan(**base)


def ask(plan, atts=(), lib=None, places=None, intake=None):
    return run_checklist(plan, intake or IntakeFields(), list(atts), lib or FakeLib(), places or {})


def ids(qs):
    return [q.id for q in qs]


def att(name, **kw):
    d = dict(name=name, kind="pdf", text="x" * 100, image_only=False, has_images=False)
    d.update(kw)
    return Attachment(**d)


def test_clean_plan_has_no_questions():
    assert ask(make()) == []


def test_late_departure_question():
    plan = make(
        hotels=[hotel(date(2026, 10, 10), date(2026, 10, 14))],
        days=[DayPlan(date=date(2026, 10, d), title="t", city="Paris") for d in (10, 11, 12, 13, 14)],
        transport=[TransportLeg(kind="flight", from_place="Paris", to_place="Rome", source="t",
                                depart=datetime(2026, 10, 15, 1, 0))],
    )
    qs = ask(plan)
    q = next(q for q in qs if q.id == "late_departure:2026-10-15")
    assert q.options == ["2026-10-14", "2026-10-15"]
    assert q.text == "Departure is at 01:00 on 15 Oct. Is checkout on 14 Oct or 15 Oct?"
    out = apply_answers(plan, qs, {q.id: "2026-10-15"})
    assert out.hotels[0].check_out == date(2026, 10, 15)
    assert plan.hotels[0].check_out == date(2026, 10, 14)


def test_hotel_gap():
    plan = make(hotels=[hotel(date(2026, 11, 1), date(2026, 11, 5)), hotel(date(2026, 11, 6), date(2026, 11, 8))],
                days=[DayPlan(date=date(2026, 11, d), title="t", city="Paris") for d in range(1, 9)])
    assert "hotel_gap:2026-11-05" in ids(ask(plan))


def test_cruise_covers_nights():
    plan = make(hotels=[hotel(date(2026, 11, 1), date(2026, 11, 3)),
                        hotel(date(2026, 11, 3), date(2026, 11, 6), kind="cruise", name="Ship"),
                        hotel(date(2026, 11, 6), date(2026, 11, 8))],
                days=[DayPlan(date=date(2026, 11, d), title="t", city="Paris") for d in range(1, 9)],
                transport=[TransportLeg(kind="flight", from_place="a", to_place="b", source="t",
                                        depart=datetime(2026, 11, 8, 12, 0))])
    assert not [i for i in ids(ask(plan)) if i.startswith("hotel_")]


def test_hotel_overlap():
    plan = make(hotels=[hotel(date(2026, 10, 10), date(2026, 10, 12)), hotel(date(2026, 10, 11), date(2026, 10, 12), name="Y")])
    assert "hotel_overlap:2026-10-11" in ids(ask(plan))


def test_voucher_notes_conflict_uses_voucher():
    plan = make(hotels=[hotel(date(2026, 10, 10), date(2026, 10, 12)),
                        hotel(date(2026, 10, 10), date(2026, 10, 12), source="notes", name="Other")])
    qs = ask(plan)
    assert ids(qs) == ["conflict:hotel:Paris"]
    out = apply_answers(plan, qs, {qs[0].id: "voucher"})
    assert [h.source for h in out.hotels] == ["voucher"]


def test_days_mismatch():
    plan = make(hotels=[hotel(date(2026, 10, 10), date(2026, 10, 14))],
                days=[DayPlan(date=date(2026, 10, 10 + i), title="t", city="Paris") for i in range(6)],
                transport=[TransportLeg(kind="flight", from_place="a", to_place="b", source="t",
                                        depart=datetime(2026, 10, 15, 12, 0))])
    assert "days_mismatch" in ids(ask(plan))


def test_open_choice_applied():
    day = DayPlan(date=date(2026, 10, 10), title="t", city="Paris", items=[
        PlannedItem(name="Top of the Rock", kind="attraction", city="Paris"),
        PlannedItem(name="Empire State Building", kind="attraction", city="Paris"),
        PlannedItem(name="Central Park", kind="attraction", city="Paris"),
    ])
    plan = make(days=[day, *make().days[1:]],
                open_choices=[OpenChoice(day=date(2026, 10, 10), text="views", options=["Top of the Rock", "Empire State Building"])])
    qs = ask(plan)
    assert "open_choice:0" in ids(qs)
    out = apply_answers(plan, qs, {"open_choice:0": "Top of the Rock"})
    assert [i.name for i in out.days[0].items] == ["Top of the Rock", "Central Park"]
    assert out.open_choices == []
    assert len(plan.days[0].items) == 3


def test_vague_day_answer():
    plan = make(vague_days=[date(2026, 10, 11)])
    qs = ask(plan)
    out = apply_answers(plan, qs, {"vague_day:2026-10-11": "Louvre, Seine cruise"})
    assert [i.name for i in out.days[1].items] == ["Louvre", "Seine cruise"]
    assert out.vague_days == []


def test_image_only_question():
    qs = ask(make(), [att("scan.pdf", text="", image_only=True, has_images=True)])
    assert qs[0].id == "image_only:scan.pdf"
    assert qs[0].text == "scan.pdf is an image — please paste its text"


def test_unreadable_and_image_file():
    qs = ask(make(), [att("bad.pdf", error="boom"), att("p.png", kind="image", text="", image_only=True, has_images=True)])
    assert ids(qs) == ["unreadable:bad.pdf", "image_details:p.png"]


def test_image_details_booking_like():
    a = att("ticket.pdf", has_images=True, text="Your ticket QR")
    b = att("notes.pdf", has_images=True)
    assert ids(ask(make(), [a, b])) == ["image_details:ticket.pdf"]


def test_missing_travel_mode():
    plan = make(travel_modes=[])
    qs = ask(plan)
    assert ids(qs) == ["missing:travel_modes"]
    out = apply_answers(plan, qs, {"missing:travel_modes": "taxi and private driver"})
    assert out.travel_modes == ["taxi", "private_driver"]


def test_missing_diet_only_when_both_empty():
    assert ids(ask(make(diet=Diet()))) == ["missing:diet"]
    intake = IntakeFields(values={"Diet (restrictions, allergies, likes)": "veg"})
    assert ask(make(diet=Diet()), intake=intake) == []


def test_no_library_stop_raises():
    plan = make()
    qs = ask(plan, lib=FakeLib(missing={"Paris"}))
    assert ids(qs) == ["no_library:Paris"] and qs[0].options == ["Proceed", "Stop"]
    apply_answers(plan, qs, {"no_library:Paris": "Proceed"})
    with pytest.raises(PreflightStop):
        apply_answers(plan, qs, {"no_library:Paris": "Stop"})


def test_hours_conflict():
    closed_mornings = WeeklyHours(periods={d: [(time(13), time(18))] for d in range(7)}, source="google")
    always_closed = WeeklyHours(periods={}, source="google")

    def place(h):
        return Place(query="q", place_id="p", name="M", address="a", lat=0, lng=0, status="OPERATIONAL", hours=h,
                     maps_url="u", fetched_at=datetime(2026, 1, 1), match_ok=True)

    def plan_with():
        item = PlannedItem(name="Museum", kind="attraction", city="Paris", slot_hint="morning")
        return make(days=[DayPlan(date=date(2026, 10, 10), title="t", city="Paris", items=[item]), *make().days[1:]])

    assert ask(plan_with(), places={"Museum": place(closed_mornings)}) == []
    qs = ask(plan_with(), places={"Museum": place(always_closed)})
    assert ids(qs) == ["hours_conflict:2026-10-10:Museum"]
    out = apply_answers(plan_with(), qs, {qs[0].id: "Remove"})
    assert out.days[0].items == []


def test_early_arrival_previous_day():
    plan = make(
        hotels=[hotel(date(2026, 9, 25), date(2026, 9, 27))],
        days=[DayPlan(date=date(2026, 9, d), title="t", city="Paris") for d in (24, 25, 26, 27)],
        transport=[TransportLeg(kind="flight", from_place="Delhi", to_place="Paris", source="t",
                                depart=datetime(2026, 9, 24, 20, 0), arrive=datetime(2026, 9, 25, 0, 10)),
                   TransportLeg(kind="flight", from_place="Paris", to_place="Delhi", source="t",
                                depart=datetime(2026, 9, 27, 12, 0))],
    )
    qs = ask(plan)
    assert ids(qs) == ["early_arrival:2026-09-25"]
    out = apply_answers(plan, qs, {qs[0].id: "2026-09-24"})
    assert out.hotels[0].check_in == date(2026, 9, 24)
    assert out.days[0].date == date(2026, 9, 24)


def test_no_departure_question():
    plan = make(transport=[])
    qs = ask(plan)
    assert ids(qs) == ["no_departure"]
    out = apply_answers(plan, qs, {"no_departure": "flight at 14:30"})
    assert out.transport[0].depart == datetime(2026, 10, 12, 14, 30)
    assert out.transport[0].kind == "flight"
    assert ask(out) == []


def test_booking_conflict_question():
    item = PlannedItem(name="Night tour", kind="activity", city="Paris", time="19:00", booking_ref="Night tour")
    days = make().days
    days[0] = DayPlan(date=date(2026, 10, 10), title="t", city="Paris", items=[item])
    plan = make(days=days, bookings=[Booking(name="Night tour", day=date(2026, 10, 11), time="20:00", source="ticket.pdf")])
    qs = ask(plan)
    assert ids(qs) == ["booking_conflict:Night tour"]
    out = apply_answers(plan, qs, {qs[0].id: "Use booking"})
    assert out.days[0].items == []
    assert out.days[1].items[0].time == "20:00"


def test_headcount_mismatch():
    def leg(label):
        return TransportLeg(kind="train", from_place="a", to_place="b", source="t", ref="R1", pax_label=label,
                            depart=datetime(2026, 10, 12, 10, 0))

    plan = make(travellers=Traveller(adults=2, kids_ages=[7]), transport=[leg("3 Adults")])
    assert ids(ask(plan)) == ["headcount:R1"]
    assert ids(ask(make(transport=[leg("2x Youth")]))) == ["headcount:R1"]
    assert ask(make(transport=[leg("2 Adults")])) == []


def test_unvouchered_confirmed():
    item = PlannedItem(name="Louvre tour", kind="activity", city="Paris", note="confirmed")
    days = make().days
    days[1] = DayPlan(date=date(2026, 10, 11), title="t", city="Paris", items=[item])
    plan = make(days=days)
    assert ids(ask(plan)) == ["unvouchered_confirmed:Louvre tour"]
    assert ask(plan, [att("v.pdf", text="Voucher: Louvre tour 11 Oct " * 3)]) == []


def test_kids_ages_only_when_unknown():
    assert ids(ask(make(travellers=Traveller(adults=2, child_counts={"child": 1})))) == ["kids_ages"]
    assert ask(make(travellers=Traveller(adults=2, kids_ages=[6], child_counts={"child": 1}))) == []
    out = apply_answers(make(travellers=Traveller(adults=2, child_counts={"child": 2})),
                        [ask(make(travellers=Traveller(adults=2, child_counts={"child": 2})))[0]], {"kids_ages": "4 and 9"})
    assert out.travellers.kids_ages == [4, 9]


def test_optional_items_not_asked():
    item = PlannedItem(name="Spa", kind="activity", city="Paris", note="booked", optional=True)
    days = make().days
    days[0] = DayPlan(date=date(2026, 10, 10), title="t", city="Paris", items=[item])
    assert ask(make(days=days)) == []


def test_permit_question():
    item = PlannedItem(name="Pangong Lake", kind="attraction", city="Leh")
    days = [DayPlan(date=date(2026, 10, d), title="t", city="Leh", items=[item] if d == 10 else []) for d in (10, 11, 12)]
    plan = make(days=days, trip_scope="domestic", hotels=[hotel(date(2026, 10, 10), date(2026, 10, 12), city="Leh")])
    assert ids(ask(plan, lib=FakeLib())) == ["permit:Pangong Lake"]
    plan.additional_notes = "Pangong inner line permit arranged"
    assert ask(plan) == []


def test_all_questions_returned_at_once():
    plan = make(
        travel_modes=[], diet=Diet(),
        hotels=[hotel(date(2026, 10, 10), date(2026, 10, 11)), hotel(date(2026, 10, 12), date(2026, 10, 13))],
        days=[DayPlan(date=date(2026, 10, d), title="t", city="Paris") for d in (10, 11, 12, 13)],
        transport=[TransportLeg(kind="flight", from_place="a", to_place="b", source="t",
                                depart=datetime(2026, 10, 13, 12, 0))],
    )
    qs = ask(plan, [att("scan.pdf", text="", image_only=True, has_images=True)])
    assert ids(qs) == ["missing:travel_modes", "missing:diet", "image_only:scan.pdf", "hotel_gap:2026-10-11"]
    assert len(set(ids(qs))) == len(qs)
    assert ids(unanswered(qs, {"missing:diet": "none", "hotel_gap:2026-10-11": " "})) == [
        "missing:travel_modes", "image_only:scan.pdf", "hotel_gap:2026-10-11"]


@pytest.mark.parametrize("ans,expected", [
    ("flight at 2:30 pm", datetime(2026, 10, 12, 14, 30)),
    ("on 15.10 at 14:30", datetime(2026, 10, 12, 14, 30)),
    ("train 9am", datetime(2026, 10, 12, 9, 0)),
])
def test_no_departure_time_parsing(ans, expected):
    plan = make(transport=[])
    qs = ask(plan)
    out = apply_answers(plan, qs, {"no_departure": ans})
    assert out.transport[0].depart == expected


@pytest.mark.parametrize("ans", ["around noonish", "15.10", "at 10:00 or 14:30"])
def test_no_departure_invalid_answer_not_applied(ans):
    plan = make(transport=[])
    qs = ask(plan)
    assert "no_departure" in validate_answers(qs, {"no_departure": ans})
    assert ids(unanswered(qs, {"no_departure": ans})) == ["no_departure"]
    assert apply_answers(plan, qs, {"no_departure": ans}).transport == []


@pytest.mark.parametrize("label,adults,kids,flagged", [
    ("1 Adult", 2, 0, True),
    ("2 Adults", 2, 1, True),
    ("1 Adult, 1 Child", 2, 1, True),
    ("2x Youth", 2, 0, True),
    ("Adult x2", 2, 0, False),
    ("Adult x3", 2, 0, True),
    ("2 Pax", 2, 0, False),
    ("2 Pax", 2, 1, True),
    ("seat A", 2, 0, True),
    ("2 Adults, 1 Child", 2, 1, False),
    ("3 Adults", 2, 1, True),
])
def test_headcount_any_disagreement(label, adults, kids, flagged):
    leg = TransportLeg(kind="train", from_place="a", to_place="b", source="t", ref="R1", pax_label=label,
                       depart=datetime(2026, 10, 12, 10, 0))
    plan = make(travellers=Traveller(adults=adults, kids_ages=[7] * kids), transport=[leg])
    assert (ids(ask(plan)) == ["headcount:R1"]) == flagged
    if flagged:
        assert "does it cover all" in ask(plan)[0].text


def test_open_choice_invalid_answer_keeps_plan():
    day = DayPlan(date=date(2026, 10, 10), title="t", city="Paris", items=[
        PlannedItem(name="Top of the Rock", kind="attraction", city="Paris"),
        PlannedItem(name="Empire State Building", kind="attraction", city="Paris"),
    ])
    plan = make(days=[day, *make().days[1:]],
                open_choices=[OpenChoice(day=date(2026, 10, 10), text="v", options=["Top of the Rock", "Empire State Building"])])
    qs = ask(plan)
    ans = {"open_choice:0": "whichever"}
    assert "open_choice:0" in validate_answers(qs, ans)
    assert ids(unanswered(qs, ans)) == ["open_choice:0"]
    out = apply_answers(plan, qs, ans)
    assert len(out.days[0].items) == 2 and len(out.open_choices) == 1


def test_non_iso_date_answers_invalid():
    plan = make(hotels=[hotel(date(2026, 10, 10), date(2026, 10, 14))],
                days=[DayPlan(date=date(2026, 10, d), title="t", city="Paris") for d in range(10, 15)],
                transport=[TransportLeg(kind="flight", from_place="Paris", to_place="Rome", source="t",
                                        depart=datetime(2026, 10, 15, 1, 0))])
    qs = ask(plan)
    ans = {"late_departure:2026-10-15": "14 Oct"}
    assert "late_departure:2026-10-15" in validate_answers(qs, ans)
    out = apply_answers(plan, qs, ans)
    assert out.hotels[0].check_out == date(2026, 10, 14)


@pytest.mark.parametrize("ans,expected", [
    ("a different plan", []),
    ("cable car and business class", []),
    ("rent a car", ["self_drive"]),
    ("cabs, buses", ["taxi", "public_transport"]),
])
def test_mode_word_boundaries(ans, expected):
    from src.aigv2.preflight import _modes
    assert _modes(ans) == expected


@pytest.mark.parametrize("note,asked", [
    ("confirmed", True), ("booked by agent", True),
    ("not booked", False), ("to be booked", False), ("not yet confirmed", False), ("isn't booked", False),
])
def test_confirmed_negation(note, asked):
    item = PlannedItem(name="Tour", kind="activity", city="Paris", note=note)
    days = make().days
    days[1] = DayPlan(date=date(2026, 10, 11), title="t", city="Paris", items=[item])
    assert bool(ask(make(days=days))) == asked


def test_permit_skips_optional_and_day_title():
    opt = PlannedItem(name="Pangong Lake", kind="attraction", city="Leh", optional=True)
    plain = PlannedItem(name="Leh Palace", kind="attraction", city="Leh")
    days = [DayPlan(date=date(2026, 10, 10), title="Road to Nubra", city="Leh", items=[opt, plain]), *make().days[1:]]
    plan = make(days=days, trip_scope="domestic")
    assert ask(plan) == []
