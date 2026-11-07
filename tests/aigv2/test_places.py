from datetime import timedelta
import json

from src.aigv2.google.places import PlacesClient, weak_coverage
from src.aigv2.store import PlaceCache
from src.library.ui.storage import LocalStorageBackend


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.posts = []
        self.gets = []

    def get(self, url, headers=None, timeout=None):
        self.gets.append((url, headers))
        return FakeResp(self.payloads.pop(0) if len(self.payloads) > 1 else self.payloads[0])

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append((url, headers, json))
        return FakeResp(self.payloads.pop(0) if len(self.payloads) > 1 else self.payloads[0])


def gp(name, addr="Beyoglu, Istanbul, Turkiye", pid="pid1", ptype="restaurant", lat=41.03, lng=28.97, **kw):
    d = {
        "id": pid,
        "displayName": {"text": name},
        "formattedAddress": addr,
        "location": {"latitude": lat, "longitude": lng},
        "businessStatus": "OPERATIONAL",
        "websiteUri": "https://x.example",
        "internationalPhoneNumber": "+90 212 000 0000",
        "primaryType": ptype,
        "types": [ptype],
    }
    d.update(kw)
    return d


def client(tmp_path, *payloads):
    sess = FakeSession(*payloads)
    cache = PlaceCache(LocalStorageBackend(tmp_path), 30)
    return PlacesClient("KEY", cache, session=sess), sess


def test_find_parses_place(tmp_path):
    roh = {"periods": [{"open": {"day": 1, "hour": 9, "minute": 0}, "close": {"day": 1, "hour": 17, "minute": 0}}]}
    c, s = client(tmp_path, {"places": [gp("Seher Restaurant", regularOpeningHours=roh)]})
    p = c.find("Seher Restaurant", "Istanbul")
    assert p.match_ok and p.place_id == "pid1" and p.status == "OPERATIONAL"
    assert p.phone == "+90 212 000 0000" and p.website == "https://x.example"
    assert p.hours is not None and p.lat == 41.03
    assert "query_place_id=pid1" in p.maps_url and "utm_" not in p.maps_url
    assert "Seher+Restaurant+Istanbul" in p.maps_url
    url, headers, body = s.posts[0]
    assert url.endswith("places:searchText") and headers["X-Goog-Api-Key"] == "KEY"
    assert "places.primaryType" in headers["X-Goog-FieldMask"]
    assert body == {"textQuery": "Seher Restaurant, Istanbul", "languageCode": "en"}


def test_malformed_hours_become_none(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Seher Restaurant", regularOpeningHours={"periods": []})]})
    assert c.find("Seher Restaurant", "Istanbul").hours is None


def test_find_uses_cache(tmp_path):
    c, s = client(tmp_path, {"places": [gp("Seher Restaurant")]})
    c.find("Seher Restaurant", "Istanbul")
    c.find("Seher Restaurant", "Istanbul")
    assert c.calls["text_search"] == 1 and len(s.posts) == 1
    c.find("Seher Restaurant", "Istanbul", fresh=True)
    assert c.calls["text_search"] == 2


def test_wrong_city_match_rejected(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Joe's Pizza", addr="1 Main St, Chicago, IL, USA")]})
    assert c.find("Joe's Pizza", "New York").match_ok is False


def test_chain_name_mismatch_rejected(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Seher Kuaför")]})
    assert c.find("Seher Restaurant", "Istanbul").match_ok is False


def test_near_allows_address_without_city(tmp_path):
    c, s = client(tmp_path, {"places": [gp("Seher Restaurant", addr="Some Street 5")]})
    p = c.find("Seher Restaurant", "Istanbul", near=(41.03, 28.98))
    assert p.match_ok
    assert s.posts[0][2]["locationBias"]["circle"]["radius"] == 20000.0


def test_no_results_returns_none(tmp_path):
    c, _ = client(tmp_path, {})
    assert c.find("Nothing", "Istanbul") is None


def test_picks_matching_candidate(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Seher Kuaför", pid="a"), gp("Seher Restaurant", pid="b")]})
    p = c.find("Seher Restaurant", "Istanbul")
    assert p.place_id == "b" and p.match_ok


def test_nearby_request_body(tmp_path):
    c, s = client(tmp_path, {"places": [gp("City Pharmacy", ptype="pharmacy")]})
    out = c.nearby(41.0, 29.0, ["pharmacy"], 1500, 5)
    url, _, body = s.posts[0]
    assert url.endswith("places:searchNearby")
    assert body["includedTypes"] == ["pharmacy"] and body["maxResultCount"] == 5
    assert body["locationRestriction"]["circle"] == {"center": {"latitude": 41.0, "longitude": 29.0}, "radius": 1500.0}
    assert c.calls["nearby"] == 1 and len(out) == 1 and out[0].match_ok


def test_steroid_shop_not_pharmacy(tmp_path):
    c, _ = client(tmp_path, {"places": [
        gp("Anabolic Sports Cosmetic Shop", ptype="store", pid="a"),
        gp("Eczane Sports Pharmacy", ptype="pharmacy", pid="b"),
        gp("Merkez Eczanesi", ptype="pharmacy", pid="c"),
    ]})
    out = c.nearby(41.0, 29.0, ["pharmacy"], 1500, 5)
    assert [p.place_id for p in out] == ["c"]


def test_equipment_firm_not_hospital(tmp_path):
    c, _ = client(tmp_path, {"places": [
        gp("Medical Equipment B.V.", ptype="hospital", pid="a"),
        gp("Dental Hospital", ptype="hospital", pid="b"),
        gp("General Hospital", ptype="hospital", pid="c", lat=41.001, lng=29.0),
    ]})
    out = c.nearby(41.0, 29.0, ["hospital"], 5000, 5)
    assert [p.place_id for p in out] == ["c"]


def test_hospital_prefers_emergency(tmp_path):
    c, _ = client(tmp_path, {"places": [
        gp("Town Hospital", ptype="hospital", pid="a", lat=41.001, lng=29.0),
        gp("City Emergency Hospital", ptype="hospital", pid="b", lat=41.005, lng=29.0),
    ]})
    out = c.nearby(41.0, 29.0, ["hospital"], 5000, 5)
    assert out[0].place_id == "b"


def test_hospital_falls_back_to_clinic(tmp_path):
    far = gp("Far Hospital", ptype="hospital", pid="far", lat=41.5, lng=29.0)
    clinic = gp("Island Clinic", ptype="medical_clinic", pid="cl", lat=41.001, lng=29.0)
    c, s = client(tmp_path, {"places": [far]}, {"places": [clinic]})
    out = c.nearby(41.0, 29.0, ["hospital"], 20000, 3)
    assert [p.place_id for p in out] == ["cl"]
    assert s.posts[1][2]["includedTypes"] == ["doctor", "medical_clinic"]
    assert out[0].verify_note == "nearest clinic, not a hospital"
    assert c.calls["nearby"] == 2


def test_weak_coverage():
    assert weak_coverage("Seoul, South Korea") and weak_coverage("South Korea") and weak_coverage("Seoul") and weak_coverage("China")
    assert not weak_coverage("Istanbul")


def _roh(open_h, close_h):
    return {"periods": [
        {"open": {"day": d, "hour": open_h, "minute": 0}, "close": {"day": d, "hour": close_h, "minute": 0}}
        for d in range(7)
    ]}


def test_city_match_is_word_bounded(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Seher Restaurant", addr="Via Roma 1, Venice, Italy")]})
    assert c.find("Seher Restaurant", "Nice").match_ok is False
    c2, _ = client(tmp_path / "b", {"places": [gp("Joe's Pizza", addr="1 Broadway, New York, NY 10001")]})
    assert c2.find("Joe's Pizza", "New York").match_ok is True


def test_weak_coverage_note_on_find_and_nearby(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Seher Restaurant", addr="Gangnam, Seoul, South Korea")]})
    assert c.find("Seher Restaurant", "Seoul").verify_note == "Google coverage is limited here — verify details"
    c2, _ = client(tmp_path / "b", {"places": [gp("Merkez Pharmacy", ptype="pharmacy")]})
    out = c2.nearby(37.5, 127.0, ["pharmacy"], 1000, 3, city="Seoul, South Korea")
    assert out[0].verify_note == "Google coverage is limited here — verify details"
    c3, _ = client(tmp_path / "c", {"places": [gp("Seher Restaurant")]})
    assert c3.find("Seher Restaurant", "Istanbul").verify_note is None


def test_hospital_unknown_hours_note(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Town Hospital", ptype="hospital", lat=41.001, lng=29.0)]})
    out = c.nearby(41.0, 29.0, ["hospital"], 5000, 3)
    assert out[0].verify_note == "check this hospital has 24-hour emergency care"


def test_hospital_24h_filter(tmp_path):
    c, _ = client(tmp_path, {"places": [
        gp("Day Hospital", ptype="hospital", pid="a", lat=41.001, lng=29.0, regularOpeningHours=_roh(9, 17)),
        gp("Round Clock Hospital", ptype="hospital", pid="b", lat=41.002, lng=29.0,
           regularOpeningHours={"periods": [{"open": {"day": 0, "hour": 0, "minute": 0}}]}),
    ]})
    out = c.nearby(41.0, 29.0, ["hospital"], 5000, 5)
    assert [p.place_id for p in out] == ["b"]


def test_filter_only_for_hospital_results(tmp_path):
    c, s = client(tmp_path, {"places": [
        gp("Day Pharmacy", ptype="pharmacy", pid="p", regularOpeningHours=_roh(9, 17)),
        gp("City Emergency Hospital", ptype="hospital", pid="h", lat=41.001, lng=29.0),
    ]})
    out = c.nearby(41.0, 29.0, ["hospital", "pharmacy"], 5000, 5)
    assert {p.place_id for p in out} == {"p", "h"}
    assert s.posts[0][2]["languageCode"] == "en"


def test_search_text_language_code(tmp_path):
    c, s = client(tmp_path, {"places": [gp("Seher Restaurant")]})
    c.find("Seher Restaurant", "Istanbul")
    assert s.posts[0][2]["languageCode"] == "en"


def test_website_tracking_params_stripped(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Seher Restaurant",
                                            websiteUri="https://x.example/menu?utm_source=gmb&ref=7&UTM_medium=maps")]})
    assert c.find("Seher Restaurant", "Istanbul").website == "https://x.example/menu?ref=7"
    c2, _ = client(tmp_path / "b", {"places": [gp("Seher Restaurant", websiteUri="https://x.example/?utm_source=g")]})
    assert c2.find("Seher Restaurant", "Istanbul").website == "https://x.example/"
    c3, _ = client(tmp_path / "c", {"places": [gp("Seher Restaurant", websiteUri="https://x.example/a?q=a%20b")]})
    assert c3.find("Seher Restaurant", "Istanbul").website == "https://x.example/a?q=a%20b"


def test_fresh_status_uses_place_details_by_id(tmp_path):
    c, s = client(tmp_path, {"places": [gp("Seher Restaurant", pid="pidX")]},
                  {"businessStatus": "CLOSED_PERMANENTLY", "regularOpeningHours": _roh(9, 17)})
    cached = c.find("Seher Restaurant", "Istanbul")
    fresh = c.fresh_status(cached)
    url, headers = s.gets[0]
    assert url == "https://places.googleapis.com/v1/places/pidX"
    assert headers["X-Goog-FieldMask"] == "businessStatus,regularOpeningHours" and headers["X-Goog-Api-Key"] == "KEY"
    assert fresh.status == "CLOSED_PERMANENTLY" and fresh.hours.periods[1]
    assert fresh.place_id == "pidX" and fresh.name == cached.name and fresh.lat == cached.lat
    assert c.calls == {"text_search": 1, "nearby": 0, "details": 1} and len(s.posts) == 1


def test_fresh_status_gone_place_is_none(tmp_path):
    class Gone(FakeResp):
        status_code = 404

    c, s = client(tmp_path, {"places": [gp("Seher Restaurant")]})
    cached = c.find("Seher Restaurant", "Istanbul")
    s.get = lambda url, headers=None, timeout=None: Gone({})
    assert c.fresh_status(cached) is None


def test_nearby_link_names_city_and_skips_malformed(tmp_path):
    broken = gp("No Location Pharmacy", ptype="pharmacy", pid="x")
    del broken["location"]
    c, _ = client(tmp_path, {"places": [broken, gp("City Pharmacy", ptype="pharmacy", pid="ok")]})
    out = c.nearby(41.0, 29.0, ["pharmacy"], 1500, 5, city="Istanbul")
    assert [p.place_id for p in out] == ["ok"]
    assert "query=City+Pharmacy+Istanbul&query_place_id=ok" in out[0].maps_url


# ---------- retry without a trailing parenthetical ----------

def test_retry_without_parenthetical_once_and_cached_under_original_key(tmp_path):
    c, s = client(tmp_path, {"places": [gp("Hotel Elsewhere", addr="Ubud, Bali")]},
                  {"places": [gp("Tegallalang Rice Terrace", addr="Tegallalang, Ubud, Bali", pid="rt")]})
    p = c.find("Tegallalang Rice Terrace (viewpoint and scenic cafe)", "Ubud")
    assert p.match_ok and p.place_id == "rt"
    assert c.calls["text_search"] == 2
    assert s.posts[1][2]["textQuery"] == "Tegallalang Rice Terrace, Ubud"
    again = c.find("Tegallalang Rice Terrace (viewpoint and scenic cafe)", "Ubud")
    assert again.place_id == "rt" and c.calls["text_search"] == 2


def test_no_retry_when_first_try_matches_or_no_parenthetical(tmp_path):
    c, s = client(tmp_path, {"places": [gp("Marine Park Sea Dragon", addr="Nusa, Ubud")]})
    assert c.find("Marine Park (Sea Dragon)", "Ubud").match_ok and c.calls["text_search"] == 1
    c2, s2 = client(tmp_path / "b", {"places": [gp("Something Else", addr="Elsewhere")]})
    assert c2.find("Mangrove boat ride", "Ubud").match_ok is False
    assert c2.calls["text_search"] == 1 and len(s2.posts) == 1


def test_retry_failure_keeps_original_result(tmp_path):
    c, s = client(tmp_path, {"places": [gp("Other", addr="Ubud")]})
    p = c.find("Marine Park (Sea Dragon)", "Ubud")
    assert p.match_ok is False and c.calls["text_search"] == 2 and len(s.posts) == 2


def test_taksu_like_case_end_to_end(tmp_path):
    from datetime import date
    from src.aigv2 import pipeline
    from src.aigv2.models import HotelStay
    c, s = client(tmp_path, {"places": [gp("Taksu Sanur Hotel and Spa Resort Bali", addr="Sanur, Bali", pid="t1")]},
                  {"places": [gp("Taksu Sanur Hotel", addr="Sanur, Bali", pid="t2")]})
    stay = HotelStay(city="Sanur", hotel="TAKSU SANUR HOTEL (Sanur beach)", check_in=date(2026, 9, 30),
                     check_out=date(2026, 10, 1), source="voucher")
    assert stay.hotel == "TAKSU SANUR HOTEL (Sanur beach)" and stay.room_type == ""
    places = pipeline.resolve_places(_trip_with(stay), c, {})
    got = places[pipeline.pkey(stay.hotel, "Sanur")]
    assert got.match_ok and got.place_id == "t2" and c.calls["text_search"] == 2


def _trip_with(stay):
    from src.aigv2.models import Diet, Traveller, TripPlan
    return TripPlan(client_names=["A"], travellers=Traveller(adults=2), diet=Diet(), travel_modes=["taxi"],
                    hotels=[stay], transport=[], bookings=[], days=[], open_choices=[], vague_days=[],
                    commentary_removed=[], trip_scope="international")


def test_room_type_split_on_real_bali_hotels():
    from datetime import date
    from src.aigv2.models import HotelStay

    def mk(h):
        return HotelStay(city="X", hotel=h, check_in=date(2026, 1, 1), check_out=date(2026, 1, 2), source="voucher")
    a = mk("MAYURA UBUD RETREAT (Deluxe Room)")
    assert (a.hotel, a.room_type) == ("MAYURA UBUD RETREAT", "Deluxe Room")
    b = mk("D'NUSA BEACH CLUB AND RESORT (Grand Deluxe Room)")
    assert (b.hotel, b.room_type) == ("D'NUSA BEACH CLUB AND RESORT", "Grand Deluxe Room")
    assert mk("Hotel X (Ubud)").hotel == "Hotel X (Ubud)" and mk("Hotel X (Ubud)").room_type == ""
    r = mk("  Resort (Pool Villa) ")
    assert (r.hotel, r.room_type) == ("Resort", "Pool Villa")
    assert mk(" Plain Hotel ").hotel == "Plain Hotel"


def test_peek_returns_cached_without_calls_or_counters(tmp_path):
    c, sess = client(tmp_path, {"places": [gp("Seher Restaurant")]})
    assert c.peek("Seher Restaurant", "Istanbul") is None
    got = c.find("Seher Restaurant", "Istanbul")
    before = dict(c.calls)
    assert c.peek("Seher Restaurant", "Istanbul") == got
    assert c.calls == before and len(sess.posts) == 1


def test_peek_none_when_expired(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Seher Restaurant")]})
    c.find("Seher Restaurant", "Istanbul")
    c.cache.max_age = timedelta(seconds=-1)
    assert c.peek("Seher Restaurant", "Istanbul") is None


# ---------- simplification retry chain ----------

def test_simplified_names_chain():
    from src.aigv2.google.places import _simplified_names
    assert _simplified_names("MANGROVE BOAT EXPERIENCE AT NUSA LEMBONGAN MANGROVE FOREST") == [
        "NUSA LEMBONGAN MANGROVE FOREST", "MANGROVE BOAT AT NUSA LEMBONGAN MANGROVE FOREST"]
    assert _simplified_names("MARINE PARK (SEA DRAGON PACKAGE)") == ["MARINE PARK"]
    assert _simplified_names("KINTAMANI VOLCANO VIEW") == ["KINTAMANI VOLCANO"]
    assert _simplified_names("DEVIL'S TEAR") == ["DEVIL'S TEARS"]
    assert _simplified_names("COFFEE PLANTATION") == []


def test_chain_steps_run_in_order_and_note_set(tmp_path):
    miss = {"places": [gp("Other", addr="Elsewhere")]}
    hit = {"places": [gp("Nusa Lembongan Mangrove Forest", addr="Nusa Lembongan, Bali", pid="m")]}
    c, s = client(tmp_path, miss, hit)
    p = c.find("MANGROVE BOAT EXPERIENCE AT NUSA LEMBONGAN MANGROVE FOREST", "Nusa Lembongan")
    assert p.match_ok and p.place_id == "m" and c.calls["text_search"] == 2
    assert s.posts[1][2]["textQuery"] == "NUSA LEMBONGAN MANGROVE FOREST, Nusa Lembongan"
    assert "simplified name" in p.verify_note
    assert c.find("MANGROVE BOAT EXPERIENCE AT NUSA LEMBONGAN MANGROVE FOREST", "Nusa Lembongan").place_id == "m"
    assert c.calls["text_search"] == 2


def test_tears_retry_and_cap(tmp_path):
    miss = {"places": [gp("Other", addr="Elsewhere")]}
    hit = {"places": [gp("Devil's Tears", addr="Nusa Lembongan, Bali", pid="d")]}
    c, s = client(tmp_path, miss, hit)
    p = c.find("DEVIL'S TEAR", "Nusa Lembongan")
    assert p.match_ok and s.posts[1][2]["textQuery"] == "DEVIL'S TEARS, Nusa Lembongan"
    c2, s2 = client(tmp_path / "b", miss)
    p2 = c2.find("A VIEW TOUR AT B (C PACKAGE)", "Ubud")
    assert not p2.match_ok and c2.calls["text_search"] <= 4


def test_no_chain_when_first_matches(tmp_path):
    c, s = client(tmp_path, {"places": [gp("Kintamani Volcano View", addr="Kintamani, Ubud, Bali")]})
    assert c.find("KINTAMANI VOLCANO VIEW", "Ubud").match_ok and c.calls["text_search"] == 1


def test_nearby_answers_are_cached_on_disk(tmp_path):
    from src.aigv2.store import NearbyCache
    backend = LocalStorageBackend(tmp_path)
    s = FakeSession({"places": [gp("City Pharmacy", ptype="pharmacy")]})
    c = PlacesClient("k", PlaceCache(backend, 30), session=s, nearby_cache=NearbyCache(backend, 30))
    first = c.nearby(41.0, 29.0, ["pharmacy"], 1500, 5, "Istanbul")
    again = c.nearby(41.0, 29.0, ["pharmacy"], 1500, 5, "Istanbul")
    assert c.calls["nearby"] == 1 and [p.name for p in again] == [p.name for p in first] == ["City Pharmacy"]
    other = c.nearby(41.0, 29.0, ["pharmacy"], 3000, 5, "Istanbul")
    assert c.calls["nearby"] == 2 and other
    # a fresh client on the same disk reuses it, an expired entry is ignored
    c2 = PlacesClient("k", PlaceCache(backend, 30), session=FakeSession({"places": []}),
                      nearby_cache=NearbyCache(backend, 30))
    assert c2.nearby(41.0, 29.0, ["pharmacy"], 1500, 5, "Istanbul") and c2.calls["nearby"] == 0
    c3 = PlacesClient("k", PlaceCache(backend, 30), session=FakeSession({"places": []}),
                      nearby_cache=NearbyCache(backend, 0))
    import time as _t; _t.sleep(0.01)
    assert c3.nearby(41.0, 29.0, ["pharmacy"], 1500, 5, "Istanbul") == [] and c3.calls["nearby"] == 1


def test_nearby_drops_rentals_and_tour_operators_for_groceries(tmp_path):
    c, _ = client(tmp_path, {"places": [
        gp("Pandan rent motor bike and snorkling trips", ptype="convenience_store", pid="a"),
        gp("Island Scooter Hire", ptype="convenience_store", pid="b"),
        gp("Blue Spa Mart", ptype="convenience_store", pid="c"),
        gp("Sunny Laundry Shop", ptype="convenience_store", pid="d"),
        gp("Dive Centre Diving Store", ptype="convenience_store", pid="e"),
        gp("Village Mini Market", ptype="convenience_store", pid="f"),
        gp("Spar Supermarket", ptype="supermarket", pid="g"),
    ]})
    out = c.nearby(41.0, 29.0, ["supermarket", "convenience_store", "grocery_store"], 900, 6)
    assert [p.place_id for p in out] == ["f", "g"]


def test_nearby_hospital_drops_labs_dental_vets_beauty_but_keeps_emergency(tmp_path):
    names = ["Poliklinik Gigi RS Ari Canti", "Laboratorium Mikrobiologi RSBM", "City Pathology Centre",
             "Paws Veterinary Hospital", "Pet Vet Hospital", "Glow Beauty Hospital", "Skin Clinic Hospital",
             "Eye Clinic Hospital", "Emergency Dental Hospital", "Sanur General Hospital"]
    c, _ = client(tmp_path, {"places": [
        gp(n, ptype="hospital", pid=f"p{i}", lat=41.001, lng=29.0) for i, n in enumerate(names)]})
    out = c.nearby(41.0, 29.0, ["hospital"], 5000, 20)
    assert sorted(p.name for p in out) == ["Emergency Dental Hospital", "Sanur General Hospital"]


def test_medical_exclusions_do_not_apply_to_pharmacies_for_lab_words(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Pet Pharmacy Rental", ptype="pharmacy", pid="a"),
                                        gp("Kimia Farma", ptype="pharmacy", pid="b")]})
    out = c.nearby(41.0, 29.0, ["pharmacy"], 900, 5)
    assert [p.place_id for p in out] == ["b"]


def test_simplified_retry_rejects_a_different_place(tmp_path):
    # 'Marine Park' retry finds 'Ducks Marine Park': Google's name has a word the voucher never had -> not found
    c, s = client(tmp_path, {"places": [gp("Marine Safari Bali", addr="Gianyar, Bali, Indonesia")]},
                  {"places": [gp("Ducks Marine Park", addr="Gianyar, Bali, Indonesia", pid="duck")]})
    place = c.find("MARINE PARK (SEA DRAGON PACKAGE)", "Bali")
    assert place is None or not place.match_ok


def test_simplified_retry_still_accepts_plural_and_reordered_names(tmp_path):
    from src.aigv2.google.places import _adds_new_words
    assert not _adds_new_words("DEVIL'S TEAR", "Devil's Tears", "Nusa Lembongan")
    assert not _adds_new_words("MANGROVE BOAT EXPERIENCE AT NUSA LEMBONGAN MANGROVE FOREST",
                               "Mangrove Forest Lembongan", "Nusa Lembongan")
    assert _adds_new_words("KINTAMANI VOLCANO VIEW", "Mountain View House Kintamani", "Ubud")


# ---- place overrides and links ----
from src.aigv2.google.maplink import MapLink, MapLinkError  # noqa: E402
from src.aigv2.google.overrides import PlaceOverrides  # noqa: E402
import pytest  # noqa: E402


def _ov_client(tmp_path, *payloads):
    c, s = client(tmp_path, *payloads)
    c.overrides = PlaceOverrides(tmp_path / "_place_overrides.json")
    return c, s


def test_override_hit_makes_no_http_call(tmp_path):
    c, s = _ov_client(tmp_path, {"places": []})
    c.overrides.put("Hotel Baren", "Grindelwald", "Baeren Hotel", 46.66, 7.86, "https://maps.app.goo.gl/x")
    for fresh in (False, True):
        p = c.find("HÔTEL baren", "grindelwald", fresh=fresh)
        assert p.match_ok and p.name == "Baeren Hotel" and p.maps_url == "https://maps.app.goo.gl/x"
    assert c.peek("Hotel Baren", "Grindelwald").lat == 46.66
    assert s.posts == [] and c.calls["text_search"] == 0


def test_override_miss_falls_through(tmp_path):
    c, s = _ov_client(tmp_path, {"places": [gp("Seher Restaurant")]})
    c.overrides.put("Hotel Baren", "Grindelwald", "Baeren Hotel", 46.66, 7.86, "u")
    assert c.find("Seher Restaurant", "Istanbul").name == "Seher Restaurant"
    assert len(s.posts) == 1


LINK = MapLink("Baeren Hotel, The Bear Inn", 46.6638, 7.8607, "0x1:0x2", "https://maps.app.goo.gl/T")


def test_from_link_enriches_from_nearby_candidate(tmp_path):
    far = gp("Far Cafe", pid="far", lat=46.70, lng=7.9)
    near = gp("Baeren Hotel", pid="pid_b", lat=46.6638, lng=7.8607, ptype="lodging")
    c, s = client(tmp_path, {"places": [far, near]})
    p = c.from_link(LINK)
    assert p.place_id == "pid_b" and p.match_ok and p.maps_url == LINK.url
    body = s.posts[0][2]
    assert body["locationBias"]["circle"]["radius"] == 150.0 and body["textQuery"] == LINK.name
    assert c.calls["text_search"] == 1


def test_from_link_without_candidate_or_on_error(tmp_path):
    c, s = client(tmp_path, {"places": [gp("Far Cafe", lat=46.9, lng=7.9)]})
    p = c.from_link(LINK)
    assert p.place_id == "" and p.match_ok and p.hours is None and (p.lat, p.lng) == (46.6638, 7.8607)

    class Boom(FakeSession):
        def post(self, *a, **k):
            raise RuntimeError("net")
    c2 = PlacesClient("K", PlaceCache(LocalStorageBackend(tmp_path / "x"), 30), session=Boom())
    assert c2.from_link(LINK).match_ok


def test_from_link_needs_pin(tmp_path):
    c, _ = client(tmp_path, {"places": []})
    with pytest.raises(MapLinkError):
        c.from_link(MapLink("", None, None, "1", "u"))
