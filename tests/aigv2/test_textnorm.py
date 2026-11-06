import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.aigv2.google.places import PlacesClient, _overlap, _simplified_names
from src.aigv2.library import Library, norm_name
from src.aigv2.models import Place, place_key
from src.aigv2.store import PlaceCache
from src.aigv2.textnorm import fold, fold_key, has_accents, strip_accents
from src.aigv2.writing.sections import _unlisted_hospitals, _unlisted_pharmacies
from src.aigv2.writing.structured import _same_dish
from src.library.ui.storage import LocalStorageBackend
from tests.aigv2.test_places import FakeSession, gp


@pytest.mark.parametrize("a,b", [
    ("Zürich", "zurich"), ("Café", "cafe"), ("Trümmelbach", "trummelbach"), ("Straße", "strasse"),
    ("Łódź", "lodz"), ("Ørsted", "orsted"), ("Mill’Feuille", "Mill'Feuille"), ("Chez L’Ami Jean", "chez l'ami jean"),
    ("Hôtel  Baren", "Hotel Baren"), ("A B", "a b"), ("Rock – Roll", "rock - roll"), ("Æther Œuvre", "aether oeuvre"),
])
def test_fold_examples(a, b):
    assert fold(a) == fold(b) == b.casefold().replace("’", "'")


def test_fold_misc():
    assert fold("") == "" and fold(None) == ""
    assert has_accents("Café") and not has_accents("Cafe") and not has_accents("Joe’s")
    assert strip_accents("Café de Flore") == "Cafe de Flore"
    assert fold_key("Café | Zürich") == "cafe|zurich"


def test_norm_name_and_pkey_fold():
    assert norm_name("Hôtel Baren") == norm_name("hotel  baren")
    assert place_key("Café de Flore", "Zürich") == place_key("Cafe de Flore", "Zurich")


def test_library_city_lookup_across_accents(tmp_path):
    (tmp_path / "Zürich.json").write_text(json.dumps({"restaurants": [{"name": "Café Sprüngli"}]}), encoding="utf-8")
    (tmp_path / "_index.json").write_text(json.dumps({"_folder_coverage": {"Switzerland": ["Zürich"]}}), encoding="utf-8")
    lib = Library(tmp_path)
    for q in ("Zürich", "Zurich", "ZURICH"):
        got = lib.restaurants(q)
        assert [r["name"] for r in got] == ["Café Sprüngli"]  # display name keeps its accent
    assert norm_name("Cafe Sprungli") == norm_name(got[0]["name"])


def test_where_to_try_and_dish_matching_fold():
    allowed = {norm_name(n): n for n in ["Café Sprüngli", "Chez L’Ami Jean"]}
    assert norm_name("Cafe Sprungli") in allowed and norm_name("Chez L'Ami Jean") in allowed
    assert allowed[norm_name("cafe sprungli")] == "Café Sprüngli"
    assert _same_dish("Crème brûlée", "Creme brulee")


def test_hospital_and_pharmacy_matching():
    assert _unlisted_hospitals("Hôpital Cantonal is open 24/7", ["Hopital Cantonal"]) == []
    assert _unlisted_pharmacies("Apotheke Bahnhof Zürich", ["Apotheke Bahnhof Zurich"], ("Zurich",)) == []


def test_google_candidate_matching_folds():
    assert _overlap("Hotel Baren", "Hôtel Bären") == 1.0


def test_simplified_names_accent_variant_keeps_total():
    out = _simplified_names("Café de Flore (Paris tour experience)")
    assert out[0] == "Cafe de Flore" and len(out) <= 3
    assert _simplified_names("Cafe de Flore (x)") == ["Cafe de Flore"]  # no accents -> no accent variant
    assert len(_simplified_names("Café de Flore")) == 1 and _simplified_names("Café de Flore") == ["Cafe de Flore"]


def _place():
    return Place(query="q", place_id="p", name="Café", address="a", lat=1, lng=2, status="OPERATIONAL",
                 maps_url="u", fetched_at=datetime.now(timezone.utc), match_ok=True)


def test_place_cache_accent_variants_share_and_legacy_read(tmp_path):
    b = LocalStorageBackend(tmp_path)
    cache = PlaceCache(b, 30)
    cache.put("Café de Flore|Paris", _place())
    assert cache.get("Cafe de Flore|PARIS") is not None
    # an entry written under the old (raw sha1) key still hits
    legacy = f"cache/places/{hashlib.sha1('Zürich Hotel|Zürich'.encode()).hexdigest()}.json"
    b.write_json(legacy, _place().model_dump(mode="json"))
    assert cache.get("Zürich Hotel|Zürich") is not None
    assert cache.get("Other|Zürich") is None


def _client(tmp_path, *payloads, days=7):
    s = FakeSession(*payloads)
    cache = PlaceCache(LocalStorageBackend(tmp_path), 30, days)
    return PlacesClient("K", cache, session=s), s, cache


def test_hotel_match_across_accents(tmp_path):
    c, s, _ = _client(tmp_path, {"places": [gp("Hôtel Bären", addr="Interlaken, Switzerland")]})
    p = c.find("Hotel Baren", "Interlaken")
    assert p is not None and p.match_ok and p.name == "Hôtel Bären"


def test_no_match_cached_then_zero_http(tmp_path):
    c, s, _ = _client(tmp_path, {})
    assert c.find("Nothing Here", "Istanbul") is None
    n = len(s.posts)
    assert n >= 1
    assert c.find("Nothing Here", "Istanbul") is None
    assert len(s.posts) == n
    assert c.find("Nöthing Hére", "Istanbul") is None  # accent variant shares the entry
    assert len(s.posts) == n


def test_rejected_candidates_cached_as_no_match(tmp_path):
    c, s, _ = _client(tmp_path, {"places": [gp("Totally Different", addr="Paris, France")]})
    p = c.find("Blue Mosque Cafe", "Istanbul")
    assert p is not None and not p.match_ok  # a rejected candidate is still returned, positive cache path unchanged


def test_error_not_cached(tmp_path):
    class Boom(FakeSession):
        def post(self, *a, **k):
            raise ConnectionError("down")
    s = Boom({})
    cache = PlaceCache(LocalStorageBackend(tmp_path), 30)
    c = PlacesClient("K", cache, session=s)
    with pytest.raises(ConnectionError):
        c.find("Nothing", "Istanbul")
    assert not cache.is_no_match("Nothing|Istanbul")


def test_negative_entry_expires_after_days(tmp_path):
    c, s, cache = _client(tmp_path, {})
    c.find("Nothing", "Istanbul")
    assert cache.is_no_match("Nothing|Istanbul")
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    cache.backend.write_json(cache._neg_key("Nothing|Istanbul"), {"no_match": True, "fetched_at": old})
    assert not cache.is_no_match("Nothing|Istanbul")
    n = len(s.posts)
    c.find("Nothing", "Istanbul")
    assert len(s.posts) > n


def test_positive_cache_untouched_and_settings_knob(tmp_path):
    from src.aigv2.config import Settings
    assert Settings(models={}).negative_cache_days == 7
    c, s, cache = _client(tmp_path, {"places": [gp("Blue Mosque", addr="Istanbul, Turkiye")]})
    assert c.find("Blue Mosque", "Istanbul").name == "Blue Mosque"
    assert not cache.is_no_match("Blue Mosque|Istanbul")
    n = len(s.posts)
    c.find("Blue Mosque", "Istanbul")
    assert len(s.posts) == n
