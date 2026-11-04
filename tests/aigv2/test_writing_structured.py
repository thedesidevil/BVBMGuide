import pytest

from src.aigv2.llm import LLMStepError
from src.aigv2.models import Diet, Traveller
from src.aigv2.writing.sections import SectionContent, write_section
from tests.aigv2.test_writing import make, sec, trip


def _g(*titles):
    return {"items": [{"heading": "x", "body": "y"}],
            "groups": [{"title": t, "items": ["Light layers", "Sandals", "Hat"]} for t in titles]}


def _pack(reply, ages=(), sol=None):
    llm, _ = make(reply, sol)
    t = trip()
    t.travellers = Traveller(adults=2, kids_ages=list(ages))
    return write_section("packing", [{"city": "Paris", "country": "France"}], {}, t, llm), llm


def test_packing_groups_in_order_and_items_flattened():
    s, _ = _pack(_g("Footwear", "Clothing", "Electronics"))
    assert [g.title for g in s.groups] == ["Clothing", "Footwear", "Electronics"]
    assert s.items[0].heading == "Clothing" and s.items[0].body == "Light layers, Sandals, Hat"
    assert s.groups[0].items[0].heading == "Light layers"


@pytest.mark.parametrize("age,expect", [(11, True), (12, False)])
def test_little_one_group_iff_child_under_12(age, expect):
    with_child = _g("Clothing", "For your little one")
    without = _g("Clothing")
    good, bad = (with_child, without) if expect else (without, with_child)
    s, llm = _pack([bad, good], [age])
    assert ("For your little one" in [g.title for g in s.groups]) is expect
    assert len(llm.cost_log) == 2


def test_unknown_group_title_rejected():
    s, llm = _pack([_g("Gadgets"), _g("Clothing")])
    assert [g.title for g in s.groups] == ["Clothing"]
    with pytest.raises(LLMStepError):
        _pack(_g("Gadgets"))


def test_packing_group_with_price_rejected():
    bad = {"items": [], "groups": [{"title": "Clothing", "items": ["Buy Airalo eSIM"]}]}
    s, _ = _pack([bad, _g("Clothing")])
    assert s.groups[0].items[0].heading == "Light layers"


def test_defaults_empty_elsewhere():
    llm, _ = make(sec([{"heading": "Cards", "body": "ok"}]))
    s = write_section("health", [{"city": "Paris", "country": "France"}], {}, trip(), llm)
    for f in ("groups", "apps", "phrases", "dos", "donts", "numbers", "contacts", "dishes", "souvenirs"):
        assert getattr(s, f) == []
    assert isinstance(s, SectionContent)


def _run(key, cities, cdata, t=None, places=None):
    llm, _ = make(sec([{"heading": "h", "body": "b"}]))
    return write_section(key, cities, cdata, t or trip(), llm, places=places)


def test_safety_numbers_and_contacts():
    cdata = {"Indonesia": {"emergency_contacts": [
        {"service": "Police", "number": "+62 110"}, {"service": "Ambulance", "number": "+62 118 / 119"},
        {"service": "Hotel concierge", "number": "+62 999"}, {"service": "Tourist Police", "number": "+62 361 224111"}],
        "embassies": [{"name": "Consulate General of India – Denpasar", "phone": "+62 361 259502", "city": "Denpasar"},
                      {"name": "US Embassy Jakarta", "phone": "+62 21 1"}]}}
    s = _run("safety", [{"city": "Ubud", "country": "Indonesia"}], cdata)
    assert [(n.service, n.number) for n in s.numbers] == [("Police", "+62 110"), ("Ambulance", "+62 118 / 119")]
    names = [c.name for c in s.contacts]
    assert "Tourist Police" in names and any("India" in n for n in names)
    assert not any("US Embassy" in n for n in names)
    assert next(c for c in s.contacts if "India" in c.name).kind == "consulate"


def test_etiquette_phrases_dedup_cap_and_dos_donts():
    ph = [{"english": f"E{i}", "local": f"L{i % 15}"} for i in range(30)]
    tips = [{"tip": "Remove shoes at temples"}, {"tip": "Don't point your feet"}, {"tip": "remove shoes at temples"},
            {"tip": "Never touch heads"}, {"tip": "Avoid public displays"}, {"tip": "No shorts in temples"},
            {"tip": "Do not litter"}, {"tip": "Smile"}]
    s = _run("etiquette", [{"city": "Ubud", "country": "Indonesia", "phrases": ph[:3]}],
             {"Indonesia": {"phrases": ph, "dos_donts": tips}})
    locs = [p.local for p in s.phrases]
    assert len(locs) == len(set(locs)) == 12
    assert s.dos == ["Remove shoes at temples", "Smile"]
    assert len(s.donts) == 5 and s.donts[0] == "Don't point your feet"


def test_connectivity_apps():
    s = _run("connectivity", [{"city": "Ubud", "country": "Indonesia"}],
             {"Indonesia": {"apps": [{"name": "Grab", "purpose": "Rides"}]}})
    assert [(a.name, a.purpose) for a in s.apps] == [("Grab", "Rides")]


def _dish_cities(restaurants):
    return [{"city": "Ubud", "country": "Indonesia", "local_dishes": [{"name": "Nasi Ayam", "description": "Rice"}],
             "restaurants": restaurants}]


def test_dishes_where_to_try_only_allowed_restaurants():
    r = [{"name": "Warung A", "must_try_dishes": ["Nasi Ayam Bali"]}, {"name": "Warung B", "must_try_dishes": ["Satay"]}]
    s = _run("dishes", _dish_cities(r), {})
    assert s.dishes[0].where_to_try == ["Warung A"] and s.dishes[0].description == "Rice"
    s = _run("dishes", _dish_cities([r[1]]), {})
    assert s.dishes[0].where_to_try == []


def test_dishes_respect_diet():
    t = trip()
    t.diet = Diet(restrictions=["vegan"])
    r = [{"name": "Meat House", "must_try_dishes": ["Nasi Ayam"]}]
    assert _run("dishes", _dish_cities(r), {}, t).dishes[0].where_to_try == []


def test_souvenirs_grouped_by_category():
    sv = [{"item": "Batik", "category": "Textiles", "where_to_buy": ["Market"]},
          {"item": "Ikat", "category": "Textiles", "where_to_buy": ["Market", "Shop"]},
          {"item": "Coffee", "category": "Food", "where_to_buy": ["Farm"]}]
    s = _run("souvenirs", [{"city": "Ubud", "country": "Indonesia", "souvenirs": sv}], {})
    assert [(x.title, x.what, x.places) for x in s.souvenirs] == [
        ("Textiles", "Batik, Ikat", ["Market", "Shop"]), ("Food", "Coffee", ["Farm"])]


@pytest.mark.parametrize("dish,entry,expect", [
    ("Nasi", "Nasi Goreng", False), ("Nasi Goreng", "Nasi Goreng (with egg)", True),
    ("Nasi Goreng", "Chicken Nasi Goreng", True), ("rice", "price", False), ("rice", "Rice", True),
    ("Sate Lilit", "Sate Lilit", True), ("Nasi Goreng", "Nasi Campur", False)])
def test_dish_matching_whole_words(dish, entry, expect):
    cities = [{"city": "Ubud", "country": "Indonesia", "local_dishes": [{"name": dish}],
               "restaurants": [{"name": "W", "must_try_dishes": [entry]}]}]
    assert bool(_run("dishes", cities, {}).dishes[0].where_to_try) is expect


def test_curly_apostrophe_dont_goes_to_donts():
    s = _run("etiquette", [{"city": "Ubud", "country": "Indonesia"}],
             {"Indonesia": {"dos_donts": [{"tip": "Don’t point your feet"}, {"tip": "Smile"}]}})
    assert s.donts == ["Don’t point your feet"] and s.dos == ["Smile"]


def test_old_saved_section_json_loads():
    s = SectionContent.model_validate({"key": "safety", "items": [{"heading": "h", "body": "b"}], "from_library": True})
    assert s.numbers == [] and s.groups == [] and s.dishes == []


def test_multi_country_merge_documents_current_dedup():
    cities = [{"city": "Ubud", "country": "Indonesia"}, {"city": "Hanoi", "country": "Vietnam"}]
    cd = {"Indonesia": {"apps": [{"name": "Grab", "purpose": "A"}]}, "Vietnam": {"apps": [{"name": "Grab", "purpose": "A"}, {"name": "Be", "purpose": "B"}]}}
    s = _run("connectivity", cities, cd)
    assert [a.name for a in s.apps] == ["Grab", "Be"]
