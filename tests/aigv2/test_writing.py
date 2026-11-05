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
from src.aigv2.writing.thanks import write_thank_you
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
    settings = Settings(models={s: "gpt-6-luna" for s in ("write_days", "write_sections", "title", "thanks")})
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
    return {"title": "Paris", "intro": "The day begins gently.", "attractions": atts,
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
    llm, _ = make({"items": [], "groups": [{"title": "Clothing", "items": ["Light jacket"]}]})
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


@pytest.mark.parametrize("key,lib_key,entry,text", [
    ("etiquette", "tipping", {"tip": "Round up the taxi fare"}, "Round up the taxi fare"),
    ("etiquette", "dos_donts", {"tip": "Remove shoes indoors"}, "Remove shoes indoors"),
    ("safety", "scams", {"tip": "Beware of fake petition clipboards"}, "Beware of fake petition clipboards"),
    ("safety", "embassies", {"name": "Embassy of India in Narnia", "city": "Paris", "phone": "+33 000", "address": "Rue Lune"},
     "Embassy of India in Narnia"),
    ("connectivity", "apps", {"name": "Citymapper", "purpose": "Offline transit maps"}, "Citymapper"),
    ("health", "insurance", {"tip": "Carry your policy card"}, "Carry your policy card"),
    ("money", "money", {"tip": "Cards are widely accepted"}, "Cards are widely accepted"),
])
def test_new_country_lists_are_library(key, lib_key, entry, text):
    llm, calls = make(sec([{"heading": "Tip", "body": text}]))
    s = write_section(key, [{"city": "Paris", "country": "France"}], {"France": {lib_key: [entry]}}, trip(), llm)
    item = [i for i in s.items if text in i.body][0]  # money also has a leading Currency item
    assert s.from_library and not item.verify
    assert text in calls[0][1]["messages"][-1]["content"]


def test_safety_library_embassy_goes_through_embassy_check():
    entry = {"name": "Embassy of India", "city": "Paris", "phone": "+33 1", "address": "Somewhere"}
    llm, _ = make(sec([{"heading": "Embassy of India", "body": "Somewhere in Paris."}]))
    s = write_section("safety", [{"city": "Paris", "country": "France"}], {"France": {"embassies": [entry]}}, trip(),
                      llm, places=FakePlaces(True))
    assert s.from_library
    e = [i for i in s.items if "Embassy of India" in i.heading][0]
    assert "1 Rue X" in e.body and not e.verify


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


def _safety_prompt(embassies):
    llm, calls = make(sec([{"heading": "Tip", "body": "ok"}]))
    s = write_section("safety", [{"city": "Paris", "country": "France"}], {"France": {"embassies": embassies}}, trip(),
                      llm, places=FakePlaces(True))
    return s, calls[0][1]["messages"][-1]["content"]


def _us_trip():
    return trip().model_copy(update={"additional_notes": "Client holds a US passport"})


def _safety_prompt_for(embassies, t):
    llm, calls = make(sec([{"heading": "Tip", "body": "ok"}]))
    s = write_section("safety", [{"city": "Paris", "country": "France"}], {"France": {"embassies": embassies}}, t,
                      llm, places=FakePlaces(True))
    return s, calls[0][1]["messages"][-1]["content"]


def test_safety_foreign_embassy_dropped_for_default_client():
    indian = {"name": "Embassy of India", "city": "Paris", "phone": "+33 1", "address": "20 Rue Alexandre"}
    us = {"name": "U.S. Embassy Cairo", "city": "Cairo", "phone": "+20 2", "address": "5 Tahrir"}
    _, prompt = _safety_prompt([us, indian])
    assert "Embassy of India" in prompt and "U.S. Embassy Cairo" not in prompt


def test_safety_us_embassy_kept_for_us_client_and_india_item_still_checked():
    us = {"name": "U.S. Embassy Cairo", "city": "Cairo", "phone": "+20 2", "address": "5 Tahrir"}
    reply = [{"heading": "Embassy of India", "body": "Somewhere in Paris."}]
    llm, calls = make(sec(reply))
    s = write_section("safety", [{"city": "Paris", "country": "France"}], {"France": {"embassies": [us]}}, _us_trip(),
                      llm, places=FakePlaces(True))
    assert "U.S. Embassy Cairo" in calls[0][1]["messages"][-1]["content"]
    e = [i for i in s.items if "Embassy of India" in i.heading][0]
    assert "1 Rue X" in e.body and not e.verify


def test_safety_embassy_mentioning_india_and_us_kept_for_default_client():
    both = {"name": "Embassy of India, near the U.S. Embassy", "city": "Paris", "phone": "+33 9"}
    _, prompt = _safety_prompt([both])
    assert "+33 9" in prompt


def test_safety_non_indian_embassies_dropped_but_embassy_item_still_checked():
    us = {"name": "U.S. Consulate General Casablanca", "city": "Casablanca", "phone": "+212", "address": "8 Bd"}
    reply = [{"heading": "Embassy of India", "body": "Somewhere in Paris."}]
    llm, calls = make(sec(reply))
    s = write_section("safety", [{"city": "Paris", "country": "France"}], {"France": {"embassies": [us]}}, trip(),
                      llm, places=FakePlaces(True))
    assert "Casablanca" not in calls[0][1]["messages"][-1]["content"]
    e = [i for i in s.items if "Embassy of India" in i.heading][0]
    assert "1 Rue X" in e.body and not e.verify


def test_safety_nameless_embassies_kept_for_default_client():
    _, prompt = _safety_prompt([{"name": "Embassy", "city": "London", "phone": "+44 20"},
                                {"name": "Embassy in Bern", "address": "Kirchenfeldstrasse 28, 3005 Bern",
                                 "phone": "+41 31"}])
    assert "+44 20" in prompt and "Kirchenfeldstrasse" in prompt


def test_client_nationalities():
    from src.aigv2.writing.sections import client_nationalities
    t = trip()
    assert client_nationalities(t) == set()
    for note in ("Is a US citizen", "travels on a U.S. Passport", "American citizen", "Holds a US passport"):
        assert client_nationalities(t.model_copy(update={"additional_notes": note})) == {"us"}
    assert client_nationalities(t.model_copy(update={"occasion": "British citizen birthday"})) == {"uk"}
    assert client_nationalities(t.model_copy(update={"additional_notes": "Stay at our US based hotel"})) == set()


# ---- rate line and motion-sickness rule ----

def test_rate_text_formats():
    from src.aigv2.writing.sections import _rate_text
    assert _rate_text("IDR", 0.0052) == "₹1 ≈ 190 IDR"
    assert _rate_text("X", 0.9) == "1 X = ₹0.90"
    assert _rate_text("X", 0.123) == "1 X = ₹0.123"
    assert _rate_text("X", 90.5) == "1 X = ₹90.50"


def test_money_line_has_no_date():
    class Fx:
        def rate(self, code, on=None):
            return 0.0052
    llm, _ = make(sec([{"heading": "Cards", "body": "Cards are widely accepted."}]))
    s = write_section("money", [{"city": "Ubud", "country": "Indonesia"}], {}, trip(), llm, fx=Fx(),
                      today=date(2026, 11, 2))
    body = s.items[0].body
    assert "₹1 ≈ 190 IDR" in body and "Indicative rate (check before you travel)" in body and "as of" not in body


@pytest.mark.parametrize("ages,expect", [([5], True), ([11, 15], True), ([12], False), ([], False)])
@pytest.mark.parametrize("key", ["packing", "health"])
def test_child_motion_sickness_rule_iff_child_under_12(key, ages, expect):
    llm, calls = make(sec([{"heading": "Layers", "body": "Bring a light jacket."}]))
    t = trip()
    t.travellers = Traveller(adults=2, kids_ages=ages)
    write_section(key, [{"city": "Paris", "country": "France"}], {}, t, llm)
    sent = json.dumps([c[1] for c in calls], default=str)
    assert ("ask your paediatrician before giving any motion-sickness medicine" in sent) is expect


def test_prompts_carry_the_voice_rule_and_no_first_person():
    import re
    from src.aigv2.writing import days, sections, title
    for system in (days._SYSTEM, sections._SYSTEM):
        assert "NEVER use the words we" in system
        assert "Style examples" in system
        assert "first-person" not in system
        assert not re.search(r"(?<!NEVER use the words )\bWe\b", system.replace("we, we'd", ""))
    assert "Begin the day's sightseeing at Tegallalang" in days._SYSTEM
    assert "Keep these saved in your phone" in sections._SYSTEM
    assert "'we'" in title._SYSTEM


def _important(name="BIMC Hospital Nusa Dua"):
    from datetime import datetime as dt
    from src.aigv2.models import Place
    from src.aigv2.planning.important_places import ImportantPlaces, NearbyPlace
    pl = Place(query=name, place_id="h", name=name, address="Jl. Nusa Dua", lat=1, lng=2, status="OPERATIONAL",
               maps_url="u", fetched_at=dt(2026, 1, 1), match_ok=True)
    return [ImportantPlaces(city="Paris", hotel="H", hospital=NearbyPlace(place=pl, drive_min=12, hours_text="Open 24 hours"))]


def test_safety_prompt_lists_important_places_hospital_as_authoritative():
    llm, calls = make(sec([{"heading": "Medical help", "body": "BIMC Hospital Nusa Dua is a 12 minute drive."}]))
    lib = {"France": {"emergency_contacts": ["Dial 112"]}}
    write_section("safety", [{"city": "Paris", "country": "France"}], lib, trip(), llm, important=_important())
    prompt = calls[0][1]["messages"][-1]["content"]
    assert "BIMC Hospital Nusa Dua" in prompt and "Name only these hospitals" in prompt and "Open 24 hours" in prompt


def test_safety_rejects_a_hospital_important_places_does_not_list():
    bad = sec([{"heading": "Medical help", "body": "Ari Canti Hospital is open 24/7."}])
    good = sec([{"heading": "Medical help", "body": "BIMC Hospital Nusa Dua is the nearest hospital."}])
    llm, calls = make(bad + [] if False else [bad, good])
    s = write_section("safety", [{"city": "Paris", "country": "France"}], {}, trip(), llm, important=_important())
    assert "BIMC" in s.items[0].body and len(calls) == 2


def test_library_safety_lines_naming_another_hospital_are_dropped():
    from src.aigv2.writing.sections import _unlisted_hospitals
    assert _unlisted_hospitals("Ari Canti Hospital is open 24/7", ["BIMC Hospital Nusa Dua"]) == ["Ari Canti Hospital"]
    assert _unlisted_hospitals("Go to BIMC Hospital Nusa Dua", ["BIMC Hospital Nusa Dua"]) == []


GOOD = {"paragraphs": ["Thank you for the opportunity to plan your trip to Paris.", "Bon Voyage by Marina is a message away."]}


def test_thank_you_valid():
    llm, _ = make(GOOD)
    out = write_thank_you(trip(), llm)
    assert out.paragraphs == GOOD["paragraphs"] and out.sign_off == "With love,"


def test_thank_you_we_retried_then_fallback():
    bad = {"paragraphs": ["We hope Paris is wonderful for you."]}
    llm, calls = make([bad, bad], [bad, bad])
    out = write_thank_you(trip(), llm)
    assert len(calls) == 2 and "Paris" in out.paragraphs[0] and out.sign_off == "With love,"
    assert not any(w in " ".join(out.paragraphs).lower().split() for w in ("we", "our", "us"))


def test_thank_you_retry_recovers():
    llm, calls = make([{"paragraphs": ["We love Paris."]}, GOOD])
    assert write_thank_you(trip(), llm).paragraphs == GOOD["paragraphs"] and len(calls) == 2


@pytest.mark.parametrize("paras", [["Enjoy your holiday, it will be wonderful."], ["Paris a.", "Paris b.", "Paris c."],
                                   ["Paris " + "x" * 330], ["Paris awaits, call +91 86000 15316."]])
def test_thank_you_rejected(paras):
    llm, calls = make({"paragraphs": paras})
    out = write_thank_you(trip(), llm)
    assert len(calls) == 2 and out.paragraphs[0].startswith("It has been a pleasure")


def test_island_in_prose_must_match_google_address():
    from src.aigv2.writing.days import island_problems
    addr = "Ceningan Island, Lembongan, Kec. Nusa Penida, Bali"
    assert island_problems("Blue Lagoon", "A cliff pool on Nusa Lembongan.", addr)
    assert not island_problems("Blue Lagoon", "A cliff pool on Ceningan Island.", addr)
    assert not island_problems("Blue Lagoon", "A cliff pool on Nusa Lembongan.", None)


# ---- booking window framing (Bali day 3: 09:00-16:00 package called "the morning")

WIN = {"booking_window": {"start": "09:00", "end": "16:00", "hours": 7.0, "lunch_in_package": True}}


def _reply(intro):
    r = day_reply()
    r["intro"] = intro
    return r


def test_long_booking_rejects_morning_intro_and_retries():
    llm, calls = make([_reply("Spend the morning at the park.")], [_reply("A full day out on the water.")])
    out = write_day({**FACTS, **WIN}, llm)
    assert out.intro == "A full day out on the water." and llm.cost_log[1]["fallback"] is True


def test_short_or_missing_window_allows_morning_intro():
    for facts in (FACTS, {**FACTS, "booking_window": {"start": "09:00", "end": "12:00", "hours": 3.0,
                                                      "lunch_in_package": False}}):
        llm, _ = make(_reply("Spend the morning at the park."))
        assert write_day(facts, llm).intro == "Spend the morning at the park."


def test_prompt_mentions_booking_window():
    from src.aigv2.writing import days
    assert "booking_window" in days._SYSTEM


# ---- library places outside the trip

def test_drop_other_places_filters_entries_and_where_to_buy():
    import re
    from src.aigv2.writing.sections import _place_regex, drop_other_places
    rx = _place_regex(["Nusa Dua", "Kuta"])
    items = [{"mode": "Grab", "description": "Casual outings such as Ubud cafe hopping and Nusa Dua to nearby restaurants"},
             {"mode": "Taxi", "description": "From Denpasar International Airport (DPS) to Ubud"},
             {"item": "Batik", "where_to_buy": ["Ubud Art Market", "Bali Collection (Nusa Dua)", "Kuta Beach Walk"]}]
    out = drop_other_places(items, rx)
    assert [i.get("mode") or i["item"] for i in out] == ["Taxi", "Batik"]
    assert out[1]["where_to_buy"] == ["Ubud Art Market"]
    assert drop_other_places(items, None) == items


def test_other_places_reach_library_named_for_transport():
    from src.aigv2.writing.sections import _library_named
    cities = [{"city": "Ubud", "country": "Indonesia", "transport_options": [
        {"mode": "Grab", "description": "Short rides in Nusa Dua"}, {"mode": "Taxi", "description": "Ubud to airport"}]}]
    named = _library_named("getting_around", cities, [{}], other_places=["Nusa Dua"])
    assert [o["mode"] for o in named["transport_options"]] == ["Taxi"]


# ---- lunch-included claims need the voucher to say so (Bali day 3)

def test_lunch_claim_rejected_unless_voucher_states_it():
    claim = _reply("A full day out on the water. The package includes lunch during the outing.")
    ok = _reply("A full day out on the water.")
    for li in (None, False):
        facts = {**FACTS, "booking_window": {**WIN["booking_window"], "lunch_included": li}}
        llm, _ = make(claim, ok)
        assert write_day(facts, llm).intro == "A full day out on the water."
    facts = {**FACTS, "booking_window": {**WIN["booking_window"], "lunch_included": True}}
    llm, _ = make(claim)
    assert "includes lunch" in write_day(facts, llm).intro


def test_lunch_claim_in_attraction_description_rejected():
    r = day_reply()
    r["attractions"][0]["description"] = "The Sea Dragon Package includes lunch during the Marine Park experience."
    llm, _ = make(r, day_reply())
    out = write_day({**FACTS, **WIN}, llm)
    assert "lunch" not in out.attractions[0].description.lower()


def test_booking_lunch_included_reads_voucher_text():
    from src.aigv2.models import Booking, booking_lunch_included
    from datetime import date as _d
    mk = lambda *ins: Booking(name="Tour", day=_d(2026, 9, 26), source="voucher", instructions=list(ins))
    assert booking_lunch_included(mk("Private basis.")) is None
    assert booking_lunch_included(mk("Includes lunch and snorkel gear")) is True
    assert booking_lunch_included(mk("Lunch not included")) is False
    assert booking_lunch_included(mk("No lunch provided")) is False


def test_pharmacy_names_must_come_from_important_places():
    from src.aigv2.writing.sections import _unlisted_pharmacies, pharmacy_mentions
    assert _unlisted_pharmacies("ApotekKU Campuhan Ubud is a 24-hour pharmacy.", ["Apotek Adapotek Mas"]) != []
    assert _unlisted_pharmacies("Apotek Adapotek Mas is close by.", ["Apotek Adapotek Mas"]) == []
    assert pharmacy_mentions("Ask the hotel for the nearest pharmacy.") == []


def test_health_rejects_unlisted_pharmacy_and_prompt_lists_them():
    from datetime import datetime as dt
    from src.aigv2.models import Place
    from src.aigv2.planning.important_places import NearbyPlace
    imp = _important()
    pl = Place(query="a", place_id="p", name="Apotek Adapotek Mas", address="Jl. Mas", lat=1, lng=2, status="OPERATIONAL",
               maps_url="u", fetched_at=dt(2026, 1, 1), match_ok=True)
    imp[0].pharmacies = [NearbyPlace(place=pl, walk_min=5, hours_text="Open 24 hours")]
    bad = sec([{"heading": "Pharmacy", "body": "ApotekKU Campuhan Ubud is a 24-hour pharmacy."}])
    good = sec([{"heading": "Pharmacy", "body": "Apotek Adapotek Mas is a short walk away."}])
    llm, calls = make(bad, good)
    s = write_section("health", [{"city": "Paris", "country": "France"}], {}, trip(), llm, important=imp)
    assert "Adapotek" in s.items[0].body and len(calls) == 2
    assert "Name only these pharmacies" in calls[0][1]["messages"][-1]["content"]


# ---- tolerant medical-name matching and never failing the build on it

SANUR = ["Apotek Kimia Farma Danau Poso",
         "ApotekKU Sanur - 24/7 Pharmacy Bali - Online Med Delivery Service & IV Drips"]


def test_listed_pharmacy_with_city_words_is_accepted():
    from src.aigv2.writing.sections import _unlisted_pharmacies
    c = ("Sanur", "Ubud")
    assert _unlisted_pharmacies("Visit Sanur ApotekKU Sanur, open 24 hours.", SANUR, c) == []
    assert _unlisted_pharmacies("ApotekKU Sanur is close.", SANUR, c) == []
    assert _unlisted_pharmacies("Apotek Kimia Farma is nearby.", SANUR, c) == []
    assert _unlisted_pharmacies("Try ApotekKU Campuhan Ubud.", SANUR, c) != [] and "Campuhan" in _unlisted_pharmacies("Try ApotekKU Campuhan Ubud.", SANUR, c)[0]
    assert _unlisted_pharmacies("Any local pharmacy in Sanur can help.", SANUR, c) == []


def test_unlisted_medical_name_is_sanitised_after_retries_not_raised():
    from datetime import datetime as dt
    from src.aigv2.models import Place
    from src.aigv2.planning.important_places import NearbyPlace
    imp = _important()
    pl = Place(query="a", place_id="p", name="ApotekKU Sanur - 24/7 Pharmacy Bali", address="Jl", lat=1, lng=2,
               status="OPERATIONAL", maps_url="u", fetched_at=dt(2026, 1, 1), match_ok=True)
    imp[0].city = "Sanur"
    imp[0].pharmacies = [NearbyPlace(place=pl, walk_min=5, hours_text="Open 24 hours")]
    bad = sec([{"heading": "Pharmacy in Sanur",
                "body": "Pick up basics at ApotekKU Campuhan Ubud. Ask your hotel about the nearest pharmacy."}])
    llm, calls = make(bad, bad)
    s = write_section("health", [{"city": "Sanur", "country": "France"}], {}, trip(), llm, important=imp)
    assert len(calls) == 2
    assert "Campuhan" not in s.items[0].body and "nearest pharmacy" in s.items[0].body and s.items[0].verify
    ok = sec([{"heading": "Pharmacy in Sanur", "body": "Sanur ApotekKU Sanur is open 24 hours."}])
    llm, calls = make(ok)
    s = write_section("health", [{"city": "Sanur", "country": "France"}], {}, trip(), llm, important=imp)
    assert len(calls) == 1 and "ApotekKU Sanur" in s.items[0].body


MD_BODY = ("Warm and humid.\n\n**Clothing**\n- Light outfits\n- Sleepwear\n\n**Beach & Island Days:**\n- Swimsuits\n"
           "* Dry bag\n\n**Mystery**\n- ignored\n\n**For your little one**\n• Diapers")


def _packing_trip(child=False):
    t = trip()
    if child:
        t.travellers = Traveller(adults=2, kids_ages=[2])
    return t


def test_markdown_packing_salvaged_into_groups():
    llm, _ = make(sec([{"heading": "Packing", "body": MD_BODY}]))
    s = write_section("packing", CITY, {}, _packing_trip(child=True), llm)
    assert len(llm.cost_log) == 1
    assert [g.title for g in s.groups] == ["Clothing", "Beach & Island Days", "For your little one"]
    assert [i.heading for i in s.groups[1].items] == ["Swimsuits", "Dry bag"]
    assert all("**" not in i.body and "- " not in i.body for i in s.items)


def test_markdown_title_tolerance_and_and():
    from src.aigv2.writing.sections import _SectionOut
    out = _SectionOut(items=[{"heading": "x", "body": "Sun and Day Trips:\n- Hat\n- Sunscreen"}])
    assert [g.title for g in out.groups] == ["Sun & Day Trips"] and not out.items


def test_markdown_in_other_section_is_rejected_then_retried():
    bad = sec([{"heading": "Cards", "body": "**Cards**\n- Visa accepted"}])
    good = sec([{"heading": "Cards", "body": "Visa is accepted."}])
    llm, calls = make([bad], [good])
    s = write_section("health", [{"city": "Paris", "country": "France"}], {}, trip(), llm)
    assert llm.cost_log[1]["fallback"] is True and s.items[0].body == "Visa is accepted."
    assert "no markdown" in calls[1][1]["messages"][1]["content"]


def test_packing_template_when_everything_fails():
    bad = sec([{"heading": "Packing", "body": "**Only prose** that is not groups, we pack"}])
    llm, _ = make(bad)
    t = _packing_trip(child=True)
    s = write_section("packing", CITY, {"France": {"plugs": [{"type": "E"}]}}, t, llm)
    titles = [g.title for g in s.groups]
    assert titles[0] == "Clothing" and titles[-1] == "For your little one"
    assert all("**" not in i.body for i in s.items) and all(i.verify for i in s.items)
    assert any("type E" in i.heading for g in s.groups for i in g.items)


def test_packing_template_no_child_group():
    llm, _ = make(sec([{"heading": "P", "body": "we **x**"}]))
    s = write_section("packing", CITY, {}, _packing_trip(), llm)
    assert "For your little one" not in [g.title for g in s.groups]


PROSE = [{"heading": h, "body": b} for h, b in [
    ("Clothing", "Light tops; a rain jacket; one layer. September is sunny."),
    ("Footwear", "Walking shoes; sandals"), ("Electronics", "Type C and Type F adapter; power bank"),
    ("Mystery", "Some lead text.")]]


def test_prose_items_salvaged_into_groups():
    from src.aigv2.writing.sections import _SectionOut
    out = _SectionOut(items=PROSE)
    assert [g.title for g in out.groups] == ["Clothing", "Footwear", "Electronics"]
    assert out.groups[0].items == ["Light tops", "a rain jacket", "one layer", "September is sunny"]
    assert [i.heading for i in out.items] == ["Mystery"]


def test_prose_items_split_on_sentences_and_cap():
    from src.aigv2.writing.sections import _SectionOut
    body = ". ".join(f"Thing {i}" for i in range(12)) + "."
    out = _SectionOut(items=[{"heading": h, "body": body} for h in ("Clothing", "Footwear", "Temple Visits")])
    assert len(out.groups[0].items) == 8


def test_two_prose_items_not_salvaged_and_packing_requires_groups():
    from src.aigv2.writing.sections import _SectionOut, _validator
    out = _SectionOut(items=PROSE[:2])
    assert not out.groups
    assert any("as groups" in p for p in _validator("packing", "", False, {})(out))


def test_prose_packing_end_to_end_gets_groups():
    llm, _ = make(sec(PROSE))
    s = write_section("packing", CITY, {}, trip(), llm)
    assert len(llm.cost_log) == 1 and [g.title for g in s.groups] == ["Clothing", "Footwear", "Electronics"]


def test_realistic_primary_groups_shape_accepted_for_toddler():
    titles = ["Clothing", "Footwear", "Beach & Island Days", "Sun & Day Trips", "Temple Visits", "Electronics",
              "Health & Comfort", "Travel Documents", "For your little one"]
    groups = [{"title": t, "items": ["Type C and Type F adapter", "Sunscreen SPF 50", "Passports valid 6 months"]} for t in titles]
    llm, _ = make({"items": [], "groups": groups})
    s = write_section("packing", CITY, {}, _packing_trip(child=True), llm)
    assert len(llm.cost_log) == 1 and len(s.groups) == 9
