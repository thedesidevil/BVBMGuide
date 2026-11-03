import pytest
from pydantic import TypeAdapter, ValidationError

from src.aigv2.guide import (Guide, Page, Component, Link, Fact, MarkerRef, Restaurant, MealBlock,
                             SightseeingCard)
from src.aigv2.guide import model as m

L = Link(text="Mayura Ubud Retreat", url="https://maps.example/x")
FACTS = [Fact(label="Room", value="Deluxe Room"), Fact(label="To", value="DPS", link=Link(text="DPS"))]
REST = Restaurant(name="Wedja", maps_url="https://maps.example/r", cuisines=["Café"], veg=True, text="t",
                  must_try="m", hours="7 AM", price=MarkerRef(kind="PRICE_UNKNOWN", text="no price"), travel="3 min")
MARK = MarkerRef(kind="VERIFY", text="check hours")


def every_component():
    return [
        m.Letter(salutation="Dear A,", paragraphs=["p"], signoff="With love,", signature="BVBM"),
        m.Opener(number=1, weekday="Thursday", date="24 September", title=["A", "B"], intro="i"),
        m.YourDay(),
        m.JourneyStrip(stops=[m.JourneyStop(label="Ubud", name=L, time="Leave 7"),
                              m.JourneyStop(label="Sanur", name=Link(text="Boat"), time=None)],
                       legs=["Approx. 60 min by car"]),
        m.SightseeingCard(when="On arrival", part=None, name=L, subtitle="s", facts=FACTS, text="t",
                          tips=["x"], markers=[MARK]),
        m.BookingCard(when="7:00 AM", kind="Transfer", prefix="Transfer to ", title=L, subtitle=None, facts=FACTS,
                      text="t", ref="IND/1", note="Included"),
        m.SimpleCard(when="8 AM", part="Breakfast", heading="h", text="t"),
        m.ChecklistCard(when="9 AM", kind="Check-out", title=L, lead="l", items=["a", "b"]),
        m.OptionCards(eyebrow="AFTERNOON", heading="Your choice", chip="At your own expense",
                      options=[m.Option(label="OPTION 1", name=L, facts=FACTS, text="t", note="n")]),
        MealBlock(meal="lunch", eyebrow="12:30 PM · LUNCH", heading="Lunch", restaurants=[REST]),
        m.PlaceholderMeal(meal="dinner", eyebrow="e", heading="h", count=3),
        m.ReviewMarkerBlock(markers=[MARK]),
        m.ReferenceOpener(eyebrow="BEFORE YOU GO", title="Packing", intro="i"),
        m.FactRowBlock(facts=FACTS),
        m.TitledParas(items=[m.TitledPara(heading="h", body="b")]),
        m.ChecklistGroups(groups=[m.ChecklistGroup(title="Clothes", items=["a"])]),
        m.TipPanel(title="t", items=["a"], columns=2, checks=True),
        m.NotePanel(title="PLEASE NOTE", text="x"),
        m.AppGrid(apps=[m.App(name="Grab", use="taxis")]),
        m.PlaceGroups(hotels=[m.HotelPlaces(hotel=L, city="UBUD", dates="24 – 28 Sep",
                                            pharmacies=[m.NearbyPlace(name=L, walk_min=3, drive_min=1,
                                                                      hours_text=None, phone=None)],
                                            groceries=[], hospitals=[], markers=[MARK])]),
        m.DishGrid(dishes=[m.Dish(name="Nasi", desc="d", where=[L])]),
        m.SouvenirGrid(categories=[m.Souvenir(title="Silver", what="w", places=[L])]),
        m.DosDonts(do=["a"], dont=["b"]),
        m.PhraseTable(phrases=[m.Phrase(local="Terima kasih", english="Thank you")]),
        m.EmergencyStrip(numbers=[m.EmergencyNumber(service="Police", number="110")], dial="Dial 0"),
        m.ContactCards(cards=[m.Contact(eyebrow="Tourist Police", name=L, phone="1", note="n")]),
        m.ThankYou(paragraphs=["p"], signoff="s", signature="BVBM"),
    ]


def test_guide_round_trip():
    comps = [m.YourDay(), MealBlock(meal="lunch", eyebrow="e", heading="h", restaurants=[REST]),
             SightseeingCard(when="w", name=L, text="t")]
    pages = [Page(kind=k, title=k, bookmark=k, components=list(comps))
             for k in ("letter", "toc", "day", "reference", "thank_you")]
    g = Guide(client="Dilna", destination="Bali", title="T", subtitle="S", pages=pages)
    assert Guide.model_validate_json(g.model_dump_json()) == g


def test_every_component_round_trips():
    comps = every_component()
    names = {c.type for c in comps}
    expected = {n for n, v in vars(m).items() if isinstance(v, type) and "type" in getattr(v, "model_fields", {})}
    assert names == expected
    g = Guide(client="c", destination="d", title="t", subtitle="s",
              pages=[Page(kind="day", title="t", bookmark="day1", components=comps)])
    assert Guide.model_validate_json(g.model_dump_json()) == g


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        SightseeingCard(when="w", name=L, text="t", colour="red")


def test_component_discriminator():
    c = TypeAdapter(Component).validate_python(
        {"type": "MealBlock", "meal": "dinner", "eyebrow": "e", "heading": "h", "restaurants": []})
    assert isinstance(c, MealBlock)
    with pytest.raises(ValidationError):
        TypeAdapter(Component).validate_python({"type": "Nope"})
