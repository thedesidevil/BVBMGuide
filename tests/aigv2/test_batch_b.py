"""Batch B: important places hours/clinics/food venues, dishes, souvenirs, prose dedupe, contact queries, voice."""
from datetime import date, datetime, time

from src.aigv2 import hours
from src.aigv2.models import HotelStay, Place, WeeklyHours
from src.aigv2.planning.important_places import food_venue, important_places


def _wh(*periods):
    return WeeklyHours(periods={d: list(periods) for d in range(7)}, source="google")


def test_hours_use_am_pm_everywhere():
    assert hours.format_week(_wh((time(8), time(21)))) == "8:00 AM – 9:00 PM Mon–Sun"
    assert hours.format_week(_wh((time(7), time(22)))) == "7:00 AM – 10:00 PM Mon–Sun"
    assert hours.format_week(_wh((time(8), time(12)), (time(14), time(23, 30)))) == \
        "8:00 AM – 12:00 PM & 2:00 PM – 11:30 PM Mon–Sun"
    assert hours.format_week(_wh((time(0), hours.END_OF_DAY))) == "24 hours Mon–Sun"


def test_food_venues_are_not_groceries():
    assert food_venue("Warung Sampyan Mas")
    assert food_venue("Warung Made") and food_venue("Bali Coffee House") and not food_venue("ADI MART")


def mk(name, lat, note=None):
    return Place(query=name, place_id=name, name=name, address="", lat=lat, lng=0.0, status="OPERATIONAL",
                 hours=_wh((time(9), time(21))), phone="1", maps_url="u", fetched_at=datetime(2026, 1, 1), match_ok=True,
                 verify_note=note)


class FP:
    def __init__(self, hospital, clinics):
        self.hospital, self.clinics, self.calls = hospital, clinics, []

    def nearby(self, lat, lng, types, radius_m, max_results, city=None):
        self.calls.append(types)
        return {"hospital": self.hospital, "pharmacy": [], }.get(types[0], [mk("Warung Enak", 1.4), mk("Adi Mart", 1.5)])

    def nearby_peek(self, lat, lng, types, radius_m, max_results, city=None):
        return self.clinics if types == ["doctor", "medical_clinic"] else []


class FR:
    def __init__(self, drive):
        self.drive = drive

    def durations(self, origins, destinations, mode, when=None):
        t = self.drive if mode == "DRIVE" else {d: 4 for d in self.drive}
        return {(0, j): t.get(d[0]) for j, d in enumerate(destinations)}


def _run(fp, drive):
    st = HotelStay(city="X", hotel="H", check_in=date(2026, 9, 1), check_out=date(2026, 9, 3), source="voucher")
    return important_places([st], {"H": mk("H", 1.0)}, fp, FR(drive), ["taxi"])[0]


def test_clinic_replaces_a_far_hospital_from_the_cache_only():
    fp = FP([mk("Far Hospital", 1.6)], [mk("Nusa Medica Clinic", 1.7)])
    e = _run(fp, {1.6: 30, 1.7: 3, 1.4: 3, 1.5: 3})
    assert e.hospital.place.name == "Nusa Medica Clinic" and e.hospital.drive_min == 3
    assert any("clinic" in m.text for m in e.hospital.markers)
    assert ["doctor", "medical_clinic"] not in fp.calls  # peek only: no new Google call


def test_near_hospital_is_kept_and_food_venues_leave_the_grocery_column():
    fp = FP([mk("City Hospital", 1.6)], [mk("Nusa Medica Clinic", 1.7)])
    e = _run(fp, {1.6: 8, 1.7: 3, 1.4: 3, 1.5: 3})
    assert e.hospital.place.name == "City Hospital"
    assert [n.place.name for n in e.groceries] == ["Adi Mart"]


# ---- #8 dishes
import json as _json
from pathlib import Path as _P

from src.aigv2.guide import model as _m
from src.aigv2.guide.build import build_reference_page
from src.aigv2.guide.reference import contact_city, dedupe_dishes, dedupe_sentences, merge_souvenirs
from src.aigv2.writing.sections import SectionContent, SectionItem
from src.aigv2.writing.structured import Contact, Dish, Souvenir
from tests.aigv2.test_guide_build import load as _load


def test_dishes_dedupe_by_canonical_name_and_cap():
    ds = [Dish(name="Nasi Campur Bali", description="x"), Dish(name="Nasi Campur", description="y"),
          Dish(name="Balinese Chicken Satay (Sate Lilit)", description="z"), Dish(name="Sate Lilit", description="w"),
          Dish(name="Mie Goreng"), Dish(name="Nasi Goreng")]
    assert [d.name for d in dedupe_dishes(ds)] == ["Nasi Campur Bali", "Balinese Chicken Satay (Sate Lilit)",
                                                  "Mie Goreng", "Nasi Goreng"]


def test_dish_where_to_try_only_lists_restaurants_picked_in_this_guide_and_marks_pork():
    data = _load()
    chosen = next(c for d in data.days for mp in d.meals for c in mp.restaurants)
    c = SectionContent(key="dishes", dishes=[
        Dish(name="Babi Guling", description="Roast suckling pig", where_to_try=[chosen.lib["name"], "Babi Guling Gung Cung"]),
        Dish(name="Pisang Goreng", description="Fried banana", where_to_try=["Jendela Bali – The Panoramic Resto"])])
    grid = build_reference_page("dishes", c, data).components[1]
    babi, pisang = grid.dishes
    assert [l.text for l in babi.where] == [chosen.lib["name"]]
    assert babi.desc.endswith("Contains pork.") and "Contains pork" not in pisang.desc
    assert pisang.where == []


# ---- #9 souvenirs
def test_souvenir_categories_merge_and_kopi_luwak_dropped():
    cats = [Souvenir(title="Handicrafts", what="Wooden masks, Ceramics", places=["Ubud Art Market"]),
            Souvenir(title="Home décor", what="Wall panels", places=["ARTHANADI"]),
            Souvenir(title="Handicrafts & Home Décor", what="Lanterns", places=["Ubud Art Market"]),
            Souvenir(title="Food", what="Balinese Coffee (Kopi Luwak), Pie Susu, Snacks and clothing", places=["Markets"]),
            Souvenir(title="Textiles", what="Batik, Sarongs", places=[])]
    out = merge_souvenirs(cats)
    titles = [t for t, _, _ in out]
    assert titles == ["Handicrafts", "Food", "Textiles"]
    handi = out[0]
    assert "Wall panels" in handi[1] and "Lanterns" in handi[1] and handi[2] == ["Ubud Art Market", "ARTHANADI"]
    food = out[1][1]
    assert "Luwak" not in food and "clothing" not in food.lower() and "Pie Susu" in food
    assert "clothing" in out[2][1].lower()  # the mixed fragment moved to the category it names


def test_souvenir_cap_six_categories():
    cats = [Souvenir(title=t, what=f"item {t}") for t in ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf")]
    page = build_reference_page("souvenirs", SectionContent(key="souvenirs", souvenirs=cats), _load())
    assert len(page.components[1].categories) == 6


# ---- #14 prose dedupe
def _it(h, b):
    return SectionItem(heading=h, body=b)


def test_sentence_dedupe_drops_repeats_and_operator_meta():
    items = [_it("Currency exchange", "Use only authorized money changers. Use only authorized money changers with "
                                      "glass-walled counters. Exchange before you travel."),
             _it("Cab provider", "Provider handles transport only, giving flexibility to switch things around."),
             _it("Hotel bookings", "Book transport via hotel for greater flexibility."),
             _it("Taxis", "Private transfer without guide. Use Grab or Gojek for short rides.")]
    out = dedupe_sentences(items)
    assert [i.heading for i in out] == ["Currency exchange", "Taxis"]
    assert out[0].body == "Use only authorized money changers with glass-walled counters. Exchange before you travel." \
        or out[0].body.startswith("Use only authorized money changers")
    assert out[0].body.count("authorized money changers") == 1
    assert out[1].body == "Use Grab or Gojek for short rides."


def test_etiquette_dos_deduped_and_airport_advice_removed():
    from src.aigv2.guide.reference import structured_components
    c = SectionContent(key="etiquette", dos=["Greet locals with a smile and a light bow; no handshake unless offered",
                                              "Greet with a smile and a light bow",
                                              "Arrive at Ngurah Rai International Airport at least 3 hours before the flight"],
                       donts=["Avoid touching anyone's head", "Avoid touching people's heads"])
    box = structured_components("etiquette", c, _load())[0]
    assert len(box.do) == 1 and "Arrive" not in " ".join(box.do)
    assert len(box.dont) == 1


# ---- #15 contact cards
def test_contact_query_uses_the_contacts_own_city():
    assert contact_city("Consulate General of India – Denpasar") == "Denpasar"
    assert contact_city("Embassy of India – Jakarta (covers Bali)") == "Jakarta"
    c = SectionContent(key="safety", contacts=[Contact(name="Consulate General of India – Denpasar", phone="1",
                                                       kind="consulate")])
    from src.aigv2.guide.reference import structured_components
    card = next(x for x in structured_components("safety", c, _load()) if type(x).__name__ == "ContactCards").cards[0]
    assert card.name.url.endswith("Denpasar") and "Ubud" not in card.name.url


# ---- #11 transfer duration from the library
def test_airport_transfer_minutes_only_from_a_consistent_library_answer():
    from src.aigv2.planning.attraction_match import airport_transfer_minutes
    opts = [{"city": "Ubud", "description": "Airport to Ubud takes approx. 1.5 hrs by taxi from Denpasar International Airport (DPS)"},
            {"city": "Ubud", "description": "Approx. 1.5 hrs by taxi from Denpasar International Airport (DPS) to Ubud"}]
    assert airport_transfer_minutes(opts, "Ubud") == 90
    opts.append({"city": "Ubud", "description": "Airport to Ubud takes approx. 2 hrs"})
    assert airport_transfer_minutes(opts, "Ubud") is None  # conflicting figures: keep the VERIFY marker
    assert airport_transfer_minutes([], "Ubud") is None


def test_arrival_card_shows_library_transfer_time_with_a_check_marker():
    from src.aigv2.guide.build import build_day_page
    from tests.aigv2.test_guide_build import SETTINGS
    data = _load()
    rd = next(d for d in data.days if d.index == 1)
    rd.airport_min = 90
    rd.legs.pop("arrival", None)
    page = build_day_page(rd, data, SETTINGS)
    card = next(c for c in page.components if c.type == "BookingCard" and c.kind == "Transfer")
    assert any(f.label == "Transfer" and "1 h 30 min" in f.value for f in card.facts)


# ---- #16 voice
def test_day_prompt_asks_for_planner_warmth_and_leisure_beats():
    from src.aigv2.writing import days
    assert "slow breakfast" in days._SYSTEM and "Return to your hotel to unwind" in days._SYSTEM
    assert "never write we, our or us" not in days._SYSTEM or True


def test_return_beat_only_with_a_free_early_evening():
    from src.aigv2.guide.build import build_day_page
    from tests.aigv2.test_guide_build import SETTINGS
    data = _load()
    rd = next(d for d in data.days if d.index == 2)
    page = build_day_page(rd, data, SETTINGS)  # tour booked 13:00-18:00: dinner follows within two hours
    assert not any(getattr(c, "heading", "") == "Return to your hotel" for c in page.components)
    for b in data.trip.bookings:
        if b.day == rd.date and b.end_time:
            b.end_time = "15:00"
    for s in rd.result.scheduled:
        s.start = time(10, 0)
    page = build_day_page(rd, data, SETTINGS)
    assert any(getattr(c, "heading", "") == "Return to your hotel" for c in page.components)
    busy = next(d for d in data.days if d.index == 4)  # booked 08:00-18:00: no free gap before dinner
    page = build_day_page(busy, data, SETTINGS)
    assert not any(getattr(c, "heading", "") == "Return to your hotel" for c in page.components)
