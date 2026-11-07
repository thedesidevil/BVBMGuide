from datetime import date

from src.aigv2.models import Booking, DayPlan, OpenChoice, PlannedItem, Question
from src.aigv2.preflight import apply_answers, run_checklist
from src.aigv2.question_days import day_label, prefix_questions
from tests.aigv2.test_preflight import FakeLib, IntakeFields, ask, att, make, hotel


def test_day_label_forms():
    trip = make()
    assert day_label(trip, [date(2026, 10, 11)]) == "Day 2 (Sun 11 Oct) - "
    assert day_label(trip, [date(2026, 10, 11), date(2026, 10, 12)]) == "Days 2-3 (Sun 11 Oct - Mon 12 Oct) - "
    assert day_label(trip, []) == "Whole trip - "
    assert day_label(trip, [date(2026, 12, 1)]).startswith("Tue 1 Dec")


def test_open_choice_without_day_finds_it_and_ids_unchanged():
    oc = OpenChoice(text="nearby stay", options=["Return to Interlaken", "Nearby stay"])
    plan = make(open_choices=[oc], days=[
        DayPlan(date=date(2026, 10, 10), title="t", city="Paris"),
        DayPlan(date=date(2026, 10, 11), title="t", city="Paris",
                items=[PlannedItem(name="Return to Interlaken", kind="activity", city="Paris")]),
        DayPlan(date=date(2026, 10, 12), title="t", city="Paris")])
    q = ask(plan)[0]
    assert q.id == "open_choice:0" and q.text.startswith("Day 2 (Sun 11 Oct) - Which do you want")


def test_other_kinds_prefixed():
    plan = make(vague_days=[date(2026, 10, 11)], days=[DayPlan(date=date(2026, 10, d), title="t", city="Paris")
                                                      for d in (10, 11, 12)])
    qs = {q.kind: q for q in ask(plan)}
    assert qs["vague_day"].text.startswith("Day 2 (Sun 11 Oct) - ")
    qs = {q.kind: q for q in ask(make(transport=[]))}
    assert qs["no_departure"].text.startswith("Day 3 (Mon 12 Oct) - ")


def test_image_details_uses_dates_in_the_file():
    a = att("tickets.png", kind="image", text_dates=["11 Oct 2026"])
    q = [x for x in ask(make(), [a]) if x.kind == "image_details"][0]
    assert q.text.startswith("Day 2 (Sun 11 Oct) - ")


def test_no_double_prefix():
    plan = make()
    q = Question(id="x", kind="hours_conflict", text="Day 1 (Sat 10 Oct) - already", day=date(2026, 10, 10))
    assert prefix_questions([q], plan)[0].text == "Day 1 (Sat 10 Oct) - already"


def test_multiline_image_details_answer_gives_timed_items_per_line():
    plan = make()
    q = Question(id="image_details:t.png", kind="image_details", text="t")
    ans = "Sat, 10 Oct 2026 03:30 PM - Louvre museum\nSun, 11 Oct 2026 10:00 - Seine cruise\n\nMon, 12 Oct 2026 09:15 - Versailles"
    out = apply_answers(plan, [q], {q.id: ans})
    items = {(dp.date.day, it.name, it.time) for dp in out.days for it in dp.items}
    assert items == {(10, "Louvre museum", "15:30"), (11, "Seine cruise", "10:00"), (12, "Versailles", "09:15")}


def test_vague_day_splits_on_newlines():
    plan = make(vague_days=[date(2026, 10, 11)])
    q = Question(id="vague_day:2026-10-11", kind="vague_day", text="t")
    out = apply_answers(plan, [q], {q.id: "Louvre\nMusee d'Orsay, Seine cruise"})
    assert [i.name for i in out.days[1].items] == ["Louvre", "Musee d'Orsay", "Seine cruise"]
