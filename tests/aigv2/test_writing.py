import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from src.aigv2.config import Settings
from src.aigv2.llm import LLMStepError, StepLLM
from src.aigv2.models import Diet, HotelStay, Traveller, TripPlan, DayPlan, PlannedItem
from src.aigv2.money import FxUnavailable
from src.aigv2.writing.days import write_day
from src.aigv2.writing.sections import write_section
from src.aigv2.writing.title import write_title


class FakeClient:
    def __init__(self, model, replies, calls):
        self.model = model
        self._replies = replies
        self._calls = calls
        self._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self._create)))

    def _create(self, **kw):
        self._calls.append((self.model, kw))
        r = self._replies[self.model]
        text = r.pop(0) if isinstance(r, list) else r
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(text)))], usage=usage)


def make(luna, sol=None):
    calls = []
    replies = {"gpt-6-luna": luna, "gpt-6.1-sol": sol if sol is not None else luna}
    settings = Settings(models={s: "gpt-6-luna" for s in ("write_days", "write_sections", "title")})
    return StepLLM(settings, client_factory=lambda m: FakeClient(m, replies, calls)), calls


def trip(scope="international", cities=("Paris",)):
    hotels = [HotelStay(city=c, hotel="H", check_in=date(2026, 10, 1), check_out=date(2026, 10, 3), source="voucher") for c in cities]
    return TripPlan(client_names=["A"], travellers=Traveller(adults=2), diet=Diet(), travel_modes=["taxi"], hotels=hotels,
                    transport=[], bookings=[], open_choices=[], vague_days=[], commentary_removed=[], trip_scope=scope,
                    days=[DayPlan(date=date(2026, 10, 1), title="t", city=cities[0],
                                  items=[PlannedItem(name="Louvre", kind="attraction", city=cities[0])])])


FACTS = {"date": "2026-10-01", "city": "Paris", "travellers": "2 adults", "occasion": "",
         "attractions": [{"name": "Louvre"}], "restaurants": [{"name": "Chez A"}]}


def day_reply(desc="A lovely start.", extra=False):
    atts = [{"name": "Louvre", "description": desc}] + ([{"name": "Eiffel"}] if extra else [])
    atts = [{**a, "description": a.get("description", "x")} for a in atts]
    return {"title": "Paris", "intro": "We begin gently.", "attractions": atts,
            "restaurants": [{"name": "Chez A", "ambience": "cozy", "best_for": "dinner"}]}


def test_day_ok_no_fallback():
    llm, _ = make(day_reply())
    assert write_day(FACTS, llm).attractions[0].name == "Louvre"
    assert len(llm.cost_log) == 1


def test_day_facts_missing_keys():
    llm, _ = make(day_reply())
    with pytest.raises(ValueError):
        write_day({"date": "x"}, llm)


def test_day_names_must_match_inputs():
    llm, _ = make([day_reply(extra=True)], [day_reply()])
    assert len(write_day(FACTS, llm).attractions) == 1
    assert llm.cost_log[1]["fallback"] is True


def test_description_with_time_rejected():
    llm, _ = make([day_reply("open 9 AM")], [day_reply()])
    write_day(FACTS, llm)
    assert llm.cost_log[1]["fallback"] is True


def test_description_with_price_still_failing_raises():
    llm, _ = make(day_reply("Tickets cost €20"))
    with pytest.raises(LLMStepError):
        write_day(FACTS, llm)


def sec(items):
    return {"items": items}


CITY = [{"city": "Paris", "country": "France", "local_dishes": [{"name": "Croissant", "description": "Flaky"}],
         "restaurants": [{"name": "Chez A"}], "souvenirs": ["Perfume"], "currency": "EUR"}]


def test_section_library_first_not_verified():
    llm, _ = make(sec([{"heading": "Croissant", "body": "Flaky and buttery."}]))
    s = write_section("dishes", CITY, {}, trip(), llm)
    assert s.from_library and not s.items[0].verify


def test_section_ai_marked_verify():
    llm, _ = make(sec([{"heading": "Museums", "body": "Plan ahead."}]))
    s = write_section("health", [{"city": "Paris", "country": "France"}], {}, trip(), llm)
    assert not s.from_library and s.items[0].verify


def test_packing_never_verify():
    llm, _ = make(sec([{"heading": "Layers", "body": "Bring a light jacket."}]))
    s = write_section("packing", CITY, {}, trip(), llm)
    assert not s.items[0].verify


def test_dishes_where_to_try_library_only():
    bad = sec([{"heading": "Croissant", "body": "Flaky", "where_to_try": ["Nowhere"]}])
    good = sec([{"heading": "Croissant", "body": "Flaky", "where_to_try": ["Chez A"]}])
    llm, _ = make([bad], [good])
    s = write_section("dishes", CITY, {}, trip(), llm)
    assert llm.cost_log[1]["fallback"] is True and "Chez A" in s.items[0].body


def test_library_price_still_verified():
    cities = [{"city": "Paris", "country": "France", "connectivity_tips": ["eSIM from Airalo"]}]
    llm, _ = make(sec([{"heading": "eSIM", "body": "eSIM from Airalo."}, {"heading": "Cost", "body": "Plan for about 10 EUR"}]))
    cities[0]["connectivity_tips"].append("about 10 EUR")
    s = write_section("connectivity", cities, {}, trip(), llm)
    assert s.from_library and all(i.verify for i in s.items)


def test_domestic_omits_money_sim():
    llm, calls = make(sec([{"heading": "x", "body": "y"}]))
    t = trip("domestic")
    for k in ("money", "connectivity", "health"):
        assert write_section(k, CITY, {}, t, llm) is None
    assert not calls
    assert write_section("health", CITY, {}, t, llm, remote_area=True) is not None


def test_domestic_safety_has_112():
    llm, _ = make(sec([{"heading": "Mountain roads", "body": "Drive slowly."}]))
    s = write_section("safety", [{"city": "Leh"}], {}, trip("domestic", ("Leh",)), llm)
    assert "112" in s.items[0].body


def test_multicountry_sections_grouped():
    cities = [{"city": "Paris", "country": "France", "souvenirs": ["Perfume"]},
              {"city": "Rome", "country": "Italy", "souvenirs": ["Leather"]}]
    llm, _ = make(sec([{"heading": "Gift", "body": "Lovely."}]))
    s = write_section("souvenirs", cities, {}, trip(cities=("Paris", "Rome")), llm)
    assert set(s.by_country) == {"France", "Italy"} and len(s.items) == 2


class FakeFx:
    def rate(self, code, on=None):
        return 90.5


def test_money_rate_line_code_generated():
    llm, _ = make(sec([{"heading": "Cards", "body": "Cards are widely accepted."}]))
    s = write_section("money", CITY, {}, trip(), llm, fx=FakeFx(), today=date(2026, 10, 1))
    assert "1 EUR = ₹90.50" in s.items[0].body and not s.items[0].verify


class FakePlaces:
    def __init__(self, ok):
        self.ok = ok

    def find(self, name, city):
        return SimpleNamespace(match_ok=self.ok, address="1 Rue X", phone="+33 1", name=name)


def test_safety_embassy_checked():
    reply = sec([{"heading": "Embassy of India", "body": "Somewhere in Paris."}])
    llm, _ = make(reply)
    s = write_section("safety", [{"city": "Paris", "country": "France"}], {}, trip(), llm, places=FakePlaces(True))
    e = s.items[0]
    assert "1 Rue X" in e.body and not e.verify
    llm, _ = make(reply)
    s = write_section("safety", [{"city": "Paris", "country": "France"}], {}, trip(), llm, places=FakePlaces(False))
    assert s.items[0].verify


def test_title_rejects_generic():
    llm, _ = make([{"title": "All Inclusive Guide"}], [{"title": "Parisian Autumn Dreams"}])
    assert write_title(trip(), llm) == "Parisian Autumn Dreams"
    assert llm.cost_log[1]["fallback"] is True
    llm, _ = make([{"title": "Your Trip"}], [{"title": "Paris"}])
    with pytest.raises(LLMStepError):
        write_title(trip(), llm)


@pytest.mark.parametrize("key,lib_key,tip", [
    ("health", "health_tips", "Drink bottled water"),
    ("safety", "safety_tips", "Watch your bag"),
    ("etiquette", "phrases", "Bonjour"),
    ("getting_around", "transport_options", "Metro runs late"),
    ("connectivity", "connectivity_tips", "Free wifi in cafes"),
])
def test_country_only_content_is_library(key, lib_key, tip):
    llm, calls = make(sec([{"heading": "Tip", "body": tip}]))
    s = write_section(key, [{"city": "Paris", "country": "France"}], {"France": {lib_key: [tip]}}, trip(), llm)
    assert s.from_library and not s.items[0].verify
    assert tip in calls[0][1]["messages"][-1]["content"]


def test_country_data_keyed_by_country_only():
    llm, calls = make(sec([{"heading": "Tip", "body": "ok"}]))
    s = write_section("health", [{"city": "Paris", "country": "France"}], {"Italy": {"health_tips": ["x"]}}, trip(), llm)
    assert not s.from_library


def test_money_is_ai_verify_and_unresolved_currency_marked():
    llm, _ = make(sec([{"heading": "Cards", "body": "Widely accepted."}]))
    s = write_section("money", [{"city": "Atlantis", "country": "Nowhere"}], {}, trip(), llm, fx=FakeFx())
    assert not s.from_library and all(i.verify for i in s.items) and s.items[0].heading == "Currency"


def test_day_restaurant_and_title_facts_rejected_and_names_canonical():
    r = day_reply()
    r["restaurants"][0]["ambience"] = "just 5 minutes away"
    llm, _ = make([r], [day_reply()])
    write_day(FACTS, llm)
    assert llm.cost_log[1]["fallback"] is True
    r = day_reply()
    r["title"] = "Paris at 9 AM"
    llm, _ = make([r], [day_reply()])
    write_day(FACTS, llm)
    assert llm.cost_log[1]["fallback"] is True
    r = day_reply()
    r["attractions"][0]["name"] = "  louvre "
    llm, _ = make(r)
    assert write_day(FACTS, llm).attractions[0].name == "Louvre"


def test_domestic_remote_guidance_is_code_written():
    llm, calls = make(sec([{"heading": "Roads", "body": "Be careful."}]))
    t = trip("domestic", ("Leh",))
    plain = write_section("safety", [{"city": "Leh"}], {}, t, llm)
    assert [i.heading for i in plain.items][:2] == ["Emergency number", "Roads"]
    for kw in ({"remote_area": True}, {"high_altitude": True}):
        llm, calls = make(sec([{"heading": "Roads", "body": "Be careful."}]))
        s = write_section("safety", [{"city": "Leh"}], {}, t, llm, **kw)
        heads = [i.heading for i in s.items]
        assert {"Altitude", "Mountain roads", "Low network"} <= set(heads)


def test_verify_heuristic_precision():
    from src.aigv2.writing.sections import needs_verify
    assert not needs_verify("Consider travel insurance and an eSIM or SIM card")
    assert not needs_verify("Pack a USB 3 charger")
    assert needs_verify("Budget 20 EUR")
    assert needs_verify("Buy a Maya eSIM")
    assert needs_verify("Try Airalo")


def test_title_rejects_hyphenated_and_strips_quotes():
    llm, _ = make([{"title": "All-Inclusive Guide Paris"}], [{"title": "\"Parisian Autumn\""}])
    assert write_title(trip(), llm) == "Parisian Autumn"
    assert llm.cost_log[1]["fallback"] is True


def test_safety_no_hotels_no_crash():
    t = trip()
    t.hotels = []
    llm, _ = make(sec([{"heading": "Bags", "body": "Watch them."}]))
    assert write_section("safety", [{"country": "France"}], {}, t, llm).items


def test_dishes_where_to_try_diet_filtered():
    cities = [{**CITY[0], "restaurants": [
        {"name": "Le Boeuf", "cuisine_type": ["Steakhouse"], "vegetarian_friendly": False},
        {"name": "Green Table", "cuisine_type": ["Vegetarian"], "vegetarian_friendly": True,
         "highlights": "Pure vegetarian kitchen"}]}]
    veg = trip().model_copy(update={"diet": Diet(restrictions=["vegetarian"], pure_veg=True)})
    bad = sec([{"heading": "Croissant", "body": "Flaky", "where_to_try": ["Le Boeuf"]}])
    good = sec([{"heading": "Croissant", "body": "Flaky", "where_to_try": ["Green Table"]}])
    llm, calls = make([bad], [good])
    s = write_section("dishes", cities, {}, veg, llm)
    assert llm.cost_log[1]["fallback"] is True
    assert "Green Table" in s.items[0].body and "Le Boeuf" not in s.items[0].body
    assert "Le Boeuf" not in calls[0][1]["messages"][1]["content"].split("where_to_try: ", 1)[1].split("\n", 1)[0]
