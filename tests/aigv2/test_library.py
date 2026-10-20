import json
import os

import pytest

from src.aigv2.library import Library, diet_fits, is_indian
from src.aigv2.models import Diet


def _r(name, cuisine=None, veg=None, **kw):
    r = {"name": name, "cuisine_type": cuisine or []}
    if veg is not None:
        r["vegetarian_friendly"] = veg
    r.update(kw)
    return r


def _write(path, data):
    path.write_text(json.dumps(data))


@pytest.fixture
def lib_dir(tmp_path):
    _write(tmp_path / "_index.json", {
        "_folder_coverage": {
            "USA": ["New York", "New York City"],
            "Bali Indonesia": ["Bali", "Ubud", "Sanur"],
        },
    })
    _write(tmp_path / "New York.json", {
        "restaurants": [_r("Joe's"), _r("Vatan", ["Gujarati"])],
        "attractions": [{"name": "Met"}],
    })
    _write(tmp_path / "New York City.json", {
        "restaurants": [_r("JOE'S"), _r("Katz")],
    })
    _write(tmp_path / "Ubud.json", {"restaurants": [_r("Locavore")]})
    _write(tmp_path / "Bali.json", {"restaurants": [_r("Warung Bali"), _r("Locavore")]})
    _write(tmp_path / "Engelberg.json", {"restaurants": [_r("Alp Hut")]})
    (tmp_path / "_country").mkdir()
    _write(tmp_path / "_country" / "Bali Indonesia.json", {"safety_tips": [{"tip": "x"}]})
    return tmp_path


def test_city_aliases_merge(lib_dir):
    lib = Library(lib_dir)
    names = [r["name"] for r in lib.restaurants("New York")]
    assert len(names) == 3
    assert len(lib.restaurants("NYC")) == 3
    assert lib.has_data("New York City")
    assert not lib.has_data("Nowhere")


def test_region_shard_merged(lib_dir):
    lib = Library(lib_dir)
    names = sorted(r["name"] for r in lib.restaurants("Ubud"))
    assert names == ["Locavore", "Warung Bali"]


def test_country_via_folder(lib_dir):
    lib = Library(lib_dir)
    assert lib.country("Bali Indonesia")["safety_tips"]
    assert lib.country("Ubud")["safety_tips"]
    assert lib.country("Atlantis") == {}


def test_restaurants_near_locality(lib_dir):
    assert [r["name"] for r in Library(lib_dir).restaurants_near("Engelberg")] == ["Alp Hut"]
    assert Library(lib_dir).restaurants_near("Nope") == []


def test_library_files_unchanged(lib_dir):
    files = [p for p in lib_dir.rglob("*.json")]
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in files}
    lib = Library(lib_dir)
    lib.city("New York"); lib.country("Bali Indonesia"); lib.restaurants("Ubud")
    lib.restaurants_near("Engelberg"); lib.has_data("x")
    assert {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in files} == before
    assert not hasattr(lib, "save") and not hasattr(lib, "write")


def test_diet_no_restrictions_all_fit():
    assert diet_fits(_r("X"), Diet())


def test_vegetarian_requires_flag_or_cuisine():
    d = Diet(restrictions=["vegetarian"])
    assert diet_fits(_r("A", veg=True), d)
    assert diet_fits(_r("B", ["Vegan"]), d)
    assert not diet_fits(_r("C", ["Steakhouse"]), d)
    assert not diet_fits(_r("D", ["Steakhouse"], veg=False), d)


def test_gujarati_fits_vegetarian():
    d = Diet(restrictions=["vegetarian"])
    assert diet_fits(_r("Vatan", ["Gujarati"]), d)
    assert diet_fits(_r("Udupi Cafe", ["South Indian"]), d)
    assert is_indian(_r("X", ["Punjabi"]))
    assert not is_indian(_r("X", ["Italian"]))


def test_pure_veg_requires_explicit():
    d = Diet(restrictions=["vegetarian"], pure_veg=True)
    assert not diet_fits(_r("Vatan", ["Gujarati"]), d)
    assert not diet_fits(_r("Veg-ish", ["Indian"], veg=True), d)
    assert diet_fits(_r("Pure Veg Thali", ["Indian"], veg=True, highlights=["Pure veg thali"]), d)
    assert diet_fits(_r("Saffron", ["Indian"], veg=True, highlights=["Vegetarian-only menu"]), d)


def test_japanese_needs_explicit_veg():
    d = Diet(restrictions=["vegetarian"])
    assert not diet_fits(_r("Sushi Go", ["Japanese"], veg=True), d)
    assert diet_fits(_r("Sushi Go", ["Japanese"], veg=True, highlights=["Vegetarian ramen without fish stock"]), d)
    assert diet_fits(_r("Shojin", ["Japanese", "Vegan"]), d)
    assert not diet_fits(_r("Seoul BBQ", ["Korean"], veg=True), d)


def test_no_beef_unknown_excluded():
    assert not diet_fits(_r("Vatan", ["Gujarati"], veg=True), Diet(restrictions=["no beef"]))


def test_halal_mention_fits_no_pork():
    d = Diet(restrictions=["no pork"])
    assert diet_fits(_r("Kebab", highlights=["Halal grill"]), d)
    assert not diet_fits(_r("Kebab", highlights=["Grill"]), d)
    assert diet_fits(_r("Y", must_try_dishes=["no beef curry"]), Diet(restrictions=["no beef"]))
    assert diet_fits(_r("Z", notes="nut-free kitchen"), Diet(allergies=["nut allergy"]))
